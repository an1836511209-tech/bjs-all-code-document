/* 02-dom: DOM 引用、顶栏状态、计时、侧栏与弹窗
   经典 script，无构建；对外只暴露 window.BP.dom。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const $ = (...args) => BP.util.$(...args);
  const $$ = (...args) => BP.util.$$(...args);
  const closePreview = (...args) => BP.document.closePreview(...args);
  const currentConversation = (...args) => BP.state.currentConversation(...args);
  const openFilesPanel = (...args) => BP.files.openFilesPanel(...args);
  const renderConvoFiles = (...args) => BP.files.renderConvoFiles(...args);
  const renderProjects = (...args) => BP.sidebar.renderProjects(...args);
  const renderWorkbookStatus = (...args) => BP.workbook.renderWorkbookStatus(...args);
  const renderingConversation = (...args) => BP.state.renderingConversation(...args);
  const resetAll = (...args) => BP.run.resetAll(...args);
  const runtimeOf = (...args) => BP.state.runtimeOf(...args);
  const saveState = (...args) => BP.state.saveState(...args);
  const state = BP.lazy('state', 'state');
  const syncComposerButton = (...args) => BP.composer.syncComposerButton(...args);
  const ui = BP.lazy('state', 'ui');
  const workbookFeatureEnabled = () => BP.workbook.workbookFeatureEnabled;
  const workbookFeatureError = () => BP.workbook.workbookFeatureError;
  const workbookFeatureRequest = () => BP.workbook.workbookFeatureRequest;

  const el = {
    shell: $('#shell'),
    runPill: $('#runPill'),
    runStatus: $('#runStatus'),
    timer: $('#timer'),
    ctxRing: $('#ctxRing'),
    ctxRingFill: $('#ctxRingFill'),
    ctxRingLabel: $('#ctxRingLabel'),
    skillBadge: $('#skillBadge'),
    skillName: $('#skillName'),
    themeIcon: $('#themeIcon'),
    thread: $('#thread'),
    messages: $('#messages'),
    taskPanel: $('#taskPanel'),
    taskHead: $('#taskHead'),
    taskBody: $('#taskBody'),
    taskProgress: $('#taskProgress'),
    input: $('#input'),
    sendBtn: $('#sendBtn'),
    chatTitle: $('#chatTitle'),
    chatSub: $('#chatSub'),
    projectList: $('#projectList'),
    convoFiles: $('#convoFiles'),
    convoFilesBody: $('#convoFilesBody'),
    convoFilesTitle: $('#convoFilesTitle'),
    refreshFiles: $('#refreshFiles'),
    preview: $('#preview'),
    previewTitle: $('#previewTitle'),
    previewSub: $('#previewSub'),
    paper: $('#paper'),
    previewToggle: $('#previewToggle'),
    footerHint: $('#footerHint'),
    attachRow: $('#attachRow'),
    fileInput: $('#fileInput'),
    attachBtn: $('#attachBtn'),
    urlBtn: $('#urlBtn'),
    urlBox: $('#urlBox'),
    urlsInput: $('#urlsInput'),
    skillSelect: $('#skillSelect'),
    modelSelect: $('#modelSelect'),
    thinkingSelect: $('#thinkingSelect'),
    convos: $('#convos'),
    convosToggle: $('#convosToggle'),
    scrim: $('#scrim')
  };

  // 下拉框必须始终落在某个真实存在的选项上。旧会话的 requestedSkill 可能是空串，
  // 或指向已经下线的值（例如早前移除的「自动路由」）—— 直接赋给 <select> 会渲染成
  // 空白，用户看到「没选 skill」。这里做一次收敛：命中就用，命不中回退到默认项。

  function setSidebarOpen(open) {
    if (!el.convos) return;
    el.convos.classList.toggle('open', open);
    if (el.scrim) el.scrim.hidden = !open;
    if (el.convosToggle) el.convosToggle.setAttribute('aria-expanded', String(open));
  }

  function closeSidebar() {
    setSidebarOpen(false);
  }

  function sidebarIsOpen() {
    return Boolean(el.convos && el.convos.classList.contains('open'));
  }

  function toggleSidebar() {
    setSidebarOpen(!sidebarIsOpen());
  }

  /* ============================================================
     Theme
     ============================================================ */

  function applyTheme(t) {
    document.documentElement.dataset.theme = t;
    localStorage.setItem('agent-theme', t);
    const sun = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>';
    const moon = '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z"/>';
    el.themeIcon.innerHTML = t === 'dark' ? sun : moon;
  }
  applyTheme(localStorage.getItem('agent-theme') || 'light');
  $('#themeBtn').addEventListener('click', () =>
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

  if (el.refreshFiles) {
    el.refreshFiles.addEventListener('click', () => {
      renderConvoFiles(currentConversation());
    });
  }
  if (el.convosToggle) {
    el.convosToggle.addEventListener('click', toggleSidebar);
  }
  if (el.scrim) {
    el.scrim.addEventListener('click', closeSidebar);
  }
  // Esc 关闭侧栏：窄屏下的常规预期，避免用户被遮罩困住。
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && sidebarIsOpen()) closeSidebar();
  });

  if (el.taskHead) {
    el.taskHead.addEventListener('click', () => {
      if (!el.taskPanel) return;
      const collapsed = el.taskPanel.classList.toggle('collapsed');
      el.taskHead.setAttribute('aria-expanded', String(!collapsed));
    });
  }

  if (el.previewToggle) {
    el.previewToggle.addEventListener('click', () => {
      // 已经是预览态就先关，再点再开，按钮像个开关。
      if (el.shell.classList.contains('has-preview')) {
        closePreview();
      } else {
        openFilesPanel();
      }
    });
  }

  /* ============================================================
     Status / timer
     ============================================================ */

  function setStatus(s) {
    state.status = s;
    const conversation = state.renderingConversation || currentConversation();
    if (conversation) runtimeOf(conversation).status = s;
    $$('[data-delete-convo]', el.projectList).forEach(button => {
      if (button.dataset.deleteConvo === conversation?.id) button.disabled = s === 'running';
    });
    if (state.silentRender) return; // background conversation: data only
    syncHeader();
    // 状态一变就同步发送键：以前漏了这一步，run 结束/失败后按钮还停在「中止」，
    // 用户点它既中止不了（后端已无任务）也发不出消息，表现就是"点了没反应"。
    if (BP.composer && BP.composer.syncComposerButton) syncComposerButton();
  }

  function syncHeader() {
    const conversation = currentConversation();
    const s = conversation ? runtimeOf(conversation).status : 'idle';
    el.runPill.className = 'run-pill ' + s;
    el.runStatus.textContent = {
      idle: '空闲', running: '执行中', waiting: '等待补充',
      completed: '已完成', failed: '失败'
    }[s] || s;
    // Always allow sending: a running conversation queues the message, and a
    // waiting one needs the composer for material uploads or clarifications.
    el.sendBtn.disabled = false;
    const workbook = $('#institutionWorkbook');
    if (workbook) {
      workbook.checked = Boolean(conversation?.institutionWorkbook);
      workbook.disabled = s === 'running' || s === 'waiting' || !workbookFeatureEnabled() || Boolean(workbookFeatureRequest());
      const label = workbook.closest('label');
      label.classList.toggle('is-disabled', workbook.disabled);
      label.title = s === 'running' ? '当前报告执行中，附件选项已锁定；请在发送前选择。'
        : workbookFeatureError() || (workbookFeatureEnabled() ? '报告完成后独立生成 Excel，不影响报告交付' : '当前服务未启用投资机构匹配附件');
    }
    renderWorkbookStatus(conversation);
    syncComposerButton();
  }

  function startTimer() {
    stopTimer();
    state.startedAt = Date.now();
    const conversation = state.renderingConversation || currentConversation();
    const startedAt = state.startedAt;
    if (conversation?.id === ui.activeConversation) el.timer.textContent = '00:00';
    state.timerId = setInterval(() => {
      if (conversation?.id !== ui.activeConversation) return;
      const sec = (Date.now() - startedAt) / 1000;
      el.timer.textContent = `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(Math.floor(sec % 60)).padStart(2, '0')}`;
    }, 150);
  }

  function stopTimer() { if (state.timerId) { clearInterval(state.timerId); state.timerId = null; } }

  /* ============================================================
     Conversation rendering
     ============================================================ */

  function scrollBottom() {
    if (state.silentRender || !state.autoScroll) return;
    requestAnimationFrame(() => { el.messages.scrollTop = el.messages.scrollHeight; });
  }

  function openInputDialog({ title, placeholder, value = '', okText = '确定' }) {
    return new Promise((resolve) => {
      const backdrop = $('#modalBackdrop');
      const input = $('#modalInput');
      $('#modalTitle').textContent = title;
      input.placeholder = placeholder || '';
      input.value = value || '';
      $('#modalOk').textContent = okText;
      backdrop.hidden = false;
      input.focus();
      input.select();

      const close = (result) => {
        backdrop.hidden = true;
        $('#modalOk').removeEventListener('click', onOk);
        $('#modalCancel').removeEventListener('click', onCancel);
        backdrop.removeEventListener('click', onBackdrop);
        input.removeEventListener('keydown', onKey);
        resolve(result);
      };
      const onOk = () => {
        const text = input.value.trim();
        close(text || null);
      };
      const onCancel = () => close(null);
      const onBackdrop = (e) => { if (e.target === backdrop) onCancel(); };
      const onKey = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); onOk(); }
        if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
      };

      $('#modalOk').addEventListener('click', onOk);
      $('#modalCancel').addEventListener('click', onCancel);
      backdrop.addEventListener('click', onBackdrop);
      input.addEventListener('keydown', onKey);
    });
  }

  $('#newProject').addEventListener('click', async () => {
    const name = await openInputDialog({
      title: '新建项目',
      placeholder: '例如：星屿储能融资项目',
      okText: '创建'
    });
    if (!name) return;
    const id = 'ws-' + Date.now();
    ui.workspaces.splice(1, 0, { id, name, demo: false, collapsed: false, conversations: [] });
    ui.activeConversation = '';
    saveState();
    renderProjects();
    resetAll();
    el.chatTitle.textContent = '新对话';
    el.chatSub.textContent = '点击项目旁的「+」新建对话';
  });

  /* ============================================================
     Composer
     ============================================================ */


  /* ============================================================
     上下文占用环
     ============================================================ */

  const CTX_RING_CIRCUMFERENCE = 2 * Math.PI * 15; // 与 CSS 里 stroke-dasharray 一致

  /**
   * 把后端记录的上下文占用画成环形。
   *
   * 轮次限制改成"200 次软中断"之后，用户最关心的变成"还能聊多久"：
   * 环涨到触发线（75%）就说明下一次调用可能触发压缩，颜色随之变黄/变红。
   */
  function renderContextUsage(usage) {
    if (!el.ctxRing || !el.ctxRingFill || !el.ctxRingLabel) return;
    const tokens = Number(usage.tokens) || 0;
    const window = Number(usage.window) || 0;
    if (!window) { el.ctxRing.hidden = true; return; }
    const ratio = Math.min(1, Math.max(0, tokens / window));
    el.ctxRing.hidden = false;
    el.ctxRingFill.style.strokeDasharray = String(CTX_RING_CIRCUMFERENCE);
    el.ctxRingFill.style.strokeDashoffset = String(CTX_RING_CIRCUMFERENCE * (1 - ratio));
    el.ctxRing.classList.toggle('is-warn', ratio >= 0.6 && ratio < Number(usage.trigger_tokens || 0) / window);
    el.ctxRing.classList.toggle('is-danger', ratio >= 0.85);
    el.ctxRingLabel.textContent = `${Math.round(ratio * 100)}%`;
    el.ctxRing.title = [
      `上下文占用 ${tokens.toLocaleString()} / ${window.toLocaleString()} token（${Math.round(ratio * 100)}%）`,
      usage.trigger_tokens ? `压缩触发线 ${Number(usage.trigger_tokens).toLocaleString()}` : '',
      usage.compressed ? '本轮已触发过压缩' : '',
    ].filter(Boolean).join('\n');
  }

  function clearContextUsage() {
    if (!el.ctxRing) return;
    el.ctxRing.hidden = true;
    el.ctxRing.classList.remove('is-warn', 'is-danger');
  }

  BP.dom = {
    renderContextUsage,
    clearContextUsage,
    el, setSidebarOpen, closeSidebar, sidebarIsOpen, toggleSidebar, applyTheme, setStatus, syncHeader, startTimer, stopTimer, scrollBottom, openInputDialog,
  };
})();
