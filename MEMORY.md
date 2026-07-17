# 记忆

## 关于我
- 角色：多角色
- 日常工作：代码开发

## 项目与上下文
- WriteSync（共笔）：Multi-Agent 协作小说写作平台
- 基于雪花写作法（Snowflake Method）
- 技术栈：Python + OpenCode Go（OpenAI 兼容端点）
- **v0.3.0 架构**：主 Agent + 子 Agent 纯 Python 异步循环 + SSE 事件流（`src/orchestrator/`）
- LangGraph 依赖已完全移除，`src/graph/` 已删除
- **默认模型**：`deepseek-v4-flash`（Agent 用）+ `deepseek-v4-pro`（编排器决策用）
- **API 网关限制**：`~/v1/chat/completions` ~100s 硬超时，flash 唯一稳定处理 3000+ 字提示词
- LLM：qwen3.6-plus（通过 OpenCode Go），推理模型需处理 reasoning_content fallback
- 核心竞品：Craft Companion（方法论）、NovelClaw（UX）

## 重要决策
- 2026-06-02：v0.3.0 架构迁移 4 阶段完成 — 主Agent+子Agent纯Python循环，SSE事件流，V1/V2端点共存（详情见 memory/2026-06-02.md）
- 2026-05-02：LangGraph State 从 dataclass 改为 TypedDict，interrupt/resume 用 Command(resume=...) 新版 API
- 2026-05-02：LLM 从 MiniMax M2.7/Anthropic 切换到 OpenCode Go（deepseek-v4-flash）
- 2026-05-02：Agent 输出改为 instructor 结构化输出，推理模型用 Mode.MD_JSON 避免 tool_choice 不兼容
- 2026-05-02：写作阶段采用独立子图（每章一个），集成到全流程图
- 2026-05-02：章纲 Agent 使用 complete() 代替 complete_structured() 避免长输出超时
- 2026-05-03：修复雪花写作法 Step 4/6/9 缺口 — 新增扩展Agent、叙事概要Agent、全书审查Agent
- 2026-05-03：协作模式改造 — Step 1 用户写一句话，每步支持多轮讨论（modify→feedback→重生成→循环）
- 2026-05-03：新增编辑确认+终稿确认+叙事确认+审查确认，所有确认节点反馈链路打通
- 2026-05-03：修复审计缺陷7个（重复定义/未导入/路由反转等）
- 2026-05-04：Web UI 从对话式重构为专业写作工作台（三栏布局 + 7 面板 + 24 节点全图）
- 2026-05-04：Web UI 搜索即时测试：前端发现缺陷13 个，已全部修复
- 2026-05-04：Default model: qwen3.6-plus

## 工作习惯与偏好
- 对话风格：详细展开，结构清晰，有分析有结论
- 无特殊习惯要求

## 重要决策
- 2026-04-20：初始化记忆系统
- 2026-05-02：LangGraph State 从 dataclass 改为 TypedDict，interrupt/resume 用 Command(resume=...) 新版 API
- 2026-05-02：LLM 从 MiniMax M2.7/Anthropic 切换到 OpenCode Go（deepseek-v4-flash）
- 2026-05-02：Agent 输出改为 instructor 结构化输出，推理模型用 Mode.MD_JSON 避免 tool_choice 不兼容
- 2026-05-02：写作阶段采用独立子图（每章一个），集成到全流程图
- 2026-05-02：章纲 Agent 使用 complete() 代替 complete_structured() 避免长输出超时
- 2026-05-03：修复雪花写作法 Step 4/6/9 缺口 — 新增扩展Agent、叙事概要Agent、全书审查Agent
- 2026-05-03：协作模式改造 — Step 1 用户写一句话，每步支持多轮讨论（modify→feedback→重生成→循环）
- 2026-05-03：新增编辑确认+终稿确认+叙事确认+审查确认，所有确认节点反馈链路打通
- 2026-05-03：修复审计缺陷7个（重复定义/未导入/路由反转等）
- 2026-05-04：Web UI 从对话式重构为专业写作工作台（三栏布局 + 7 面板 + 24 节点全图）
- 2026-05-04：Web UI 搜索即时测试：前端发现缺陷13 个，已全部修复
- 2026-05-04：Default model: qwen3.6-plus
- **2026-05-06**：知识库动态更新 — 新增 DynamicContext（14字段）、agents/context.py（13函数）、LLM提取+正则降级、伏笔追踪、跨章上下文注入、上下文面板（第8面板）
- **2026-05-06**：代码审查发现并修复 3 Critical + 6 Major 缺陷
- **2026-05-09**：修复 context.py logger 名称 `WriteSync.context` → `writesync`
- **2026-05-09**：全流程详细日志增强 — 新增 state_flags/route_decision/user_action/graph_error(带堆栈) 日志函数，graph/writing_graph/app/cli 全覆盖
- **2026-05-09**：修复一句话确认循环 — `_用户一句话()` 中用户确认即设 `confirmed_at`，跳过冗余确认
- **2026-05-09**：修复 `章纲确认()` Bug — `story.confirmed_at` → `outline.confirmed_at`；删除死代码重复定义
- **2026-05-09**：项目持久化 — 新增 `GET /api/projects` + `POST /api/load/{id}`，服务重启后可继续已有项目
- **2026-05-09**：workflow 文档更新 — AGENTS.md 补充计划检查/测试 pattern/已安装 skill，CLAUDE.md 更新技术栈和记忆协议
- **2026-05-09**：Smart Resume 智能跳过 — 11 个 Agent 节点 + 8 个确认节点添加"已有输出则跳过"逻辑，加载项目后图在 ~50ms 内自动跳过已完成步骤，精准停在下一步中断点
- **2026-05-09**：CLI 加载增强 — 加载已有项目时显示状态摘要，配合 Smart Resume 无缝恢复
- **2026-05-09**：详设文档更新 — 在 2026-05-04-web-ui-workbench-design.md 追加持久化存储结构/恢复加载流程/智能跳过矩阵
- **2026-05-09**：交互流程文档更新 — web-ui-flow.md 补充项目加载 4 步骤 + Smart Resume 原理
- **2026-05-09**：UI 设计稿 — 新建 docs/superpowers/specs/2026-05-09-ui-redesign.html，包含项目列表/设置面板/工作台三栏布局/智能跳过矩阵的完整 HTML 原型
- **2026-05-09**：Interrupt 横幅落地 — 金色中断横幅置于编辑器上方，与聊天区按钮同步，`resume()` 自动隐藏
- **2026-05-09**：SVG 进度环 — 圆形进度指示器替换线性进度条，`stroke-dasharray` 驱动动画
- **2026-05-09**：入口两步流 — 有项目时只显示卡片列表 + "新建项目"按钮，无项目时直接显示表单（去掉了混合布局）
- **2026-05-09**：项目卡片 v2 — 富信息卡片（阶段徽章/一句话摘要/进度条/字数/3 操作按钮），后端 `list_projects()` 返回 richer 信息
- **2026-05-09**：加载动画 — 全屏 `loading-overlay`（spinner + 标题 + 跳动点）在加载项目时展示
- **2026-05-09**：删除项目 — `DELETE /api/projects/{id}` + 前端确认弹窗
- **2026-05-09**：Bug 修复 — `// ── Time helper ──function renderReview(){` 注释吞掉函数定义，导致全局 JS 不执行（"Illegal return statement"）。修复后所有 JS 函数正确注册，Playwright 测试通过
- **2026-05-09**：新增 2 个 Playwright UI 测试（test_ui_flow.py 31 项 + test_ui_comprehensive.py），覆盖入口流/卡片/导航/上下文面板/横幅/加载动画
- **2026-05-09**：入口改造为小红书风格全页卡片网格（`.grid-card`），替代弹窗混合布局；新增 `backToGrid()` 返回按钮
- **2026-05-09**：删除功能改用 `data-*` 属性 + 事件委托修复特殊字符注入问题
- **2026-05-09**：移除未使用的 Quill.js CDN 引用（修复超时加载失败）
- **2026-05-09**：全局滚动条样式统一（5px 细条 + `scrollbar-width:thin` + 暗色主题适配）
- **2026-05-09**：修复 `// ── Time helper ──function renderReview(){` 注释吞函数定义 Bug
- **2026-05-09**：Playwright 测试发现 Google Fonts CDN 阻塞 `domcontentloaded`，添加 `page.route()` 拦截解决
- **2026-05-12**：默认模型改为 `deepseek-v4-pro`（之前 deepseek-v4-flash 为默认）
- **2026-05-12**：推理模型 `max_tokens` 最低设为 4096，防止 reasoning tokens 耗尽 budget
- **2026-05-12**：简化 `response_models.py` 中 `TopicSuggestion`/`TopicEvaluation` 的复杂字段为 Optional，避免校验失败重试
- **2026-05-12**：扩展 Agent 改用 `complete()` 替代 `complete_structured()`，跳过 instructor 开销
- **2026-05-12**：`complete_structured()` 外层添加 SSL 断连/连接错误指数退避重试机制
- **2026-05-12**：修复规划图 `策划确认` 边映射 Bug（`角色Agent` → `扩展Agent`）

## 2026-07-01/02 死循环修复与全流程优化

**核心问题**：冒烟测试策划阶段 story/expansion 无限循环，world agent 失败后编排器无法推进到 outline。

**根因 4 层连锁**：
1. world agent max_tokens 截断 → world.confirmed_at 未设
2. `_validate_decision` 拒 outline（world 未确认）同时放行 story
3. 防循环守卫不触发（要求 world in completed_agents）
4. LLM 持续选择 story → 无限循环

**修复**（6 文件）：
- `decision.py`：防循环守卫 2→6 层（含 attempted_agents 追踪、writer 死循环检测、通用同 agent 检测）
- `world.py`：JSON 控制字符降级 + complete() fallback + max_tokens 16384
- `adapters.py`：outline 降级占位 WorldState 防崩
- `writer.py`：timeout=600 + max_retries=0
- `llm.py`：complete() 默认 timeout 45→180s
- `expansion.py/proofreader.py`：timeout=300

**结果**：198/198 单元测试通过，策划阶段全线一次通关（story→character→world→outline）

## 2026-06-30 测试修复

- **orchestrator 测试 13 ERROR**：`TestResult` 类未注册为 pytest fixture → 两个文件各加 `@pytest.fixture`
- **SSE 超时**：心跳间隔 15s > uvicorn `--timeout-keep-alive` 5s → 改为 3s
- **事件循环阻塞**：`decide_next_action()` 同步调 LLM → 包 `asyncio.to_thread()`
- **决策重试**：3 次 → 2 次，减少阻塞时间
- **防循环守卫**：story 确认后连续 2+ story 调用 → 硬规则强制 character
- 199 项全量测试全部通过

## 2026-05-25 流程精简

### 决策
- **删除只出报告不改文的 Agent**：编辑Agent、节奏Agent 这类仅输出 review notes 不改正文的节点直接删除或合并
- **每章 LLM 调用精简到 2 次**：文笔Agent（写稿）→ 校对Agent（校对+节奏），其余 review 层全部砍掉
- **前端步进必须与后端同步**：删除 Agent 时必须同步删除前端的步骤定义、面板渲染、中断处理、AGENT_PANEL_MAP
- **Context flush 降频**：LLM 上下文检查从每章改为每 3 章触发一次
- **Stage 状态流简化**：draft → confirmed → proofread → final（去掉了 checked/revised/polished）
- **2026-06-11**：v0.4.0 分卷雪花架构设计并实现 — 全书大纲+分卷迭代两层结构，新增钩子矩阵引擎+爽点曲线引擎+平台策略层+黄金三章专项模式，所有校验为辅助提醒不自动阻断。详情见 `docs/superpowers/specs/2026-06-10-volume-snowflake-design.md`
- **2026-06-12**：v0.4.0 收尾 — Dashboard 补全 hook_landing_rate/pleasure_density/auto_degraded 字段（从 VolumeState 计算）；前端新增 auxiliary_check SSE 事件监听器，将钩子/爽点/毒点/字数/黄金三章 5 项检查渲染为聊天卡片；E2E 测试新增 AUXILIARY_CHECK 事件捕获与 Dashboard v0.4.0 字段验证
- **2026-06-14**：Web 启动排障 — fastapi 0.136.3 依赖 starlette>=1.3.1，Starlette 1.x 改了 `TemplateResponse` API 签名：
  - 旧: `TemplateResponse(name, {"request": request})`
  - 新: `TemplateResponse(request, name)`
  - `src/web/app.py:65` 已修复为新格式
  - 配套安装：`python-multipart`（Form 依赖，缺失会报 RuntimeError）
  - 清理了 `__pycache__/` 避免跨 Python 版本（3.12/3.14 共存）缓存干扰
