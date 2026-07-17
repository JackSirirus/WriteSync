# 竞品调研与借鉴文档

> WriteSync（共笔）项目

## 调研范围

- Craft Companion (qcx1919788736-collab/craft-companion)
- NovelClaw (iLearn-Lab/NovelClaw)
- chronicler (shyuni4u/chronicler)
- nico (applebiter/nico)
- multi-agent-novel-system

---

## 竞品分析

### 1. Craft Companion

**基本信息**
- 仓库：https://github.com/qcx1919788736-collab/craft-companion
- 技术栈：Node.js (CLI)
- License：MIT
- 定位：AI 协作小说创作框架（非产品，是方法论框架）

**核心特性**
- 5阶段工作流：章纲 → 初稿 → 自查（双层）→ 修订 → 终版确认
- 双层质量保障：执行层自查 + 评估层复核
- 结构化知识库（5层）
- 双入口：从零开始 / 导入已有小说
- checkpoint 机制 + 知识库更新
- 推荐工具：Codex / Claude Code（多 agent 协作）

**架构图**
```
用户请求 → 入口分流 → 初始化/导入 → 知识库就绪
→ 执行层 Writer（章纲→初稿→自查）
→ 评估层 Evaluator（confirmed/disputed/dismissed）
→ 仲裁层 Arbiter（裁决 disputed + 修订）
→ 终版确认 + 检查点 + 知识库更新
```

**知识库分层**
```
00_核心上下文/   ← 每次创作必读
01_人物档案/
02_世界观设定/
03_故事进展/
04_写作参考/
```

**章纲输出格式**
包含：核心事件、关键场景、人物状态变化、伏笔操作、情绪节奏与详略、预计字数

**终版自查清单（可复用）**
- 设定层：数值、机制、时间线一致性
- 人物层：OOC、渐进性成长、知识边界
- 结构层：承接性、篇幅分配、世界观信息不滑入课堂模式
- 文字层：叙事效率、单句成段、情绪动作去重
- 伏笔层：伏笔植入三问（何时？谁的视角？能否立刻走？）

**优点**
- 三层分离架构清晰，执行/评估/仲裁各司其职
- 知识库分层设计优秀，减少 AI 跑偏
- 5阶段工作流可操作性强
- 终版自查清单可直接复用为编辑 Agent 评估标准
- 双入口设计降低冷启动门槛
- 有完整的错题集和微调意图学习库

**不足**
- 不是真正的 multi-agent，是单 AI + 流程编排
- 无雪花写作法原生融合
- 无 UI，纯 CLI / Codex 协作
- 网文场景无专属优化

---

### 2. NovelClaw

**基本信息**
- 仓库：https://github.com/iLearn-Lab/NovelClaw
- 技术栈：Python, FastAPI
- Stars：195
- 定位：长篇小说协作写作平台（在线）
- 地址：https://colong-idea-studio.cloud/

**核心特性**
- Memory-aware 写作控制
- 章节级控制 + session 持续性
- 可检查的运行日志（worker.log, progress.log）
- Portal / MultiAgent / NovelClaw 三层入口
- 稿本界面、故事板、世界观/角色视图
- 有中文 README

**架构**
- Portal：公共入口层
- MultiAgent：可选的快速构思层
- NovelClaw：主写作工作区

**优点**
- 完整的 Web UI，用户体验好
- session + memory 机制解决长篇记忆问题
- 运行日志可完全检查，用户知道 AI 在做什么
- 有稿本对比功能（草稿 vs 修订版 vs 终版）
- 中文友好

**不足**
- Multi-agent 是可选层，核心仍是单 agent 为主
- 无雪花写作法
- 架构偏复杂（三层入口）
- 网文场景无专属优化

---

### 3. chronicler

**基本信息**
- 仓库：https://github.com/shyuni4u/chronicler
- 技术栈：TypeScript
- 定位：AI-powered multi-agent 长篇写作系统

**核心特性**
- TypeScript 原生 multi-agent
- Agent 分工：世界观、角色、情节
- 章节逐章推进

**优点**
- 真正的 multi-agent 分工
- TypeScript/Node.js 生态

**不足**
- 新项目，信息少
- 无雪花写作法
- 无中文支持

---

### 4. nico

**基本信息**
- 仓库：https://github.com/applebiter/nico
- 技术栈：Python
- 定位：类 Scrivener 的本地优先写作工具 + AI 辅助

**核心特性**
- 本地优先，隐私保护
- 角色/世界/事件/主题管理
- ComfyUI 集成（图片生成）

**优点**
- 本地优先，数据安全
- 结构化故事工具完整

**不足**
- 非 multi-agent
- 无协作流程
- 无雪花写作法

---

## 关键发现

1. **没有项目同时做到**：multi-agent 协作 + 雪花写作法 + 中文网文
2. **Craft Companion 最接近我们的方法论**，但不是真正的 multi-agent
3. **NovelClaw 提供了最好的 UX 参考**，但核心是单 agent
4. **"craft companies" 这个名字**实际是 craft-companion，定位是框架而非产品

---

## 可借鉴内容汇总

### 直接复用

| 来源 | 可复用内容 | 用途 |
|------|-----------|------|
| Craft Companion | 知识库5层结构 | 设计 WriteSync 知识库 |
| Craft Companion | 三层分离架构（执行/评估/仲裁） | 设计 Agent 协作流程 |
| Craft Companion | 5阶段工作流 | 对齐雪花写作法 |
| Craft Companion | 终版自查清单 | 作为编辑 Agent 评估标准 |
| Craft Companion | 双入口设计（从零/导入） | 用户冷启动 |
| NovelClaw | session + memory 机制 | 跨章节状态保持 |
| NovelClaw | 运行日志可检查 | 用户看到幕僚团队决策过程 |
| NovelClaw | 稿本对比视图 | 草稿/修订/终版对比 |

### 映射关系

| Craft Companion | WriteSync（共笔）|
|----------------|-----------------|
| 执行层 Writer | 文笔 Agent |
| 评估层 Evaluator | 编辑 Agent |
| 仲裁层 Arbiter | 策划 Agent（章纲决策）|
| — | 节奏 Agent（情绪节奏评估）|

### 我们的独特点（无竞品）

| 独特点 | 说明 |
|--------|------|
| 真正的 Multi-agent | 策划/编辑/文笔/节奏各有专职 |
| 雪花写作法原生融合 | 工程化映射到 agent 流程 |
| 网文专属优化 | 章节爆更、订阅节奏、爽点铺设 |
| 幕僚团队 UX 隐喻 | 用户感觉在调用专业团队 |

---

## 参考链接

- Craft Companion：https://github.com/qcx1919788736-collab/craft-companion
- NovelClaw：https://github.com/iLearn-Lab/NovelClaw
- chronicler：https://github.com/shyuni4u/chronicler
- nico：https://github.com/applebiter/nico

---

## 更新记录

- 2026-04-20：初版
