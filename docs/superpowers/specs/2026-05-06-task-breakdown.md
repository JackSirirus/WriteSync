# WriteSync — 知识库动态更新 · 任务拆解

> 日期：2026-05-06
> 基于：`2026-05-06-dynamic-knowledge-design.md`
> 项目当前版本：0.1.2 Pre-alpha

---

## 拆解原则

1. 每个 MWP（最小工作包）仅修改 **1 个文件**，或 1 组紧密耦合的同类改动
2. 每个 MWP **独立可验证**——运行一个具体命令即可确认完成
3. 严格按 **依赖图** 编排顺序——被依赖者必须先完成
4. 每个 MWP 附 **具体的验证命令**

---

## 依赖关系总图

```
MWP-01 (DynamicContext 数据结构)
  ├→ MWP-02 (response_models 辅助模型)
  ├→ MWP-03 (context.py 骨架 + build/inject/persist) ────┐
  │     ├→ MWP-04 (__init__.py 导出)                      │
  │     ├→ MWP-05 (persistence.py 持久化)                  │
  │     ├→ MWP-06 (context.py LLM 提取: 角色变化+一致性)   │
  │     ├→ MWP-07 (graph.py 策划确认节点注入)               │
  │     ├→ MWP-08 (writing_graph.py 写作确认节点注入)       │
  │     ├→ MWP-10 (web/app.py 后端集成)                    │
  │     └→ MWP-12 (Agent 上下文注入: writer/editor/...)    │
  ├→ MWP-09 (web/templates 面板 HTML + CSS + 日志埋点)     │
  ├→ MWP-11 (前端 JS: ContextPoller + 渲染 + 折叠条)       │
  ├→ MWP-13 (后端单元测试)                                 │
  ├→ MWP-14 (后端集成测试)                                 │
  ├→ MWP-15 (前端 Playwright E2E)                          │
  ├→ MWP-15a (前端 JS 单元测试)                            │
  └→ MWP-16 (全量回归验证)                                │
```

---

## 最小工作包清单

### MWP-01: DynamicContext 数据结构
**文件**: `src/state/state_types.py`
**改动**: 新增 `DynamicContext` dataclass（14 字段），在 `WriteSyncState` 追加 `dynamic_context: Optional[DynamicContext] = None`
**行数**: ~40 行新增
**依赖**: 无
**验证**:
```bash
python -c "from src.state.state_types import DynamicContext, WriteSyncState; dc = DynamicContext(); ws = WriteSyncState(); ws.dynamic_context = dc; print('OK')"
```

---

### MWP-02: 辅助 response_models
**文件**: `src/agents/response_models.py`
**改动**: 新增 `CharacterChange`, `CharacterChangeList`, `ContradictionItem`, `ContradictionList`
**行数**: ~15 行新增
**依赖**: MWP-01（仅概念依赖，可不严格等）
**验证**:
```bash
python -c "from src.agents.response_models import CharacterChange, CharacterChangeList, ContradictionItem, ContradictionList; c = CharacterChange(name='李凡', change='突破'); print(c)"
```

---

### MWP-03: context.py 骨架（Phase 1 · 纯本地逻辑）
**文件**: `src/agents/context.py`（新建）
**改动**: 实现 6 个纯本地函数（不调用 LLM）+ 日志埋点
- `build_writing_context(state) → str` — 从 `state.data.dynamic_context` 拼装 ≤800 字摘要
- `_inject(prompt, ctx_text) → str` — 包裹上下文到 prompt 前
- `persist_context(data) → None` — 写 `projects/{id}/context.json`（tmp→rename）+ `docs/dynamic/context.json`
- `_guess_arc_progress(character, ch_num) → str` — 基于章节进度的弧线估算
- `_get_recent_chapters(data, ch_num, n) → list[str]` — 取最近 n 章摘要
- `_gather_word_counts(data) → dict[int, int]` — 统计每章字数
- `_assess_pacing(data, ch_num) → str` — 节奏建议字符串
- 日志: `context.update`（耗时+字段长度）、`context.build`（输出字数）、`context.persist`（成功/失败）
- 数据上限裁剪: `unresolved_foreshadows` 保留最近 30 条、`resolved_foreshadows` 保留最近 30 条、`chapter_word_counts` 保留最近 50 章（在 update_dynamic_context 输出前统一裁剪）

同时提供 `update_dynamic_context` 的 **Phase 1 版本**（仅策划阶段 ch_num=0，不含 LLM 提取）：
- `update_dynamic_context(state, ch_num) → DynamicContext` — ch_num=0 时从 state 数据拼装各字段；ch_num>0 时暂返回空 DynamicContext()（含 `context.update` 日志埋点）

**行数**: ~200 行新增
**依赖**: MWP-01
**验证**:
```bash
python -c "
from src.state.state_types import WriteSyncState, DynamicContext
from src.agents.context import build_writing_context, persist_context
ws = WriteSyncState()
ws.dynamic_context = DynamicContext(character_snapshot='张三(主角)：...', plot_progress='0/30章')
ctx = build_writing_context({'data': ws})
assert len(ctx) <= 800
print(f'build_wc OK, len={len(ctx)}')
"
```

---

### MWP-04: __init__.py 导出
**文件**: `src/agents/__init__.py`
**改动**: 追加 `context.py` 公开函数的 re-export
**行数**: ~3 行新增
**依赖**: MWP-03
**验证**:
```bash
python -c "from src.agents import build_writing_context, persist_context; print('import OK')"
```

---

### MWP-05: persistence.py 持久化
**文件**: `src/state/persistence.py`
**改动**:
- 新增 `_safe_load_context(path)` / `_safe_dump_context(ctx)` / `_fix_dict_keys(data)` — 处理 dict[int,*] JSON 往返
- 修改 `load_project()` — 末尾追加 context.json 读取
**行数**: ~40 行新增
**依赖**: MWP-01
**验证**:
```bash
python -c "
from src.state.persistence import PersistenceManager
from src.state.state_types import DynamicContext, WriteSyncState
ws = WriteSyncState()
ws.metadata.project_id = 'test-mwp05'
ws.dynamic_context = DynamicContext(character_snapshot='测试', updated_chapter=1)
# 模拟写 + 读
import json, os
from pathlib import Path
Path('projects/test-mwp05').mkdir(parents=True, exist_ok=True)
with open('projects/test-mwp05/context.json','w') as f:
    json.dump(ws.dynamic_context.__dict__, f)
pm = PersistenceManager()
ws2 = pm.load_project('test-mwp05')
assert ws2.dynamic_context.character_snapshot == '测试'
print('roundtrip OK')
"
```

---

### MWP-06: context.py LLM 提取（Phase 3）
**文件**: `src/agents/context.py`（修改）
**改动**: 新增 2 个 LLM 提取函数 + 完善 `update_dynamic_context`
- `_extract_character_changes(content, chars) → list[CharacterChange]` — LLM 提取角色变化，超时→正则降级
- `_extract_contradictions(content, ctx) → list[ContradictionItem]` — LLM 检测一致性矛盾（无正则降级，失败直接跳过）
- 修改 `update_dynamic_context` — ch_num>0 时调用上述函数，并追加：
  - `_scan_foreshadows(data, ch_num)` — 从章纲提取未收伏笔列表
  - `_scan_resolved(data, ch_num)` — 检测本章已收伏笔
  - `_deadline_foreshadows(data, ch_num)` — 预估伏笔收束章节
  - `_check_foreshadow_resolved(ch, desc, content)` — 关键词匹配判断伏笔是否已收
  - ⑤节奏统计（`_gather_word_counts` + `_assess_pacing`）
  - ⑥全书进度（`plot_progress` + `story_beats_remaining`）
  - **6 个子步骤独立 try/except**：每步失败仅保持对应字段上版值，不污染其他字段（§4.6）
- 日志: `context.llm.chars`（成功/超时/fallback）、`context.llm.consistency`（矛盾数/耗时/状态）

**行数**: ~120 行新增
**依赖**: MWP-02, MWP-03
**验证**:
```bash
python -c "
from src.agents.context import update_dynamic_context
from src.state.state_types import WriteSyncState, CharactersState, Character, StoryState, StoryCore, StoryArc
ws = WriteSyncState()
ws.story = StoryState(step1=StoryCore(one_sentence='测试', tag='仙侠'), step2=StoryArc(setup='...',inciting='...',rising='...',climax_prep='...',resolution='...'))
ws.dynamic_context = None
ctx = update_dynamic_context({'data': ws, 'messages': []}, 0)
assert ctx.character_snapshot == ''
assert ctx.plot_progress == '0/?章'
print('update_dc(0) OK')
"
```

---

### MWP-07: graph.py 策划确认节点注入
**文件**: `src/graph/graph.py`
**改动**: 在 **7 个确认节点** 的 `y/confirm` 分支末尾追加 3 行：
- `一句话确认`、`策划确认`、`_扩展确认`、`_叙事确认`、`角色确认`、`世界观确认`、`章纲确认`
- 每个节点追加: `from ..agents.context import update_dynamic_context, persist_context; ctx = update_dynamic_context(state, 0); state["data"].dynamic_context = ctx; persist_context(state["data"])`
**行数**: ~21 行新增（每节点 3 行 × 7）
**依赖**: MWP-03, MWP-04
**验证**:
```bash
python -m pytest tests/test_graph.py -v -k "test_" 2>&1 | Select-String "PASSED|FAILED"
# 确认现有 graph 测试仍通过
python test_graph.py
```

---

### MWP-08: writing_graph.py 写作确认节点注入
**文件**: `src/graph/writing_graph.py`
**改动**: 在 `终稿确认` 节点的 `y` 分支末尾追加 `update_dynamic_context(state, ch)` + `persist_context`
**行数**: ~5 行新增
**依赖**: MWP-03, MWP-04（LLM 提取可选，Phase 1 无 LLM 也可运行）
**验证**:
```bash
python -m pytest tests/test_writing_graph.py -v 2>&1 | Select-String "PASSED|FAILED"
```

---

### MWP-09: web/templates 上下文面板 HTML + CSS
**文件**: `src/web/templates/workbench.html`
**改动**:
- 左侧导航新增「写作上下文」面板入口（§5.2 位置）
- 中间主区新增面板 HTML 结构（空态卡片 + 策划态卡片 + 写作态卡片）
- 新增 CSS: 骨架屏 shimmer 动画、卡片 fade-in（`prefers-reduced-motion` 降级）、编辑冲突黄色提示条、保存按钮三态
**行数**: ~120 行新增
**依赖**: 无（纯前端，可独立验证）
**验证**: 浏览器打开 `http://localhost:8000`，左侧导航应出现「写作上下文」；点击后中间主区显示空态面板

---

### MWP-10: web/app.py 后端集成
**文件**: `src/web/app.py`
**改动**:
- `resume_session()` — 末尾追加 `update_dynamic_context` + `persist_context` + `logger.info("[context.web] updating after resume")`
- `save_panel()` — 末尾追加 `update_dynamic_context` + `persist_context` + `logger.info("[context.web] updating after panel save")`
- 新增 `PUT /api/panel/{sid}/context` 端点 — 处理字段覆盖 + `foreshadows_add`/`foreshadows_remove` 列表操作
  - **关键约束**: 不调用 `update_dynamic_context()`，避免 LLM 提取覆盖用户手动修改
  - 字段级覆盖: `character_snapshot` / `world_changes` / `world_consistency_notes` 直接覆写
  - 列表操作: `foreshadows_add` 追加去重, `foreshadows_remove` 移除匹配
- `get_status()` — 响应追加 `context` 字段
- 统一错误响应格式（`{error, code, status}`）
**行数**: ~60 行新增
**依赖**: MWP-03, MWP-04
**验证**:
```bash
python -m pytest tests/test_web_ui.py -v -k "test_" 2>&1 | Select-String "PASSED|FAILED"
```

---

### MWP-11: 前端 JS（ContextPoller + 渲染 + 折叠条）
**文件**: `src/web/templates/workbench.html`（修改 `<script>` 部分）
**改动**:
- `ContextPoller` 类 — 1s 轮询 + `visibilitychange` 暂停/恢复 + 指数退避重试
- `deserializeContext(raw)` / `serializeContextUpdate(fields)` — snake↔camel 序列化
- `refreshContextPanel(data)` — 读取 `data.context`，渲染 5 种卡片
- `renderContextCard(id, title, content)` / `renderForeshadows(id, ctx)` / `renderProgressBar(id, progress)`
- `bindInlineEdit(fieldId, fieldName)` — 内联编辑 + 冲突检测（§5.11.4）
- `renderContextCollapse(ctxText)` — 对话区 AI 消息上方的可折叠上下文条
- `extractStats(ctxText)` — 从上下文提取统计数据（"角色3人·前章2章"）
**行数**: ~180 行新增
**依赖**: MWP-09（HTML 结构需先存在）
**验证**: 新建 session → 完成策划 → 切换到上下文面板 → 面板渲染角色快照+世界格局+伏笔列表；AI 生成初稿后对话区显示折叠条

---

### MWP-12: Agent 上下文注入（5 文件）
**文件**: `src/agents/writer.py`, `editor.py`, `writer_check.py`, `rhythm.py`, `proofreader.py`
**改动**: 每个 Agent 的 `run_*` 函数中，在 `build_*_prompt()` 调用后、`llm.complete_structured()` 调用前，追加 3 行：
```python
from .context import build_writing_context
ctx_text = build_writing_context(state)
if ctx_text:
    prompt = _inject(prompt, ctx_text)
```
**行数**: ~15 行新增（每文件 3 行 × 5）
**依赖**: MWP-03, MWP-04
**验证**:
```bash
python -m pytest tests/test_cli.py -v 2>&1 | Select-String "PASSED|FAILED"
# CLI 全流程应正常运行，Agent 生成质量不受影响
```

---

### MWP-13: 后端单元测试
**文件**: `tests/test_context.py`（新建）
**用例** (≥14，覆盖设计 §11.5.1 + §11.5.2):
1. `test_update_dc_empty_state` — 空 state → 全默认 DynamicContext
2. `test_update_dc_chars_confirmed` — 角色已确认 → character_snapshot 非空
3. `test_update_dc_world_confirmed` — 世界已确认 → world_changes 非空
4. `test_update_dc_outline_confirmed` — 章纲已确认 → foreshadows + plot_progress 非空
5. `test_build_wc_null_context` — context=None → 返回 ""
6. `test_build_wc_full_context` — 满 context → 返回 ≤800 字摘要
7. `test_build_wc_truncation` — 超长字段 → 截断到 800 字
8. `test_persist_roundtrip` — 写 context.json → 读回 → 字段一致
9. `test_inject_format` — ctx_text 非空 → prompt 被包裹；ctx_text 空 → prompt 不变
10. `test_guess_arc_progress` — ch_num=0 → "0%"；主角 5/30 → 接近 "16%"
11. `test_extract_changes_timeout` — mock LLM 超时 → 降级正则 → 返回空列表
12. `test_extract_changes_rate_limit` — mock 429 → 重试 1 次 → 返回结果
13. `test_extract_changes_malformed_json` — mock 返回非 JSON → 降级正则
14. `test_extract_changes_empty` — mock 返回空 changes → character_snapshot 未变
15. `test_update_dc_boundary_ch_out_of_range` — ch_num 越界 → 不抛异常
16. `test_update_dc_boundary_content_none` — cd.final.content is None → 不抛异常
17. `test_update_dc_boundary_chapter_outline_none` — chapter_outline=None → 跳过伏笔/进度
18. `test_update_dc_boundary_cd_final_none` — cd.final is None → 跳过 LLM 提取
19. `test_update_dc_boundary_chapters_empty` — drafts.chapters 为空 → 跳过摘要/节奏
20. `test_persist_disk_full` — mock OSError → 不抛异常
21. `test_persist_rename_fail` — mock rename OSError → 不抛异常
22. `test_data_cap_foreshadows` — unresolved 超 30 → 裁剪到 30；resolved 同理
23. `test_data_cap_word_counts` — chapter_word_counts 超 50 → 裁剪到 50
**依赖**: MWP-06
**验证**:
```bash
python -m pytest tests/test_context.py -v
```

---

### MWP-14: 后端集成测试
**文件**: `tests/test_graph.py`（补充）、`tests/test_api.py`（补充）、`tests/test_context_e2e.py`（新建）
**用例** (≥5):
1. (graph) 终稿确认后 `state.data.dynamic_context` 非空
2. (graph) 写 2 章后 `recent_chapters_summary` 包含最近章节
3. (api) `PUT /api/panel/{sid}/context` 保存后 `GET /api/status/{sid}` 返回更新后的 context
4. (api) 字段超长 → 返回 400
5. (e2e) `test_full_3_chapter_context_accumulation` — 模拟写 3 章全流程，验证逐章累积（使用 mock LLM + `@pytest.mark.slow`）

**依赖**: MWP-07, MWP-08, MWP-10
**验证**:
```bash
python -m pytest tests/test_graph.py tests/test_api.py -v
```

---

### MWP-15a: 前端 JS 单元测试
**文件**: `tests/test_frontend_context.test.js`（新建，Vitest/Jest）
**用例** (≥6，详见 §5.14.1):
1. `deserializeContext(null)` → null
2. `deserializeContext({character_snapshot:"张三…"})` → camelCase 对象，所有字段有默认值
3. `serializeContextUpdate({characterSnapshot:"新值"})` → `{character_snapshot:"新值"}`
4. `extractStats("角色 3人 · 前章2章")` → `"3项"` 格式
5. `renderContextCard("", title, "")` → null（空内容不渲染）
6. `renderContextCard("", title, 超长内容)` → 截断到 maxLength
**依赖**: MWP-11（JS 函数需先存在）
**验证**:
```bash
npx vitest run tests/test_frontend_context.test.js
```

---

### MWP-15: 前端 Playwright E2E
**文件**: `tests/test_playwright.py`（补充）
**用例** (≥8，详见 §5.14.2):
1. 上下文面板展示（策划完成 → 切换面板）
2. 手动修正角色快照（点击编辑 → 修改 → 保存）
3. 手动添加伏笔（点击添加 → 输入 → 确认）
4. 对话区折叠上下文（AI 生成 → 折叠条可见 → 展开查看）
5. 轮询暂停/恢复（切 tab → 切回）
6. 编辑冲突（打开编辑 → 等待 AI 更新 → 冲突提示）
7. 窄屏响应式（<768px）
8. 骨架屏（新 session 首次加载）

**依赖**: MWP-09, MWP-10, MWP-11
**验证**:
```bash
python -m pytest tests/test_playwright.py -v -k "context"
```

---

### MWP-16: 全量回归验证
**操作**: 运行全部现有测试 + CLI 全流程 + Web UI 手动端到端
```bash
# 1. 后端全量
python -m pytest tests/ --ignore=tests/test_e2e.py -v

# 2. 图测试
python test_graph.py

# 3. CLI 全流程
python -m src.cli --full

# 4. Web UI
uvicorn src.web.app:app --reload
# 手动验证: 新建项目 → 走完策划 → 写 2 章 → 检查上下文面板 → 切换面板 → 编辑上下文 → 保存
```
**依赖**: 全部 MWP 完成
**通过标准**: 现有 44 测试 + 新增测试 全部 PASS，CLI/Web 无报错

---

## 明确不纳入本次实施的项

| 设计引用 | 内容 | 原因 |
|---------|------|------|
| §5.9.3 TypeScript 类型 | DynamicContext / StatusResponse / ContextPanelUpdateRequest 的 .d.ts 定义 | 项目当前为纯 JS，不引入 TS。前端通过 JSDoc 注释实现类型提示 |
| §5.10.1 Props 接口 | ContextPanelProps / ContextCardProps / ForeshadowListProps | 同上，纯 JS 项目 |
| §8 调试端点 | `GET /api/debug/context/{sid}` | 仅开发环境 (`DEBUG=true`)，后续迭代按需添加 |
| §8 Session 主动清理 | 定时扫描 expired session | 设计标注为"建议后续迭代，非本次范围" |
| §9.2 性能优化 | 并行 LLM 调用、ch≤3 跳过一致性、正则预扫描、异步写入 | 优化策略，非功能需求。功能稳定后再做 |
| §12.2 可观测性指标 | 超时率/成功率监控面板 | 运维层面，不在本次功能范围 |
| §15.3 消息角色控制 | context 注入为 user 角色而非 system prompt | 当前 Agent 均为单一 prompt 字符串（非 chat message 模式），无 system/user 角色区分 |

---

## 实施顺序与分组

按依赖拓扑排序，可分 6 个批次执行：

### Batch 1: 基础数据层（2 MWP · ~55 行）
```
MWP-01: DynamicContext dataclass
MWP-02: response_models 辅助模型
```
> 此批结束后，`DynamicContext` 和辅助模型可正常导入。

### Batch 2: context.py 骨架 + 持久化（4 MWP · ~243 行）
```
MWP-03: context.py 骨架（build/inject/persist + update Phase 1 + 日志）
MWP-04: __init__.py 导出
MWP-05: persistence.py 持久化
MWP-06: context.py LLM 提取
```
> 此批结束后，`update_dynamic_context(state, 0)` 可正常工作，`build_writing_context` 可返回摘要。

### Batch 3: 图集成（2 MWP · ~26 行）
```
MWP-07: graph.py 策划确认节点注入
MWP-08: writing_graph.py 写作确认节点注入
```
> 此批结束后，每次确认后 `context.json` 自动落地。

### Batch 4: Web 后端 + 前端（3 MWP · ~360 行）
```
MWP-09: workbench.html 面板 HTML + CSS
MWP-10: app.py 后端集成
MWP-11: 前端 JS（ContextPoller + 渲染）
```
> 此批结束后，浏览器可查看/编辑上下文面板。

### Batch 5: Agent 注入（1 MWP · ~15 行）
```
MWP-12: 5 个 Agent 注入上下文
```
> 此批结束后，AI 生成时使用累积上下文。

### Batch 6: 测试与验证（5 MWP）
```
MWP-13: 后端单元测试 (≥14 用例)
MWP-14: 后端集成测试 (≥4 用例)
MWP-15a: 前端 JS 单元测试 (≥6 用例)
MWP-15: 前端 Playwright E2E (≥8 用例)
MWP-16: 全量回归验证
```
> 此批结束后，所有测试通过，可标记功能完成。

---

## 每批验证关口

| 批次 | 关口验证命令 | 预期结果 |
|------|------------|---------|
| Batch 1 | `python -c "from src.state.state_types import DynamicContext; print(DynamicContext())"` | 无报错 |
| Batch 2 | `python -c "from src.agents.context import build_writing_context; print('OK')"` | 无报错 |
| Batch 3 | `python test_graph.py` | PASS |
| Batch 4 | 浏览器打开 → 左侧出现「写作上下文」→ 点击有空态 | 无 JS 报错 |
| Batch 5 | `python -m src.cli --full` 走完策划+写作 | 正常运行 |
| Batch 6 | `python -m pytest tests/ --ignore=tests/test_e2e.py` | 全部 PASS |

---

## 预计工作量

| 批次 | MWP 数 | 新增代码行 | 预计耗时 |
|------|--------|----------|---------|
| Batch 1 | 2 | ~55 | 20 min |
| Batch 2 | 4 | ~260 | 100 min |
| Batch 3 | 2 | ~26 | 20 min |
| Batch 4 | 3 | ~360 | 120 min |
| Batch 5 | 1 | ~15 | 10 min |
| Batch 6 | 5 | ~520 | 80 min |
| **合计** | **17** | **~1236** | **~5.8 h** |
