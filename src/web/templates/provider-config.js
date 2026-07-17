/**
 * WriteSync Provider Configuration Panel
 *
 * Renders the multi-source LLM provider management UI.
 */

(function () {
  'use strict';

  // Expose globally so workbench.html can call it
  window.renderProviderPanel = renderProviderPanel;
  window.addProvider = addProvider;
  window.editProvider = editProvider;
  window.deleteProvider = deleteProvider;
  window.testProvider = testProvider;
  window.setDefaultProvider = setDefaultProvider;
  window.closeProviderModal = closeProviderModal;
  window.saveProviderForm = saveProviderForm;

  let providerData = [];
  let editingName = null;

  // ------------------------------------------------------------------
  // Main panel renderer
  // ------------------------------------------------------------------
  function renderProviderPanel() {
    currentPanel = 'providers';
    document.querySelectorAll('.nav-item').forEach(function (el) {
      el.classList.toggle('active', el.dataset.panel === 'providers');
    });

    let h = '<div class="panel-header"><h2>模型配置</h2>';
    h += '<div class="actions"><button class="btn primary" onclick="addProvider()">＋ 添加供应商</button></div>';
    h += '</div><div class="panel-body" id="providerBody">';
    h += '<div id="providerList"></div>';
    h += '</div>';
    document.getElementById('centerPanel').innerHTML = h;
    loadProviders();
  }

  // ------------------------------------------------------------------
  // API helpers
  // ------------------------------------------------------------------
  async function loadProviders() {
    const el = document.getElementById('providerList');
    if (!el) return;
    el.innerHTML = '<p style="color:var(--text-muted)">加载中...</p>';
    try {
      const r = await fetch('/api/providers');
      const d = await r.json();
      providerData = d.providers || [];
      renderProviderList();
    } catch (e) {
      el.innerHTML = '<p style="color:var(--danger)">加载失败: ' + esc(e.message) + '</p>';
    }
  }

  function renderProviderList() {
    const el = document.getElementById('providerList');
    if (!el) return;
    if (providerData.length === 0) {
      el.innerHTML = '<p style="color:var(--text-muted);padding:20px 0">暂无配置供应商。点击上方按钮添加。</p>';
      return;
    }
    let h = '<div style="display:flex;flex-direction:column;gap:10px">';
    providerData.forEach(function (p) {
      const isDefault = p.is_default;
      h += '<div style="background:var(--bg-elevated);border:1px solid ' + (isDefault ? 'var(--accent-dim)' : 'var(--border)') + ';border-radius:var(--radius-md);padding:14px 16px;position:relative">';
      h += '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">';
      h += '<div><strong style="font-size:15px;color:var(--text-primary)">' + esc(p.name) + '</strong>';
      if (isDefault) h += ' <span style="font-size:10px;padding:2px 6px;border-radius:4px;background:var(--accent-glow);color:var(--accent);border:1px solid rgba(212,168,83,.2)">默认</span>';
      h += '<div style="font-size:12px;color:var(--text-muted);margin-top:2px">' + esc(p.provider_type) + ' · ' + esc(p.default_model || '-') + '</div>';
      h += '</div>';
      h += '<div style="display:flex;gap:6px">';
      if (!isDefault) {
        h += '<button class="btn btn-sm" onclick="setDefaultProvider(\'' + esc(p.name) + '\')" style="font-size:11px;padding:4px 10px">设为默认</button>';
      }
      h += '<button class="btn btn-sm" onclick="editProvider(\'' + esc(p.name) + '\')" style="font-size:11px;padding:4px 10px">编辑</button>';
      h += '<button class="btn btn-sm" onclick="testProvider(\'' + esc(p.name) + '\')" style="font-size:11px;padding:4px 10px">测试</button>';
      h += '<button class="btn btn-sm danger" onclick="deleteProvider(\'' + esc(p.name) + '\')" style="font-size:11px;padding:4px 10px">删除</button>';
      h += '</div></div>';
      h += '<div style="font-size:12px;color:var(--text-secondary);line-height:1.5">';
      h += '<div>Base URL: <span style="color:var(--text-muted)">' + esc(p.base_url) + '</span></div>';
      h += '<div>API Key: <span style="color:var(--text-muted)">' + esc(p.api_key || '未设置') + '</span></div>';
      h += '<div>Max Tokens: <span style="color:var(--text-muted)">' + esc(String(p.max_tokens)) + '</span> · Context Window: <span style="color:var(--text-muted)">' + esc(String(p.context_window)) + '</span></div>';
      h += '</div>';
      h += '<div id="test-result-' + esc(p.name) + '" style="margin-top:8px;font-size:12px;display:none"></div>';
      h += '</div>';
    });
    h += '</div>';
    el.innerHTML = h;
  }

  // ------------------------------------------------------------------
  // CRUD actions
  // ------------------------------------------------------------------
  function addProvider() {
    editingName = null;
    showProviderModal({});
  }

  function editProvider(name) {
    const p = providerData.find(function (x) { return x.name === name; });
    if (!p) return;
    editingName = name;
    showProviderModal(p);
  }

  async function deleteProvider(name) {
    if (!confirm('确定删除供应商「' + name + '」吗？')) return;
    try {
      const r = await fetch('/api/providers/' + encodeURIComponent(name), { method: 'DELETE' });
      const d = await r.json();
      if (d.ok) {
        addChat('system', '✅ 已删除供应商: ' + name);
        loadProviders();
      } else {
        addChat('system', '❌ 删除失败');
      }
    } catch (e) {
      addChat('system', '❌ 删除错误: ' + e.message);
    }
  }

  async function testProvider(name) {
    const resultEl = document.getElementById('test-result-' + name);
    if (resultEl) {
      resultEl.style.display = 'block';
      resultEl.style.color = 'var(--text-muted)';
      resultEl.textContent = '测试中...';
    }
    try {
      const r = await fetch('/api/providers/' + encodeURIComponent(name) + '/test', { method: 'POST' });
      const d = await r.json();
      if (resultEl) {
        if (d.ok) {
          resultEl.style.color = 'var(--success)';
          resultEl.textContent = '✅ 连接成功 | 可用模型: ' + (d.models || []).slice(0, 5).join(', ') + ((d.models || []).length > 5 ? '...' : '');
        } else {
          resultEl.style.color = 'var(--danger)';
          resultEl.textContent = '❌ 连接失败: ' + (d.error || '未知错误');
        }
      }
    } catch (e) {
      if (resultEl) {
        resultEl.style.color = 'var(--danger)';
        resultEl.textContent = '❌ 测试错误: ' + e.message;
      }
    }
  }

  async function setDefaultProvider(name) {
    try {
      const r = await fetch('/api/providers/' + encodeURIComponent(name), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_default: true })
      });
      const d = await r.json();
      if (d.ok) {
        addChat('system', '✅ 已设置默认供应商: ' + name);
        loadProviders();
      } else {
        addChat('system', '❌ 设置失败: ' + (d.error || ''));
      }
    } catch (e) {
      addChat('system', '❌ 错误: ' + e.message);
    }
  }

  // ------------------------------------------------------------------
  // Modal
  // ------------------------------------------------------------------
  function showProviderModal(data) {
    closeProviderModal();
    const overlay = document.createElement('div');
    overlay.className = 'setup-overlay';
    overlay.id = 'providerModal';
    overlay.style.display = 'flex';
    overlay.style.zIndex = '300';

    const isEdit = !!editingName;
    const title = isEdit ? '编辑供应商' : '添加供应商';

    let h = '<div class="setup-panel" style="width:480px">';
    h += '<button class="setup-close" onclick="closeProviderModal()">&times;</button>';
    h += '<h2 style="font-size:18px;margin-bottom:16px">' + title + '</h2>';
    h += '<form id="providerForm" onsubmit="event.preventDefault();saveProviderForm();">';

    h += '<label>名称</label>';
    h += '<input id="p-name" value="' + esc(data.name || '') + '" ' + (isEdit ? 'readonly style="background:var(--bg-deep);color:var(--text-muted)"' : '') + ' placeholder="例如 openai">';

    h += '<label>供应商类型</label>';
    h += '<select id="p-type">';
    const types = ['openai', 'anthropic', 'ollama', 'custom'];
    types.forEach(function (t) {
      h += '<option value="' + t + '"' + (data.provider_type === t ? ' selected' : '') + '>' + t + '</option>';
    });
    h += '</select>';

    h += '<label>Base URL</label>';
    h += '<input id="p-baseurl" value="' + esc(data.base_url || '') + '" placeholder="https://api.openai.com/v1">';

    h += '<label>API Key</label>';
    h += '<input id="p-apikey" type="password" value="' + esc(data.api_key || '') + '" placeholder="sk-...">';

    h += '<label>默认模型</label>';
    h += '<input id="p-model" value="' + esc(data.default_model || '') + '" placeholder="gpt-4o">';

    h += '<div style="display:flex;gap:12px;margin-top:12px">';
    h += '<div style="flex:1"><label>Max Tokens</label><input id="p-maxtokens" type="number" value="' + esc(String(data.max_tokens || 4096)) + '"></div>';
    h += '<div style="flex:1"><label>Context Window</label><input id="p-ctxwindow" type="number" value="' + esc(String(data.context_window || 128000)) + '"></div>';
    h += '</div>';

    h += '<div style="margin-top:12px;display:flex;align-items:center;gap:8px">';
    h += '<input type="checkbox" id="p-default" ' + (data.is_default ? 'checked' : '') + ' style="width:auto">';
    h += '<label for="p-default" style="margin:0">设为默认供应商</label>';
    h += '</div>';

    h += '<button type="submit" class="btn-start" style="margin-top:20px">' + (isEdit ? '保存修改' : '添加供应商') + '</button>';
    h += '</form></div>';

    overlay.innerHTML = h;
    document.body.appendChild(overlay);
  }

  function closeProviderModal() {
    const m = document.getElementById('providerModal');
    if (m) m.remove();
    editingName = null;
  }

  async function saveProviderForm() {
    const name = document.getElementById('p-name').value.trim();
    const provider_type = document.getElementById('p-type').value;
    const base_url = document.getElementById('p-baseurl').value.trim();
    const api_key = document.getElementById('p-apikey').value;
    const default_model = document.getElementById('p-model').value.trim();
    const max_tokens = parseInt(document.getElementById('p-maxtokens').value) || 4096;
    const context_window = parseInt(document.getElementById('p-ctxwindow').value) || 128000;
    const is_default = document.getElementById('p-default').checked;

    if (!name || !provider_type || !base_url) {
      alert('请填写名称、供应商类型和 Base URL');
      return;
    }

    const payload = {
      name: name,
      provider_type: provider_type,
      base_url: base_url,
      api_key: api_key,
      default_model: default_model,
      max_tokens: max_tokens,
      context_window: context_window,
      is_default: is_default,
    };

    try {
      const url = editingName ? '/api/providers/' + encodeURIComponent(editingName) : '/api/providers';
      const method = editingName ? 'PUT' : 'POST';
      const r = await fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (d.ok) {
        closeProviderModal();
        addChat('system', '✅ 供应商已保存: ' + name);
        loadProviders();
      } else {
        alert('保存失败: ' + (d.error || '未知错误'));
      }
    } catch (e) {
      alert('保存错误: ' + e.message);
    }
  }
})();
