# WriteSync（共笔）

> Multi-Agent 协作小说写作平台 · 基于雪花写作法（Snowflake Method）

WriteSync 是一个 **主 Agent + 子 Agent 协作**的小说写作平台。不同于纯 AI 生成工具，它强调**用户与 AI 搭档共创**——主 Agent 自主编排流程，子 Agent 各司其职，每一步都支持用户反馈 → AI 调整 → 循环直到满意。

---

## 核心特性

- **主 Agent 智能编排**：LLM 自主决策下一步做什么、调用哪个 Agent、何时完工，无需固定流水线
- **7 个子 Agent**：故事策划 / 角色 / 世界观 / 章纲 / 文笔 / 校对 / 全书审查
- **雪花写作法全覆盖**：从一句话核心到全书审查，逐层扩展
- **协作共创模式**：用户写一句话核心，AI 展开，每步可讨论修改，反复迭代直到满意
- **双界面**：CLI（命令行）+ Web UI（浏览器）
- **SSE 实时事件流**：thinking → agent_call → confirm → done，前端实时渲染
- **多 LLM Provider**：通过 OpenCode Go 网关支持多种模型
- **全流程持久化**：项目自动保存、断点续写、导出 Markdown/TXT
- **动态上下文引擎**：写作过程中自动提取角色变化/一致性矛盾，逐章累积知识点，后续章节注入上下文确保跨章一致性

---

## 快速开始

```bash
# 安装依赖
pip install langgraph langgraph-checkpoint pydantic openai instructor fastapi uvicorn jinja2

# CLI 模式（推荐先试策划阶段）
python -m src.cli

# 全流程模式（策划 + 逐章写作）
python -m src.cli --full

# 使用指定模型
python -m src.cli --full --model gpt-4o --provider openai

# Web UI 模式
$env:LANGGRAPH_STRICT_MSGPACK="false"  # 避免 msgpack 警告
uvicorn src.web.app:app --reload
# 浏览器打开 http://localhost:8000
# V2 编排器端点：/api/v2/stream / /api/v2/start / /api/v2/respond
```

---

## 架构（v0.3.0）

```
用户输入 → 主 Agent（deepseek-v4-pro）
              │
              ├─ thinking ──→ 自主决策下一步
              ├─ agent_call → 子 Agent（deepseek-v4-flash）
              ├─ confirm ──→ 等待用户确认/反馈
              └─ done ─────→ 全书完成
```

主 Agent 通过 SSE 事件流实时推送进度到前端：
- `thinking` — 决策中
- `agent_call` — 调度子 Agent 执行
- `confirm` — 需要用户确认
- `workspace_update` — 状态已更新
- `done` / `error`

编排器内部通过 **Phase（阶段）** 自动判断当前进度：

| Phase | 触发条件 | 允许的 Agent |
|-------|---------|-------------|
| `new` | 全新项目，无任何产出 | story（强制） |
| `topic_selection` | 选题建议已生成，待确认 | story（选题确认后自动创建故事核心） |
| `planning` | 故事核心已确认 | character / world / outline |
| `writing_chapters` | 章纲已确认或已有章节 | writer / proofreader |
| `review` | 全部章节终审完成 | novel_review |
| `idle` | 默认兜底 | — |

> **选题阶段**（`topic_selection`）是 v0.3.0 引入的首个关卡：主 Agent 调 story Agent 的 Stage 1 生成选题建议，用户选择后自动从选题创建一句话故事核心（`StoryState`），阶段跃迁到 `planning`。

---

## 7 个子 Agent

| # | Agent | 雪花步 | 职责 | 交互方式 |
|---|-------|--------|------|---------|
| 1 | 故事策划 Agent | Step 1→2 | **用户写**一句话 → AI 扩五句话 | 用户写 → AI 扩 → 讨论修改 |
| 2 | 角色 Agent | Step 3+5 | 生成角色卡 | AI 出 → 讨论修改 |
| 3 | 世界观 Agent | — | 力量体系/地理/社会/历史 | AI 出 → 讨论修改 |
| 4 | 章纲 Agent | Step 6+7 | 三幕大纲 + 章纲 | AI 出 → 讨论修改 |
| 5 | 文笔 Agent | Step 8 | 按章写初稿（注入跨章上下文） | AI 写 → 用户审阅/提意见重写 |
| 6 | 校对 Agent | Step 9 | 错别字/格式/节奏 | AI 校 → 用户终审 |
| 7 | 全书审查 Agent | Step 10 | 结构/弧线/伏笔全景评估 | AI 出报告 → 用户确认 |

> **v0.3.0 精简**：从 14 个 Agent 精简到 7 个。编辑 Agent、节奏 Agent 等仅输出报告不改文的节点已移除或合并，每章 LLM 调用精简到 2 次（文笔 + 校对）。

---

## 项目结构

```
src/
├── orchestrator/      # ★ v0.3.0 核心 — 主Agent+子Agent异步循环
│   ├── models.py      #   OrchestratorDecision / AgentResult / SSEEvent
│   ├── loop.py        #   异步主循环（SSE yield）
│   ├── adapters.py    #   7 个子 Agent 包装层
│   ├── decision.py    #   主 Agent LLM 决策
│   └── workspace.py   #   状态管理 / 上下文缓存 / 持久化
├── agents/            # 7 个 Agent（V1 兼容文件保留）
│   └── context.py     # 动态上下文构建器
├── state/             #   GraphState TypedDict + WriteSyncState
│   └── persistence.py #   项目持久化（JSON 文件）
├── utils/             #   LLM 客户端 + 知识库 + 导出工具
│   └── llm.py         #   网关适配（opencode/openai/anthropic）
├── web/               #   FastAPI Web UI
│   ├── app.py         #   V1 Graph 端点
│   ├── orchestrator_api.py  # V2 编排器 SSE 端点
│   └── templates/     #   workbench.html
└── cli.py             #   CLI 入口
tests/
├── test_orchestrator_phase1.py  # 核心循环测试（18 项）
├── test_orchestrator_phase2.py  # 持久化与状态测试（62 项）
├── test_e2e_orchestrator.py     # E2E 编排器实测
├── test_context.py              # 上下文单元测试（34 项）
├── test_context_e2e.py          # 上下文累积回放测试
├── test_context_e2e_playwright.py  # 上下文面板前端 E2E
├── test_playwright.py           # 前端 E2E（28 项）
├── test_persistence.py          # 持久化层测试
├── test_response_models.py      # 响应模型校验
└── test_grid_layout.py          # 网格布局 UI 测试
docs/
├── superpowers/specs/           # 7 份设计文档
│   └── 2026-05-27-main-sub-agent-architecture-design.md  # v0.3.0 架构设计
├── dynamic/                     # 运行时动态上下文数据
├── platforms/                   # 平台写作指南（起点/飞卢/番茄/纵横）
├── templates/                   # 模板（角色卡/世界观/选题卡/章纲）
└── techniques/                  # 写作技法（钩子/开篇三章/人物弧线/爽点）
```

---

## 技术栈

| 组件 | 选型 |
|------|------|
| 语言 | Python 3.10+ |
| 编排架构 | **主 Agent + 子 Agent 异步循环**（纯 Python asyncio） |
| 事件流 | SSE（Server-Sent Events） |
| 模型网关 | OpenCode Go（OpenAI 兼容端点） |
| 编排器模型 | `deepseek-v4-pro`（短 prompt，7s 响应，高质量决策） |
| 子 Agent 模型 | `deepseek-v4-flash`（长 prompt 3000+ 字，21s 稳定完成） |
| 结构化输出 | instructor Mode.MD_JSON / `complete()` fallback |
| 持久化 | JSON 文件（本地 projects/ 目录），V2 自动迁移 |
| Web UI | FastAPI + Jinja2 |
| 测试 | pytest（127 后端 + Playwright 前端 E2E） |
| 动态上下文 | `DynamicContext` TypedDict + LLM 提取 + 正则降级 |

---

## 动态上下文引擎

每次用户确认策划产出或每章终稿确认时，自动触发上下文更新流水线：

```
用户确认 → update_dynamic_context(state, ch_num)
  ├── ① 角色变化提取（LLM，超时降级正则）
  ├── ② 一致性检测（LLM，超时跳过）
  ├── ③ 前章摘要（最近 3 章滑动窗口）
  ├── ④ 伏笔追踪（收/未收 + deadline）
  ├── ⑤ 节奏统计（字数/节奏建议）
  └── ⑥ 全书进度（剩余节拍/进度百分比）
```

5 个写作 Agent 在生成前自动注入累积上下文（≤800 字摘要），确保跨章节一致性。前端左侧导航有「📋 写作上下文」面板，支持手动修正编辑。

---

## 降级策略

| 故障 | 降级 |
|------|------|
| LLM 角色提取超时 | 正则扫描 → 保持上版 |
| LLM 一致性检测超时 | 跳过，保持上版 |
| 正则也提取不到 | character_snapshot 追加滞后标记 |
| 主 Agent 决策超时 | 规则兜底（首步强制 story） |
| Agent 名称不规范 | 关键词模糊匹配自动修正 |
| context.json 磁盘满 | catch OSError，不阻断流程 |
| SSE 断线 | 前端自动降级到轮询 |

---

## 模型分配策略

| 角色 | 模型 | 原因 |
|------|------|------|
| 编排器决策 | `deepseek-v4-pro` | 短 prompt（<1000 字），7s 响应，高质量决策 |
| 所有子 Agent | `deepseek-v4-flash` | 长 prompt（3000+ 字），21s 响应，快速稳定 |
| 推理模型兜底 | `deepseek-v4-flash` | 网关 ~100s 硬超时，flash 唯一稳定通过 |

> 网关限制：OpenCode Go 的 `/v1/chat/completions` 有 ~100s 硬超时。pro/qwen 处理大提示词时推理 >100s 会被断连。

---

## 文档

- [v0.3.0 架构设计](./docs/superpowers/specs/2026-05-27-main-sub-agent-architecture-design.md)
- [Web UI 工作台设计](./docs/superpowers/specs/2026-05-04-web-ui-workbench-design.md)
- [动态上下文设计](./docs/superpowers/specs/2026-05-06-dynamic-knowledge-design.md)
- [竞品分析](./docs/competitor-analysis.md)
- [工作流规范](./AGENTS.md)
- 知识库：`docs/platforms/` `docs/templates/` `docs/standards/` `docs/techniques/`

---

## 项目状态

**版本** 0.4.0 · Alpha

| 模块 | 状态 |
|------|------|
| 主 Agent + 子 Agent 异步循环 | ✅ |
| SSE 事件流（CLI + Web） | ✅ |
| 7 子 Agent | ✅ |
| V1 Graph 端点（兼容） | ✅ |
| V2 编排器 SSE 端点 | ✅ |
| CLI + Web UI 双界面 | ✅ |
| 动态上下文引擎 | ✅ |
| 上下文面板（前端） | ✅ |
| 跨章上下文注入 | ✅ |
| 项目持久化 + 断点续写 | ✅ |
| 导出 Markdown/TXT | ✅ |
| 分卷雪花两层架构 | ✅ |
| 钩子矩阵引擎 | ✅ |
| 爽点曲线引擎 | ✅ |
| 平台策略层（起/飞/番/纵） | ✅ |
| 黄金三章专项模式 | ✅ |
| 辅助检验清单（5项纯规则） | ✅ |
| 辅助检验前端渲染（SSE卡片） | ✅ |
| 后端单元测试 | 127 项 ✅ |
| v0.4.0 新增测试 | 33 项 ✅ |
| 前端 Playwright E2E | 28 项 ✅ |
| 编排器 E2E 实测 | 4 步链路通过 ✅ |

---

## 许可

MIT
