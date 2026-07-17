// ============================================================
// stale-warning.js — Surface downstream-impact warnings on panels
// ============================================================
// Extracted from workbench.html (2026-07-13).
//
// Public API:
//   renderPanelWithStale(panelName, contentHtml) — wrap a panel's HTML
//     with a ⚠ indicator + title-attribute explaining which upstream
//     agent's edit caused the staleness.
//   applyStaleWarningToCurrentPanel() — post-render hook called from
//     refreshV2State() to inject a badge into the live DOM.
//
// Globals expected:
//   stateData.stale_markers : { panelName: [upstreamAgentName, ...], ... }
//   currentPanel (in workbench.html)
//
// Globals provided:
//   (none — pure side-effect functions)
//
// Design spec: docs/superpowers/specs/2026-07-12-confirm-edit-design.md §5.6
// ============================================================

const STALE_AGENT_LABELS = {
    story: '故事核心',
    character: '角色',
    world: '世界观',
    outline: '章纲',
    writer: '正文',
    proofreader: '校对',
    novel_review: '全书审查'
};

// Wrap a content string with a stale-warning container if the panel
// is marked stale. Otherwise return the content unchanged.
function renderPanelWithStale(panelName, content) {
    const staleInfo = (typeof stateData !== 'undefined' && stateData && stateData.stale_markers) || {};
    const reasons = staleInfo[panelName];
    if (!reasons || reasons.length === 0) {
        return content;
    }
    const reasonTexts = reasons.map(function (r) {
        return STALE_AGENT_LABELS[r] || r;
    }).join('、');
    const tooltip = '因 ' + reasonTexts + ' 变更，此内容可能已过时';
    return '<div title="' + esc(tooltip) + '" data-stale="true" data-stale-reasons="' + esc(reasons.join(',')) + '" '
        + 'style="position:relative">'
        + '<span style="position:absolute;top:2px;right:4px;font-size:14px;cursor:help" '
        + 'title="' + esc(tooltip) + '">⚠️</span>'
        + content
        + '</div>';
}

// Post-render: after renderAllPanels() lands the current panel's HTML
// in #centerPanel, decorate its panel-header with a stale badge.
function applyStaleWarningToCurrentPanel() {
    if (typeof stateData === 'undefined' || !stateData) return;
    const staleInfo = stateData.stale_markers || {};
    const reasons = staleInfo[currentPanel];
    const header = document.querySelector('#centerPanel .panel-header h2');
    if (!header) return;

    // Remove any previous badge so a re-render doesn't accumulate them.
    const old = header.querySelector('.stale-badge');
    if (old) old.remove();

    if (!reasons || reasons.length === 0) return;

    const reasonTexts = reasons.map(function (r) {
        return STALE_AGENT_LABELS[r] || r;
    }).join('、');
    const tooltip = '因 ' + reasonTexts + ' 变更，此内容可能已过时';

    const badge = document.createElement('span');
    badge.className = 'stale-badge';
    badge.title = tooltip;
    badge.textContent = '⚠️ 待审';
    badge.style.cssText = 'margin-left:8px;font-size:11px;font-weight:500;'
        + 'color:var(--accent);background:var(--accent-glow);'
        + 'border:1px solid rgba(212,168,83,.3);'
        + 'border-radius:4px;padding:1px 6px;cursor:help;'
        + 'vertical-align:middle';
    header.appendChild(badge);
}
