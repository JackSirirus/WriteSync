# WriteSync 借鉴 StoryForge 分析报告

> 📄 **本文档角色：执行摘要（Executive Summary）**
> 
> 与 [`../../storyforge-reference.md`](../../storyforge-reference.md) 的关系：
> - **本文档** = 执行摘要 — 精选 8 项可借鉴功能，含工作量估算和优先级排序
> - **storyforge-reference** = 完整规格 — 20 项功能详细设计、数据模型、接口定义、架构演化路线图
> 
> 实际开发以本文档的优先级排序为准，以 storyforge-reference 的详细设计为参考。

日期：2026-07-12
来源：对比分析 [StoryForge](https://github.com/yuanbw2025/storyforge)（v3.7.5）与 WriteSync（v0.5.0）

---

## 1. 两项目核心差异总结

| 维度 | WriteSync | StoryForge |
|------|-----------|-----------|
| 架构 | Python 后端 + 主 Agent 编排 | 纯前端 React + IndexedDB |
| AI 模式 | 多 Agent 协作，LLM 自主决策 | 单 Agent + 30+ 提示词适配器 |
| 方法论 | 雪花写作法（Snowflake Method） | 混合式（自顶向下 + 角色驱动） |
| 用户角色 | AI 搭档（interrupt + 多轮反馈） | AI 工具箱（用户主导触发） |
| 代码规模 | ~7,135 行 Python | ~59,000 行 TypeScript/TSX |
| 上下文策略 | 3 层（L0-L2）≤800 字注入 | 30+ 注册源 + 4 层裁剪 + Continuity Envelope |
| 一致性机制 | 角色变化提取 + 一致性检测 | 事实账本 + 状态卡 + 物品栏 + 时间线 + 场景考证 |
| 部署 | 本地 Python 服务 | Vercel 一键部署 / PWA 离线 |

---

## 2. 可借鉴清单（按实现优先级排序）

### 🔴 P0 — 短期可实现，高收益

#### 2.1 提示词模板化

**StoryForge 怎么做**：
所有 AI 调用的提示词以模板形式存储，用户可以查看、编辑、克隆、分叉。模板支持 `{{var}}` 变量替换、`{{#if}}` 条件块、参数控件（select/slider/number/text）。系统模板可克隆为用户模板，题材包（仙侠/都市/悬疑等）可一键切换。

**WriteSync 现状**：
提示词硬编码在各 Agent 文件（`src/agents/`）的 system prompt 中，用户完全看不到。

**借鉴方案**：
1. 在 `src/agents/` 下新增 `prompts/` 目录，将各 Agent 的 system prompt 抽离为模板文件
2. 模板格式：Markdown + `{{placeholder}}` 变量 + 头部元数据（适用题材、参数定义）
3. 前端新增「提示词库」面板，列出各 Agent 的提示词模板，支持预览和自定义
4. 题材包：定义一组预设变量值（仙侠→`朝代=架空，力量体系=修仙`，都市→`背景=现代，力量体系=异能`）
5. `workspace` 中存储用户自定义的提示词覆盖，Agent 调用时 merge

**预估工作量**：3-5 天
**影响范围**：`src/agents/*.py`（提取提示词）、`src/web/templates/workbench.html`（前端面板）、新增 `src/agents/prompts/` 目录

---

#### 2.2 事实账本（Temporal Fact Ledger）

**StoryForge 怎么做**：
`src/lib/fact-ledger/` 实现了一个结构化事实追踪系统：
- 从正文中提取事实（如"张三在 12 岁学会了剑法"、"李四在第三章受伤"）
- 每条事实有 `validFrom` / `validTo` 章节范围
- 状态生命周期：candidate → confirmed → denied
- 生成后续章节时，自动投影「当前有效的事实」到上下文

**WriteSync 现状**：
`DynamicContext` 有角色变化提取和一致性检测，但缺乏结构化的事实追踪。当前是「摘要式」上下文（≤800 字），信息密度低。

**借鉴方案**：
1. 在 `src/agents/context.py` 中新增 `FactLedger` 类
2. 每次章节确认后，LLM 从正文中提取新事实（结构化输出）
3. 事实数据模型：
   ```python
   class TemporalFact:
       content: str          # "张三在12岁学会了剑法"
       category: str         # "character" | "plot" | "world" | "item"
       valid_from_ch: int    # 从第几章开始有效
       valid_to_ch: int|None # 到第几章失效（None=至今有效）
       status: str           # "candidate" | "confirmed" | "denied"
       source_chapter: int   # 来源章节
   ```
4. 生成后续章节时，`build_writing_context()` 注入当前有效的事实列表
5. 前端上下文面板新增「事实账本」标签页

**预估工作量**：5-7 天
**影响范围**：`src/agents/context.py`、`src/state/state_types.py`、前端上下文面板

---

### 🟡 P1 — 中期规划，结构优化

#### 2.3 Continuity Envelope 机制

**StoryForge 怎么做**：
跨章连续性不是靠摘要，而是靠一个结构化的「Continuity Envelope」：
1. **交接文本**（Handoff Text）：上一章的结尾状态精确传递（谁在哪里、什么情绪、正在做什么）
2. **计划对账**（Plan Reconciliation）：对比章纲中计划的剧情走向和实际写作的偏差
3. **保护块**（Protected Blocks）：标记需要跨章严格保持一致的内容（用 `CONTINUITY_CORE_START/END` 包裹）
4. **硬约束协议**：要求 AI 在正文前 40% 逐项落实保护块中的事实、动作、禁令

**WriteSync 现状**：
跨章上下文是 ≤800 字的「最近 3 章摘要」，信息损失严重。AI 不知道上一章结尾的具体状态。

**借鉴方案**：
1. 将 `DynamicContext` 的 `recent_chapters` 改为结构化的 `ContinuityEnvelope`
2. 每章确认后自动抽取：
   - `handoff`: 章末状态（位置、角色情绪、进行中的动作、未解决的冲突）
   - `plan_delta`: 章纲节拍 vs 实际内容的偏差
   - `protected`: 需要严格保持的设定/事实
3. Writer agent prompt 中注入 envelope，并加入硬约束指令
4. 这个可以和事实账本配合：`protected` 中的事实来自 FactLedger

**预估工作量**：5-7 天
**影响范围**：`src/agents/context.py`、`src/agents/writer.py`、`src/state/state_types.py`

---

#### 2.4 状态卡（State Cards）

**StoryForge 怎么做**：
跟踪角色在每章的状态变化，不限于属性，而是动态维度的快照：
- 情绪状态、物理位置、当前目标、关系变化
- 每章生成一张状态卡，形成时间线

**WriteSync 现状**：
`DynamicContext` 的角色快照只是静态属性的摘要，没有逐章状态演化。

**借鉴方案**：
1. 在 `DynamicContext` 中新增 `character_states` 字段
2. 每章确认后，LLM 提取每个角色在本章结束时的状态变化
3. 前端上下文面板展示「角色状态时间线」

**预估工作量**：2-3 天
**影响范围**：`src/agents/context.py`、前端上下文面板

---

### 🟢 P2 — 长期锦上添花

#### 2.5 文风学习

**StoryForge 怎么做**：
从用户已完成/修改过的章节中提取写作风格特征（句子长度分布、用词偏好、对话风格、描写密度），注入后续 AI 生成，使产出更贴近用户风格。

**借鉴方案**：
1. 用户确认的章节 → 提取风格特征向量
2. 风格特征存储到 workspace
3. Writer agent prompt 中注入风格约束

---

#### 2.6 Workflow 模板链

**StoryForge 怎么做**：
预定义的多步 AI 调用链，一键执行。例如「极速起书」= Story Core → World Origin → Main Characters → Volume Outline → Ch1 Prose。

**借鉴方案**：
在 WriteSync 的主 Agent 编排基础上，增加「快捷流程」预设。用户可以选择「快速起书」模式，主 Agent 按预设顺序快速推进，减少确认节点。

---

#### 2.7 场景考证

**StoryForge 怎么做**：
`scene-verify-adapter.ts` 交叉引用世界观规则、历史时间线、创作规则来验证特定场景细节的合理性。

**借鉴方案**：
作为辅助检验的扩展（目前 5 项纯规则 + 本章编辑功能），增加场景级的世界观一致性校验。

---

#### 2.8 EPUB 导出 / PWA 支持 / 文档解析导入

低优先级的功能扩展，可根据用户需求逐步添加。

---

## 3. 不借鉴 / 延后借鉴的方面

| StoryForge 特性 | 决策 | 原因 |
|----------------|------|------|
| 纯前端架构 | 不借鉴 | WriteSync 的后端编排是核心差异优势 |
| 45 张 IndexedDB 表 | 不借鉴 | 过度设计，WriteSync 的文件/SQLite 持久化足够 |
| 用户手动触发所有 AI 调用 | 不借鉴 | 主 Agent 智能编排是 WriteSync 的核心竞争力 |
| 多世界支持（诸天流） | 延后 | 细分场景，当前用户群体需求不明确，架构预留即可 |
| 程序化世界地图生成 | 不借鉴 | 与写作核心流程关联弱 |
| 三注册表架构 | **Phase 7 延后引入** | 早期引入是过度抽象，但 Phase 1-6 累积 20+ 功能模块后，三注册表是必要的架构收口手段。**不在 Phase 1-4 做，而在 Phase 7 作为固化步骤** |

---

## 4. 实施路线图建议

```
Week 1-2:  P0.1 提示词模板化 + P0.2 事实账本
Week 3-4:  P1.1 Continuity Envelope + P1.2 状态卡
Week 5+:   P2 各项按需推进
```

每个 P0/P1 项的完整实现应包括：
- 后端模块
- 前端 UI（如涉及）
- 单元测试
- 烟雾测试验证
- 更新 AGENTS.md 已知陷阱（如适用）

---

## 5. 核心设计原则

借鉴 StoryForge 时需保持 WriteSync 的设计哲学：

1. **不破坏主 Agent 编排**：新增功能是对 Agent 能力的增强，不是替代主 Agent 的决策
2. **用户可选择性使用**：新功能应是可选的增强，不是强制流程
3. **保持架构简洁**：7 个 Agent + 纯 Python 循环的架构不要膨胀到 StoryForge 的 30+ 适配器规模
4. **向后兼容**：所有变更不破坏现有项目数据和流程
