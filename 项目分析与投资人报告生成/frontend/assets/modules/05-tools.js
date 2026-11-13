/* 05-tools: 工具调用折叠组
   经典 script，无构建；对外只暴露 window.BP.tools。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const ICON = BP.lazy('util', 'ICON');
  const esc = (...args) => BP.util.esc(...args);
  const scrollBottom = (...args) => BP.dom.scrollBottom(...args);
  const state = BP.lazy('state', 'state');
  const svg = (...args) => BP.util.svg(...args);

  function ensureToolGroup() {
    if (state.toolGroup && state.toolGroup.root.isConnected) return state.toolGroup;
    const root = document.createElement('div');
    root.className = 'tool-group collapsed';
    root.innerHTML = `
      <button type="button" class="tool-group-head">
        <span class="tg-ico">${svg(ICON.plan || ICON.spark)}</span>
        <span class="tg-label">工具调用</span>
        <span class="tg-count">0</span>
        <span class="tg-state"><span class="tg-dot"></span><span class="tg-text"></span></span>
        <span class="tg-chev">${svg(ICON.chev)}</span>
      </button>
      <div class="tool-group-body"></div>`;
    root.querySelector('.tool-group-head').addEventListener('click', () => {
      const collapsed = root.classList.toggle('collapsed');
      root.querySelector('.tool-group-head').setAttribute('aria-expanded', String(!collapsed));
    });
    state.aiEl.appendChild(root);
    state.toolGroup = {
      root,
      body: root.querySelector('.tool-group-body'),
      count: 0,
      running: 0,
      failed: 0,
    };
    return state.toolGroup;
  }

  function setToolGroupState(group) {
    if (!group) return;
    const head = group.root.querySelector('.tool-group-head');
    const text = group.root.querySelector('.tg-text');
    group.root.querySelector('.tg-count').textContent = String(group.count);
    if (group.failed) {
      group.root.classList.remove('running');
      group.root.classList.add('failed');
      text.textContent = `${group.failed} 个失败`;
    } else if (group.running > 0) {
      group.root.classList.add('running');
      group.root.classList.remove('failed');
      text.textContent = '执行中…';
    } else {
      group.root.classList.remove('running', 'failed');
      text.textContent = '已完成';
    }
    head.setAttribute('aria-expanded', String(!group.root.classList.contains('collapsed')));
  }

  function appendTool(ev) {
    const group = ensureToolGroup();
    const row = document.createElement('div');
    row.className = 'tool-line';
    row.dataset.call = ev.id;
    row.innerHTML = `
      <span class="ticon"><span class="spinner"></span></span>
      <span class="tname">${esc(ev.name)}</span>
      <span class="tsum">调用中…</span>
      <span class="ttime"></span>`;
    group.body.appendChild(row);
    group.count += 1;
    group.running += 1;
    setToolGroupState(group);
    state.tools.set(ev.id, { name: ev.name, status: 'running' });
    if (!group.root.classList.contains('collapsed')) scrollBottom();
  }

  function finishTool(ev) {
    const group = state.toolGroup;
    const row = (group?.body || state.aiEl)?.querySelector(`[data-call="${ev.id}"]`);
    if (!row) return;
    const ok = ev.status === 'ok' || ev.status === 'success';
    const warn = ev.status === 'partial' || ev.status === 'empty' || ev.status === 'waiting';
    row.className = 'tool-line ' + (ok ? 'ok' : warn ? 'warn' : 'err');
    row.querySelector('.ticon').innerHTML = svg(ok ? ICON.check : ICON.alert);
    row.querySelector('.tsum').textContent = ev.summary || '';
    row.querySelector('.ttime').textContent = ev.duration ? (ev.duration / 1000).toFixed(1) + 's' : '';
    state.tools.set(ev.id, { name: ev.name, status: ev.status });
    if (group) {
      group.running = Math.max(0, group.running - 1);
      if (!ok && !warn) {
        group.failed += 1;
        // 出错时自动展开，让用户直接看到哪一步红了
        group.root.classList.remove('collapsed');
      }
      setToolGroupState(group);
    }
    if (!group || !group.root.classList.contains('collapsed')) scrollBottom();
  }

  /* ---------- approval ---------- */

  BP.tools = {
    ensureToolGroup, setToolGroupState, appendTool, finishTool,
  };
})();
