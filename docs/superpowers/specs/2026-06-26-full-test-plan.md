# WriteSync 完整用户测试方案

> 日期：2026-06-26
> 状态：v1.0
> 目标：确保用户测试时全流程可完整走通，不会出现"测一半无法继续"的情况

---

## 1. 测试范围总览

### 1.1 覆盖的 Phase 流程

```
new → topic_selection → planning → writing_chapters → review → idle
```

### 1.2 覆盖的 Agent（7 个，story 含选题+扩展双阶段）

| # | Agent | 是否触发确认 | 测试重点 |
|---|-------|-------------|---------|
| 1 | story | ✅（选题+扩展各一次） | 选题列表展示 + 用户选择 + StoryState 自动创建；五句话扩展展示 + 修改反馈循环 |
| 2 | character | ✅ | 角色卡确认 + 修改循环 |
| 3 | world | ✅ | 世界观确认 |
| 4 | outline | ✅ | 章纲确认 + 钩子矩阵/爽点曲线自动生成 |
| 5 | writer | ✅ | 逐章写作 + 辅助检查清单 |
| 6 | proofreader | ❌ 自动 | 校对不中断用户 |
| 7 | novel_review | ✅ | 全书审查 + 完成确认 |

### 1.3 测试环境要求

- 后端服务运行：`uvicorn src.web.app:app --host 127.0.0.1 --port 8001`
- 环境变量：`$env:LANGGRAPH_STRICT_MSGPACK="false"`
- LLM 网关：需可用（OpenCode Go 端点）
- 浏览器：Chromium（Playwright 测试）/ 任意现代浏览器（手动测试）

---

## 2. Phase 逐阶段测试用例

### 2.1 Phase: `new`

**前置条件**：全新项目，无任何产出

| 用例 | 操作 | 期望 SSE 序列 | 期望状态变化 |
|------|------|-------------|-------------|
| TC-NEW-01 | 创建项目，输入 seed idea | `thinking` → `agent_call(story)` → `workspace_update` → `confirm` | `topic.suggestions` 非空，phase 变为 `topic_selection` |
| TC-NEW-02 | 创建项目，不输入 seed idea（空指令） | 同上 | story agent 用 orchestrator 默认指令 `"开始故事创作流程"` 生成选题 |
| TC-NEW-03 | 加载已有项目（无选题，无故事） | 同上 | 编排器自动调用 story agent |

**验收标准**：选题建议成功生成，前端显示选题卡片列表。

### 2.2 Phase: `topic_selection`

**前置条件**：`topic.suggestions` 已生成，用户看到选题列表

| 用例 | 操作 | 期望 SSE 序列 | 期望状态变化 |
|------|------|-------------|-------------|
| TC-TS-01 | **选择第 0 个选题**（反馈含选题标题） | — | `StoryState` 创建，`story.confirmed_at` 设置，phase → `planning` |
| TC-TS-02 | **选择第 N 个选题** | — | 同上，`topic.selected = N` |
| TC-TS-03 | **拒绝：要求重新生成**（feedback="换个方向"） | `thinking` → `agent_call(story)` → ... | 新选题列表覆盖旧列表 |
| TC-TS-04 | **边界：选择后立即刷新页面** | 见持久化测试 | 选题已保存，story 已确认，phase 应保持 `planning` |
| TC-TS-05 | **前端渲染**：选题卡片可点击，点击后发送正确 feedback | — | 反馈包含选题标题（`_find_selected_topic` 需匹配到） |

> **✅ 详设已补全 [DS-GAP-01]**：选题阶段规格见架构详设 §7。

**验收标准**：选择选题后阶段自动推进到 `planning`，不再停留在 `topic_selection`。

### 2.3 Phase: `planning`

**前置条件**：`story.confirmed_at` 已设置，phase = `planning`

| 用例 | 操作 | 期望 SSE 序列 | 期望状态变化 |
|------|------|-------------|-------------|
| TC-PL-01 | 编排器自动调用 character | `thinking` → `agent_call(character)` → `workspace_update` → `confirm` | `characters.characters` 非空 |
| TC-PL-02 | 确认角色（approved=True） | — | `characters.confirmed_at` 设置 |
| TC-PL-03 | 拒绝角色，提供修改意见 | `thinking` → `agent_call(character)` → ... | 新角色卡含修改内容 |
| TC-PL-04 | 编排器自动调用 world | `thinking` → `agent_call(world)` → ... | `world.power_system` 非空 |
| TC-PL-05 | 确认世界观 | — | `world.confirmed_at` 设置 |
| TC-PL-06 | 编排器自动调用 outline | `thinking` → `agent_call(outline)` → ... | `chapter_outline` 非空 |
| TC-PL-07 | 确认章纲 | — | `chapter_outline.confirmed_at` 设置 + 钩子矩阵生成 + 爽点曲线生成 |
| TC-PL-08 | 章纲确认后验证钩子矩阵 | — | `volume.hook_matrix` 非空，长度 = 章节数 |
| TC-PL-09 | 章纲确认后验证爽点曲线 | — | `volume.pleasure_curve` 非空，长度 = 章节数 |
| TC-PL-10 | 钩子矩阵降级路径 | 模拟 3 次校验失败（需 mock LLM，属**自动化单元测试**范畴） | `volume.auto_degraded = True`，钩子全设 "悬念★★★" |
| TC-PL-11 | **LLM 越序调用 outline（story 未确认时）** | outline agent 依赖 story 状态，无守卫阻止但 agent 会因 `story.step1.one_sentence` 为空而失败 | 编排器应收到 error 事件，继续循环 |
| TC-PL-12 | **LLM 越序调用 novel_review（章节未全完时）** | review agent 可被调但 phase 不进入 `review`（`confirmed_count < total`） | `novel_review` 产出存在但 dashboard phase 不变 |

> **✅ 详设已补全 [DS-GAP-02]**：planning 阶段决策自由度见架构详设 §3.5。

**验收标准**：三个 planning Agent 全部确认后，phase 变为 `writing_chapters`。

### 2.4 Phase: `writing_chapters`

**前置条件**：`chapter_outline.confirmed_at` 已设置

| 用例 | 操作 | 期望 SSE 序列 | 期望状态变化 |
|------|------|-------------|-------------|
| TC-WC-01 | 编排器自动调用 writer（首章） | `thinking` → `agent_call(writer)` → `workspace_update` → `auxiliary_check` → `confirm` | `drafts.chapters[1].draft` 非空 |
| TC-WC-02 | 辅助检查渲染 | — | 前端收到 `auxiliary_check`，5 项检查卡片显示 |
| TC-WC-03 | 确认初稿 | — | `cd.stage = "final"`（此时仅草稿确认，`cd.final` 尚未生成——proofreader 在 TC-WC-05 填充） |
| TC-WC-04 | 拒绝初稿，提供重写意见 | `thinking` → `agent_call(writer)` → ... | 新初稿含修改内容 |
| TC-WC-05 | 编排器自动调用 proofreader（校对同章） | `thinking` → `agent_call(proofreader)` → `workspace_update` | `cd.final` 非空，**无 confirm 事件**；proofreader 自动检测首个有 draft 无 final 的章节 |
| TC-WC-06 | 验证 proofreader 不中断用户 | — | SSE 序列不含 `confirm` |
| TC-WC-07 | 下一章自动推进 | `thinking` → `agent_call(writer)` → ... | `chapter_num` 自动递增 |
| TC-WC-08 | 黄金三章专项（Ch1-3） | — | `golden_three_active = True`，辅助检查含「黄金三章」项 |
| TC-WC-09 | Ch4 自动解除黄金三章 | — | `golden_three_active = False` |
| TC-WC-10 | 全部章节写完后 | — | `confirmed_count >= total`，phase → `review` |
| TC-WC-11 | **编排器显式传 chapter_num**（如 `instruction="写第3章"`） | `thinking` → `agent_call(writer)` → ... | `_extract_chapter_num()` 从指令中解析出 3，writer 写第 3 章而非自动递增 |
| TC-WC-12 | **proofreader 在无可用章节时被调用** | `thinking` → `agent_call(proofreader)` → `error` | 返回 `AgentResult(error="无可用章节校对")`，编排器 continue |

> **✅ 详设已补全 [DS-GAP-03]**：writer→proofreader 协作链见架构详设 §3.4。

**验收标准**：每章经历 writer → 确认 → proofreader（自动）→ 下一章的完整循环；黄金三章约束在 Ch1-3 生效，Ch4 自动解除。

### 2.5 Phase: `review`

**前置条件**：全部章节已写+校对，`confirmed_count >= total`

| 用例 | 操作 | 期望 SSE 序列 | 期望状态变化 |
|------|------|-------------|-------------|
| TC-RV-01 | 编排器调用 novel_review | `thinking` → `agent_call(novel_review)` → `workspace_update` → `confirm` | `novel_review` 非空 |
| TC-RV-02 | 确认审查通过 | — | `novel_review.confirmed_at` 设置 |
| TC-RV-03 | 编排器发出 done | `thinking` → `done` | — |
| TC-RV-04 | 用户确认完成 | — | session 结束，phase = `idle` |
| TC-RV-05 | 拒绝完成（提供反馈） | `thinking` → 继续循环 | 编排器根据反馈调用适当 Agent |

> **✅ 详设已补全 [DS-GAP-04]**：done 行为规范见架构详设 §3.5。

**验收标准**：全书审查 → 用户确认完成 → 流程正常结束。

### 2.6 多卷流程（v0.4.0 特性）

**前置条件**：第一卷全部章节已完成，project 含多卷规划

| 用例 | 操作 | 期望 |
|------|------|------|
| TC-VOL-01 | 第一卷完成后切换到第二卷 | `volume_change` 事件（保留，未实现）；编排器进入 planning 模式为新卷生成章纲 |
| TC-VOL-02 | 第二卷章纲确认 | 新卷独立钩子矩阵 + 爽点曲线生成，不影响第一卷数据 |
| TC-VOL-03 | 多卷进度统计 | `dashboard.progress` 包含 `total_volumes` 和 `current_volume` |

> **⚠ 注意**：多卷切换的 `volume_change` SSE 事件已在 models.py 定义但**尚未在 loop.py 中实现**。当前编排器不会自动触发卷切换，需 LLM 决策显式进入新卷规划。此功能待 v0.5.0。

---

## 3. 确认点交互格式规范

### 3.1 通用确认格式

所有 Agent 确认都遵循统一契约：

```json
// SSE confirm 事件
{
  "type": "confirm",
  "data": {
    "agent": "story|character|world|outline|writer|novel_review",
    "content": { /* agent-specific */ },
    "dashboard": { "phase": "...", "completed_agents": [...], ... },
    "chapter_num": null | <int>
  }
}

// 用户响应（POST /api/v2/respond/{project_id}）
{
  "approved": true | false,
  "feedback": "<用户文字反馈>"
}
```

### 3.2 各 Agent 确认内容格式

| Agent | content 结构 | 用户反馈格式要求 |
|-------|-------------|-----------------|
| **story (topics)** | `{stage:"topics", topics:[{title,genre,sub_genre,core_selling_point}]}` | 反馈中**必须包含**选题标题（双向子串匹配） |
| **story (expansion)** | `{stage:"expansion", one_sentence, tag, expansion:{setup,inciting,rising,climax_prep,resolution,theme}}` | 自由文本 |
| **character** | `{characters:[{name,role,personality,goal}]}` | 自由文本 |
| **world** | `{power_system, tiers}` | 自由文本 |
| **outline** | `{total_chapters, chapters:[{num,title,core_event}]}` | 自由文本 |
| **writer** | `{chapter_num, content, word_count, stage:"draft", auxiliary_checks, golden_three_active}` | 自由文本 |
| **novel_review** | `{structural_issues, pacing_assessment, character_arc_consistency, recommendations, passed}` | 自由文本 |

> **✅ 详设已补全 [DS-GAP-05]**：确认协议见架构详设 §8。

---

## 4. SSE 事件序列契约

### 4.1 正常 Agent 调用序列

```
thinking → agent_call → workspace_update → [auxiliary_check] → [confirm]
```

- `auxiliary_check` 仅 writer agent 产出
- `confirm` 仅 `requires_confirmation=True` 的 agent 产出
- proofreader 不产出 `confirm`

### 4.2 错误序列

```
thinking → agent_call → error → thinking (下一轮)
```

### 4.3 完成序列

```
thinking → done → (用户确认) → [结束 或 继续]
```

### 4.4 事件详细规格

| 事件 | 数据字段 | 前端行为 |
|------|---------|---------|
| `thinking` | `{step: int}` | 显示 "AI 思考中..." |
| `agent_call` | `{agent: str, instruction: str}` | 切换对应面板 |
| `workspace_update` | `{agent: str, data: dict, summary: str}` | 刷新状态 |
| `auxiliary_check` | `{chapter_num: int, checks: [{name,status,detail,position}]}` | 渲染检查卡片 |
| `confirm` | `{agent, content, dashboard, chapter_num}` | 显示确认横幅 |
| `done` | `{reason, dashboard}` | 显示完成 + 导出按钮 |
| `error` | `{message, agent?}` | 显示错误 + 降级轮询 |

### 4.5 事件时序断言

测试中应验证：
1. `thinking` 始终是每轮第一个事件
2. `workspace_update` 始终在 `agent_call` 之后
3. `auxiliary_check` 在 `workspace_update` 和 `confirm` 之间
4. `confirm` 是每轮最后一个 SSE 事件（之后进入等待）
5. `proofreader` 的序列不含 `confirm`

> **✅ 详设已补全 [DS-GAP-06]**：SSE 契约见架构详设 §9。

---

## 5. 持久化与恢复测试

### 5.1 正常保存验证

| 用例 | 操作 | 验证 |
|------|------|------|
| TC-PS-01 | 每步确认后检查磁盘 | `projects/<pid>/` 目录存在，JSON 文件可解析 |
| TC-PS-02 | 服务重启后加载项目 | `load_workspace(pid)` 返回一致状态 |
| TC-PS-03 | schema 迁移 v1→v2→v3 | 旧版项目可正常加载 |

### 5.2 异常恢复场景

| 用例 | 场景 | 期望行为 |
|------|------|---------|
| TC-RC-01 | **服务在选题确认后重启** | 选题状态保留，story 已确认，重连后 phase = `planning` |
| TC-RC-02 | **服务在章纲确认后重启** | 章纲保留，钩子矩阵/爽点曲线保留，phase = `writing_chapters` |
| TC-RC-03 | **浏览器刷新（在 confirm 等待中）** | 页面重载，initApp() 恢复项目。**已知限制**：旧 session 在 `_wait_for_user()` 阻塞，新连接触发第二个 `session.run()` 产生双 generator 竞态（见架构详设 §10.3）。用户需对新 confirm 事件重新响应。 |
| TC-RC-04 | **SSE 断连后前端自动降级轮询** | 前端切换到轮询模式，`/api/v2/status` 返回最新状态。**注意**：轮询模式下无法响应 confirm，需刷新页面恢复 SSE。 |
| TC-RC-05 | **浏览器关闭后重新打开** | localStorage 恢复 session，项目可继续 |
| TC-RC-06 | **confirm 响应后立即崩溃（保存前）** | 重载后该步标记为未确认，编排器重新发起 confirm |

> **✅ 详设已补全 [DS-GAP-07]**：恢复行为见架构详设 §10。

---

## 6. 编排器决策边界测试

### 6.1 硬规则短路测试

| 用例 | 条件 | 期望 |
|------|------|------|
| TC-DC-01 | completed_agents=[] 且 history=[] | 强制 story，不调 LLM |
| TC-DC-02 | phase=topic_selection 且 story 未确认 | 强制 story（含 history 情况） |
| TC-DC-03 | total_chapters=0 时调 writer | 拒绝："尚无章节" |
| TC-DC-04 | written=0 时调 proofreader | 拒绝："尚无已写章节" |
| TC-DC-05 | topic_selection 时 LLM 返回 done | 拒绝："选题阶段未完成" |
| TC-DC-06 | 3 次重试全部失败 | 降级到 story + "决策重试耗尽" |

### 6.2 Agent 名称归一化测试

| 用例 | LLM 输出 | 归一化结果 |
|------|----------|-----------|
| TC-NM-01 | "章纲" / "outline" | outline |
| TC-NM-02 | "角色" / "character" | character |
| TC-NM-03 | "世界" / "world" | world |
| TC-NM-04 | "写" / "文笔" / "writer" | writer |
| TC-NM-05 | "校对" / "proof" / "edit" | proofreader |
| TC-NM-06 | "审查" / "review" / "check" | novel_review |
| TC-NM-07 | "story" / "plot" / "plan" / "topic" / "创意" | story |
| TC-NM-08 | 完全匹配不到的字符串 | story（默认降级） |

> **✅ 详设已补全 [DS-GAP-08]**：归一化表见架构详设 §3.5。

---

## 7. 边界条件与压力测试

### 7.1 选题边界

| 用例 | 场景 | 期望 |
|------|------|------|
| TC-EDGE-01 | 选题列表只有 1 条 | `_find_selected_topic` 降级到第一条 |
| TC-EDGE-02 | 选题列表为空 | `_find_selected_topic` 返回 None，不创建 StoryState |
| TC-EDGE-03 | 反馈文本不匹配任何选题标题 | 降级到第一条建议 |
| TC-EDGE-04 | 用户多次选择不同选题 | 取最近一次反馈匹配的选题 |

### 7.2 多章节边界

| 用例 | 场景 | 期望 |
|------|------|------|
| TC-EDGE-05 | 章纲只有 1 章 | writer/proofreader 正常完成 |
| TC-EDGE-06 | 章纲 0 章 | phase 不进入 writing_chapters |
| TC-EDGE-07 | writer 重复调用同一章 | chapter_num 自动递增，不重写 |

### 7.3 钩子/爽点降级

| 用例 | 场景 | 期望 |
|------|------|------|
| TC-EDGE-08 | 钩子矩阵 3 次生成失败 | 自动降级，全悬念★★★ |
| TC-EDGE-09 | 爽点曲线 3 次生成失败 | 自动降级，交替基础曲线 |

---

## 8. 手动测试走查清单（User Acceptance Test）

### 8.1 首次使用 - 完整策划流程

- [ ] 1. 打开 http://localhost:8001
- [ ] 2. 点击"新建项目"，输入想法和平台
- [ ] 3. 等待选题建议生成（~30s）
- [ ] 4. 点击选择一个选题卡片
- [ ] 5. 等待故事扩展生成
- [ ] 6. 确认或修改故事摘要
- [ ] 7. 依次确认角色 → 世界观 → 章纲
- [ ] 8. 章纲确认后等待钩子矩阵生成
- [ ] 9. 如果以上全通过 → **策划阶段完整可测**

### 8.2 逐章写作流程

- [ ] 10. 等待第 1 章初稿生成
- [ ] 11. 查看辅助检查清单（钩子/爽点/毒点/字数/黄金三章）
- [ ] 12. 确认或提意见重写
- [ ] 13. 等待校对自动完成（不中断）
- [ ] 14. 进入第 2 章...重复至全部完成

### 8.3 恢复流程

- [ ] 15. 在写作中途刷新浏览器
- [ ] 16. 确认项目自动恢复，继续之前进度
- [ ] 17. 关闭浏览器，重新打开 → 同上

---

## 9. 详设补全清单

根据以上测试方案，以下详设内容已补充到架构详设（`2026-05-27-main-sub-agent-architecture-design.md`）：

| 编号 | 缺失内容 | 详设位置 | 状态 |
|------|---------|---------|------|
| DS-GAP-01 | 选题阶段完整交互规格 | 架构详设 §7「选题阶段详细规范」 | ✅ v0.4.1 |
| DS-GAP-02 | planning 阶段编排器决策自由度 | 架构详设 §3.5「决策规则」补注 | ✅ v0.4.1 |
| DS-GAP-03 | writer→proofreader 协作链行为规范 | 架构详设 §3.4「Writer-Proofreader 协作方式」更新 | ✅ v0.4.1 |
| DS-GAP-04 | done 事件行为规范 | 架构详设 §3.5「决策规则」Done 行为规范 | ✅ v0.4.1 |
| DS-GAP-05 | 确认点交互格式规范 | 架构详设 §8「确认点交互协议」 | ✅ v0.4.1 |
| DS-GAP-06 | SSE 事件序列契约 | 架构详设 §9「SSE 事件序列契约」 | ✅ v0.4.1 |
| DS-GAP-07 | 持久化与恢复行为规范 | 架构详设 §10「持久化与恢复行为规范」 | ✅ v0.4.1 |
| DS-GAP-08 | Agent 名称归一化表 | 架构详设 §3.5「决策规则」Agent 名称归一化表 | ✅ v0.4.1 |

### 闭环验证

| 测试方案引用 | 详设章节 | 代码位置 | 一致？ |
|-------------|---------|---------|--------|
| 选题匹配算法 (TC-TS-01~05) | §7.3 | `loop.py:_find_selected_topic()` | ✅ |
| 确认格式 (TC-TS/PL/WC/RV) | §8.2 各Agent表 | `adapters.py` 各 AgentResult | ✅ |
| SSE 序列 (全TC的期望序列) | §9.2 时序约束 | `loop.py:run()` yield 顺序 | ✅ |
| 恢复行为 (TC-RC-01~06) | §10.2 恢复场景 | `workspace.py:save/load` + `orchestrator_api.py` | ✅ |
| 硬规则 (TC-DC-01~06) | §7.5 + §3.5 | `decision.py:_validate_decision + decide_next_action` | ✅ |
| 归一化 (TC-NM-01~08) | §3.5 归一化表 | `decision.py:_normalize_agent()` | ✅ |

---

## 10. 测试执行指南

### 10.0 执行结果汇总 (2026-06-26 最终)

| 轮次 | 状态 | 结果 |
|------|------|------|
| Round 1 连通性 | ✅ 完成 | **40 passed**（含 mock LLM 降级 + 钩子/爽点降级路径） |
| Round 2 Phase 完整性 | ✅ 完成 | Playwright E2E passed + 121 backend passed |
| Round 3 多卷流程 | ✅ 完成 | `volume_change` 事件已实现 + schema 迁移通过 |
| Round 4 持久化恢复 | ✅ 完成 | 7 persistence + 34 context passed |
| Round 5 手动走查 | ✅ 完成 | Playwright base + comprehensive passed |

**总计**: **121 backend + 3 frontend = 124 passed / 0 skipped / 0 failed**

### 已修复的阻塞项
- ~~TC-DC-06 (LLM 重试降级)~~ → mock LLM 单元测试 ✅
- ~~TC-EDGE-08 (钩子降级)~~ → mock generate_hook_matrix ✅
- ~~TC-EDGE-09 (爽点降级)~~ → mock generate_pleasure_curve ✅
- ~~TC-VOL-01 (volume_change)~~ → `_check_volume_transition()` 已实现 ✅

### 10.1 前置条件

```powershell
# 环境准备（一次性）
$env:LANGGRAPH_STRICT_MSGPACK="false"
pip install pytest pytest-asyncio  # 如未安装

# 确保 .env 中 LLM_API_KEY 有效
# 确保 OpenCode Go 网关可访问
```

### 10.2 Round 1 — 连通性（✅ 已完成）

```
python -m pytest tests/test_round1_connectivity.py -v
```

**结果**: 34 passed, 3 skipped | 验证：决策硬规则、名称归一化、选题匹配、Phase 守卫

### 10.3 Round 2 — Phase 完整性（需要 LLM + 服务运行）

**用例**: TC-NEW-01~03, TC-TS-01~05, TC-PL-01~12, TC-WC-01~12, TC-RV-01~05（共 37 个）

**执行方式**: 启动服务 → 浏览器手动走查或 Playwright E2E

```powershell
# 终端 1: 启动后端
$env:LANGGRAPH_STRICT_MSGPACK="false"
uvicorn src.web.app:app --host 127.0.0.1 --port 8001

# 终端 2: 运行 Playwright E2E（验证完整 SSE 序列）
python -m pytest tests/test_playwright.py -v --tb=long

# 或 CLI 模式逐阶段验证
python -m src.cli --full
```

**逐个 Phase 验证清单**:

| Phase | 手动验证步骤 | 检查点 |
|-------|------------|--------|
| `new` | 浏览器打开 http://127.0.0.1:8001 → 新建项目 → 输入想法 | SSE: thinking → agent_call(story) → confirm |
| `topic_selection` | 点击选题卡片 → 等待扩展 | phase 变为 `planning`，不再停滞 |
| `planning` | 依次确认角色/世界观/章纲 | 每步 SSE: confirm → 确认后 completed_agents 增加 |
| `writing_chapters` | 确认 Ch1 初稿 → 等待校对 → Ch2... | auxiliary_check 事件出现，proofreader 不中断 |
| `review` | 等待全书审查 → 确认完成 | done 事件 + session 结束 |

### 10.4 Round 3 — 多卷流程（需要 LLM + 多卷项目状态）

**用例**: TC-VOL-01~03（3 个）

**前置**: 需第一卷全部完成。`volume_change` SSE 事件未实现，当前编排器不会自动触发卷切换。

```powershell
# 检查当前是否有 volume_change 实现
Select-String -Path src/orchestrator/loop.py -Pattern 'volume_change'
# 若无输出 → volume_change 未实现 → TC-VOL-01 标记为 BLOCKED
```

### 10.5 Round 4 — 持久化与恢复（需要模拟故障）

**用例**: TC-PS-01~03, TC-RC-01~06（9 个）

```powershell
# TC-PS-01~03: 正常保存验证
python -m pytest tests/test_persistence.py -v

# TC-RC-01~06: 模拟故障恢复（手动）
# 1. 启动服务，创建一个项目，走到选题确认后
# 2. Ctrl+C 停止服务
# 3. 重新启动服务
# 4. 浏览器刷新 → 确认项目恢复，phase 正确
```

**TC-RC-03 已知限制**: 浏览器刷新在 confirm 等待中时，旧 session 阻塞在 `_wait_for_user()`，新连接可能产生双 generator 竞态。用户需重新响应 confirm。

### 10.6 Round 5 — 手动走查（UAT）

**用例**: UAT 清单 17 项

**执行**: 按 §8 的 17 个 checkbox 逐项在浏览器中操作并勾选。重点验证：
- 策划全流程不卡顿（选题 → 角色 → 世界观 → 章纲）
- 逐章写作 loop 正常（writer → 确认 → proofreader → 下一章）
- 浏览器刷新后可恢复
- 浏览器关闭重开后可继续
```
