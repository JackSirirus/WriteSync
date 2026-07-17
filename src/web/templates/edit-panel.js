// ============================================================
// edit-panel.js — Confirm-time inline editor for WriteSync
// ============================================================
// Extracted from workbench.html (2026-07-13).
//
// Public API:
//   renderEditPanel(confirmData)         - dispatches to form/richtext/topics
//   renderFormFields(fields, agent)      - structured-edit (character/outline/...)
//   renderRichtextFields(fields)         - long-text editor (writer/proofreader)
//   collectEdits()                       - read all [data-field] inputs
//   buildEditedContent(agent, flat)      - rebuild {characters:[...]} / {chapters:[...]} arrays
//   submitEdit(agent, chNum)             - one-step submit (form mode)
//   cancelEdit()                         - abort & request AI re-generation
//   resumeV2Edit(editedContent)          - POST edited_content to /api/v2/respond
//
// Globals expected (defined in workbench.html):
//   esc(), addChat(), setChatStatus(), updateChatInputState(),
//   stateData, v2ProjectId, hasInterrupt
//
// Globals exported (consumed by diff-panel.js):
//   EDITABLE_MODE_SAVE (window), getAgentLabel(), skipEdit()
//
// Design spec: docs/superpowers/specs/2026-07-12-confirm-edit-design.md §5
// ============================================================

// Shared state — must be defined before diff-panel.js loads
const EDITABLE_MODE_SAVE = {};

function getAgentLabel(agent) {
    const map = {
        story: '故事核心',
        character: '角色设定',
        world: '世界观',
        outline: '章纲',
        writer: '章节正文',
        proofreader: '校对稿',
        novel_review: '全书审查'
    };
    return map[agent] || agent;
}

// ----- main dispatcher ---------------------------------------
function renderEditPanel(confirmData) {
    const { agent, content, editable, chapter_num } = confirmData;
    const container = document.getElementById('chatMessages');

    // Clear old actions & banner
    const actionsDiv = document.getElementById('chatActions');
    if (actionsDiv) { actionsDiv.innerHTML = ''; }
    const banner = document.getElementById('interruptBanner');
    if (banner) { banner.style.display = 'none'; }

    let html = '<div class="edit-panel" data-agent="' + esc(agent) + '">';
    html += '<div class="edit-panel-header">' + getAgentLabel(agent) + ' · 编辑确认</div>';

    if (editable.mode === 'richtext') {
        html += renderRichtextFields(editable.fields);
        if (editable.preview_required) {
            html += '<div class="edit-actions" style="margin-top:12px;display:flex;gap:8px">'
                + '<button onclick="previewEdit(\'' + agent + '\', ' + (chapter_num || 0) + ')" class="primary">预览修改</button>'
                + '<button onclick="skipEdit(\'' + agent + '\')">不做修改，直接确认</button>'
                + '</div>';
        } else {
            html += '<div class="edit-actions" style="margin-top:12px;display:flex;gap:8px">'
                + '<button onclick="submitEdit(\'' + agent + '\', ' + (chapter_num || 0) + ')" class="primary">确认</button>'
                + '<button onclick="cancelEdit()">放弃，提意见重做</button>'
                + '</div>';
        }
    } else if (editable.mode === 'form') {
        html += renderFormFields(editable.fields, agent);
        html += '<div class="edit-actions" style="margin-top:12px;display:flex;gap:8px">'
            + '<button onclick="submitEdit(\'' + agent + '\', ' + (chapter_num || 0) + ')" class="primary">确认</button>'
            + '<button onclick="cancelEdit()">放弃，提意见重做</button>'
            + '</div>';
    } else if (editable.mode === 'topics') {
        if (content && content.topics && typeof renderTopicCards === 'function') {
            html += renderTopicCards(content.topics);
        }
    }

    html += '</div>';
    container.insertAdjacentHTML('beforeend', html);
    container.scrollTop = container.scrollHeight;
}

// ----- field renderers ---------------------------------------
function renderFormFields(fields, agent) {
    let html = '<div class="edit-form" style="display:flex;flex-direction:column;gap:10px">';

    if (agent === 'character' && fields.length > 0) {
        const characters = fields[0].current || [];
        characters.forEach(function (char, i) {
            html += '<div class="char-card" style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:8px;padding:12px">';
            html += '<label style="display:block;margin-bottom:6px"><span style="font-size:12px;color:var(--text-muted);display:block">姓名</span><input data-field="characters[' + i + '].name" value="' + esc(char.name || '') + '" style="width:100%"></label>';
            html += '<label style="display:block;margin-bottom:6px"><span style="font-size:12px;color:var(--text-muted);display:block">角色</span><input data-field="characters[' + i + '].role" value="' + esc(char.role || '') + '" style="width:100%"></label>';
            html += '<label style="display:block;margin-bottom:6px"><span style="font-size:12px;color:var(--text-muted);display:block">性格</span><textarea data-field="characters[' + i + '].personality" style="width:100%;min-height:50px">' + esc(char.personality || '') + '</textarea></label>';
            html += '<label style="display:block;margin-bottom:6px"><span style="font-size:12px;color:var(--text-muted);display:block">目标</span><textarea data-field="characters[' + i + '].goal" style="width:100%;min-height:50px">' + esc(char.goal || '') + '</textarea></label>';
            html += '</div>';
        });
    } else if (agent === 'outline') {
        const chapters = (fields.find(function (f) { return f.key === 'chapters'; }) || {}).current || [];
        chapters.forEach(function (ch, i) {
            html += '<div class="chapter-row" style="display:flex;gap:8px;align-items:center;padding:4px 0">';
            html += '<span style="min-width:50px;text-align:right;font-size:12px;color:var(--text-muted)">' + (ch.num || (i + 1)) + '章</span>';
            html += '<input data-field="chapters[' + i + '].title" value="' + esc(ch.title || '') + '" placeholder="标题" style="flex:1">';
            html += '<input data-field="chapters[' + i + '].core_event" value="' + esc(ch.core_event || '') + '" placeholder="核心事件" style="flex:2">';
            html += '</div>';
        });
    } else {
        // Generic fallback for any agent not in the special-cased list
        fields.forEach(function (f) {
            html += '<label style="display:block">';
            html += '<span style="font-size:12px;color:var(--text-muted);display:block">' + esc(f.label) + '</span>';
            if (f.type === 'textarea' || (f.current && f.current.length > 100)) {
                html += '<textarea data-field="' + esc(f.key) + '" style="width:100%;min-height:80px">' + esc(f.current || '') + '</textarea>';
            } else {
                html += '<input data-field="' + esc(f.key) + '" value="' + esc(f.current || '') + '" style="width:100%">';
            }
            html += '</label>';
        });
    }

    html += '</div>';
    return html;
}

function renderRichtextFields(fields) {
    let html = '<div class="edit-form richtext-mode" style="display:flex;flex-direction:column;gap:10px">';
    fields.forEach(function (f) {
        html += '<label style="display:block">';
        html += '<span style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px;font-weight:600">' + esc(f.label) + '</span>';
        html += '<textarea class="richtext-editor" data-field="' + esc(f.key) + '" '
            + 'style="min-height:400px;width:100%;font-family:monospace;font-size:13px;'
            + 'background:var(--bg-elevated);color:var(--text-primary);'
            + 'border:1px solid var(--border);border-radius:6px;padding:12px;resize:vertical">'
            + esc(f.current || '') + '</textarea>';
        html += '</label>';
    });
    html += '</div>';
    return html;
}

// ----- data round-trip ---------------------------------------
function collectEdits() {
    const edits = {};
    document.querySelectorAll('[data-field]').forEach(function (el) {
        edits[el.dataset.field] = el.value;
    });
    return edits;
}

// Build the structured payload from flat "characters[0].name" keys.
// character agent → { characters: [{name, role, personality, goal}, ...] }
// outline   agent → { chapters:  [{title, core_event}, ...] }
// everything else → return as-is (field-level edits)
function buildEditedContent(agent, flatEdits) {
    if (agent === 'character') {
        const chars = [];
        let i = 0;
        while (flatEdits['characters[' + i + '].name'] !== undefined) {
            chars.push({
                name: flatEdits['characters[' + i + '].name'] || '',
                role: flatEdits['characters[' + i + '].role'] || '',
                personality: flatEdits['characters[' + i + '].personality'] || '',
                goal: flatEdits['characters[' + i + '].goal'] || ''
            });
            i++;
        }
        return { characters: chars };
    }
    if (agent === 'outline') {
        const chapters = [];
        let i = 0;
        while (flatEdits['chapters[' + i + '].title'] !== undefined) {
            chapters.push({
                title: flatEdits['chapters[' + i + '].title'] || '',
                core_event: flatEdits['chapters[' + i + '].core_event'] || ''
            });
            i++;
        }
        return { chapters: chapters };
    }
    return flatEdits;
}

// ----- submit flows ------------------------------------------
async function submitEdit(agent, chapterNum) {
    const flatEdits = collectEdits();
    const structuredEdits = buildEditedContent(agent, flatEdits);
    await resumeV2Edit(structuredEdits);
}

async function resumeV2Edit(editedContent) {
    if (!v2ProjectId) return;
    const f = new FormData();
    f.append('approved', 'true');
    f.append('edited_content', JSON.stringify(editedContent));
    f.append('scope', 'all');
    await fetch('/api/v2/respond/' + v2ProjectId, { method: 'POST', body: f });
    hasInterrupt = false;
    updateChatInputState();
    setChatStatus('AI 思考中...');
}

// "No edits, just approve" — same shape as a confirm without edits
async function skipEdit(agent) {
    if (!v2ProjectId) return;
    const f = new FormData();
    f.append('approved', 'true');
    f.append('scope', 'all');
    await fetch('/api/v2/respond/' + v2ProjectId, { method: 'POST', body: f });
    hasInterrupt = false;
    updateChatInputState();
    setChatStatus('AI 思考中...');
}

// "Throw away the form, ask AI to redo with feedback"
async function cancelEdit() {
    let feedback = '';
    try {
        feedback = prompt('请输入修改意见（将触发 AI 重新生成）：') || '';
    } catch (e) {
        feedback = '';
    }
    if (!v2ProjectId) return;
    const f = new FormData();
    f.append('approved', 'false');
    if (feedback) f.append('feedback', feedback);
    f.append('scope', 'all');
    await fetch('/api/v2/respond/' + v2ProjectId, { method: 'POST', body: f });
    hasInterrupt = false;
    updateChatInputState();
    setChatStatus('AI 思考中...');
}
