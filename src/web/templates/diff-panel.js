// ============================================================
// diff-panel.js — Two-step richtext edit flow
// ============================================================
// Extracted from workbench.html (2026-07-13).
//
// Public API:
//   previewEdit(agent, chNum)   - step 1: stash edits, render diff panel
//   confirmEdit(agent, chNum)   - step 2: submit the stashed edits
//   backToEdit()                - tear down diff panel, keep form
//   renderDiffPanel(agent, chNum, edits)  - low-level renderer
//
// Reads from globals provided by edit-panel.js:
//   EDITABLE_MODE_SAVE (stashed edits between preview & confirm)
//   resumeV2Edit(editedContent) — submit the stashed payload
//   getAgentLabel(agent)        — for the diff header
//   esc()                       — HTML-escape helper (workbench.html)
//
// Design spec: docs/superpowers/specs/2026-07-12-confirm-edit-design.md §5.5
// ============================================================

// Step 1 — capture current form values, then render side-by-side diff.
async function previewEdit(agent, chapterNum) {
    const flatEdits = collectEdits();
    EDITABLE_MODE_SAVE._edits = buildEditedContent(agent, flatEdits);
    EDITABLE_MODE_SAVE._agent = agent;
    EDITABLE_MODE_SAVE._chNum = chapterNum;
    renderDiffPanel(agent, chapterNum, EDITABLE_MODE_SAVE._edits);
}

// Step 2 — submit what was stashed in EDITABLE_MODE_SAVE._edits.
async function confirmEdit(agent, chapterNum) {
    const edits = EDITABLE_MODE_SAVE._edits;
    if (!edits) return;
    await resumeV2Edit(edits);
}

// User backed out of the diff — keep the form intact for further editing.
function backToEdit() {
    const panels = document.querySelectorAll('.diff-panel');
    panels.forEach(function (p) { p.remove(); });
    EDITABLE_MODE_SAVE._edits = null;
    EDITABLE_MODE_SAVE._agent = null;
    EDITABLE_MODE_SAVE._chNum = null;
}

// Side-by-side original vs edited.
function renderDiffPanel(agent, chapterNum, edits) {
    const container = document.getElementById('chatMessages');
    if (!container) return;

    // Pull the current value from the live form (single-richtext case)
    const origEl = document.querySelector('[data-field="content"]');
    const origContent = origEl ? origEl.value : '';
    const editedContent = (edits && typeof edits.content === 'string')
        ? edits.content
        : origContent;

    const headerLabel = chapterNum
        ? '第' + chapterNum + '章'
        : getAgentLabel(agent);

    const html = '<div class="diff-panel" style="margin:12px 0">'
        + '<div class="edit-panel-header">修改对比 — ' + headerLabel + '</div>'
        + '<div class="diff-columns" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px">'
        +   '<div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:6px;padding:10px;max-height:500px;overflow-y:auto">'
        +     '<div style="font-size:12px;color:var(--text-muted);margin-bottom:6px">原始版本</div>'
        +     '<div style="font-size:13px;white-space:pre-wrap">' + esc(origContent) + '</div>'
        +   '</div>'
        +   '<div style="background:var(--bg-elevated);border:1px solid var(--accent);border-radius:6px;padding:10px;max-height:500px;overflow-y:auto">'
        +     '<div style="font-size:12px;color:var(--accent);margin-bottom:6px">修改后</div>'
        +     '<div style="font-size:13px;white-space:pre-wrap">' + esc(editedContent) + '</div>'
        +   '</div>'
        + '</div>'
        + '<div class="edit-actions" style="margin-top:12px;display:flex;gap:8px">'
        +   '<button onclick="confirmEdit(\'' + agent + '\', ' + (chapterNum || 0) + ')" class="primary">确认修改</button>'
        +   '<button onclick="backToEdit()">继续编辑</button>'
        +   '<button onclick="cancelEdit()">放弃</button>'
        + '</div>'
        + '</div>';

    container.insertAdjacentHTML('beforeend', html);
    container.scrollTop = container.scrollHeight;
}
