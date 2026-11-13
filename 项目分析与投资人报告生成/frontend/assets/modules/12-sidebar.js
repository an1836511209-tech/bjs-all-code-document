/* 12-sidebar: 项目树与对话切换
   经典 script，无构建；对外只暴露 window.BP.sidebar。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const $$ = (...args) => BP.util.$$(...args);
  const closePreview = (...args) => BP.document.closePreview(...args);
  const closeSidebar = (...args) => BP.dom.closeSidebar(...args);
  const el = BP.lazy('dom', 'el');
  const esc = (...args) => BP.util.esc(...args);
  const findConversation = (...args) => BP.state.findConversation(...args);
  const getApiBase = (...args) => BP.run.getApiBase(...args);
  const loadDraft = (...args) => BP.composer.loadDraft(...args);
  const reconcileConversation = (...args) => BP.run.reconcileConversation(...args);
  const renderArtifactTabs = (...args) => BP.document.renderArtifactTabs(...args);
  const renderConvoFiles = (...args) => BP.files.renderConvoFiles(...args);
  const renderHistory = (...args) => BP.message.renderHistory(...args);
  const renderingConversation = (...args) => BP.state.renderingConversation(...args);
  const replayEvents = (...args) => BP.run.replayEvents(...args);
  const restorePlan = (...args) => BP.plan.restorePlan(...args);
  const runtimeOf = (...args) => BP.state.runtimeOf(...args);
  const saveDraft = (...args) => BP.composer.saveDraft(...args);
  const saveState = (...args) => BP.state.saveState(...args);
  const scrollBottom = (...args) => BP.dom.scrollBottom(...args);
  const sidebarIsOpen = (...args) => BP.dom.sidebarIsOpen(...args);
  const startMock = (...args) => BP.run.startMock(...args);
  const state = BP.lazy('state', 'state');
  const svg = (...args) => BP.util.svg(...args);
  const syncHeader = (...args) => BP.dom.syncHeader(...args);
  const syncSkillSelect = (...args) => BP.composer.syncSkillSelect(...args);
  const threadFor = (...args) => BP.state.threadFor(...args);
  const ui = BP.lazy('state', 'ui');

  function renderProjects() {
    el.projectList.innerHTML = ui.workspaces.map((ws) => `
      <div class="project ${ws.collapsed ? 'collapsed' : ''}" data-ws="${ws.id}">
        <div class="project-head" data-toggle="${ws.id}" role="button" tabindex="0">
          <svg class="project-chev" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
          <span class="project-name">${esc(ws.name)}</span>
          <span class="project-count">${ws.conversations.length}</span>
          <button class="project-add" data-add="${ws.id}" title="新建对话">+</button>
        </div>
        <div class="project-body">
          ${ws.conversations.length === 0
            ? '<div class="project-empty">暂无对话</div>'
            : ws.conversations.map((c) => `
              <div class="convo-row">
              <button class="convo ${c.id === ui.activeConversation ? 'on' : ''}" data-convo="${c.id}">
                <span class="convo-dot ${c.mode === 'mock' ? 'idle' : 'ok'}"></span>
                <span class="convo-main">
                  <span class="convo-title">${esc(c.title)}${c.mode === 'mock' ? '<span class="demo-tag">演示</span>' : ''}</span>
                  <span class="convo-meta">${c.mode === 'mock' ? '演示示例' : '真实任务'}</span>
                </span>
              </button>
              <button class="convo-delete" data-delete-convo="${c.id}" aria-label="删除会话：${esc(c.title)}" title="删除会话" ${c.runtime?.status === 'running' || c.runtime?.submitting || c.runtime?.deleting ? 'disabled' : ''}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6"/></svg>
              </button></div>`).join('')}
        </div>
      </div>
    `).join('');

    $$('.project-head', el.projectList).forEach((head) => {
      head.addEventListener('click', (e) => {
        const addBtn = e.target.closest('.project-add');
        if (addBtn) {
          e.stopPropagation();
          createConversation(addBtn.dataset.add);
          return;
        }
        const ws = ui.workspaces.find((w) => w.id === head.dataset.toggle);
        if (!ws) return;
        ws.collapsed = !ws.collapsed;
        saveState();
        renderProjects();
      });
    });

    $$('.convo', el.projectList).forEach((btn) => {
      btn.addEventListener('click', () => openConversation(btn.dataset.convo));
    });
    $$('[data-delete-convo]', el.projectList).forEach(button => {
      button.addEventListener('click', () => void deleteConversation(button.dataset.deleteConvo));
    });
  }

  async function deleteConversation(id) {
    const found = findConversation(id);
    if (!found) return;
    const {ws, conversation} = found;
    const runtime = runtimeOf(conversation);
    if (runtime.status === 'running' || runtime.submitting || runtime.deleting) return;
    if (!window.confirm(`删除会话“${conversation.title}”？删除后将从会话列表移除，已上传材料和生成文件保留。`)) return;
    runtime.deleting = true;
    renderProjects();
    try {
      if (conversation.taskId) {
        const response = await fetch(`${getApiBase()}/api/conversations/${encodeURIComponent(conversation.taskId)}`, {
          method:'DELETE', signal:AbortSignal.timeout(10000)
        });
        if (!response.ok) {
          const result = await response.json();
          throw new Error(result.detail || '删除未成功，请稍后重试。');
        }
      }
      conversation.deleted = true;
      runtime.es?.close();
      clearInterval(runtime.timerId);
      clearTimeout(runtime.auxiliaryTimer);
      runtime.queue = [];
      BP.composer.draftFiles.delete(id);
      runtime.threadEl?.remove();
      ws.conversations = ws.conversations.filter(c => c.id !== id);
      if (ui.activeConversation === id) {
        ui.activeConversation = '';
        const next = ws.conversations[0] || ui.workspaces.flatMap(w => w.conversations).find(c => c.mode !== 'mock');
        if (next) openConversation(next.id);
        else createConversation('ws-default');
      }
      saveState();
    } catch (error) {
      window.alert(error.message || '删除未成功，请稍后重试。');
    } finally {
      runtime.deleting = false;
      renderProjects();
    }
  }

  function createConversation(wsId) {
    let ws = ui.workspaces.find((w) => w.id === wsId);
    if (!ws) {
      ws = { id: wsId, name: '我的项目', demo: false, collapsed: false, conversations: [] };
      ui.workspaces.push(ws);
    }
    const id = 'conv-' + Date.now();
    ws.conversations.unshift({
      id, title: '新对话', mode: ws.demo ? 'mock' : 'live', createdAt: Date.now(), messages: []
    });
    ws.collapsed = false;
    saveState();
    // openConversation saves the *previous* conversation's draft before it
    // flips the active id, so the old composer state is not lost.
    openConversation(id);
  }

  function openConversation(id) {
    const found = findConversation(id);
    if (!found) return;
    // Mock playback is local-only; stop it when leaving so it cannot write
    // into the newly mounted thread. Real runs keep their SSE untouched.
    if (state.mode === 'mock') {
      state.timers.forEach((t) => { clearTimeout(t); clearInterval(t); });
      state.timers = [];
    }
    saveDraft();
    ui.activeConversation = id;
    saveState();
    renderProjects();
    // 窄屏下点完对话就把抽屉收起来，否则遮罩会挡住刚打开的内容。
    if (sidebarIsOpen()) closeSidebar();

    const { conversation } = found;
    const runtime = runtimeOf(conversation);
    el.chatTitle.textContent = conversation.title;
    el.chatSub.textContent = conversation.mode === 'mock'
      ? '演示示例 · 本地播放'
      : (runtime.status === 'running' ? '执行中 · 后台继续' : '真实任务');
    state.mode = conversation.mode;
    closePreview();
    renderArtifactTabs(conversation);

    // 计划面板是会话级的：优先用该会话记下的步骤快照恢复，没有才收起。
    // 只靠 write_todos 事件重建不够——第二轮起 agent 往往不再写 todo。
    restorePlan(runtime);

    // Swap in this conversation's own thread; background runs keep writing
    // into their detached thread, so switching back shows live progress.
    const thread = threadFor(conversation);
    el.messages.innerHTML = '';
    el.messages.appendChild(thread);
    el.thread = thread;
    el.threadEl = thread;

    loadDraft(conversation);
    syncSkillSelect(conversation.requestedSkill);
    if (BP.composer && BP.composer.syncModelSelects) BP.composer.syncModelSelects(conversation);
    el.skillBadge.style.display = runtime.skill ? 'inline-flex' : 'none';
    el.skillName.textContent = runtime.skill;
    syncHeader();
    renderConvoFiles(conversation);

    if (!thread.children.length) {
      if (conversation.mode === 'mock') {
        state.renderingConversation = conversation;
        startMock();
        state.renderingConversation = null;
      } else if (conversation.events && conversation.events.length) {
        // Rebuild the plan, tool rows and artifact card from the saved log.
        replayEvents(conversation);
      } else {
        renderHistory(conversation);
      }
    }
    state.autoScroll = true;
    scrollBottom();
    if (conversation.mode === 'live' && !runtime.es) void reconcileConversation(conversation);
  }

  /* ---------- per-conversation drafts ---------- */
  // File objects only live in memory; text/urls persist with the conversation.

  BP.sidebar = {
    renderProjects, createConversation, openConversation, deleteConversation,
  };
})();
