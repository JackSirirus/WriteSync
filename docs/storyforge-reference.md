# StoryForge 深度借鉴参考文档

> 📄 **本文档角色：完整规格（Full Specification）**
> 
> 与 [`2026-07-12-storyforge-borrow-analysis.md`](./2026-07-12-storyforge-borrow-analysis.md) 的关系：
> - **borrow-analysis** = 执行摘要 — 精选 8 项可借鉴功能，含工作量估算和优先级排序
> - **本文档** = 完整规格 — 20 项功能详细设计、数据模型、接口定义、架构演化路线图
> 
> 两个文档没有矛盾，仅有粒度差异。实际开发以 borrow-analysis 的优先级排序为准，以本文档的详细设计为参考。

> **目标**：从 [StoryForge（故事熔炉）](https://github.com/yuanbw2025/storyforge) 的系统分析中提取可供 WriteSync（共笔）借鉴的设计理念、架构模式和功能特性。
> 
> **对比时间**：2026-07-12 · StoryForge v3.7.5 / WriteSync v0.5.0
> 
> **核心定位差异**：
> - StoryForge = **作者控制的 AI 工坊**（提示词全透明、结构化设定管理、纯前端本地优先）
> - WriteSync = **AI 驱动的写作流水线**（主Agent自主编排、用户-AI 共创、Python后端）
> 
> 本文件的借鉴策略**不是照搬**，而是在保持 WriteSync 自动化优势的前提下，吸收 StoryForge 在"用户掌控力"和"结构化设定"方面的设计智慧。

---

## 目录

- [一、核心理念转变](#一核心理念转变)
  - [1.1 LLM 角色：从"导演"到"助手"](#11-llm-角色从导演到助手)
  - [1.2 编排器：从"自主决策"到"辅助决策"](#12-编排器从自主决策到辅助决策)
  - [1.3 用户掌控感：从"AI驱动确认"到"作者主动选择"](#13-用户掌控感从ai驱动确认到作者主动选择)
- [二、技术架构借鉴](#二技术架构借鉴)
  - [2.1 AI Provider 多源化](#21-ai-provider-多源化)
  - [2.2 数据持久化升级](#22-数据持久化升级)
  - [2.3 离线能力](#23-离线能力)
  - [2.4 上下文管理](#24-上下文管理)
  - [2.5 架构纪律](#25-架构纪律)
  - [2.6 AI 输出安全性](#26-ai-输出安全性)
  - [2.7 跨章一致性](#27-跨章一致性)
- [三、功能特性借鉴（按优先级）](#三功能特性借鉴按优先级)
  - [P0 - 核心写作体验](#p0---核心写作体验)
  - [P1 - 长篇创作管理](#p1---长篇创作管理)
  - [P2 - 作者工作台增强](#p2---作者工作台增强)
- [四、详细功能规格](#四详细功能规格)
  - [4.1 采纳机制（Adoption Pattern）](#41-采纳机制adoption-pattern)
  - [4.2 伏笔追踪系统](#42-伏笔追踪系统)
  - [4.3 事实库与长期记忆](#43-事实库与长期记忆)
  - [4.4 状态表与物品栏](#44-状态表与物品栏)
  - [4.5 提示词模板系统](#45-提示词模板系统)
  - [4.6 多世界架构](#46-多世界架构)
- [五、架构演化路线图建议](#五架构演化路线图建议)
- [六、StoryForge 关键设计模式速查](#六storyforge-关键设计模式速查)

---

## 一、核心理念转变

### 1.1 LLM 角色：从"导演"到"助手"

**当前状态（WriteSync）**：
```
主Agent（deepseek-v4-pro）是创作过程的"导演"：
- 自主决策下一步调用哪个子Agent
- 自主判断当前阶段（new → planning → writing → review）
- 用户只在 confirm 节点介入
```

**目标方向**：
```
LLM 是作者的"助手团队"：
- LLM 提供建议和选项，不替作者做决定
- 作者选择方向，AI 执行展开
- 每个 AI 输出都经过"预览→采纳/修改/拒绝"的流程
```

**具体改动思路**：

| 场景 | 当前（LLM是导演） | 目标（LLM是助手） |
|------|------------------|------------------|
| 下一步做什么 | 主Agent自主决策下一个Agent | 主Agent产出2-3个建议选项，作者选择 |
| Agent输出 | 直接输出结果，用户确认/反馈 | 输出预览→用户编辑/采纳/拒绝/要求重做 |
| 阶段跃迁 | 主Agent自动判断阶段 | 阶段建议由LLM提出，作者手动确认跃迁 |
| 写作参数 | 固定模板+模型 | 作者可在每个步骤选择模型/参数/模板 |

**实施建议**：
1. 在编排器中增加"建议模式"：主Agent产出 `Suggestions[]`（含推理+选项），前端展示给作者选择
2. 每个Agent的输出增加"采纳面板"：预览渲染 → 编辑区 → 采纳/重做/修改后采纳
3. 允许作者在编排过程中随时"打断"并指定下一步

### 1.2 编排器：从"自主决策"到"辅助决策"

**当前状态**：
```
主Agent决策流程：
  orchestrate(state) → decision: {next_agent, reasoning}
  → 直接执行 next_agent
  → 用户确认结果 → 循环
```

**目标方向**：
```
主Agent决策流程：
  orchestrate(state) → proposal: {
    suggestion: "建议下一步做什么",
    options: [
      {action: "call_agent writer", reasoning: "章纲已确认，可以开始写第一章", confidence: 0.92},
      {action: "call_agent character", reasoning: "主角设定还不够丰满", confidence: 0.75},
      {action: "call_agent outline", reasoning: "需要先完善章纲再动笔", confidence: 0.88},
    ],
    phase_suggestion: "writing_chapters"
  }
  → 前端展示 options → 作者选择 → 执行
  → 作者也可以手动指定任意Agent
```

**核心变化**：
- 主Agent从"决策者"变为"参谋"
- 出具多个选项+置信度+推理，供作者参考
- 作者可以自由选择、组合或完全手动指定

### 1.3 用户掌控感：从"AI驱动确认"到"作者主动选择"

**StoryForge 的做法**（借鉴目标）：
- 每个AI功能有独立的"触发按钮"，作者主动点击才执行
- AI输出预览后，作者选择"采纳/编辑后采纳/丢弃"
- 提示词可见可改，作者知道AI为什么这样写
- 工作流引擎将多个AI步骤串联，但作者依然可以控制每个节点

**WriteSync 的改进方向**：
1. **增加"预览→采纳"环节**：不只是确认/反馈，而是可编辑的采纳面板
2. **开放提示词**：每个Agent的System Prompt和User Template对作者可见（可选修改）
3. **增加"手动模式"**：允许作者跳过编排器，直接在界面上选择要调用的Agent
4. **建议与执行分离**：编排器只提建议，执行由作者确认

---

## 二、技术架构借鉴

### 2.1 AI Provider 多源化

**StoryForge 现状**（借鉴目标）：
```
支持的 Provider（20+）：
国际：OpenAI / Anthropic Claude / Google Gemini / Poe / NVIDIA NIM
国内：DeepSeek / 通义千问 / 豆包 / 智谱GLM / 文心一言 / Kimi
      MiniMax / ModelScope / Agnes AI / LongCat / OpenCode Go
本地：Ollama / LM Studio / 自定义OpenAI-compatible端点
```

**WriteSync 当前限制**：仅支持 OpenCode Go 网关单一通道。

**借鉴方案**：

```python
# Provider 配置抽象层（思路）
@dataclass
class AIProviderConfig:
    name: str
    provider_type: Literal["opencode", "openai", "anthropic", "gemini", "ollama", "custom"]
    base_url: str
    api_key: str | None = None
    default_model: str = ""
    max_tokens: int = 4096
    context_window: int = 128000

# 模型路由策略
class ModelRouter:
    """根据任务类型自动选择最优模型"""
    def select(self, task_type: str, user_preference: str | None = None) -> tuple[AIProviderConfig, str]:
        """
        编排器决策用: pro/推理模型（高质量、短prompt）
        子Agent执行用: flash/快速模型（长prompt、高吞吐）
        用户可覆盖默认路由
        """
        ...
```

**实施要点**：
1. 配置管理：支持多Provider配置，每个配置包含 base_url / api_key / model / parameters
2. 模型路由：按任务类型（决策 vs 执行 vs 校对）自动选择最优模型
3. 用户覆盖：允许在编排过程中临时切换模型
4. 本地优先：支持 Ollama / LM Studio，彻底解决API成本问题
5. 失败降级：主Provider失败时自动切换到备用Provider

### 2.2 数据持久化升级

**StoryForge**：Dexie.js + IndexedDB，42张表，完整CRUD + 事务 + 索引。

**WriteSync 当前**：JSON文件存储（`projects/`目录），无索引/查询/事务。

**借鉴方向**：

| 维度 | 当前（JSON文件） | 目标（SQLite） |
|------|-----------------|---------------|
| 存储引擎 | 文件系统读写 | SQLite（Python内置） |
| 查询能力 | 无（全量加载后filter） | SQL + 索引 |
| 事务 | 无 | ACID事务 |
| 并发 | 单进程文件锁 | WAL模式多线程 |
| 迁移 | 手动文件操作 | schema版本+迁移脚本 |
| 备份 | 文件复制 | JSON dump / .backup |

**建议方案**：

```
Python 3.10+ 自带 sqlite3
↓
使用 ProjectTable 管理所有表的生命周期（借鉴 StoryForge PROJECT_TABLES 理念）
↓
保持 JSON 导出导入作为备份/迁移格式
↓
新增表时只需在注册表中添加一行定义
```

```python
# 数据表注册表（借鉴 StoryForge PROJECT_TABLES）
PROJECT_TABLES = {
    "projects": {"sql": "CREATE TABLE projects (id TEXT PK, name TEXT, ...)", "exportable": True},
    "characters": {"sql": "CREATE TABLE characters (id TEXT PK, project_id TEXT FK, ...)", "exportable": True},
    "chapters": {"sql": "CREATE TABLE chapters (id TEXT PK, project_id TEXT FK, ...)", "exportable": True},
    # ... 表定义统一收口，派生 CRUD / 导出 / 导入 / 删除
}
```

**迁移策略**：
1. Phase 1：保持JSON + 增加SQLite并行写入（双写）
2. Phase 2：切换为SQLite为主，JSON作为导出格式
3. Phase 3：下线JSON持久化

### 2.3 离线能力

**StoryForge**：纯前端PWA，完全离线运行，所有数据在浏览器IndexedDB。

**WriteSync 当前**：依赖Python后端运行，无法离线。

**借鉴方向**：
1. **本地模型集成**：支持 Ollama/LM Studio，AI推理在本地完成
2. **离线缓存层**：Web UI 缓存最近项目数据到 IndexedDB（前后端分离后）
3. **PWA 包装**：将 Web UI 包装为 PWA，支持离线访问静态资源
4. **本地优先架构**：先写本地、再同步到后端（长期方向）

**短期可行方案**（不改变后端架构）：
- 支持 `python -m src.cli --local-model ollama` 模式，使用本地模型
- Web UI + Service Worker 缓存静态资源，断网时可查看已加载页面

### 2.4 上下文管理

**StoryForge 的四层记忆**（借鉴目标）：

```
L1 - 章节交接（continuityHandoff）：
    上一章结尾的精确状态 → 下一章开头使用
L2 - 层级摘要（narrativeSummaryNodes）：
    长篇滚动摘要，确定性 roll-up
L3 - 事实账本（temporalFacts canon）：
    已确认的事实 → 后续生成保护（不被推翻）
L4 - 原文检索（retrievalChunks）：
    远距离细节召回 + 混合检索
```

**WriteSync 当前**：单层动态上下文引擎（≤800字摘要 + 角色变化 + 一致性检测 + 伏笔追踪）。

**借鉴方向**：
1. **增加层级**：将动态上下文拆为多层（当前章交接/近3章摘要/全局事实/原文检索）
2. **事实账本**：从已确认的章节中提取"已发生事实"，后续生成中做约束
3. **预算裁剪**：StoryForge的L0保护块（关键上下文永不裁掉）+ L1→L2→L3逐级裁剪
4. **记忆闭环**：读→写→下一轮继续读的闭环（WriteSync已部分实现，可强化）

```python
# 上下文预算分层（借鉴方案）
class ContextBudget:
    L0: int = 2000    # 保护块：当前章纲+创作规则（永不裁剪）
    L1: int = 3000    # 角色状态+已确认事实
    L2: int = 2000    # 近3章摘要+伏笔状态
    L3: int = 3000    # 原文检索结果+远距离上下文
    total: int = 10000  # 总预算上限
    
    def assemble(self, state) -> str:
        """按优先级分层装配，超出预算时裁L3→L2→L1"""
```

### 2.5 架构纪律

**StoryForge 的三注册表**（借鉴目标，非照搬）：

```
CONTEXT_SOURCES   → AI读什么（上下文装配的统一入口）
FIELD_REGISTRY    → AI写什么（字段映射 + 采纳校验）
PROJECT_TABLES    → 表生命周期（CRUD/导出/导入/删除全派生）
```

**针对 WriteSync 的简化应用**：

```python
# 1. Agent 注册表（统一管理所有Agent的定义）
AGENT_REGISTRY = {
    "story": AgentDef(
        module="src.agents.story",
        input_schema=StoryInput,
        output_schema=StoryOutput,
        context_sources=["project_info", "genre_guide"],
        allowed_phases=["new", "planning"],
        model_preference="deepseek-v4-pro",
    ),
    "character": AgentDef(...),
    "writer": AgentDef(...),
    # 新增Agent只需在此注册，编排器自动发现
}

# 2. 上下文源注册表（取代各Agent手拼上下文）
CONTEXT_SOURCES = {
    "project_info": {"builder": "build_project_context", "scope": "global", "priority": 1},
    "characters": {"builder": "build_character_context", "scope": "project", "priority": 2},
    "world_lore": {"builder": "build_world_context", "scope": "project", "priority": 3},
    "cross_chapter_memory": {"builder": "build_memory_context", "scope": "dynamic", "priority": 4},
    # 统一收口，任何Agent需要上下文都走 assemble_context()
}

# 3. 持久化表注册表（统一定义数据生命周期）
PERSISTENCE_TABLES = {
    "projects": {"table": ProjectModel, "exportable": True, "cascade_delete": []},
    "chapters": {"table": ChapterModel, "exportable": True, "cascade_delete": ["chapter_notes"]},
    # ...
}
```

**核心原则**（借鉴 StoryForge 宪法）：
- 任何Agent的输入输出必须经注册表定义 → 不自拼prompt、不自写字段映射
- 任何数据操作必须经注册表派生 → 不自写CRUD、不散落手写
- 新增Agent/字段/表只改注册表一处 → 生命周期自动覆盖

### 2.6 AI 输出安全性

**StoryForge 的多层安全网**（借鉴目标）：

```
AI输出 → ① AdoptionSchema 类型校验（字段类型/枚举/FK）
       → ② 去重校验（按name/key去重）
       → ③ 受控谓词校验（不允许未注册的字段）
       → ④ 用户预览+采纳确认
       → ⑤ hash/CAS溯源（正文变更→派生记忆stale）
       → ⑥ 引文逐字回查（AI引用的原文必须存在）
```

**WriteSync 当前**：用户确认机制（较简单）。

**借鉴方向**：

```python
# 采纳校验层（借鉴 AdoptionSchema）
class AdoptionValidator:
    def validate(self, agent_output: dict, target_field: str) -> ValidationResult:
        """
        1. 字段白名单校验（不允许未注册字段写入）
        2. 类型校验（str/int/float/bool/list/dict）
        3. 枚举校验（如角色戏份: main/secondary/npc/extra）
        4. 外键存在性校验（如引用的角色ID必须存在）
        5. 去重校验（批量写入时按name去重）
        """
        ...

    def adopt(self, validated_data: dict) -> AdoptResult:
        """校验通过后写入，记录溯源hash"""
        ...
```

**实施要点**：
1. 每个Agent的输出定义 Schema，AI输出必须经Schema校验才能落库
2. 不允许AI写入Schema中未定义的字段（防止幻觉字段）
3. 正文变更时标记所有依赖该正文的派生数据为"待复核"

### 2.7 跨章一致性

**StoryForge 的解决方案**（借鉴目标）：
- 四层记忆闭环（章节交接 / 层级摘要 / 事实账本 / 原文检索）
- hash溯源：正文变更→派生记忆stale→影响分析
- 物品持有硬校验：防止物品重复获得
- 事实账本护卫：已确认事实不能被后续生成推翻
- 未来章过滤：生成当前章时只召回之前章节的内容

**WriteSync 当前**：动态上下文引擎（角色变化提取+一致性检测+前章摘要）。

**借鉴方向**：

| 机制 | StoryForge | WriteSync 当前 | 借鉴优先级 |
|------|-----------|---------------|-----------|
| 事实账本 | ✅ temporalFacts canon | ❌ 无 | 🔴 P0 |
| 章节交接 | ✅ continuityHandoff | ⚠️ 前章摘要 | 🟡 P1 |
| 溯源失效 | ✅ hash→stale→影响分析 | ❌ 无 | 🟡 P1 |
| 未来章过滤 | ✅ 只召回当前章之前 | ❌ 无 | 🟡 P1 |
| 上下文预算裁剪 | ✅ L0/L1/L2/L3分层 | ❌ 固定800字 | 🟠 P2 |

**事实账本优先实施**（最小可行方案）：

```python
class FactLedger:
    """事实账本：从已确认章节中提取已发生事实"""
    
    def extract_facts(self, chapter_content: str) -> list[Fact]:
        """从正文中提取事实候选"""
        ...
    
    def confirm_fact(self, fact: Fact):
        """用户/系统确认事实为canon"""
        ...
    
    def get_active_facts(self, up_to_chapter: int) -> list[Fact]:
        """获取截至某章的所有已确认事实"""
        ...
    
    def inject_into_prompt(self, facts: list[Fact], max_tokens: int = 1000) -> str:
        """将事实注入写作提示词，约束AI不推翻已确认事实"""
        ...
```

---

## 三、功能特性借鉴（按优先级）

### P0 - 核心写作体验

| # | 功能 | StoryForge 实现 | WriteSync 现状 | 借鉴思路 |
|---|------|----------------|---------------|---------|
| 1 | **提示词模板系统** | 系统模板+用户模板+克隆+题材包+参数控件+工作流 | 固定prompt，不可见不可改 | 开放每个Agent的System Prompt和User Template，允许作者查看/克隆/修改 |
| 2 | **采纳机制** | 预览→编辑→采纳，不自动覆盖 | 确认/反馈循环 | 增加采纳面板：预览渲染→编辑区→采纳/重做/修改后采纳 |
| 3 | **多Provider** | 20+Provider + 本地模型 | 仅OpenCode Go | 增加Provider配置层，支持多模型路由+本地模型 |
| 4 | **灵感反推** | 短梗→结构化创作资料 | ❌ 无 | 增加"灵感→故事核心/世界观/角色/大纲"反推功能 |
| 5 | **创作规则** | 风格/视角/基调/禁忌/参考作品注入 | ❌ 在writer prompt中硬编码 | 独立创作规则模块，用户可配置写作约束 |

### P1 - 长篇创作管理

| # | 功能 | StoryForge 实现 | WriteSync 现状 | 借鉴思路 |
|---|------|----------------|---------------|---------|
| 6 | **伏笔追踪** | 看板视图+埋设/呼应/回收+紧急度 | ❌ 无 | 增加伏笔管理面板（类型/状态/关联章节/紧急度看板） |
| 7 | **事实库/长期记忆** | 四层记忆（交接/摘要/事实/检索） | 动态上下文引擎 | 增加事实账本+章节交接+溯源失效机制 |
| 8 | **跨章一致性** | hash溯源+事实护卫+未来章过滤 | 简单的上下文注入 | 实施事实账本护卫（已确认事实不被推翻） |
| 9 | **状态表** | 角色状态卡+地点/势力/持有物聚合 | ❌ 无 | 增加状态表：角色的当前状态/地点/伤势/持有物追踪 |
| 10 | **物品栏账本** | 物品流水（获得/持有/转移/消耗） | ❌ 无 | 增加物品流水追踪（谁持有、何时获得、何时消耗） |
| 11 | **多世界** | 多世界组+世界关系+归属管理 | ❌ 无 | 考虑是否要做（适合诸天流/无限流），至少预留架构 |

### P2 - 作者工作台增强

| # | 功能 | StoryForge 实现 | WriteSync 现状 | 借鉴思路 |
|---|------|----------------|---------------|---------|
| 12 | **故事年表** | 剧情事件时间线 | ❌ 无 | 增加全局事件时间线（按章节+剧情时间排序） |
| 13 | **文风学习** | 从已写章节提取文风画像 | ❌ 无 | 从已确认章节提取句式/节奏/词汇偏好，注入后续生成 |
| 14 | **场景考证** | 结合世界观/历史/规则检查场景 | ❌ 无 | 与事实库联动，检查场景设定一致性 |
| 15 | **项目参考** | 故事参考/风格参考/历史资料管理 | ❌ 无 | 增加参考资料库（可注入AI上下文） |
| 16 | **文档解析导入** | 大文档流水线+断点续跑 | ❌ 无 | 支持导入外部文档（设定集/旧稿/资料）  |
| 17 | **版本历史** | 自动快照+手动快照+恢复 | ❌ 无 | 增加项目快照机制（写入前自动备份） |
| 18 | **导出格式** | JSON/MD/TXT/HTML/Gist/文件夹 | MD/TXT | 增加HTML导出+JSON完整备份+自动备份 |
| 19 | **消耗统计** | 调用次数/token/费用估算 | ❌ 无 | 增加AI调用用量统计 |
| 20 | **PWA/离线** | 纯浏览器运行+Service Worker | 依赖后端 | 长期方向：考虑前后端分离+Web UI离线缓存 |

---

## 四、详细功能规格

### 4.1 采纳机制（Adoption Pattern）

**借鉴来源**：StoryForge `adopt()` + `FIELD_REGISTRY` + `ADOPTION_SCHEMAS`

**目标**：AI 输出不是直接落库，而是经过"校验→预览→采纳"的三步流程。

**接口设计**：

```
作者触发AI生成
  → AI输出（原始文本/结构化数据）
  → 采纳面板展示：
      ├─ 渲染预览（Markdown渲染/结构化数据表格）
      ├─ 内联编辑区（作者可直接修改）
      ├─ 对比视图（原有内容 ↔ AI生成内容）
      └─ 操作按钮：[采纳] [编辑后采纳] [重做] [拒绝]
  → 采纳后：
      ├─ 通过 Schema 校验字段类型/枚举/FK
      ├─ 记录溯源hash
      └─ 写入数据库
```

**数据结构**：

```python
@dataclass
class AdoptableOutput:
    agent_name: str
    output_type: str  # "text" / "structured" / "mixed"
    content: str | dict  # AI原始输出
    rendered_preview: str  # 渲染后预览
    schema_def: dict | None  # 字段定义（用于校验）
    source_hash: str  # 溯源hash

class AdoptionResult:
    adopted: bool
    modified: bool  # 用户是否手动修改过
    validated: bool  # Schema校验是否通过
    target_field: str  # 写入的目标字段
    final_content: str | dict  # 最终落库内容
```

### 4.2 伏笔追踪系统

**借鉴来源**：StoryForge Foreshadow kanban + 埋设/呼应/回收

**目标**：跟踪全书的"未兑现承诺清单"，防止伏笔丢失。

**数据模型**：

```python
@dataclass
class Foreshadow:
    id: str
    project_id: str
    title: str
    description: str
    foreshadow_type: str  # "plot" / "character" / "item" / "mystery"
    status: str  # "planned" / "planted" / "called_back" / "resolved"
    
    # 关联章节
    planted_chapter: str | None  # 埋设章节ID
    callback_chapters: list[str]  # 呼应章节ID列表
    resolved_chapter: str | None  # 回收章节ID
    
    # 紧急度
    urgency: int  # 1-5，越高越紧急
    expected_callback_range: str  # "前1/3" / "中段" / "后段" / "完结前"
    deadline_chapter: int | None  # 最迟回收章节号
    
    created_at: datetime
    updated_at: datetime
```

**UI 建议**：
- 看板视图：planned → planted → called_back → resolved
- 列表视图：按紧急度排序，高亮即将逾期的伏笔
- 注入 writer prompt：写当前章时提示"本章有3个伏笔需要呼应"

### 4.3 事实库与长期记忆

**借鉴来源**：StoryForge 四层记忆（temporalFacts + 连续性handoff + 摘要roll-up + 检索chunks）

**目标**：从"单层动态上下文"升级为"多层长期记忆体系"。

**架构**：

```
写入路径：
  章节确认 → ① 章节交接提取（continuationHandoff）
           → ② 层级摘要更新（narrativeSummary）
           → ③ 事实提取 → temporalFacts候选
           → ④ 原文切片 → retrievalChunks

读取路径（写作前装配）：
  assemble_context()
    → L0: 创作规则 + 当前章纲（必须包含）
    → L1: 上一章交接 + 当前角色状态
    → L2: 已确认事实（readCurrentFacts）
    → L3: 近3章摘要
    → L4: 检索召回远距离上下文（可选）
```

**最小可行实现（P0）**：

```python
class CrossChapterMemory:
    """跨章记忆（简化版，先做事实账本）"""
    
    # 存储
    chapter_handoffs: dict[int, str]  # 每章结尾状态
    confirmed_facts: list[dict]  # 已确认事实列表
    chapter_summaries: dict[int, str]  # 每章摘要
    
    def on_chapter_confirm(self, chapter_num: int, content: str):
        """章节确认时自动提取"""
        handoff = self._extract_handoff(content)
        facts = self._extract_facts(content)
        summary = self._summarize(content)
        self.chapter_handoffs[chapter_num] = handoff
        self.confirmed_facts.extend(facts)
        self.chapter_summaries[chapter_num] = summary
    
    def build_writer_context(self, current_chapter: int) -> str:
        """装配writer的跨章上下文"""
        parts = []
        # L1: 上一章交接
        if current_chapter - 1 in self.chapter_handoffs:
            parts.append(f"【上章结尾】{self.chapter_handoffs[current_chapter - 1]}")
        # L2: 已确认事实
        active_facts = [f for f in self.confirmed_facts if f["chapter"] < current_chapter]
        parts.append(f"【已确认事实】{self._format_facts(active_facts)}")
        # L3: 近3章摘要
        for i in range(max(1, current_chapter - 3), current_chapter):
            if i in self.chapter_summaries:
                parts.append(f"【第{i}章概要】{self.chapter_summaries[i]}")
        return "\n\n".join(parts)
```

### 4.4 状态表与物品栏

**借鉴来源**：StoryForge StateTable + Inventory（状态卡 + 物品流水账本）

**目标**：追踪角色关键状态和重要物品的持有变化。

**状态表（最小实现）**：

```python
@dataclass
class CharacterState:
    character_id: str
    project_id: str
    
    # 状态字段（可扩展）
    current_location: str | None = None
    current_status: str | None = None  # 如"受伤"、"逃亡"、"谈判中"
    health_state: str | None = None
    relationship_status: dict[str, str] = None  # character_id → "友好/敌对/暧昧"
    held_items: list[str] = None  # 当前持有物品ID列表
    
    # 元数据
    last_updated_chapter: int = 0
    last_updated_at: datetime = None
```

**物品栏（最小实现）**：

```python
@dataclass
class ItemLedger:
    """物品账本（流水式）"""
    item_id: str
    item_name: str
    project_id: str
    
    # 流水记录
    transactions: list[ItemTransaction] = None

@dataclass
class ItemTransaction:
    item_id: str
    action: Literal["acquire", "transfer_in", "transfer_out", "consume", "lose", "destroy"]
    holder: str  # 持有者character_id（或"Narrator"）
    previous_holder: str | None = None
    chapter: int  # 发生章节
    quantity: int = 1
    note: str = ""
```

### 4.5 提示词模板系统

**借鉴来源**：StoryForge Prompt Library（模板库 + 参数控件 + 题材包 + 工作流）

**目标**：每个Agent的prompt对作者可见可改，支持模板变量和参数化。

**架构**：

```
提示词模板系统
├── 系统模板（内置，只读，可克隆）
│   ├── story-planner
│   ├── character-designer
│   ├── writer-draft
│   └── proofreader
├── 用户模板（克隆自系统模板，可自由修改）
│   └── my-writer-style  (克隆自 writer-draft)
├── 题材包（预置题材风格的热切换）
│   ├── 仙侠
│   ├── 历史
│   ├── 悬疑推理
│   └── 都市
├── 参数控件
│   ├── select (如叙事视角: 第一人称/第三人称有限/第三人称全知)
│   ├── slider (如爽点密度: 1-10)
│   └── boolean (如是否启用伏笔感知)
└── 工作流
    └── 步骤序列（策划→角色→世界观→大纲→写作）
```

**模板渲染引擎**：

```python
class PromptTemplate:
    system_template: str  # "你是一个{{genre}}小说写作助手..."
    user_template: str    # "请根据以下章纲写正文：\n{{outline}}"
    parameters: dict      # {"genre": "仙侠", "outline": "..."}
    
    def render(self, context: dict) -> tuple[str, str]:
        """渲染system + user prompt"""
        system = self._render_template(self.system_template, context)
        user = self._render_template(self.user_template, context)
        return system, user
```

### 4.6 多世界架构

**借鉴来源**：StoryForge MultiWorld（世界组 + 世界关系 + 归属管理）

**目标**：支持诸天流/无限流/多宇宙题材，不同世界独立维护设定。

**核心概念**：

```
项目（Project）
└── 世界组（WorldGroup）x N
    ├── 主世界（primary）
    └── 次级世界（secondary）x N
        ├── 世界观（独立）
        ├── 角色（独立/共享）
        ├── 大纲（按世界过滤）
        └── 章节（按世界过滤）
```

**是否实施的判断**：
- 如果目标用户以单世界写作为主，多世界不是必须的
- 但架构需要预留 `world_group_id` 字段，避免后续重构
- **建议**：先做数据模型预留，不做UI和编排器集成

---

## 五、架构演化路线图建议

借鉴 StoryForge 的 Phase 系统，建议 WriteSync 按以下阶段演进：

### Phase 1 —— 采纳与透明（1-2周）【计划中】
- [ ] 采纳面板：AI输出预览→编辑→采纳
- [ ] 提示词开放：Agent的system prompt对作者可见
- [ ] 编排器建议模式：多选项+置信度

### Phase 2 —— Provider多源化（1周）【计划中】
- [ ] Provider配置管理界面
- [ ] 模型路由（决策模型/执行模型分离）
- [ ] Ollama本地模式支持

### Phase 3 —— 事实库与长期记忆（2周）【计划中】
- [ ] 事实账本：从章节提取已确认事实
- [ ] 章节交接：上下章衔接状态
- [ ] 上下文预算分层裁剪

### Phase 4 —— 结构化设定管理（3周）【计划中】
- [ ] 伏笔追踪系统
- [ ] 状态表与物品栏
- [ ] 创作规则模块
- [ ] 灵感反推功能

### Phase 5 —— 数据持久化升级（2周）【计划中】
- [ ] SQLite迁移
- [ ] 数据表注册表
- [ ] 导出格式丰富（HTML/JSON备份）
- [ ] 版本快照

### Phase 6 —— 作者工作台增强（3周）【计划中】
- [ ] 故事年表
- [ ] 文风学习
- [ ] 项目参考资料库
- [ ] 文档解析导入
- [ ] 消耗统计

### Phase 7 —— 架构固化（1周）【计划中】
- [ ] Agent注册表
- [ ] 上下文源注册表
- [ ] 数据表注册表
- [ ] 架构 lint + CI 校验

---

## 六、StoryForge 关键设计模式速查

| 模式 | StoryForge 对应 | 核心思想 |
|------|----------------|---------|
| **单一事实源** | 三个注册表 | 任何数据/表/上下文源只在一处登记，派生所有操作 |
| **采纳模式** | adopt() + FIELD_REGISTRY | AI输出必须经校验+用户确认才能落库 |
| **软硬分离** | AI造零件（软） + 代码车床质检（硬） | AI生成/抽取是软的，代码校验/簿记/隔离是硬的 |
| **四层记忆** | 交接/摘要/事实/检索 | 不同记忆解决不同尺度的跨章一致性问题 |
| **预算裁剪** | L0→L1→L2→L3分层 | 关键上下文永远不会被裁掉 |
| **引用即声明** | PROJECT_TABLES.refs | 所有外键/JSON引用/数组引用必须注册，不允许潜规则 |
| **集合不是字段** | AdoptionSchema | 多值写回（角色/伏笔等）必须有独立的去重+FK校验 |
| **文档由代码生成** | AI manual自动生成 | AI功能说明书不是手写的，是由代码扫描生成的 |

---

## 附录：StoryForge 项目快照

| 指标 | 数据 |
|------|------|
| 仓库 | [yuanbw2025/storyforge](https://github.com/yuanbw2025/storyforge) |
| Stars | 275 |
| 版本 | v3.7.5（7个Release） |
| 技术栈 | React 19 + TypeScript 5 + Zustand 5 + Dexie 4 + Vite 6 + TipTap 3 |
| 代码量 | 282个源文件 / 59,020行 TS/TSX |
| 数据表 | 42张（IndexedDB via Dexie.js） |
| AI Provider | 20+ (OpenAI/Claude/Gemini/DeepSeek/豆包/智谱/Ollama等) |
| 架构约束 | 三注册表（CONTEXT_SOURCES / FIELD_REGISTRY / PROJECT_TABLES） |
| 已知P0级bug | 8个（重构Phase 0中） |
| 许可 | MIT |
| 适合题材 | 长篇、系列文、多世界、群像、历史/架空深度考据 |
| 不适合 | 一键生成、团队协作、后端托管 |

---

## 更新记录

- 2026-07-12：初版，基于 StoryForge v3.7.5 全量分析
