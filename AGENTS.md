# AGENTS.md — WriteSync 工作流规范

> **思考层**：CLAUDE.md 定义了 6 阶段思考过程（苏格拉底追问 → 第一性原理 → 科斯定理 → 执行 → 墨菲审查 → 交付）。本文件定义对应的执行步骤。思考阶段与执行步骤的映射见 CLAUDE.md「Stage ↔ Execution 映射」。

## 项目开发流程

```
用户提出想法/需求 → 用 skill 完善想法 → 输出任务计划 → 检查计划完整性/一致性/可行性 → 执行 → 验证
```

> **对应 Stage 1-3**：brainstorming skill 执行苏格拉底追问，输出任务计划时执行第一性原理分析和科斯定理论证。

### 1. 收到新需求时

1. 先加载 `brainstorming` skill 探索需求意图
2. 确认：范围 / 优先级 / 验收标准
3. 输出结构化任务计划（含影响范围、改动文件、验证方法）
4. **检查计划**：完整性（是否覆盖所有改动点）、一致性（是否与现有架构/约定冲突）、可行性（是否可验证）
5. 确认无误后开始编码

### 2. 修改代码前

> **对应 Stage 4-5**：执行与编码阶段。先写测试（Stage4），改完后 code-reviewer 审查（Stage5）。

1. 确认是否有相关测试
2. 检查影响范围（哪些 Agent / Node / State 会变）
3. 先写测试（或更新现有测试）— 参考 tests/ 下已有测试的写法模式：
   - `test_routing.py`: 直接测试路由函数，绕过 compiled subgraph mock 限制
   - `test_cli.py`: mock input/interrupt，测试用户交互分支
   - `test_writing_graph.py`: mock LLM + interrupt，走完整子图流程
   - `test_fixes_*.py`: 针对性回归测试，确保已知陷阱不再复现
   - 新写前端 Playwright 测试时加载 `webapp-testing` skill
4. 改代码 → 跑全量测试
5. 改完后可加载 `code-reviewer` skill 做结构化代码审查（含架构/安全/性能/可维护性检查）

### 3. 提交前检查

> **对应 Stage 5 墨菲审查**：全量测试是最终防线，必须通过。

```bash
# 全量后端测试
python -m pytest tests/ --ignore=tests/test_e2e.py --ignore=tests/test_web_ui.py --ignore=tests/test_context_e2e_playwright.py
# 图流程测试
python test_graph.py
# 上下文独立测试
python -m pytest tests/test_context.py -v
# 上下文端到端测试
python -m pytest tests/test_context_e2e.py -v
# 修复回归测试（确认循环/变量名/日志等已知陷阱）
python -m pytest tests/test_fixes_20260509.py -v
# 前端 E2E（需要 Web 服务运行在 8000 端口）
python tests/test_playwright.py
```

### 4. 技术栈约束

- **LangGraph 1.x**: State 必须是 TypedDict，节点返回 dict，interrupt 新版 API
- **LLM 客户端**: 经过 `create_llm_client()`，不直接 import OpenAI
- **结构化输出**: 优先 `complete_structured()`，推理模型用默认 MD_JSON
- **长文本生成**: `writer` 和 `proofreader` 用 `complete()` fallback（instructor 在大输出上超时）
- **默认模型**: `deepseek-v4-pro`（编排器决策），`deepseek-v4-flash`（子 Agent）
- **推理模型 content fallback**: 推理模型可能返回空 `content`，需 fallback 到 `reasoning_content`
- **LLM 超时**: 180s（已从 120s 调整）
- **环境变量**: `$env:LANGGRAPH_STRICT_MSGPACK="false"` 避免 msgpack 警告
- **写作阶段子图**: 每章一个独立子图，集成到全流程图
- **协作模式**: 所有确认节点支持多轮讨论（modify→feedback→重生成→循环），反馈链路打通
- **Agent 职责**: 检查Agent只做定性判断（有/没有），节奏Agent做定量优化（好/不好）。检查Agent提问题，编辑Agent执行修改

### 5. 已知陷阱与修复模式

#### 5.1 确认循环陷阱
- `_用户一句话()` 用户确认后应直接设 `story.confirmed_at`，不需要再进入 `_一句话确认`
- 症状：两步确认死循环，用户反复确认
- 修复：确认节点设置对应 `*_confirmed_at` 后 router 返回已确认→结束，不要返回到确认入口

#### 5.2 确认节点变量名 Bug
- 复制粘贴确认模板时，容易把 `story.confirmed_at` 留在非 story 确认节点（如章纲确认）
- 症状：章纲确认后 `outline.confirmed_at` 不设值，无限等待确认
- 修复：每个确认节点检查 `*.confirmed_at` 中 `*` 是否匹配当前节点

#### 5.3 Logger 名称不一致
- 所有模块统一使用 `"writesync"`（小写 w）作为 logger name
- 不要用 `"WriteSync"`（大写 S）— 会导致日志不写入文件
- 2026-05-09 修复例：`context.py` 中 `"WriteSync.context"` → `"writesync"`

#### 5.4 LangGraph interrupt 新版 API
- State 必须用 TypedDict（不用 dataclass），节点返回 dict
- interrupt() 暂停图，invoke 返回带 `__interrupt__` 键的 dict
- 恢复用 `Command(resume=...)`，不是 `update_state` + `invoke(None)`
- 需要设 `LANGGRAPH_STRICT_MSGPACK=false` 避免 msgpack 警告

### 6. 常用调试命令

```bash
# 查看日志（debug 级别）
Get-Content logs/writesync-*.log -Tail 50

# 检查 context 模块日志是否写入
Select-String -Path logs/writesync-*.log -Pattern "context"
# 如果找不到，说明 logger name 不一致（见 5.3）

# 设环境变量避免 msgpack 警告
$env:LANGGRAPH_STRICT_MSGPACK="false"

# 直接验证模块导入
python -c "from src.state.state_types import DynamicContext; print(DynamicContext())"
python -c "from src.agents.context import build_writing_context; print('OK')"
```

### 7. 记忆协议

- **对话结束**：问用户"这次有值得记录的吗？"
- **写入文件**：确认后写入 `memory/YYYY-MM-DD.md`
- **长期决策**：同步更新 `MEMORY.md`
- **即时记录**：用户说"记住这个"时立刻写入，不等结束
- **蒸馏提醒**：每日记忆积累超过 7 天时，主动提议蒸馏到 MEMORY.md
- **记忆来源**：以本项目文件为准，忽略外部记忆系统
- **历史上下文**：需要时搜索 `memory/YYYY-MM-DD.md`
