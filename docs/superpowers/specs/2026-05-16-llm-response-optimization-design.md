# LLM 响应速度优化设计

## 背景

用户在 AI 协作对话中选择选项后（如"角色"按钮），需要等待极长时间（up to 300s）才有反馈，甚至超时无结果。

## 问题诊断

### 根因：deepseek-v4-flash 被误归类为推理模型

```python
REASONING_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro", "kimi-k2.5", "kimi-k2.6", ...}
```

`deepseek-v4-flash` 虽然是 flash 模型（应 fast + cheap），但代码将其归为推理模型，导致：

| 配置 | 推理模型路径 (当前) | 非推理路径 (期望) |
|------|-------------------|------------------|
| structured mode | `Mode.MD_JSON` | `Mode.JSON_SCHEMA` |
| timeout | 300s | 180s → 优化后 45s |
| max_retries | 1 | 3 |
| max_tokens | 16384 | 4096 |

### 次级问题

1. timeout 过长导致用户体验差 —— 即使网络断了也得等 300s（5 分钟）才报错
2. 前端无进度反馈 —— 仅显示"AI 思考中..."，用户不知道还要等多久
3. 失败后无引导 —— 超时/连接失败后，session 卡死，用户不知道该怎么做

## 优化方案

### 1. deepseek-v4-flash 移出推理模型名单

**文件**: `src/utils/llm.py`

```python
# before
REASONING_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro", "kimi-k2.5", ...}

# after
REASONING_MODELS = {"deepseek-v4-pro", "kimi-k2.5", "kimi-k2.6", ...}
```

影响：
- `complete_structured()` 自动选择 `Mode.JSON_SCHEMA`（比 MD_JSON 快 2-3x）
- timeout 从 300s 降到非推理模型的 180s

### 2. 非推理模型 timeout 从 180s 降到 45s

**文件**: `src/utils/llm.py`

```python
# before
timeout = kwargs.pop("timeout", 300 if self._is_reasoning_model() else 180)

# after — flash 模型 45s 足够，加上 3 次重试约 60s 上限
timeout = kwargs.pop("timeout", 300 if self._is_reasoning_model() else 45)
```

重试策略（外层循环）：
- 第 1 次：45s 超时 → 等 0s
- 第 2 次：45s 超时 → 等 2s
- 第 3 次：45s 超时 → 等 4s
- 总上限约 45+47+49 ≈ 141s

**触发重试的异常类型**（`src/utils/llm.py` `complete_structured()` 外层 catch）：
- `APITimeoutError` → 重试
- `APIConnectionError` → 重试（网络闪断）
- `APIConnectionError` 包装的 `RemoteProtocolError` / `ConnectionError` → 重试
- `InstructorRetryException` → 计入重试计数（instructor 内部已重试过）
- `AuthenticationError` / `BadRequestError` / `NotFoundError` → **不重试，立即失败**（配置错误重试无意义）

但实际上 flash 模型 95% 的请求在 5-15s 内返回。45s 超时主要是为了网络闪断时的快速降级。

### 3. 前端等待提示改版

**文件**: `src/web/templates/workbench.html`

当前：
```
setChatStatus('AI 思考中...')
```

改为显示重试进度和时间：
```
⏳ AI 生成中 (第 1/3 次尝试，已等 5 秒...)
⏳ AI 生成中 (第 2/3 次尝试，已等 8 秒...)
✅ 角色生成完成
```

通过在后端 session 中记录重试状态，前端轮询 `/api/status` 时读取并展示。

### 4. Session 状态字段定义

后端 session 新增字段（`src/web/app.py`，`_run_graph_thread` 内管理）：

| 字段名 | 类型 | 生命周期 | 说明 |
|--------|------|---------|------|
| `session["retry_count"]` | `int` | 每次 graph invoke 开始时置 0，重试时递增 | 当前重试次数，供前端轮询读取 |
| `session["agent_error"]` | `str\|None` | 每个 Agent 节点开始时置 None，失败时设错误消息 | 最后一次 Agent 失败的原因 |
| `session["agent_name"]` | `str\|None` | 每个 Agent 节点开始时设当前节点名 | 当前正在执行的 Agent 名称 |

前端通过 `GET /api/status` 读取这些字段（`src/web/app.py` status endpoint 新增返回值字段）。

**注意**：这些字段在 graph 完成 / 到达 interrupt 后由 `_merge_panel_data` 清理。

### 5. 失败后自动跳转面板

当 `_safe_agent_call`（`src/graph/graph.py`）捕获异常时，除了返回 `{}`，还会在 session 中设置 `agent_error` 标记。

**agent_name → 面板映射**：

| agent_name | 面板 ID | 说明 |
|-----------|---------|------|
| `角色Agent` | `characters` | 跳转到角色管理面板，显示"AI 生成失败，请手动添加角色" |
| `世界观Agent` | `world` | 跳转到世界观面板 |
| `扩展Agent` | `story` | 跳转到故事大纲面板 |
| `章纲Agent` | `outline` | 跳转到章纲视图 |
| `叙事概要Agent` | `story` | 跳转到故事大纲面板 |
| `全书审查Agent` | `review` | 跳转到审查面板 |
| 其他写作 Agent | `editor` | 跳转到编辑器 |

前端检测到 `stateData.agent_error` 时：
1. 显示提示：❌ AI 暂时不可用，请手动填写
2. 根据 `agent_name` 自动跳转到对应面板
3. 面板显示指导文字

### 6. 前端轮询改进

当前 10s 固定间隔，已加 `pollingBusy` 标志（上一轮未完成时不发新请求）。但还可以加：
- 有活跃 interrupt 时暂停轮询（因为 graph 在等用户操作，状态不会变）
- graph 执行中加快轮询频率（从 10s 降到 2s），以便第一时间捕获完成状态

## 影响范围

| 文件 | 改动内容 | 风险 |
|------|---------|------|
| `src/utils/llm.py` | 移出 REASONING_MODELS + 调 timeout + 异常分类重试 | 低 — 仅改配置 |
| `src/web/app.py` | session 新增 retry_count/agent_error/agent_name 字段；status endpoint 返回这些字段；_run_graph_thread 管理字段生命周期；_merge_panel_data 清理字段 | 低 |
| `src/graph/graph.py` | _safe_agent_call 增加重试计数/错误标记写入 session 的逻辑 | 低 |
| `src/web/templates/workbench.html` | 前端等待提示显示重试次数和时间；失败后自动跳转面板；轮询策略优化 | 中 — JS 逻辑 |

## 验证方法

1. 启动 web 服务，新建项目
2. 完成选题/故事大纲
3. 点击"角色"快速按钮
4. 验证：① 前端显示尝试次数和时间 ② 45s 内出结果 ③ 如果 LLM 断开，45s 后降级显示"手动填写"提示
5. `python -m pytest tests/` 全量通过
