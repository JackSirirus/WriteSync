# WriteSync 主Agent + 子Agent 架构设计

日期：2026-05-27
状态：已确认
版本：v0.3.0

---

## 1. 背景与动机

### 当前问题

现有 WriteSync 采用 LangGraph StateGraph 实现雪花写作法的固定管道流程。尽管经历了 5/25 流程精简（LLM 调用从每章 7 次降到 2 次），架构层面仍存在根本缺陷：

- **流程死板**：必须按预定义顺序走，无法根据内容需要动态跳跃
- **线性思维**：A→B→C 固定路径，但写作本质上是非线性的
- **扩展困难**：每增加一种场景就要加节点 + 边，维护成本高
- **不符合雪花写作法本质**：雪花法是"搭积木"式的迭代构建，不是流水线

### 设计目标

将架构从 LangGraph 固定状态机迁移到**主 Agent + 子 Agent 智能调度**模式：

- 一个主 Agent 作为编排器，理解当前状态，自主决定调用哪个子 Agent
- 子 Agent 各司其职，被调用时专注于完成单一任务
- 关键产出物保持用户确认节点，用户反馈回到主 Agent 重新决策
- 上下文分层注入，主 Agent 可按需获取深层信息

---

## 2. 整体架构

### 2.1 会话循环（Session Loop）

```
用户启动/恢复会话
       │
       ▼
  ┌─────────────────┐
  │ 主Agent 评估      │ ← L0仪表盘 + 用户反馈(如有)
  │ "现在该做什么？"  │   可选请求 L2 深层上下文
  └────────┬────────┘
           │ 决策: 调谁 + 什么指令
           ▼
  ┌─────────────────┐
  │  子Agent 执行     │ ← 拿到 workspace + instruction
  └────────┬────────┘
           │ 产出结果
           ▼
  ┌─────────────────┐
  │  是确认节点？     │
  │  否 → 回主Agent  │
  │  是 → interrupt  │
  │  用户提反馈      │
  │  反馈回主Agent   │
  └────────┬────────┘
           │
           ▼
    主Agent重新评估
           │
    判定"全书完成"？
    否 → 继续循环
    是 → 提议结束 → 用户确认 → 终止
```

### 2.2 角色定义

#### 主 Agent（Orchestrator）

| 项目 | 说明 |
|------|------|
| 模型 | `deepseek-v4-pro`（推理模型） |
| 职责 | 评估全局状态 → 决定调哪个子Agent → 生成调用指令 → 判断终止条件 |
| 输入 | L0 仪表盘 + L1 产出摘要 + 用户反馈 |
| 可按需获取 | L2 深层上下文（完整角色卡、章纲、已写章节等） |
| 输出 | `OrchestratorDecision` |
| 终止 | 主Agent提议"全书已完成"，用户最终确认 |

#### 子 Agent（7个，照搬现有）

| 子Agent | 职责 | 模型 | 需要确认？ |
|---------|------|------|-----------|
| `story_agent` | 选题 → 一句话 → 策划扩展 | `deepseek-v4-flash` | 是（一句话确认） |
| `character_agent` | 生成/修改角色卡 | `deepseek-v4-flash` | 是 |
| `world_agent` | 生成/修改世界观设定 | `deepseek-v4-flash` | 是 |
| `outline_agent` | 生成/修改章纲（含每章节拍） | `deepseek-v4-flash` | 是 |
| `writer_agent` | 撰写指定章节正文 | `deepseek-v4-flash` | 是 |
| `proofreader_agent` | 校对+节奏分析 | `deepseek-v4-flash` | 否（结果随 writer 一起确认） |
| `novel_review_agent` | 全书完稿后整体审查 | `deepseek-v4-flash` | 是 |

**story_agent 内部流程**：选题阶段由主Agent在首次调用时传入用户选题偏好作为 `instruction`，story_agent 内部完成选题+一句话+策划扩展后返回结果。选题环节不再需要独立用户确认——用户可在确认一句话时一并审核选题方向。若用户不满意，反馈回到主Agent，主Agent可再次调 story_agent 重新选题或直接指定新选题方向。story_agent 是唯一一个内部进行流程合并的子Agent（适配层需将原多步流程串联为单次调用）。

**选题阶段（`topic_selection`）说明**：当 `topic.suggestions` 存在但 `story` 尚未确认时，编排器进入 `topic_selection` 阶段。此阶段仅允许调用 `story` agent。用户确认选题后，`_mark_confirmed("story")` 自动从选中选题创建 `StoryState`，阶段跃迁至 `planning`。

**模型选择规则**：所有子 Agent 统一使用 `deepseek-v4-flash`（低延迟，稳定处理长文本）。主 Agent 使用 `deepseek-v4-pro`（高质量决策）。

### 2.3 上下文分层模型

| 层级 | 名称 | 内容 | 注入时机 |
|------|------|------|----------|
| L0 | 仪表盘 | 当前阶段、已完成列表、待确认列表、用户最新反馈、进度百分比 | 每次决策默认注入 |
| L1 | 产出摘要 | 角色卡摘要、世界观摘要、章纲摘要、最近一章正文摘要（≤800字） | 子Agent产出后，由 AgentAdapter 层调用LLM生成摘要并填入 `AgentResult.summary` |
| L2 | 按需深入 | 完整角色卡、完整世界观、完整章纲、所有已写章节全文 | 主Agent主动请求时才拉取 |
| L3 | 日志 | 完整调度历史、每步决策理由、用户反馈记录 | 调试/审计，不注入Agent |

### 2.4 用户交互模型

- 子Agent产出是确认节点 → interrupt 展示给用户
- 用户可确认（"可以"）或提修改意见
- **意见回到主Agent**（而非直接给子Agent），主Agent重新判断"该调谁来修"
- 主Agent始终是唯一决策点

### 2.5 终止规则

- 主Agent检测到所有章节已终审 → 可提议"全书已完成"
- 用户确认后终止
- 用户也可随时主动终止

---

## 3. 数据模型

### 3.1 Workspace 状态结构

```json
{
  "id": "proj_001",
  "schema_version": 2,

  "story": {
    "step1": {"one_sentence": "...", "tag": "..."},
    "step2": {"setup": "...", "inciting": "...", "rising": "...", "climax_prep": "...", "resolution": "...", "theme": "..."},
    "expanded_paragraphs": [...],
    "confirmed_at": "2026-05-27T10:00:00"
  },
  "topic": {
    "user_original_idea": "...",
    "suggestions": [{"title": "...", "genre": "...", "core_selling_point": "..."}],
    "selected": 0,
    "confirmed_at": "..."
  },
  "characters": {
    "cards": [...],
    "confirmed_at": "..."
  },
  "world": {
    "setting": "...",
    "rules": "...",
    "factions": [...],
    "confirmed_at": "..."
  },
  "outline": {
    "chapters": [
      {"num": 1, "title": "...", "beats": [...], "status": "written"}
    ],
    "confirmed_at": "..."
  },
  "drafts": {
    "chapters": {
      "1": {
        "num": 1,
        "draft": "...",
        "proofread": "...",
        "rhythm_notes": "...",
        "stage": "final",
        "word_count": 3500
      }
    }
  },

  "session": {
    "history": [
      {"step": 1, "action": "call_agent", "agent": "outline_agent", "reason": "...", "timestamp": "..."}
    ],
    "history_max": 100,
    "feedbacks": [
      {"step": 2, "agent": "character", "feedback": "角色A动机不够"}
    ],
    "last_pending_confirm": null
    // 或 {"agent": "writer", "content": {...}, "chapter_num": 1, "stage": "proofread"}
  },

  "context_cache": {
    "characters_summary": "...",
    "world_summary": "...",
    "outline_summary": "...",
    "last_chapter_summary": "..."
  },

  "_dashboard": {
    "phase": "planning",
    "completed_agents": ["story", "character", "world"],
    "pending_confirm": "",
    "last_user_feedback": "主角性格再尖锐一点",
    "progress": {"total_chapters": 20, "written": 0, "proofread": 0, "confirmed": 0},
    "updated_at": "2026-05-27T10:00:00"
  }
}
```

### 3.2 主Agent 决策结构（LLM 结构化输出）

```python
class OrchestratorDecision:
    action: Literal["call_agent", "done"]
    agent: Optional[Literal["story", "character", "world", "outline", "writer", "proofreader", "novel_review"]]
    instruction: Optional[str]                      # 传给子Agent的自然语言指令
    request_context: Optional[list[str]]            # 请求L2上下文 ["characters_full", "outline_full"]
    reason: str                                     # 决策理由（日志用）
```

**决策 → 暂停转换**：主Agent只输出 `call_agent` 或 `done`，不直接输出"暂停等确认"。确认暂停由 Orchestrator 层自动处理：子Agent返回 `AgentResult.requires_confirmation=True` → Orchestrator 自动 emit confirm 事件并进入 asyncio.Event 等待。

### 3.3 子Agent 结果契约

所有子Agent遵循统一接口 `agent.run(workspace, instruction) -> AgentResult`：

```python
class AgentResult:
    agent: str
    content: str | dict
    requires_confirmation: bool
    summary: Optional[str]
    error: Optional[str] = None
```

各子Agent具体产出：

| 子Agent | result.content 类型 | requires_confirmation |
|---------|---------------------|-----------------------|
| `story_agent` | `{one_sentence, expansion}` | True |
| `character_agent` | `{cards: [...]}` | True |
| `world_agent` | `{setting, rules, factions}` | True |
| `outline_agent` | `{chapters: [...]}` | True |
| `writer_agent` | `{chapter_num, content, word_count}` | True |
| `proofreader_agent` | `{chapter_num, proofread_content, rhythm_notes}` | False |
| `novel_review_agent` | `{report, suggestions}` | True |

**Agent 适配说明**：现有 Agent 函数的入参格式各异（如 `run_writer_agent(state, chapter_num)` 直接取 State 字段）。适配方式为每个 Agent 外层包一层 `AgentAdapter`，负责从 `workspace(JSON)` 提取所需数据后调用原函数，并将返回结果包装为 `AgentResult`。不对 Agent 内部逻辑做改动。

### 3.4 Writer-Proofreader 协作方式

主Agent将 writer 和 proofreader 视为独立的子Agent，自行决定调用顺序：

- 写完一章后，主Agent判断是否需要校对 → 如需，下一步调用 proofreader
- proofreader 产出随 writer 结果一起展示给用户（proofreader **不需要单独确认中断**，`requires_confirmation=False`）
- proofreader 自动检测第一个有 draft 无 final 的章节
- 用户确认的是 writer 的 confirm（`stage: "draft"`），proofreader 在后台自动完成

典型调用序列：
```
主Agent → writer(ch=1) → 产出草稿 → workspace_update → auxiliary_check → confirm → 用户确认
主Agent → proofreader(ch=1) → 产出校对稿 → workspace_update（无 confirm，不中断用户）
主Agent → writer(ch=2) → 下一章...
```

confirm 事件 payload（writer 阶段）：
```json
{
  "type": "confirm",
  "agent": "writer",
  "content": {"chapter_num": 1, "content": "...", "word_count": 3500, "stage": "draft", "auxiliary_checks": [...]},
  "chapter_num": 1
}
```

> **v0.4.1 补全** (对应 DS-GAP-03)：proofreader 失败时通过 SSE `error` 事件通知，编排器下一轮可决定重试或跳过。`_mark_confirmed("writer")` 将 `cd.stage` 置为 `"final"`，与 proofreader 的 `cd.final` 是独立字段。

### 3.5 Orchestrator 决策系统

**系统提示词模板**（核心行为契约）：

```
你是WriteSync的主编，负责统筹一部小说的协作写作流程。

## 当前状态（每次决策时注入）
- 仪表盘：已完成哪些Agent确认、待确认列表、用户最新反馈、进度
- 上下文缓存：角色/世界观/章纲摘要

## 可用资源（子Agent目录）
- story_agent: 选题→一句话→策划扩展故事框架
- character_agent: 生成/修改角色卡
- world_agent: 构建世界观设定
- outline_agent: 规划章节目录和章节节拍
- writer_agent: 撰写指定章节正文（传入chapter_num）
- proofreader_agent: 校对指定章节并分析节奏
- novel_review_agent: 全书完稿后整体审查

## 决策规则
1. 优先遵循写作的自然顺序：故事框架→角色→世界观→章纲→逐章写作
2. 但灵活应对：写完章节后若发现角色不一致，应回头调用 character_agent 修改
3. writer_agent 产出章节草稿后，通常应紧接着调用 proofreader_agent 校对同一章
4. 用户反馈中明确指向某Agent时，优先处理该反馈
5. 全书完成条件：所有章节已写+校对，且用户已确认全书终审
6. instruction 用自然语言描述具体任务需求
7. 若需深入了解某部分内容才能决策，在 request_context 中请求相应L2上下文

> **v0.4.1 补全** (对应 DS-GAP-02, DS-GAP-08)：
> **Planning 阶段自由度**：character/world/outline 的调用顺序由 LLM 自主决定，无固定流水线。推荐 character→world→outline，但 LLM 可跳过或重调。
> **Agent 名称归一化**：编排器接收 LLM 返回的 agent 名后，通过关键词模糊匹配归一化：

| 关键词 | 归一化结果 |
|--------|-----------|
| outline, chapter, 章 | `outline` |
| story, plot, plan, topic, 创意 | `story` |
| character, 角色 | `character` |
| world, 世界, setting | `world` |
| writer, draft, 写, 文笔, create | `writer` |
| proof, 校对, edit | `proofreader` |
| review, 审查, check | `novel_review` |
| 其他 | `story`（默认降级） |

> **Done 行为规范** (对应 DS-GAP-04)：LLM 返回 `done` 时触发 SSE `done` 事件并等待用户确认。用户批准 → session 结束（`finished_at` 设置，loop break）。用户拒绝并提供反馈 → 反馈存入 `feedbacks["orchestrator"]`，loop continue。选题阶段禁止 `done`（硬规则守卫）。
```

**instruction 格式**（自由文本）：`"根据已确认的一句话和角色卡，生成20章的章纲"` / `"撰写第3章正文，注意主角此时刚经历背叛"` / `"校对第3章，重点关注对话节奏"`

**用户反馈驱动**：用户确认时的文字反馈作为下一轮决策上下文。主Agent根据反馈内容判断应调哪个子Agent（"角色X太单薄"→character_agent；"第5章节奏太慢"→proofreader_agent）。

**首次启动**：当 workspace 为空时（新项目），主Agent需一个初始种子指令（用户创建项目时填写的一句"我想写什么"），主Agent以此为基础调用 `story_agent` 开始写作流程。

**错误决策恢复**：若用户认为主Agent决策不对（如"我觉得不对，应该先改角色"），用户可拒绝当前方向。此反馈注入下一轮决策时，主Agent必须优先遵循用户指明的方向。

---

## 4. 前后端协议

### 4.1 事件流（SSE）

前后端通过 SSE 事件流通信，替换原来 LangGraph 的 invoke/resume 调用：

| 事件类型 | 含义 | payload | 前端行为 |
|----------|------|---------|----------|
| `thinking` | 主Agent在思考 | `{}` | 状态栏显示"思考中..." |
| `agent_call` | 主Agent调用子Agent | `{agent, instruction}` | 对应面板 loading |
| `confirm` | 产出完成，等待确认 | 见下方统一格式 | 面板高亮 + 确认/修改按钮 |
| `done` | 主Agent提议完成 | `{reason}` | 弹出"全书已完成"确认框 |
| `workspace_update` | 数据变更 | `{agent, data}` | 刷新对应面板 |
| `error` | 出错 | `{message}` | 错误提示 + 重试按钮 |

**事件触发时机**：
- `workspace_update`：仅在用户确认后（即 workspace 数据已持久化）触发，不在每个中间步骤触发。携带变更的 agent 名称和对应的新数据，前端按 agent 类型更新对应面板。
- `agent_call`：主Agent每次调度子Agent时触发，前端显示对应面板的 loading 状态。
- `confirm`：子Agent产出后且需要用户确认时触发。非确认节点的产出不触发此事件，直接进入下一轮主Agent决策。

**confirm 事件统一格式**：
```json
{
  "type": "confirm",
  "agent": "writer",
  "content": {},                 // 子Agent产出
  "dashboard": {},               // 仪表盘快照
  "chapter_num": null,
  "stage": null
}
```
- writer+proofreader 链并入一个 confirm：`content = {draft, proofread, rhythm_notes}`，`stage = "proofread"`
- 单独 writer（proofreader 尚未调用）：`content = {draft}`，`stage = "draft"`

### 4.2 用户操作 → 后端

| 操作 | 端点 | payload |
|------|------|---------|
| 启动/恢复会话 | POST /session/start | `{project_id}` |
| 确认产出 | POST /session/confirm | `{approved: bool, feedback?: str, scope?: "draft" | "proofread" | "all"}` |
| 确认全书完成 | POST /session/finish | `{confirmed: true}` |
| 取消完成/继续 | POST /session/finish | `{confirmed: false, feedback?: str}` |

- `scope`（可选）：当用户只想要求重写校对而保留草稿时，传 `scope: "proofread"`。默认 `"all"` 表示全部需要重做
- `feedback`：修改意见文本，注入下一轮主Agent决策

### 4.3 会话暂停/恢复机制

```
POST /session/start → 创建 SSE 连接 → Orchestrator 开始循环
         ↓
   SSE 持续推送事件
         ↓
   confirm 事件 → Orchestrator 暂停（asyncio.Event 等待）
         ↓
   用户 POST /session/confirm → 解除暂停 → 继续循环
         ↓
   done 事件 → 循环结束 → SSE 连接关闭
```

**断线恢复**：SSE 断开 → Orchestrator 检测到并暂停，状态已持久化到磁盘。用户重新 `POST /session/start` → 从 `session.last_pending_confirm` 恢复，重发 confirm 事件。

```python
class OrchestratorSession:
    workspace: Workspace
    pause_event: asyncio.Event
    sse_queue: asyncio.Queue
    user_response: dict | None
```

---

## 5. 实现策略

### 5.1 分阶段实施

**阶段一：核心循环（CLI验证）**
1. 新建 `src/orchestrator/` 目录
2. 实现 `Orchestrator` 主循环类（async generator，yield SSE事件）
3. 实现主Agent决策逻辑（`complete_structured` 输出 `OrchestratorDecision`，含格式校验和3次重试；3次全失败则 emit error，用户决定重试/跳过/手动）
4. 为 7 个现有 Agent 编写 `AgentAdapter` 包装层：从 workspace 提取数据 → 调用原函数 → 包装为 `AgentResult`（不改 Agent 内部逻辑）
5. 写 CLI 测试，验证主循环在纯命令行下的行为

**阶段二：持久化与状态管理**
6. 数据迁移：添加 `schema_version=2`，v1→v2 转换逻辑（旧 `drafts.N.content` + multi-stage → 新 `drafts.chapters.N.{draft,proofread,stage}`）
7. 适配 `PersistenceManager` 到新 Workspace 结构
8. 实现上下文缓存（L1 摘要由子Agent在 Adapter 中生成、L2 按需拉取、session.history 保留最近100条）
9. L3 调试日志：JSONL 追加写入 `projects/{id}/orchestrator_log.jsonl`
10. 写状态持久化测试

**阶段三：Web UI 适配**
11. `src/web/app.py` 新增 SSE 端点
12. 替换 LangGraph invoke/resume 为事件流
13. 前端适配新事件类型（复用现有面板和确认 UI）
14. Playwright 测试验证 Web 流程

**阶段四：清理**
15. 删除 `graph/` 目录
16. 删除 6 个死代码 Agent 文件（editor/rhythm/writer_check/topic_check/expansion/narrative）
17. 更新测试，移除 LangGraph 依赖
18. 更新 README 和记忆文档

### 5.2 复用清单

| 模块 | 处置 |
|------|------|
| `src/agents/*.py`（7个活跃Agent） | 外层 AgentAdapter 包装，不改内部逻辑 |
| `src/state/state_types.py` | 保留，简化为 Workspace 子结构 |
| `src/state/persistence.py` | 适配新结构 + v1→v2 迁移 |
| `src/utils/llm.py` | 完全复用 |
| `src/utils/export.py` | 完全复用 |
| `src/web/app.py` | 修改端点，保留框架 |
| `src/web/templates/workbench.html` | 前端微调，保留框架 |
| `src/cli.py` | 重写会话循环部分 |

### 5.3 废弃清单

| 模块 | 处置 |
|------|------|
| `src/graph/*` | 删除 |
| `src/agents/editor.py` | 删除 |
| `src/agents/rhythm.py` | 删除 |
| `src/agents/writer_check.py` | 删除 |
| `src/agents/topic_check.py` | 删除 |
| `src/agents/expansion.py` | 删除 |
| `src/agents/narrative.py` | 删除 |
| `test_graph.py` | 删除 |
| `test_node_debug.py` | 删除 |

---

## 6. 关键决策记录

| 决策 | 选项 | 选择 | 理由 |
|------|------|------|------|
| 子Agent职责划分 | 照搬 vs 重新切分 | 照搬 | 先保持现有Agent边界，后续迭代再优化 |
| 主Agent决策方式 | 纯LLM / 规则混合 / 纯规则 | 纯LLM | 最大限度灵活性 |
| 用户反馈流向 | 直给子Agent / 回主Agent | 回主Agent | 主Agent保持唯一决策权 |
| 上下文注入 | 全量 / 分层 / 仅摘要 | 分层 | 默认摘要控token，关键时按需深入 |
| 终止机制 | 主Agent自主 / 用户主动 / 混合 | 混合 | 主Agent提议 + 用户确认 |
| 是否保留 LangGraph | 纯Python / 保留基础设施 / 全不用 | 纯Python | 循环不复杂，LangGraph增加心智负担 |
| 前端策略 | 只换协议 / 重构 / 后做 | 只换协议 | 现有Web UI可用 |

---

## 7. 选题阶段详细规范 (v0.4.1 补全)

> 本节补充于 2026-06-26，对应测试方案 [DS-GAP-01]。

### 6.1 阶段入口

选题阶段 (`topic_selection`) 由 `get_dashboard()` 自动判定。触发条件：
- `TopicState.suggestions` 非空（由 story agent Stage 1 生成）
- `StoryState` 未确认（`story.confirmed_at` 为空或 `story` 为 None）

### 6.2 用户交互

前端收到 `confirm` 事件（`agent=story, stage=topics`）后渲染选题卡片。

用户点击卡片 → 前端发送 `POST /api/v2/respond/{pid}`：
```
approved=true&feedback=选题: {topic.title}
```

### 6.3 选题匹配算法

`_find_selected_topic()` 使用**双向子串匹配**：
1. 从最新的 `story` agent feedback 中取 `text`
2. 遍历 `TopicState.suggestions`，检查 `s.title in text or text in s.title`
3. 匹配成功 → 设置 `TopicState.selected = idx`，返回该选题
4. 若无匹配 → 检查 `TopicState.selected`（-1 表示未选）
5. 仍无 → 降级取第一条建议（`selected = 0`）
6. 列表为空 → 返回 None，不创建 `StoryState`

### 6.4 StoryState 自动创建

选题匹配成功后，`_mark_confirmed("story")` 自动创建 `StoryState`：
```
ws_state.story = StoryState(
    step1=StoryCore(one_sentence=selected.core_selling_point or selected.title, tag=selected.genre),
    step2=StoryArc(...), confirmed_at=now
)
```
创建后 `has_story()` 返回 True，阶段跃迁到 `planning`。

### 6.5 阶段守卫

1. **LLM 决策守卫**：选题阶段 `completed_agents` 为空时，只允许 `story`，且禁止 `done`
2. **硬规则兜底**：`phase == "topic_selection"` 且 story 未确认时，直接返回 `story`

---

## 8. 确认点交互协议 (v0.4.1 补全)

> 本节补充于 2026-06-26，对应测试方案 [DS-GAP-05]。

### 7.1 协议概述

所有需确认的 Agent 产出遵循统一 SSE `confirm` 事件 + HTTP `respond` 响应协议。

### 7.2 各 Agent 确认内容格式

| Agent | content.stage | 必含字段 | 确认后状态变化 |
|-------|---------------|---------|--------------|
| story | `topics` | `topics[{title,genre,sub_genre,core_selling_point}]` | 创建 `StoryState` |
| story | `expansion` | `one_sentence, tag, expansion{setup,inciting,rising,climax_prep,resolution,theme}` | `story.confirmed_at = now` |
| character | — | `characters[{name,role,personality,goal}]` | `characters.confirmed_at = now` |
| world | — | `power_system, tiers` | `world.confirmed_at = now` |
| outline | — | `total_chapters, chapters[{num,title,core_event}]` | `chapter_outline.confirmed_at = now` + 钩子矩阵/爽点曲线 |
| writer | — | `chapter_num, content, word_count, stage:"draft", auxiliary_checks` | `drafts.chapters[N].stage = "final"` |
| novel_review | — | `structural_issues, pacing_assessment, passed` | `novel_review.confirmed_at = now` |

### 7.3 反馈驱动的重生成

当 `approved=false` 且有 `feedback` 时：
1. feedback 存入 `workspace.feedbacks[]`
2. 编排器下一轮决策时，LLM 看到该 feedback
3. 若 LLM 决定重调同一 Agent，`pending_feedback` 随 instruction 传入
4. Agent 基于反馈重新生成

---

## 9. SSE 事件序列契约 (v0.4.1 补全)

> 本节补充于 2026-06-26，对应测试方案 [DS-GAP-06]。

### 8.1 事件类型

| 事件 | 触发条件 | 数据字段 |
|------|---------|---------|
| `thinking` | 每轮循环开始 | `{step: int}` |
| `agent_call` | LLM 决策为 `call_agent` | `{agent: str, instruction: str}` |
| `workspace_update` | Agent 执行成功 | `{agent: str, data: dict, summary: str}` |
| `auxiliary_check` | writer 产出含 checks | `{chapter_num: int, checks: [{name,status,detail,position}]}` |
| `confirm` | `requires_confirmation=True` | `{agent, content, dashboard, chapter_num}` |
| `done` | LLM 决策为 `done` | `{reason: str, dashboard: dict}` |
| `error` | Agent 失败或异常 | `{message: str, agent?: str}` |

### 8.2 时序约束

```
thinking → agent_call → workspace_update → [auxiliary_check] → [confirm]
```

1. `thinking` 始终是每轮第一个事件
2. `workspace_update` 始终在 `agent_call` 之后
3. `auxiliary_check` 仅在 writer agent 产出，位于 `workspace_update` 与 `confirm` 之间
4. `confirm` 是每轮最后一个 SSE 事件（之后编排器进入 `_wait_for_user()` 阻塞）
5. proofreader agent（`requires_confirmation=False`）不产出 `confirm`

### 8.3 错误与完成序列

- 错误：`thinking → agent_call → error → thinking`（编排器 continue）
- 完成：`thinking → done → (用户确认) → [结束 或 继续]`

---

## 10. 持久化与恢复行为规范 (v0.4.1 补全)

> 本节补充于 2026-06-26，对应测试方案 [DS-GAP-07]。

### 9.1 持久化机制

**保存粒度**：每轮循环 Agent 执行成功后自动 `workspace.save()`。

**保存内容**：`projects/<pid>/` 目录下分文件保存各阶段产出 + session_data + context_cache + orchestrator_log。

**不持久化**：`OrchestratorSession` 的运行状态（`_running`, `_pause`, `_user_response`）。

### 9.2 恢复场景

| 场景 | 行为 |
|------|------|
| 服务重启 | in-memory 会话丢失。`load_workspace(pid)` 从磁盘加载，编排器从当前 phase 重新决策 |
| 浏览器刷新 | `initApp()` 从 localStorage 恢复，`POST /api/v2/start` 返回当前 dashboard，新建 SSE 连接 |
| SSE 断连 | 前端降级到轮询 `/api/v2/status`；确认需刷新页面恢复 SSE |
| confirm 响应后崩溃 | 若崩溃在 `_mark_confirmed()` 前，重载后编排器检测未确认，重新发起 confirm |
| 浏览器关闭后重开 | localStorage 恢复 session → `load_workspace()` → 编排器重新决策 |

### 9.3 局限性

- **无事务保证**：用户响应与状态保存间无原子性，崩溃可能丢失最近确认
- **无超时会话清理**：长期运行可能 OOM
- **双 SSE 连接风险**：自动重连时若旧 session 仍运行，可能并发 generator 产生重复事件
