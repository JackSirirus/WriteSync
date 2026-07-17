// ============================================================
// prompt-library.js — Prompt template inspector & customizer
// ============================================================
// Phase 1.2: Makes AI system prompts transparent and customizable.
//
// Public API:
//   renderPromptLibrary()       — render the full prompt library panel
//
// Globals expected (defined in workbench.html):
//   esc(), BASE_URL (or window.location.origin)
//
// Design: docs/superpowers/specs/2026-07-12-dev-plan-v0.5.0.md §1.2
// ============================================================

let _promptData = null;       // cached API response
let _currentAgent = null;     // currently selected agent
let _currentGenre = 'default'; // active genre pack
let _editMode = false;        // whether user is editing the template

// ── Main entry point ────────────────────────────────────────

async function renderPromptLibrary() {
  const panel = document.getElementById('centerPanel');
  if (!panel) return;

  panel.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted)">加载提示词库...</div>';

  try {
    const resp = await fetch('/api/prompts');
    _promptData = await resp.json();
  } catch (e) {
    panel.innerHTML = '<div style="padding:20px;text-align:center;color:var(--danger)">提示词库加载失败: ' + esc(e.message) + '</div>';
    return;
  }

  _renderLibraryUI(panel);
}

// ── UI render ────────────────────────────────────────────────

function _renderLibraryUI(panel) {
  const agents = _promptData.agents || [];
  const packs = _promptData.genre_packs || [];

  let h = '<div class="panel-header"><h2>提示词库</h2>';
  h += '<div class="actions"><span class="btn-sm" style="color:var(--text-muted);font-size:11px">查看和自定义 AI 写作指令</span></div></div>';
  h += '<div class="panel-body" style="display:flex;height:calc(100% - 50px);overflow:hidden">';

  // ── Left sidebar: agent list ──
  h += '<div style="width:180px;border-right:1px solid var(--border);padding:8px;overflow-y:auto;flex-shrink:0">';
  h += '<div style="font-size:11px;color:var(--text-muted);margin-bottom:8px;font-weight:600">AGENT</div>';
  agents.forEach(function (a) {
    const active = _currentAgent === a.name ? ' style="background:var(--accent);color:var(--bg-deep)"' : '';
    h += '<div onclick="selectPromptAgent(\'' + esc(a.name) + '\')"' + active
      + ' style="padding:6px 10px;border-radius:4px;cursor:pointer;font-size:12px;margin-bottom:2px;transition:background .15s"'
      + ' onmouseover="if(!this.style.background)this.style.background=\'var(--bg-elevated)\'"'
      + ' onmouseout="if(!this.style.background)this.style.background=\'\'">'
      + esc(a.label) + '<br><span style="font-size:10px;color:var(--text-muted)">' + esc(a.name) + '</span></div>';
  });
  h += '</div>';

  // ── Right: detail area ──
  h += '<div id="promptDetail" style="flex:1;padding:12px 16px;overflow-y:auto">';
  if (_currentAgent) {
    h += _renderAgentDetail();
  } else {
    h += '<div style="text-align:center;padding:40px;color:var(--text-muted)">← 选择一个 Agent 查看其提示词模板</div>';
  }
  h += '</div>';

  h += '</div></div>'; // panel-body
  panel.innerHTML = h;
}

// ── Agent detail ─────────────────────────────────────────────

function _renderAgentDetail() {
  if (!_promptData) return '';

  const packs = _promptData.genre_packs || [];

  // Genre pack selector
  let h = '<div style="margin-bottom:12px;display:flex;align-items:center;gap:8px">';
  h += '<span style="font-size:12px;color:var(--text-muted)">题材包:</span>';
  h += '<select id="promptGenreSelect" onchange="switchPromptGenre(this.value)" style="padding:4px 8px;background:var(--bg-elevated);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;font-size:12px">';
  packs.forEach(function (p) {
    const sel = p === _currentGenre ? ' selected' : '';
    h += '<option value="' + esc(p) + '"' + sel + '>' + esc(p) + '</option>';
  });
  h += '</select>';

  // Action buttons
  if (_editMode) {
    h += '<button onclick="saveCustomPrompt()" style="margin-left:auto;padding:4px 12px;background:var(--accent);color:var(--bg-deep);border:none;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600">保存自定义</button>';
    h += '<button onclick="cancelPromptEdit()" style="padding:4px 12px;background:var(--bg-surface);color:var(--text-secondary);border:1px solid var(--border);border-radius:4px;cursor:pointer;font-size:12px">取消</button>';
  } else {
    h += '<button onclick="startPromptEdit()" style="margin-left:auto;padding:4px 12px;background:var(--bg-surface);color:var(--accent);border:1px solid var(--accent);border-radius:4px;cursor:pointer;font-size:12px">自定义</button>';
  }
  h += '</div>';

  // Rendered preview
  h += '<div id="promptRendered" style="background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;padding:12px;font-size:12px;line-height:1.6;white-space:pre-wrap;max-height:400px;overflow-y:auto;font-family:var(--font-sans)"></div>';

  // Load rendered content asynchronously
  _loadPromptContent();

  return h;
}

// ── Data loading ─────────────────────────────────────────────

async function _loadPromptContent() {
  const detail = document.getElementById('promptRendered');
  if (!detail || !_currentAgent) return;

  detail.innerHTML = '<span style="color:var(--text-muted)">加载中...</span>';

  try {
    const url = '/api/prompts/' + _currentAgent + '?genre=' + encodeURIComponent(_currentGenre);
    const resp = await fetch(url);
    const data = await resp.json();

    if (!data.ok) {
      detail.innerHTML = '<span style="color:var(--danger)">' + esc(data.error) + '</span>';
      return;
    }

    if (_editMode) {
      detail.innerHTML = '<textarea id="promptEditor" style="width:100%;min-height:350px;padding:10px;background:var(--bg-surface);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;font-family:monospace;font-size:12px;line-height:1.5;resize:vertical">'
        + esc(data.raw_template) + '</textarea>';
    } else {
      // Highlight placeholders in rendered view
      let html = esc(data.rendered);
      (data.placeholders || []).forEach(function (ph) {
        html = html.replace(
          new RegExp(esc('{{' + ph + '}}'), 'g'),
          '<span style="background:var(--accent);color:var(--bg-deep);padding:1px 4px;border-radius:3px;font-size:11px">{{' + esc(ph) + '}}</span>'
        );
      });
      detail.innerHTML = html;
    }
  } catch (e) {
    detail.innerHTML = '<span style="color:var(--danger)">加载失败: ' + esc(e.message) + '</span>';
  }
}

// ── User actions ─────────────────────────────────────────────

function selectPromptAgent(name) {
  _currentAgent = name;
  _editMode = false;
  const panel = document.getElementById('centerPanel');
  if (panel) _renderLibraryUI(panel);
}

function switchPromptGenre(genre) {
  _currentGenre = genre;
  _loadPromptContent();
}

function startPromptEdit() {
  _editMode = true;
  _loadPromptContent().then(function () {
    const panel = document.getElementById('centerPanel');
    if (panel) _renderLibraryUI(panel);
  });
}

function cancelPromptEdit() {
  _editMode = false;
  _loadPromptContent().then(function () {
    const panel = document.getElementById('centerPanel');
    if (panel) _renderLibraryUI(panel);
  });
}

async function saveCustomPrompt() {
  const editor = document.getElementById('promptEditor');
  if (!editor) return;

  const content = editor.value;
  try {
    const resp = await fetch('/api/prompts/customize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent: _currentAgent, content: content }),
    });
    const data = await resp.json();
    if (data.ok) {
      _editMode = false;
      _loadPromptContent().then(function () {
        const panel = document.getElementById('centerPanel');
        if (panel) _renderLibraryUI(panel);
      });
      if (typeof addChat === 'function') {
        addChat('system', '提示词已保存: ' + _currentAgent);
      }
    } else {
      alert('保存失败: ' + (data.error || 'unknown'));
    }
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}
