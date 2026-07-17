# WriteSync 确认编辑功能设计

日期：2026-07-12
状态：设计中
版本：v0.5.0

---

## 1. 背景与动机

### 当前问题

WriteSync 的确认循环中，用户面对 AI 产出的内容只能「看 + 打字反馈」，无法直接编辑内容：

```
SSE confirm → 用户看纯文本结果 → 输入反馈文字 → 确认/拒绝 → 主 Agent 重决策
```

这导致：
- 用户想改一个角色的名字，必须打字描述「把张三改成李四」，然后等 AI 重新生成整个角色卡
- 章节正文只需微调几个句子，却要走「反馈 → 主 Agent 决策 → 重写」的完整循环
- 反馈文字和实际想要的修改之间存在理解偏差（LLM 可能改错地方）

### 设计目标

在 confirm 事件和 `_mark_confirmed` 之间插入「用户直接编辑」环节：

1. AI 产出 → 用户可以在确认前直接修改内容
2. 修改后的内容直接存入 state，不再触发 AI 重生成
3. 编辑确认后自动标记下游依赖为「待审」（stale）

### 竞品参考

此设计参考了 StoryForge（故事熔炉）的「Preview → Edit → Adopt」模式：
- StoryForge 所有 AI 产出都先展示为预览，用户编辑后再采纳
- 采纳后的内容进入 IndexedDB，与原 AI 产出分离存储
- WriteSync 借鉴其「编辑即确认」的理念，但保持自己的主 Agent 编排架构

---

## 2. 整体流程变更

```
AI 产出 → SSE confirm（携带 editable 元数据）
         │
         ├─ 结构化产出（角色/世界观/章纲/故事）
         │    → 表单编辑 → 直接点「确认」
         │
         └─ 长文本产出（章节正文/校对稿）
              → 富文本编辑 → 点「预览对比」→ 查看 diff → 点「确认」

POST /api/v2/respond 新增字段: edited_content（JSON）
↓
loop.py 接收 → 如果 edited_content 存在 → 先 apply 编辑 → 再 _mark_confirmed
→ 触发 stale_tracker：标记依赖项为「待审」
```

**关键变化**：
1. `confirm` SSE 事件 payload 新增 `editable` 字段 — 告诉前端哪些字段可编辑、类型是什么、当前值
2. POST `/api/v2/respond` 新增可选参数 `edited_content` — 用户编辑后的内容
3. 依赖追踪模块 `stale_tracker` — 编辑确认后自动标记受影响的下游产出
4. 前端 confirm 处理器改为渲染编辑表单，而非纯文本按钮

---

## 3. 数据模型

### 3.1 SSE confirm 事件扩展

当前 `confirm` payload：
```json
{"type":"confirm", "agent":"writer", "content":{...}, "dashboard":{...}, "chapter_num":1}
```

新增 `editable` 字段：
```json
{
  "type": "confirm",
  "agent": "writer",
  "content": {...},
  "dashboard": {...},
  "chapter_num": 1,
  "editable": {
    "mode": "richtext",
    "fields": [
      {"key": "content", "label": "正文", "type": "richtext", "current": "..."},
      {"key": "title", "label": "章节标题", "type": "text", "current": "..."}
    ],
    "preview_required": true
  }
}
```

各 Agent 的 `editable` 配置：

| Agent | mode | preview_required | 可编辑字段（SSE key → dataclass 字段映射） | 备注 |
|-------|------|-----------------|-----------|------|
| story (expansion) | form | false | one_sentence (→ step1.one_sentence), tag (→ step1.tag), setup/inciting/rising/climax/theme/moral (→ step2.*) | step2 = StoryArc dataclass |
| story (topics) | topics | false | 选题选择（非编辑，保持现有逻辑） | |
| character | form | false | name, role, personality, goal | 前端按索引 i 重建 `[{name,role,...}]` 数组提交；adapter 当前仅发送 4 字段 |
| world | form | false | power_system (→ power_system.system_name), tiers (→ power_system.tiers), locations (→ geography.major_locations), factions (→ society.factions) | WorldState 是嵌套 dataclass，编辑时需展开到子对象 |
| outline | form | false | title (→ chapter_title), core_event (→ core_event) | SSE key `title` 映射到 dataclass `chapter_title`；前端用 `num` 做索引 |
| writer | richtext | **true** | content (→ draft.content) | 两步流：编辑→预览对比→确认；无 title 字段 |
| proofreader | — | — | content (→ final.content，不单独确认，内嵌于 writer 的 confirm payload) | `requires_confirmation` 保持 False |
| novel_review | form | false | passed, recommendations | |

### 3.2 用户响应扩展

当前 `_user_response`：
```python
{"approved": bool, "feedback": str, "scope": str}
```

改为：
```python
{
    "approved": bool,
    "feedback": str,
    "scope": str,
    "edited_content": Optional[dict]  # {field_key: new_value, ...}
}
```

### 3.3 Stale 追踪模型

新增 `src/orchestrator/stale_tracker.py`：

```python
# 依赖关系定义
DEPENDENCY_MAP = {
    "story":      ["character", "world", "outline", "writer"],
    "character":  ["outline", "writer"],
    "world":      ["outline", "writer"],
    "outline":    ["writer"],
    "writer":     ["proofreader"],
}
```

需要在 `WriteSyncState` dataclass（`state_types.py`）中新增字段：
```python
stale_markers: dict = field(default_factory=dict)
# 例: {"outline": ["character", "world"], "writer": ["outline"]}
# 含义: outline 因 character/world 变更而 stale; writer 因 outline 变更而 stale
```

需要在 `Dashboard` dataclass（`models.py`）中新增字段供主 Agent 决策可见：
```python
stale_markers: dict = field(default_factory=dict)
```

### 3.4 AgentResult 扩展

在 `AgentResult` dataclass（`models.py`）中新增可选字段：
```python
editable: Optional[dict] = None  # {mode, fields, preview_required}
```

---

## 4. 后端变更

### 4.1 loop.py

在 `_wait_for_user()` 返回后、`_mark_confirmed()` 之前插入 apply 逻辑：

```python
# 位置：loop.py run() 方法中，confirm 分支
from .stale_tracker import mark_stale

response = await self._wait_for_user()

# ★ 新增：先应用用户编辑
if response.get("edited_content"):
    self._apply_edits(result.agent, response["edited_content"], chapter_num)
    # 标记下游依赖为 stale
    mark_stale(self.workspace, result.agent)
    # ★ 编辑了章节/设定内容 → 触发事实重新提取（占位，事实账本实现后启用）
    self._request_fact_revalidation(result.agent, chapter_num)

# 然后再确认
if response.get("feedback"):
    self.workspace.add_feedback(result.agent, response["feedback"])

if response.get("approved"):
    self._mark_confirmed(result.agent)
```

新增 `_apply_edits` 方法（所有状态访问使用 `self.workspace.raw_state` dataclass 属性）：

```python
def _apply_edits(self, agent: str, edits: dict, chapter_num: int = 0):
    """将用户编辑的内容直接写入 workspace state（使用 raw_state dataclass）"""
    state = self.workspace.raw_state  # WriteSyncState dataclass
    
    if agent == "story":
        story = state.story
        if not story:
            return
        if "one_sentence" in edits:
            story.step1.one_sentence = edits["one_sentence"]
        if "tag" in edits:
            story.step1.tag = edits["tag"]
        # step2 是 StoryArc dataclass
        if story.step2:
            for field in ["setup", "inciting", "rising", "climax_prep", "resolution", "theme", "moral"]:
                if field in edits:
                    setattr(story.step2, field, edits[field])
    
    elif agent == "character":
        # edits["characters"] 是前端重建的完整列表 [{name, role, personality, goal}, ...]
        if "characters" in edits and state.characters:
            new_list = edits["characters"]
            for i, ch_data in enumerate(new_list):
                if i < len(state.characters.characters):
                    card = state.characters.characters[i]
                    for key in ["name", "role", "personality", "goal"]:
                        if key in ch_data:
                            setattr(card, key, ch_data[key])
    
    elif agent == "world":
        world = state.world
        if not world:
            return
        # WorldState 是嵌套 dataclass：power_system / geography / society / history
        if "power_system" in edits and world.power_system:
            world.power_system.system_name = edits["power_system"]
        if "tiers" in edits and world.power_system:
            world.power_system.tiers = edits["tiers"]
        if "locations" in edits and world.geography:
            # adapter SSE 发送 locations: [{name, description}, ...] 或 [str, ...]
            if edits["locations"] and isinstance(edits["locations"][0], dict):
                world.geography.major_locations = edits["locations"]
            else:
                # 简单字符串列表 → 转为 dict 格式
                world.geography.major_locations = [
                    {"name": loc, "description": "", "significance": ""}
                    if isinstance(loc, str) else loc
                    for loc in edits["locations"]
                ]
        if "factions" in edits and world.society:
            if edits["factions"] and isinstance(edits["factions"][0], dict):
                world.society.factions = edits["factions"]
            else:
                world.society.factions = [
                    {"name": fac, "description": "", "align": ""}
                    if isinstance(fac, str) else fac
                    for fac in edits["factions"]
                ]
    
    elif agent == "outline":
        outline = state.chapter_outline
        if not outline:
            return
        if "chapters" in edits:
            for i, ch_data in enumerate(edits["chapters"]):
                if i < len(outline.chapters):
                    ch = outline.chapters[i]
                    if "title" in ch_data:
                        # SSE key "title" → dataclass field "chapter_title"
                        ch.chapter_title = ch_data["title"]
                    if "core_event" in ch_data:
                        ch.core_event = ch_data["core_event"]
        if "total_chapters" in edits:
            outline.total_chapters = edits["total_chapters"]
    
    elif agent == "writer":
        ch = state.drafts.chapters.get(chapter_num)
        if ch and ch.draft:
            if "content" in edits:
                ch.draft.content = edits["content"]
            # 注：ChapterDraft 无独立 title 字段；章节标题来自 outline.chapter_title
    
    elif agent == "proofreader":
        ch = state.drafts.chapters.get(chapter_num)
        if ch and ch.final:
            if "content" in edits:
                ch.final.content = edits["content"]
    
    self.workspace.save()
```

### 4.2 app.py

`/api/v2/respond` 端点新增参数：

```python
@app.post("/api/v2/respond/{project_id}")
async def respond_v2(
    project_id: str,
    approved: str = Form("true"),
    feedback: str = Form(""),
    scope: str = Form("all"),
    edited_content: str = Form(""),  # ★ 新增：JSON 字符串
):
    edits = None
    if edited_content:
        try:
            edits = json.loads(edited_content)
        except json.JSONDecodeError:
            pass
    
    ok = send_to_session(
        project_id,
        approved=approved.lower() in ("true", "1", "yes"),
        feedback=feedback,
        scope=scope,
        edited_content=edits,  # ★ 新增参数
    )
    return JSONResponse({"ok": ok})
```

### 4.3 orchestrator_api.py

`send_to_session` 新增参数：

```python
def send_to_session(project_id, approved, feedback="", scope="all", edited_content=None):
    session = _orchestrator_sessions.get(project_id)
    if session is None or not session.is_running():
        return False
    session.user_respond(
        approved=approved,
        feedback=feedback,
        scope=scope,
        edited_content=edited_content,  # ★ 新增
    )
    return True
```

### 4.4 loop.py — user_respond

```python
def user_respond(self, approved, feedback="", scope="all", edited_content=None):
    self._user_response = {
        "approved": approved,
        "feedback": feedback,
        "scope": scope,
        "edited_content": edited_content,
    }
    self._pause.set()
```

### 4.5 新增 stale_tracker.py

```python
"""编辑后的依赖追踪 — 标记下游产出为待审"""

DEPENDENCY_MAP: dict[str, list[str]] = {
    "story":      ["character", "world", "outline", "writer"],
    "character":  ["outline", "writer"],
    "world":      ["outline", "writer"],
    "outline":    ["writer"],
    "writer":     ["proofreader"],
}

def mark_stale(workspace, edited_agent: str):
    """编辑确认后自动标记下游依赖（使用 raw_state dataclass）"""
    downstream = DEPENDENCY_MAP.get(edited_agent, [])
    if not downstream:
        return
    
    state = workspace.raw_state  # WriteSyncState dataclass
    for target in downstream:
        if target not in state.stale_markers:
            state.stale_markers[target] = []
        if edited_agent not in state.stale_markers[target]:
            state.stale_markers[target].append(edited_agent)
    workspace.save()

def clear_stale(workspace, agent: str):
    """Agent 被重新确认后清除其 stale 标记。在 _mark_confirmed 中条件调用"""
    state = workspace.raw_state
    state.stale_markers.pop(agent, None)
    workspace.save()

def get_stale_info(workspace) -> dict:
    """获取当前 stale 状态，供 Dashboard 和前端使用"""
    return workspace.raw_state.stale_markers
```

**clear_stale 调用位置说明**：在 `_mark_confirmed()` 方法内部，确认成功后检查是否需要清除：
```python
# _mark_confirmed 内部
if agent_name in {"story", "character", "world", "outline", "writer", "proofreader"}:
    from .stale_tracker import clear_stale
    clear_stale(self.workspace, agent_name)
```


---

## 5. 前端变更（workbench.html）

### 5.1 confirm 事件处理器改造

当前 `sseClient.addEventListener('confirm', ...)` 在收到事件后调用 `showActions()` 渲染按钮。改为：

```javascript
sseClient.addEventListener('confirm', async (e) => {
    const d = JSON.parse(e.data);
    hasInterrupt = true;
    
    // ★ 新增：检查是否有 editable 元数据
    if (d.editable) {
        renderEditPanel(d);   // 渲染编辑面板（替代纯文本按钮）
    } else {
        // 向后兼容：无 editable 元数据时走原有按钮逻辑
        showActions(['请确认 ' + d.agent + ' 的产出']);
    }
    
    // 填充 stateData（保持现有逻辑）
    if (d.content) {
        // ... 现有 stateData 填充逻辑 ...
    }
    refreshV2State();
});
```

### 5.2 renderEditPanel — 编辑面板渲染

```javascript
function renderEditPanel(confirmData) {
    const { agent, content, editable, chapter_num } = confirmData;
    const container = document.getElementById('chatMessages');
    
    // 清除旧的 actions
    const actionsDiv = document.getElementById('chatActions');
    if (actionsDiv) { actionsDiv.innerHTML = ''; }
    
    let html = `<div class="edit-panel" data-agent="${agent}">`;
    html += `<div class="edit-panel-header">📝 编辑 ${getAgentLabel(agent)} 产出</div>`;
    
    if (editable.mode === 'richtext') {
        // 模式 B：富文本编辑（章节正文）
        html += renderRichtextFields(editable.fields);
        
        if (editable.preview_required) {
            // 两步流：先编辑 → 预览对比 → 确认
            html += `<div class="edit-actions">
                <button onclick="previewEdit('${agent}', ${chapter_num || 0})">预览修改</button>
                <button onclick="skipEdit('${agent}')">不做修改，直接确认</button>
            </div>`;
        } else {
            html += `<div class="edit-actions">
                <button onclick="submitEdit('${agent}', ${chapter_num || 0})">确认</button>
                <button onclick="cancelEdit()">放弃编辑，提意见重做</button>
            </div>`;
        }
    } else if (editable.mode === 'form') {
        // 模式 A：表单编辑（角色/世界观/章纲）
        html += renderFormFields(editable.fields, agent);
        html += `<div class="edit-actions">
            <button onclick="submitEdit('${agent}', ${chapter_num || 0})">确认</button>
            <button onclick="cancelEdit()">放弃编辑，提意见重做</button>
        </div>`;
    } else if (editable.mode === 'topics') {
        // 模式 C：选题选择（保持现有逻辑）
        html += renderTopicSelection(content.topics);
    }
    
    html += '</div>';
    container.innerHTML += html;
    container.scrollTop = container.scrollHeight;
}
```

### 5.3 字段渲染函数

```javascript
function renderFormFields(fields, agent) {
    let html = '<div class="edit-form">';
    
    if (agent === 'character' && fields.length > 0) {
        // 角色卡数组：每个角色一个卡片
        // adapter 当前发送: name, role, personality, goal（4 字段）
        // 后续可扩展为包含 background 等更多字段
        const characters = fields[0].current || [];
        characters.forEach((char, i) => {
            html += `<div class="char-card">
                <label>姓名: <input data-field="characters[${i}].name" value="${esc(char.name)}"></label>
                <label>角色: <input data-field="characters[${i}].role" value="${esc(char.role)}"></label>
                <label>性格: <textarea data-field="characters[${i}].personality">${esc(char.personality)}</textarea></label>
                <label>目标: <textarea data-field="characters[${i}].goal">${esc(char.goal)}</textarea></label>
            </div>`;
        });
    } else if (agent === 'outline') {
        // 章纲：每章一行
        const chapters = fields.find(f => f.key === 'chapters')?.current || [];
        chapters.forEach((ch, i) => {
            html += `<div class="chapter-row">
                <span class="ch-num">第${ch.num}章</span>
                <input data-field="chapters[${i}].title" value="${esc(ch.title)}" placeholder="标题">
                <input data-field="chapters[${i}].core_event" value="${esc(ch.core_event)}" placeholder="核心事件">
            </div>`;
        });
    } else {
        // 通用表单
        fields.forEach(f => {
            html += `<label>${f.label}: `;
            if (f.type === 'textarea' || (f.current && f.current.length > 100)) {
                html += `<textarea data-field="${f.key}">${esc(f.current || '')}</textarea>`;
            } else {
                html += `<input data-field="${f.key}" value="${esc(f.current || '')}">`;
            }
            html += '</label>';
        });
    }
    
    html += '</div>';
    return html;
}

function renderRichtextFields(fields) {
    let html = '<div class="edit-form richtext-mode">';
    fields.forEach(f => {
        html += `<label>${f.label}: `;
        html += `<textarea class="richtext-editor" data-field="${f.key}" 
                  style="min-height:400px;width:100%;font-family:monospace;">${esc(f.current || '')}</textarea>`;
        html += '</label>';
    });
    html += '</div>';
    return html;
}
```

### 5.4 提交函数

```javascript
// 收集表单编辑数据
function collectEdits() {
    const edits = {};
    document.querySelectorAll('[data-field]').forEach(el => {
        edits[el.dataset.field] = el.value;
    });
    return edits;
}

// 将扁平字段值重建为结构化数据（按 agent 类型）
function buildEditedContent(agent, flatEdits) {
    if (agent === 'character') {
        // 从 "characters[0].name" 等键值重建完整数组
        // adapter 发送 4 字段: name, role, personality, goal
        const chars = [];
        let i = 0;
        while (flatEdits[`characters[${i}].name`] !== undefined) {
            chars.push({
                name: flatEdits[`characters[${i}].name`] || '',
                role: flatEdits[`characters[${i}].role`] || '',
                personality: flatEdits[`characters[${i}].personality`] || '',
                goal: flatEdits[`characters[${i}].goal`] || '',
            });
            i++;
        }
        return { characters: chars };
    }
    if (agent === 'outline') {
        // 从 "chapters[0].title" 等键值重建章纲数组
        // SSE key: "title" → dataclass field: "chapter_title"（映射在 _apply_edits 中处理）
        const chapters = [];
        let i = 0;
        while (flatEdits[`chapters[${i}].title`] !== undefined) {
            chapters.push({
                title: flatEdits[`chapters[${i}].title`] || '',
                core_event: flatEdits[`chapters[${i}].core_event`] || '',
            });
            i++;
        }
        return { chapters };
    }
    if (agent === 'world') {
        // locations/factions 扁平整体替换
        return flatEdits;
    }
    // story/writer/proofreader: 字段级编辑直接使用
    return flatEdits;
}

// 一步提交（表单模式）
async function submitEdit(agent, chapterNum) {
    const flatEdits = collectEdits();
    const structuredEdits = buildEditedContent(agent, flatEdits);
    await resumeV2Edit(structuredEdits);
}

// 预览对比（两步流第一步）
async function previewEdit(agent, chapterNum) {
    const flatEdits = collectEdits();
    window._pendingEdits = buildEditedContent(agent, flatEdits);
    renderDiffPanel(agent, chapterNum, window._pendingEdits);
}

// 确认提交（两步流第二步）
async function confirmEdit(agent, chapterNum) {
    const edits = window._pendingEdits;
    if (!edits) return;
    await resumeV2Edit(edits);
}

// 核心提交函数
async function resumeV2Edit(editedContent) {
    const f = new FormData();
    f.append('approved', 'true');
    f.append('edited_content', JSON.stringify(editedContent));
    f.append('scope', 'all');
    
    await fetch('/api/v2/respond/' + v2ProjectId, { method: 'POST', body: f });
    hasInterrupt = false;
    setChatStatus('AI 思考中...');
}

// 跳过编辑
async function skipEdit(agent) {
    const f = new FormData();
    f.append('approved', 'true');
    f.append('scope', 'all');
    await fetch('/api/v2/respond/' + v2ProjectId, { method: 'POST', body: f });
    hasInterrupt = false;
    setChatStatus('AI 思考中...');
}

// 放弃编辑
async function cancelEdit() {
    const feedback = prompt('请输入修改意见（将触发 AI 重新生成）：');
    const f = new FormData();
    f.append('approved', 'false');
    if (feedback) f.append('feedback', feedback);
    f.append('scope', 'all');
    await fetch('/api/v2/respond/' + v2ProjectId, { method: 'POST', body: f });
    hasInterrupt = false;
    setChatStatus('AI 思考中...');
}
```

### 5.5 对比面板（diff view）

```javascript
function renderDiffPanel(agent, chapterNum, edits) {
    const container = document.getElementById('chatMessages');
    const origContent = document.querySelector('[data-field="content"]')?.value || '';
    const editedContent = edits.content || origContent;
    
    const html = `
    <div class="diff-panel">
        <div class="diff-panel-header">📋 修改对比 — 第${chapterNum || '?'}章</div>
        <div class="diff-columns">
            <div class="diff-col">
                <div class="diff-col-title">原始版本</div>
                <div class="diff-content">${esc(origContent).replace(/\n/g, '<br>')}</div>
            </div>
            <div class="diff-col">
                <div class="diff-col-title">修改后</div>
                <div class="diff-content">${esc(editedContent).replace(/\n/g, '<br>')}</div>
            </div>
        </div>
        <div class="diff-actions">
            <button onclick="confirmEdit('${agent}', ${chapterNum || 0})">确认修改</button>
            <button onclick="backToEdit()">继续编辑</button>
            <button onclick="cancelEdit()">放弃</button>
        </div>
    </div>`;
    
    container.innerHTML += html;
    container.scrollTop = container.scrollHeight;
}
```

### 5.6 Stale 警告渲染

```javascript
// 在 refreshV2State() 中，各面板渲染时检查 stale 标记
function renderPanelWithStale(panelName, content) {
    const staleInfo = stateData.stale_markers || {};
    const isStale = staleInfo[panelName] && staleInfo[panelName].length > 0;
    
    if (isStale) {
        const reasons = staleInfo[panelName].join('、');
        return `<div class="stale-warning" title="因 ${reasons} 变更，此内容可能已过时">
            ⚠️ ${content}
        </div>`;
    }
    return content;
}
```

---

## 6. 依赖追踪

### 6.1 触发时机

- 用户在 confirm 前编辑了某个 Agent 产出并点「确认」
- `_apply_edits()` 执行后 → `workspace.mark_stale(agent)` 自动触发
- 用户不编辑直接确认 → 不触发 stale 标记

### 6.2 清除时机

- 当被标记为 stale 的 Agent 被重新确认（AI 重新生成或用户重新编辑）时，清除其 stale 标记
- 在 `_mark_confirmed()` 中调用 `clear_stale(workspace, agent)`

### 6.3 Dashboard 集成

`stale_markers` 作为 Dashboard 的一个字段，主 Agent 决策时可以看到哪些产出因上游变更而可能过时。主 Agent 可以据此优先调对应 Agent 重新生成。

需在 `workspace.get_dashboard()` 中新增一行填充：
```python
# get_dashboard() 返回的 Dashboard 对象中
stale_markers=s.stale_markers,
```

---

## 7. 编辑触发事实重提取

### 7.1 问题

用户直接编辑内容（如修改角色设定、改写章节事件）后，如果不触发事实重新提取，后续章节的上下文注入仍会使用旧事实，导致一致性断裂。

例如：用户把 "张三学会了剑法" 改成 "张三学会了刀法"，但事实账本仍记录 "张三学会了剑法"。

### 7.2 触发规则

| 编辑的 Agent | 需重新提取的内容 |
|-------------|----------------|
| writer（章节正文） | 角色变化提取 + 一致性检测 + 事实提取（FactLedger 实现后） |
| character（角色卡） | 角色快照重建 + 下游章纲/章节标记 stale |
| world（世界观） | 世界观一致性校验 |
| story / outline | 无需事实重提取（仅标记下游 stale） |

### 7.3 实现方案

```python
def _request_fact_revalidation(self, agent: str, chapter_num: int):
    """编辑确认后请求事实重新提取（轻量级占位，FactLedger 实现后启用完整管道）"""
    # 当前阶段：仅记录日志，不做实际重提取
    logger.info("事实重提取请求: agent=%s, chapter=%s", agent, chapter_num)

    # TODO: FactLedger 实现后启用以下管道
    # if agent == "writer":
    #     await self.context_pipeline.revalidate_chapter(chapter_num)
    # elif agent == "character":
    #     await self.context_pipeline.rebuild_character_snapshot()
    # elif agent == "world":
    #     await self.context_pipeline.recheck_world_consistency()
```

### 7.4 与 borrow-analysis 的联动

`borrow-analysis.md` 中的 P0.2「事实账本」和 P1.1「Continuity Envelope」实现后，
`_request_fact_revalidation` 将从占位升级为完整的上下文重建管道。

---

## 8. 向后兼容

- `editable` 字段为可选：不传则前端走原有按钮逻辑
- `edited_content` 参数为可选：不传则后端按原有逻辑处理
- 选题模式（`mode: "topics"`）保持现有交互不变
- 现有 `/api/panel` 编辑接口保持不变，互不干扰

---

## 9. 文件变更清单

| 文件 | 变更类型 | 内容 |
|------|---------|------|
| `src/orchestrator/loop.py` | 修改 | `_user_response` 增加 `edited_content`；新增 `_apply_edits()`（使用 `raw_state` dataclass 访问）；`user_respond()` 签名扩展；`_mark_confirmed()` 末尾调用 `clear_stale()` |
| `src/orchestrator/models.py` | 修改 | `AgentResult` 新增 `editable` 字段；`Dashboard` 新增 `stale_markers` 字段 |
| `src/state/state_types.py` | 修改 | `WriteSyncState` 新增 `stale_markers: dict` 字段 |
| `src/web/app.py` | 修改 | `/api/v2/respond` 增加 `edited_content` Form 参数 |
| `src/web/orchestrator_api.py` | 修改 | `send_to_session()` 签名扩展 |
| `src/orchestrator/stale_tracker.py` | **新增** | `DEPENDENCY_MAP` + `mark_stale()` + `clear_stale()` + `get_stale_info()`（使用 `raw_state` 访问） |
| `src/orchestrator/adapters.py` | 修改 | 各 adapter 的 `AgentResult` 增加 `editable` 元数据字段 |
| `src/web/templates/workbench.html` | 修改 | confirm 事件处理器改造；新增 `renderEditPanel()` / `renderFormFields()` / `renderRichtextFields()` / `buildEditedContent()` / `resumeV2Edit()` / `renderDiffPanel()`；stale 警告渲染 |

---

## 10. 已知陷阱（来自 AGENTS.md）

- **确认循环陷阱（5.1）**：`_apply_edits` 后直接走 `_mark_confirmed`，不要在编辑后创建新的确认节点 — 编辑和确认是同一次 respond
- **变量名 Bug（5.2）**：`_mark_confirmed` 中确保 `story.confirmed_at` / `outline.confirmed_at` 等变量名正确
- **Logger 名称（5.3）**：stale_tracker.py 使用 `"writesync"` 作为 logger name

---

## 11. 验证计划

1. **单元测试**：`test_stale_tracker.py` — 测试依赖标记/清除逻辑
2. **编排器测试**：扩展 `test_orchestrator_phase1.py` — 测试 `_apply_edits` 各 Agent 分支
3. **API 测试**：测试 `/api/v2/respond` 接收 `edited_content` 参数
4. **烟雾测试**：策划阶段编辑角色卡 → 确认章纲出现 stale 警告
5. **前端测试**：新增 Playwright 测试 — 编辑表单渲染、编辑提交、diff 面板
