# WriteSync 操作手册

> 完整覆盖前后端操作逻辑、启动步骤、用户流程、测试方法

---

## 1. 环境准备

### 1.1 依赖安装

```bash
pip install langgraph langgraph-checkpoint pydantic openai instructor fastapi uvicorn jinja2 python-multipart
pip install pytest pytest-asyncio playwright  # 测试用
playwright install chromium                   # Playwright 浏览器
```

### 1.2 环境变量

```powershell
# .env 文件（项目根目录）
LLM_BASE_URL=https://opencode.ai/zen/go/v1
LLM_MODEL=deepseek-v4-flash
LLM_PROVIDER=opencode
LLM_API_KEY=sk-xxxxxxxx

# 运行时必须设置（PowerShell）
$env:LANGGRAPH_STRICT_MSGPACK="false"
```

### 1.3 项目结构速览

```
WriteSync/
├── src/
│   ├── orchestrator/   # ★ 核心编排引擎
│   │   ├── loop.py        # 异步主循环 (SSE yield)
│   │   ├── decision.py    # LLM 决策 + 守卫 + 归一化
│   │   ├── adapters.py    # 7 个 Agent 适配器
│   │   ├── workspace.py   # 状态管理 + Phase 计算
│   │   └── models.py      # 数据模型 + SSE 事件类型
│   ├── agents/         # 7 个 Agent 实现
│   ├── state/          # 状态类型定义
│   ├── utils/          # LLM 客户端 + 知识库
│   └── web/            # FastAPI Web UI
│       ├── app.py          # V1/V2 端点
│       ├── orchestrator_api.py  # SSE 流管理
│       └── templates/workbench.html  # 前端单页
├── tests/              # 测试（121+ 单元 + Playwright E2E）
├── docs/               # 详设文档 + 知识库模板
├── projects/           # 项目持久化目录（自动生成）
└── logs/               # 运行日志
```

---

## 2. 启动运行

### 2.1 Web UI 模式（推荐）

```powershell
# 终端 1：启动后端
$env:LANGGRAPH_STRICT_MSGPACK="false"
uvicorn src.web.app:app --host 127.0.0.1 --port 8001
# 输出: Uvicorn running on http://127.0.0.1:8001
```

浏览器打开 `http://127.0.0.1:8001` → 进入写作工作台。

### 2.2 CLI 模式

```powershell
# 策划阶段（选题 → 故事扩展 → 角色 → 世界观 → 章纲）
python -m src.cli

# 全流程模式（策划 + 逐章写作到全书完成）
python -m src.cli --full

# 指定模型
python -m src.cli --full --model deepseek-v4-pro
```

---

## 3. 完整用户操作流程（逐步详解）

> 以下按一个全新项目从头到尾的完整路径，逐步讲解每一步用户看到什么、做什么、系统怎么响应。

---

### 步骤 0：打开工作台

浏览器打开 `http://127.0.0.1:8001`，看到两种界面之一：

**场景 A — 首次使用（无项目）**：
```
┌──────────────────────────────────────────┐
│         WriteSync 共笔                    │
│    Multi-Agent 协作小说写作平台             │
│                                          │
│   ┌────────────────────────────────┐     │
│   │ 请描述你的创作想法...             │     │
│   │                                │     │
│   │ (文本框，可输入多行)              │     │
│   └────────────────────────────────┘     │
│                                          │
│   目标平台: [起点 ▼]                       │
│                                          │
│   [ 开始创作 ]                            │
└──────────────────────────────────────────┘
```

**场景 B — 已有项目**（显示项目卡片网格，可点击卡片继续或点"新建项目"）。

---

### 步骤 1：创建项目 → Phase: `new`

**用户操作**：
1. 在文本框输入想法，如：`一个程序员穿越到蒸汽时代的克苏鲁世界，发明了AI从而成为主神的故事`
2. 下拉选择目标平台（默认"起点"）
3. 点击 **"开始创作"** 按钮

**前端行为**：
- 按钮变灰显示"创建中..."
- 发送请求：`POST /api/v2/start`（参数：`idea` + `platform`）

**后端处理**：
```
1. Workspace.create(name=idea前40字, platform, idea)
2. ws.set_seed_idea(idea) → 写入 TopicState.user_original_idea
3. ws.save() → projects/<pid>/ 目录创建
4. 返回 { project_id, dashboard: { phase: "new", completed_agents: [] } }
```

**前端收到响应后**：
- 存储 `project_id` 到 `localStorage`
- 建立 SSE 连接：`GET /api/v2/stream/{project_id}`
- 页面切换到工作台三栏布局
- 编排器自动启动，开始发送 SSE 事件

---

### 步骤 2：选题生成 → Phase: `topic_selection`

**此时用户在屏幕上看到**：
- 右侧聊天区显示：`[1] AI 思考中...`
- 然后：`调用 story...` `📋 开始故事创作流程`

**等待约 20-40 秒**（LLM 生成 3-5 个选题建议）。

**SSE 事件序列**：
```
1. thinking     → {step: 1}              → 聊天区: "AI 思考中..."
2. agent_call   → {agent: "story", ...}   → 聊天区: "调用 story..." + 自动切到故事面板
3. workspace_update → {summary: "选题建议：蒸汽纪元..."} → 聊天区: "✅ 选题建议：..."
4. confirm      → {agent: "story", stage: "topics", topics: [...]}
```

**用户此时在屏幕上看到**（确认事件到达后）：
```
右侧聊天区:
  [1] AI 思考中...
  📋 开始故事创作流程
  调用 story...
  ✅ 选题建议：蒸汽纪元：我创造了智能神明
  请确认 story 的产出

中央写作区 → 自动切到故事面板 → 显示选题卡片:
  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
  │ 蒸汽纪元：              │  │ 我在蒸汽世界造邪神       │  │ 蒸汽之主：我即是代码     │
  │ 我创造了智能神明         │  │                      │  │                      │
  │ 科幻 · AI创世流          │  │ 奇幻 · 幕后黑手流       │  │ 游戏 · 主神建设         │
  │ 程序员穿越蒸汽朋克...     │  │ 主角穿越后发现...      │  │ 主角穿越到被旧日...     │
  └──────────────────────┘  └──────────────────────┘  └──────────────────────┘
  ... (共 3-5 张卡片)

底部中断横幅:
  [ 请选择一个选题 ]
```

**用户操作**：点击一张心仪的选题卡片（如第一张"蒸汽纪元：我创造了智能神明"）。

**前端行为**：
- 卡片高亮
- 发送：`POST /api/v2/respond/{pid}` `{approved: true, feedback: "选题: 蒸汽纪元：我创造了智能神明"}`

**后端处理**：
```
1. session.user_respond(approved=true, feedback="选题: 蒸汽纪元：我创造了智能神明")
2. _wait_for_user() 被唤醒，返回 {approved: true, feedback: "选题: ..."}
3. workspace.add_feedback("story", "选题: ...")
4. _mark_confirmed("story")
   └─ _find_selected_topic()
      └─ 扫描 feedbacks: "选题: 蒸汽纪元..." 包含 "蒸汽纪元：我创造了智能神明"
      └─ 匹配成功 → topic.selected = 0
   └─ ws_state.story = StoryState(
        step1=StoryCore(one_sentence="程序员穿越蒸汽朋克世界...", tag="科幻"),
        step2=StoryArc(setup="", ...),
        confirmed_at=now
      )
5. workspace.save()
6. dashboard.phase → "planning"（因为 story.confirmed_at 已设置）
```

**用户此时看到**：
- 右侧聊天区横幅消失
- 下一轮 thinking 开始
- 左下角进度 → 阶段变为 "planning"

---

### 步骤 3：故事扩展确认 → Phase: `planning`（story 第二次调用）

编排器检测到 `has_story()` 为 True，调用 story agent 的 Stage 2。

**SSE 事件序列**：
```
thinking → agent_call(story) → workspace_update → confirm(stage: "expansion")
```

**用户此时在屏幕上看到**（确认事件到达后）：
```
中央写作区（故事面板）:
  一句话核心:
    程序员穿越蒸汽朋克世界，用差分机打造AI'智械核心'，
    以科技侧面成神

  五句话扩展:
    背景设定: 在蒸汽与齿轮的轰鸣中，主角林晨一觉醒来...
    第一转折: 当第一台差分机开始自行运算未知程序...
    中点: 他用代码重构了被古神污染的仪式...
    第二转折: 智械网络觉醒，开始反向解析神的权柄...
    结局: 机械神国降临，他以逻辑引擎登临主神之位

右侧聊天区:
  [2] AI 思考中...
  调用 story...
  ✅ 故事摘要已生成
  请确认 story 的产出

底部中断横幅:
  [ ✅ 确认 ]  [ ✏️ 提出修改意见 ]
```

**用户操作**：
- 点 **"确认"** → 故事摘要通过
- 或点 **"提出修改意见"** → 输入文字如"主角性格不够鲜明" → 编排器重新调用 story agent 修改

**后端处理（确认时）**：
```
1. _mark_confirmed("story") → story.confirmed_at = now（story 已存在，直接设置）
2. workspace.save()
```

---

### 步骤 4：角色生成确认

编排器自动决定调用 `character` agent。

**SSE 事件序列**：
```
thinking → agent_call(character) → workspace_update → confirm
```

**用户此时在屏幕上看到**：
```
中央写作区（自动切到角色面板）:
  角色列表:
    ┌──────────────────────────────────┐
    │ 林晨 — 主角                       │
    │ 性格: 理性冷静、偏执、好奇心旺盛      │
    │ 目标: 解析世界本质，以科技登临神位     │
    │ 冲突: 理性思维 vs 不可名状的疯狂      │
    ├──────────────────────────────────┤
    │ 艾琳·瓦特 — 女主                   │
    │ 性格: 勇敢、叛逆、对新技术痴迷        │
    │ ...                               │
    └──────────────────────────────────┘

底部横幅:
  [ ✅ 确认 ]  [ ✏️ 提出修改意见 ]
```

**用户操作**：点"确认"（或提意见重新生成）。

**后端处理**：`_mark_confirmed("character")` → `characters.confirmed_at = now`

---

### 步骤 5：世界观确认

编排器自动调用 `world` agent。流程同上，用户看到力量体系、地理、社会结构等内容，确认或提意见。

**后端处理**：`_mark_confirmed("world")` → `world.confirmed_at = now`

---

### 步骤 6：章纲确认 → Phase: `writing_chapters`

编排器调用 `outline` agent 生成章节目录。

**用户此时在屏幕上看到**：
```
中央写作区（章纲面板）:
  全书共 20 章
  Ch1  觉醒之日       — 主角穿越，发现差分机的秘密
  Ch2  第一行代码      — 首次用代码影响现实
  Ch3  深渊的回响      — 古神注意到异常
  Ch4  信徒与算法      — 第一批原住民成为信徒
  ...

底部横幅:
  [ ✅ 确认 ]  [ ✏️ 提出修改意见 ]
```

**后端处理（确认时）**：
```
1. _mark_confirmed("outline") → chapter_outline.confirmed_at = now
2. _generate_hook_matrix() → 为每章分配钩子类型/强度
3. _generate_pleasure_curve() → 为每章分配爽点类型/密度
4. Phase 跃迁: planning → writing_chapters
```

---

### 步骤 7：第 1 章写作

编排器自动调用 `writer` agent。

**SSE 事件序列**：
```
thinking → agent_call(writer) → workspace_update → auxiliary_check → confirm
```

**用户屏幕分步变化**：

**① agent_call 到达时**：
- 聊天区：`[N] AI 思考中...` → `📋 撰写第1章正文` → `调用 writer...`
- 中央区自动切换到**编辑器面板**

**② 等待 30-60 秒**（LLM 生成 3000-5000 字正文）

**③ workspace_update 到达时**：
- 聊天区：`✅ 第1章初稿：3521字`
- 编辑器加载正文内容 + 字数统计

**④ auxiliary_check 到达时**（仅 writer 有）：
```
聊天区叠入 5 张检查卡片:
  ┌─────────────────────────────┐
  │ 钩子落地 ✅                   │
  │ 末段检测到钩子信号              │
  └─────────────────────────────┘
  ┌─────────────────────────────┐
  │ 爽点密度 ⚠️                   │
  │ 估算 8%，预设 12%             │
  └─────────────────────────────┘
  ┌─────────────────────────────┐
  │ 毒点扫描 ✅                   │
  │ 未检测到毒点                  │
  └─────────────────────────────┘
  ┌─────────────────────────────┐
  │ 字数范围 ✅                   │
  │ 3521 字（建议 3000-5000）      │
  └─────────────────────────────┘
  ┌─────────────────────────────┐
  │ 黄金三章 ⚠️                   │
  │ 开头环境描写词过多，建议从冲突切入 │
  └─────────────────────────────┘
```

**⑤ confirm 到达时**：
- 聊天区：`请确认 writer 的产出`
- 编辑器：显示完整正文
- 底部横幅：`[ ✅ 确认 ]  [ ✏️ 修改 ]`

**用户操作**：
- 点 **"确认"** → `cd.stage = "final"`，本章草稿确认
- 或点 **"修改"** + 输入意见 → 编排器重新调用 writer 重写本章

---

### 步骤 8：第 1 章校对（自动）

编排器自动调用 `proofreader` agent。**用户无需操作**。

**SSE 事件序列**：
```
thinking → agent_call(proofreader) → workspace_update
（无 confirm 事件！proofreader 不中断用户）
```

**用户此时看到**：
- 聊天区：`调用 proofreader...` → `✅ 第1章校对完成`
- 编辑器：正文更新为校对后的版本
- **没有确认横幅**，编排器自动进入下一轮

---

### 步骤 9：第 2 章 → 第 N 章（循环）

编排器自动重复步骤 7-8：
- writer 写第 2 章 → 用户确认 → proofreader 校对第 2 章
- writer 写第 3 章 → 用户确认 → proofreader 校对第 3 章
- ...

**黄金三章特殊处理**：
- Ch1-Ch3：`golden_three_active = True`，辅助检查含"黄金三章"专项
  - 开头 100 字内不能有过多环境描写
  - 对话占比 ≥ 50%
  - 钩子强度 ≥ ★★★★
- Ch4 起：`golden_three_active = False`，约束自动解除

**章节号自动检测**：
- writer 自动扫描 `chapter_outline.chapters`，找第一个未写的章节
- proofreader 自动扫描 `drafts.chapters`，找第一个有 draft 无 final 的章节

---

### 步骤 10：全书审查 → Phase: `review`

全部章节写完后（`confirmed_count >= total_chapters`），编排器调用 `novel_review` agent。

**用户此时在屏幕上看到**：
```
中央写作区（审查面板）:
  结构问题:
    - 第二卷过渡略显突兀
  节奏评估:
    - 中段 Ch8-12 节奏偏慢
  角色弧线一致性:
    - 主角从理性到疯狂的转变自然
    - 女主艾琳的成长线完整
  修改建议:
    1. 在 Ch8 末增加一个钩子
    2. Ch12 的爽点可以提前到 Ch10
  审查结果: 通过 ✅

底部横幅:
  [ ✅ 确认完成 ]
```

**用户操作**：点"确认完成"。

**后端处理**：`_mark_confirmed("novel_review")` → `novel_review.confirmed_at = now`

---

### 步骤 11：全书完成

编排器判定全书工作完成，发出 `done`。

**用户此时在屏幕上看到**：
```
右侧聊天区:
  🎉 全书写作完成！
  全部章节已确认，审查已通过。

底部横幅:
  [ ✅ 确认完成 ]  [ 💾 导出 Markdown ]

导出按钮出现，点击可下载完整小说。
```

**用户操作**：点"确认完成" → session 结束。

**后端处理**：`session.finished_at` 设置，loop break。

---

### 步骤 12（可选）：多卷切换

如果项目配置了多卷（`volumes` 列表长度 > 1），第一卷全部章节确认后：

```
SSE: volume_change
  { from_volume: 1, to_volume: 2, total_volumes: 3 }
```

编排器对新卷重新进入 `planning` 阶段，生成新卷的章纲 + 钩子矩阵 + 爽点曲线，然后逐章写作。

---

### 补充：修改反馈的完整循环

在任何确认步骤中，用户选择"提出修改意见"后的流程：

```
1. 用户输入修改意见（如"主角性格不够鲜明"） + 点"修改"
2. POST /api/v2/respond {approved: false, feedback: "主角性格不够鲜明"}
3. feedback 存入 workspace.feedbacks[]
4. 编排器下一轮 decision 看到此 feedback
5. LLM 决定重调同一 Agent，pending_feedback 随 instruction 传入
6. Agent 基于反馈重新生成
7. SSE: agent_call → workspace_update → confirm（再次到达确认点）
8. 用户可再确认或再提意见（无限循环直到满意）
```

### 补充：全程可中断恢复

- **浏览器刷新**：页面重载后 `initApp()` 从 localStorage 恢复 `project_id`，重新建立 SSE 连接。编排器从当前 phase 继续决策。
- **关闭浏览器重开**：同上，localStorage 保留 session。
- **服务重启**：所有 in-memory 会话丢失，但项目磁盘状态保留。重新访问后编排器从当前 phase 重新决策。

---

## 4. 前端操作界面

### 4.1 布局结构

```
┌──────────────────────────────────────────────────────┐
│  顶部导航栏                                          │
│  [项目名称] [平台] [进度] [阶段徽章]                    │
├──────────┬──────────────────────────┬────────────────┤
│ 左侧导航  │     中央写作区             │  右侧聊天区      │
│          │                          │                │
│ 📖 故事   │  编辑/预览章节内容          │  AI 对话 +      │
│ 👤 角色   │                          │  SSE 事件流     │
│ 🌍 世界观  │                          │                │
│ 📋 章纲   │                          │  thinking...    │
│ ✍️ 写作   │                          │  agent_call     │
│ 🔍 校对   │                          │  confirm 横幅   │
│ 📊 审查   │                          │  auxiliary_check│
│ 📋 上下文  │                          │                 │
└──────────┴──────────────────────────┴────────────────┘
```

### 4.2 聊天区与中央写作区的互动流程

前端三栏布局中，**右侧聊天区**是 SSE 事件流的主交互入口，**中央写作区**是内容展示/编辑器。两者通过 SSE 事件驱动联动：

```
SSE 事件到达 → 聊天区更新 + 中央区切换
```

#### 4.2.1 事件驱动的面板切换

| SSE 事件 | 聊天区行为 | 中央写作区行为 |
|---------|----------|--------------|
| `thinking` | 显示"AI 思考中..." | 保持当前面板（loading 状态） |
| `agent_call` | 显示"调用 {agent}..." + 指令文本 | **自动切换**到对应面板 |
| `workspace_update` | 显示"✅ {摘要}" | 刷新当前面板数据 (`refreshV2State`) |
| `confirm` | 显示"请确认 {agent}" + 确认横幅按钮 | 切到对应面板 + 展示待确认内容 |
| `auxiliary_check` | 渲染 5 项检查卡片（✅/⚠️） | 无变化（卡片叠在聊天区） |
| `done` | 显示"🎉 全书完成" + 导出按钮 | 禁用聊天输入 |
| `error` | 显示"❌ {错误}" + 降级轮询 | 无变化 |

#### 4.2.2 Agent → 面板映射

`agent_call` 到达时，前端根据 Agent 名自动切换中央写作区面板：

| Agent 名 | 切换到的面板 | 展示内容 |
|---------|------------|---------|
| `story` | **故事面板** (`#panel-story`) | 一句话核心 + 五句话扩展 |
| `character` | **角色面板** (`#panel-characters`) | 角色卡列表 |
| `world` | **世界观面板** (`#panel-world`) | 力量体系/地理/社会 |
| `outline` | **章纲面板** (`#panel-outline`) | 章节目录 + 每章事件 |
| `writer` | **编辑器面板** (`#panel-editor`) | 当前章正文 + 字数统计 |
| `proofreader` | **编辑器面板** | 校对后的文本（自动刷新） |
| `novel_review` | **审查面板** (`#panel-review`) | 结构/节奏/角色弧线评估 |

#### 4.2.3 确认交互的完整流程

以 **writer 初稿确认**为例：

```
1. SSE agent_call(writer) 到达
   ├── 聊天区: "📋 撰写第1章正文" + "调用 writer..."
   └── 中央区: 自动切换到编辑器面板

2. SSE workspace_update 到达
   ├── 聊天区: "✅ 第1章初稿：3500字"
   └── 中央区: 编辑器加载 draft.content + 渲染字数

3. SSE auxiliary_check 到达
   └── 聊天区: 5 张检查卡片叠在对话流中
        ├── 钩子落地 ✅  末段检测到钩子信号
        ├── 爽点密度 ⚠️  估算 8%，预设 12%
        ├── 毒点扫描 ✅  未检测到毒点
        ├── 字数范围 ✅  3500 字
        └── 黄金三章 ⚠️  开头环境描写词过多

4. SSE confirm 到达
   ├── 聊天区: "请确认 writer 的产出"
   ├── 聊天区: 底部出现中断横幅按钮 ["✅ 确认"] ["✏️ 修改"]
   └── 中央区: 编辑器显示完整正文

5. 用户操作
   ├── 点"确认" → POST /api/v2/respond {approved:true}
   │   └── 聊天区横幅消失 → 下一轮 thinking 开始
   └── 点"修改" + 输入意见 → POST {approved:false, feedback:"节奏太慢"}
       └── 下一轮 agent_call(writer) 带修改意见重写
```

#### 4.2.4 选题阶段的特殊交互

选题确认不走聊天输入，而是**点击中央区选题卡片**：

```
1. SSE confirm(story, stage=topics) 到达
   ├── 聊天区: "请确认 story 的产出"
   └── 中央区: 渲染选题卡片网格（3-5 张）

2. 用户点击卡片
   └── 触发 selectTopicCard(title)
       └── POST /api/v2/respond {approved:true, feedback:"选题: {title}"}

3. 后端 _find_selected_topic() 双向子串匹配
   └── 匹配成功 → 创建 StoryState → phase → planning
```

#### 4.2.5 左侧导航手动切换

用户可随时点击左侧导航手动切换面板查看历史产出：

| 导航项 | 面板 | 数据来源 |
|--------|------|---------|
| 📖 故事 | `#panel-story` | `stateData.story` |
| 👤 角色 | `#panel-characters` | `stateData.characters` |
| 🌍 世界观 | `#panel-world` | `stateData.world` |
| 📋 章纲 | `#panel-outline` | `stateData.outline` |
| ✍️ 写作 | `#panel-editor` | `stateData.drafts` |
| 📊 审查 | `#panel-review` | `stateData.novel_review` |
| 📋 上下文 | 上下文面板 | `contextData`（动态上下文引擎） |

> **注意**：手动切换不会影响 SSE 事件流。`agent_call` 到达时仍会自动切到对应面板。

---

## 5. 后端 API 速查

| 端点 | 方法 | 用途 | 参数 |
|------|------|------|------|
| `/api/v2/start` | POST | 创建/恢复项目 | `idea`, `platform`, `project_id` |
| `/api/v2/stream/{pid}` | GET | SSE 事件流 | — |
| `/api/v2/respond/{pid}` | POST | 用户响应确认 | `approved`, `feedback`, `scope` |
| `/api/v2/status/{pid}` | GET | 查询状态 | — |
| `/api/v2/finish/{pid}` | POST | 确认全书完成 | `confirmed`, `feedback` |
| `/api/projects` | GET | 列出所有项目 | — |
| `/api/export/{pid}` | GET | 导出 Markdown | `fmt=md` |

---

## 6. 测试执行

### 6.1 纯逻辑测试（无需 LLM / 无需服务）

```powershell
# Round 1：决策规则 + 归一化 + 边界 + 降级路径
python -m pytest tests/test_round1_connectivity.py -v
# 预期：40 passed

# 持久化 + 上下文 + 响应模型 + v0.4.0
python -m pytest tests/test_persistence.py tests/test_context.py tests/test_context_e2e.py tests/test_response_models.py tests/test_v04_webnovel.py -v
# 预期：81 passed
```

### 6.2 前端 E2E 测试（需服务运行）

```powershell
# 启动服务（终端 1）
$env:LANGGRAPH_STRICT_MSGPACK="false"
uvicorn src.web.app:app --host 127.0.0.1 --port 8001

# 运行 Playwright（终端 2）
$env:WRITESYNC_URL="http://127.0.0.1:8001"
python -m pytest tests/test_playwright.py tests/test_playwright_comprehensive.py -v
# 预期：2 passed
```

### 6.3 一键全量

```powershell
$env:LANGGRAPH_STRICT_MSGPACK="false"
$env:WRITESYNC_URL="http://127.0.0.1:8001"
python -m pytest tests/test_persistence.py tests/test_context.py tests/test_context_e2e.py tests/test_response_models.py tests/test_v04_webnovel.py tests/test_round1_connectivity.py tests/test_playwright.py tests/test_playwright_comprehensive.py -v
# 预期：123 passed
```

---

## 7. SSE 事件流参考

每轮编排器循环的标准事件序列：

```
thinking → agent_call → workspace_update → [auxiliary_check] → [confirm]
                                                                    │
                                                          用户响应 ←┘
                                                                    │
                                                           下一轮 thinking
```

| 事件 | 触发条件 | 数据 |
|------|---------|------|
| `thinking` | 每轮开始 | `{step: int}` |
| `agent_call` | 调用 Agent 前 | `{agent, instruction}` |
| `workspace_update` | Agent 成功后 | `{agent, data, summary}` |
| `auxiliary_check` | writer 产出 | `{chapter_num, checks: [...]}` |
| `confirm` | 需确认时 | `{agent, content, dashboard, chapter_num}` |
| `done` | 全书完成 | `{reason, dashboard}` |
| `error` | 异常时 | `{message, agent?}` |
| `volume_change` | 卷切换 | `{from_volume, to_volume, total_volumes}` |

---

## 8. 常见问题排查

### 8.1 服务启动失败

```powershell
# 检查端口占用
netstat -ano | findstr 8001
npx kill-port 8001  # 清理幽灵端口

# 检查依赖
pip list | findstr "fastapi uvicorn instructor"
```

### 8.2 LLM 调用超时

OpenCode Go 网关 ~100s 硬超时。大 prompt（3000+ 字）用 `deepseek-v4-flash`，编排器决策用 `deepseek-v4-pro`。

### 8.3 SSE 断连

前端自动降级到轮询模式（`/api/v2/status`）。确认操作需刷新页面恢复 SSE 连接。

### 8.4 项目恢复

```powershell
# 检查项目文件
ls projects/<project_id>/
# 应包含: metadata.json, story.json, session_data.json 等

# 查看编排器日志
Get-Content logs/writesync-*.log -Tail 50
```

### 8.5 日志排查

```powershell
# 所有模块统一用 "writesync" logger
Select-String -Path logs/writesync-*.log -Pattern "决策|Orchestrator|error"
```

---

## 9. 项目状态持久化

```
projects/<project_id>/
├── metadata.json           # 项目名称/平台/时间戳
├── schema_version.json     # 当前 v3
├── topic.json              # 选题建议
├── story.json              # 故事核心（Step1+Step2）
├── characters.json         # 角色卡
├── world.json              # 世界观设定
├── chapter_outline.json    # 章节目录
├── novel_review.json       # 全书审查
├── volumes.json            # 分卷数据（含钩子矩阵/爽点曲线）
├── drafts/
│   ├── chapter_001.json    # 第1章初稿+校对稿
│   └── chapter_002.json
├── context.json            # 动态上下文（角色变化/伏笔）
├── context_cache.json      # L1 摘要缓存
├── session_data.json       # 编排器历史 + 用户反馈
└── orchestrator_log.jsonl  # L3 审计日志
```

保存时机：每轮循环 Agent 执行成功后自动 `workspace.save()`。
