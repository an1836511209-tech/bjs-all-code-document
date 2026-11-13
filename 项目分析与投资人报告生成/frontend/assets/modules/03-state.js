/* 03-state: 会话状态、持久化、runtime 生命周期
   经典 script，无构建；对外只暴露 window.BP.state。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const STORAGE_KEY = () => BP.config.STORAGE_KEY;

  function freshState() {
    return {
      workspaces: [
        {
          id: 'ws-demo',
          name: '演示示例',
          demo: true,
          collapsed: false,
          conversations: [
            { id: 'demo-bp', title: '星屿储能 · 一页纸 BP', mode: 'mock', createdAt: 1, messages: [] },
            { id: 'demo-report', title: '云帆智造 · 投资建议书', mode: 'mock', createdAt: 2, messages: [] }
          ]
        },
        {
          id: 'ws-default',
          name: '我的项目',
          demo: false,
          collapsed: false,
          conversations: []
        }
      ],
      activeConversation: ''
    };
  }

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY());
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && Array.isArray(parsed.workspaces)) return parsed;
      }
    } catch { /* ignore corrupted storage */ }
    return freshState();
  }

  function saveState() {
    // Runtime fields hold DOM nodes / EventSource / Maps and must never be
    // serialized; only the durable conversation data is persisted.
    const clean = {
      workspaces: ui.workspaces.map((ws) => ({
        id: ws.id,
        name: ws.name,
        demo: ws.demo,
        collapsed: ws.collapsed,
        conversations: ws.conversations.map((c) => ({
          id: c.id,
          title: c.title,
          titleAttempted: Boolean(c.titleAttempted),
          mode: c.mode,
          createdAt: c.createdAt,
          messages: c.messages,
          // Compact event log so a reload can rebuild the plan / tool rows
          // instead of collapsing into plain text.
          events: c.events || [],
          taskId: c.taskId || '',
          lastRunId: c.lastRunId || '',
          requestedSkill: c.requestedSkill || '',
          activeSkill: c.activeSkill || '',
          // Debug knobs. Kept per conversation so a follow-up run keeps the
          // same model and reasoning mode as the run it continues.
          modelName: c.modelName || '',
          thinking: c.thinking || '',
          pendingQuestion: c.pendingQuestion || null,
          execution: c.execution || null,
          institutionWorkbook: Boolean(c.institutionWorkbook),
          auxiliaryJobs: c.auxiliaryJobs || [],
          questionDraft: c.questionDraft || null,
          lastSeq: c.lastSeq || 0,
          draft: c.draft || { text: '', urls: '' }
        }))
      })),
      activeConversation: ui.activeConversation
    };
    try { localStorage.setItem(STORAGE_KEY(), JSON.stringify(clean)); } catch { /* quota */ }
  }

  const ui = loadState();

  function findConversation(id) {
    for (const ws of ui.workspaces) {
      const conversation = ws.conversations.find((c) => c.id === id);
      if (conversation) return { ws, conversation };
    }
    return null;
  }

  /**
   * Per-conversation runtime: DOM nodes, the SSE connection, tool state and
   * the pending-message queue. Kept outside `ui` so persistence stays clean.
   */

  function runtimeOf(conversation) {
    if (!conversation.runtime) {
      conversation.runtime = {
        runId: conversation.lastRunId || '',
        status: 'idle',
        aiEl: null,
        planEl: null,
        plan: [],
        tools: new Map(),
        doc: null,
        artifactsById: new Map(),
        activeArtifactId: '',
        es: null,
        threadEl: null,
        queue: [],
        lastPayload: null,
        skill: conversation.activeSkill || '',
        approvalId: null,
        timerId: null,
        startedAt: 0
      };
    }
    return conversation.runtime;
  }

  function threadFor(conversation) {
    const runtime = runtimeOf(conversation);
    if (!runtime.threadEl) {
      runtime.threadEl = document.createElement('div');
      runtime.threadEl.className = 'thread';
    }
    return runtime.threadEl;
  }

  // Swap the global render state onto another conversation's runtime so the
  // existing render helpers can keep writing into a detached DOM tree.

  const renderStack = [];

  function enterRuntime(conversation) {
    const runtime = runtimeOf(conversation);
    renderStack.push({
      aiEl: state.aiEl, planEl: state.planEl, plan: state.plan,
      planOwner: state.planOwner,
      toolGroup: state.toolGroup,
      tools: state.tools, doc: state.doc, runId: state.runId,
      status: state.status, approvalId: state.approvalId, skill: state.skill,
      timerId: state.timerId, startedAt: state.startedAt,
      silent: state.silentRender, rendering: state.renderingConversation
    });
    state.planOwner = conversation;
    state.aiEl = runtime.aiEl;
    state.toolGroup = runtime.toolGroup || null;
    state.planEl = runtime.planEl;
    state.plan = runtime.plan;
    state.tools = runtime.tools;
    state.doc = runtime.doc;
    state.runId = runtime.runId;
    state.status = runtime.status;
    state.approvalId = runtime.approvalId;
    state.skill = runtime.skill;
    state.timerId = runtime.timerId;
    state.startedAt = runtime.startedAt;
    state.silentRender = conversation.id !== ui.activeConversation;
    state.renderingConversation = conversation;
  }

  function exitRuntime(conversation) {
    const runtime = runtimeOf(conversation);
    runtime.aiEl = state.aiEl;
    runtime.toolGroup = state.toolGroup;
    runtime.planEl = state.planEl;
    runtime.plan = state.plan;
    runtime.tools = state.tools;
    runtime.doc = state.doc;
    runtime.runId = state.runId;
    runtime.status = state.status;
    runtime.approvalId = state.approvalId;
    runtime.skill = state.skill;
    runtime.timerId = state.timerId;
    runtime.startedAt = state.startedAt;
    const savedState = renderStack.pop();
    Object.assign(state, {
      aiEl: savedState.aiEl,
      planEl: savedState.planEl,
      planOwner: savedState.planOwner,
      toolGroup: savedState.toolGroup,
      plan: savedState.plan,
      tools: savedState.tools,
      doc: savedState.doc,
      runId: savedState.runId,
      status: savedState.status,
      approvalId: savedState.approvalId,
      skill: savedState.skill,
      timerId: savedState.timerId, startedAt: savedState.startedAt,
      silentRender: savedState.silent,
      renderingConversation: savedState.rendering
    });
  }

  // Rendering scopes are synchronous. Network requests must run outside them.

  function withRuntime(conversation, render) {
    enterRuntime(conversation);
    try { return render(); } finally { exitRuntime(conversation); }
  }

  /* ============================================================
     Runtime state
     ============================================================ */

  const state = {
    mode: 'live',
    status: 'idle',
    speed: 2,
    eventIndex: 0,
    paused: false,
    timers: [],
    autoScroll: true,
    aiEl: null,
    planEl: null,
    plan: [],
    planSteps: [],
    planOwner: null,
    tools: new Map(),
    doc: null,
    startedAt: 0,
    timerId: null,
    es: null,
    timelineBase: 0,
    files: [],
    skill: '',
    runId: '',
    approvalId: null,
    lastPayload: null,
    silentRender: false,
    renderingConversation: null,
    replaying: false
  };

  function currentConversation() {
    const found = findConversation(ui.activeConversation);
    return found ? found.conversation : null;
  }

  function recordMessage(role, text, files) {
    if (state.replaying) return;
    const conversation = renderingConversation();
    if (!conversation) return;
    const entry = { role, text, runId: state.runId };
    if (files && files.length) entry.files = files;
    conversation.messages.push(entry);
    saveState();
  }

  function renderingConversation() {
    return state.renderingConversation || currentConversation();
  }

  BP.state = {
    freshState, loadState, saveState, ui, findConversation, runtimeOf, threadFor, renderStack, enterRuntime, exitRuntime, withRuntime, state, currentConversation, recordMessage, renderingConversation,
  };
})();
