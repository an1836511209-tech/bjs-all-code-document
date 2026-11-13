/* 10-run: 事件驱动：SSE 订阅、live 与 mock 播放器
   经典 script，无构建；对外只暴露 window.BP.run。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const ICON = BP.lazy('util', 'ICON');
  const addLiveDoc = (...args) => BP.document.addLiveDoc(...args);
  const addUserMessage = (...args) => BP.message.addUserMessage(...args);
  const advancePlanForTool = (...args) => BP.plan.advancePlanForTool(...args);
  const appendAIText = (...args) => BP.message.appendAIText(...args);
  const appendTool = (...args) => BP.tools.appendTool(...args);
  const bindFileChips = (...args) => BP.files.bindFileChips(...args);
  const closePreview = (...args) => BP.document.closePreview(...args);
  const createAIMessage = (...args) => BP.message.createAIMessage(...args);
  const createPlan = (...args) => BP.plan.createPlan(...args);
  const currentConversation = (...args) => BP.state.currentConversation(...args);
  const el = BP.lazy('dom', 'el');
  const renderContextUsage = (...args) => BP.dom.renderContextUsage(...args);
  const ensurePlan = (...args) => BP.plan.ensurePlan(...args);
  const esc = (...args) => BP.util.esc(...args);
  const filesBlock = (...args) => BP.message.filesBlock(...args);
  const finishTool = (...args) => BP.tools.finishTool(...args);
  const hidePlan = (...args) => BP.plan.hidePlan(...args);
  const maybeAutoTitle = (...args) => BP.session.maybeAutoTitle(...args);
  const normalizeQuestionPayload = (...args) => BP.approval.normalizeQuestionPayload(...args);
  const renderConvoFiles = (...args) => BP.files.renderConvoFiles(...args);
  const renderingConversation = (...args) => BP.state.renderingConversation(...args);
  const runtimeOf = (...args) => BP.state.runtimeOf(...args);
  const saveState = (...args) => BP.state.saveState(...args);
  const scrollBottom = (...args) => BP.dom.scrollBottom(...args);
  const setStatus = (...args) => BP.dom.setStatus(...args);
  const showApproval = (...args) => BP.approval.showApproval(...args);
  const showDocCard = (...args) => BP.document.showDocCard(...args);
  const showSkill = (...args) => BP.message.showSkill(...args);
  const startAuxiliaryPolling = (...args) => BP.workbook.startAuxiliaryPolling(...args);
  const startTimer = (...args) => BP.dom.startTimer(...args);
  const state = BP.lazy('state', 'state');
  const stopTimer = (...args) => BP.dom.stopTimer(...args);
  const svg = (...args) => BP.util.svg(...args);
  const syncHeader = (...args) => BP.dom.syncHeader(...args);
  const syncSkillSelect = (...args) => BP.composer.syncSkillSelect(...args);
  const syncModelSelects = (...args) => BP.composer.syncModelSelects(...args);
  const threadFor = (...args) => BP.state.threadFor(...args);
  const ui = BP.lazy('state', 'ui');
  const updatePlan = (...args) => BP.plan.updatePlan(...args);
  const withRuntime = (...args) => BP.state.withRuntime(...args);
  const workbookFeatureEnabled = () => BP.workbook.workbookFeatureEnabled;

  function resetAll() {
    state.timers.forEach((t) => clearInterval(t));
    state.timers = [];
    stopTimer();
    el.thread.innerHTML = '';
    el.skillBadge.style.display = 'none';
    el.previewToggle.style.display = 'none';
    state.aiEl = null;
    state.planEl = null;
    state.plan = [];
    state.tools = new Map();
    state.doc = null;
    state.eventIndex = 0;
    state.paused = false;
    state.autoScroll = true;
    state.runId = '';
    state.approvalId = null;
    state.skill = '';
    setStatus('idle');
    el.timer.textContent = '00:00';
    closePreview();
  }

  function startMock(userText) {
    const conversation = renderingConversation() || currentConversation();
    if (!conversation) return;
    // The mock thread belongs to this conversation; clear it before replay.
    threadFor(conversation).innerHTML = '';
    resetAll();
    state.mode = 'mock';
    state.renderingConversation = conversation;
    const script = window.MOCK_SCRIPT;
    addUserMessage(userText || script.userMessage);
    state.aiEl = createAIMessage();
    state.timelineBase = performance.now();
    state.eventIndex = 0;
    setStatus('running');
    startTimer();
    scheduleMock();
  }

  function scheduleMock() {
    if (state.paused) return;
    const events = window.MOCK_SCRIPT.events;
    if (state.eventIndex >= events.length) return;
    if (state.timelineBase === 0) return;
    const ev = events[state.eventIndex];
    const target = ev.at / state.speed;
    const elapsed = performance.now() - state.timelineBase;
    const delay = Math.max(0, target - elapsed);
    const timer = setTimeout(() => {
      handleMockEvent(ev);
      state.eventIndex++;
      if (ev.type === 'approval') return;
      scheduleMock();
    }, delay);
    state.timers.push(timer);
  }

  function resumeMock() {
    if (state.mode !== 'mock') return;
    const events = window.MOCK_SCRIPT.events;
    const prevAt = state.eventIndex > 0 ? events[state.eventIndex - 1].at : 0;
    state.timelineBase = performance.now() - prevAt / state.speed;
    scheduleMock();
  }

  function handleMockEvent(ev) {
    switch (ev.type) {
      case 'ai.say': appendAIText(ev.text); break;
      case 'skill': showSkill(ev.name); break;
      case 'plan.add': createPlan(); break;
      case 'plan.update': updatePlan(ev.index, ev.status, ev.duration); break;
      case 'tool.start': appendTool(ev); break;
      case 'tool.end': finishTool({ ...ev, status: ev.status }); break;
      case 'approval': showApproval(ev); break;
      case 'doc.ready': showDocCard(); break;
      case 'done': finishTurn(); break;
      default: break;
    }
  }

  function finishTurn() {
    stopTimer();
    setStatus('completed');
    if (!state.silentRender) el.chatSub.textContent = '已完成';
    // Drain the queue: a message typed while the run was active starts now.
    const conversation = state.renderingConversation || currentConversation();
    if (conversation) {
      const runtime = runtimeOf(conversation);
      if (runtime.queue.length && !state.replaying) {
        const next = runtime.queue.shift();
        setTimeout(() => { void submitLive(next, conversation); }, 200);
      }
    }
  }

  /* ============================================================
     Live mode
     ============================================================ */

  function getApiBase() {
    const q = new URLSearchParams(location.search).get('api');
    if (q) return q;
    const saved = localStorage.getItem('agent-api');
    if (saved) return saved;
    // Set when the page was opened under the nginx-only opaque prefix; after
    // history.replaceState the address bar no longer contains it.
    const prefix = sessionStorage.getItem('bjsConsolePrefix')
      || sessionStorage.getItem('bjsInvestmentPrefix');
    if (prefix) return prefix;
    if (location.protocol !== 'file:') return '';
    return 'http://127.0.0.1:8000';
  }

  async function submitLive(payload, conversationArg) {
    const conversation = conversationArg || currentConversation();
    if (!conversation || conversation.deleted || conversation.runtime?.deleting) return false;
    const runtime = runtimeOf(conversation);
    if (runtime.submitting || runtime.status === 'running') return false;
    runtime.submitting = true;
    const question = conversation.pendingQuestion;
    const api = getApiBase();
    const fd = new FormData();
    fd.append('message', payload.text || '');
    fd.append('institution_workbook', String(Boolean(payload.institutionWorkbook ?? conversation.institutionWorkbook)));
    (payload.files || []).forEach(f => fd.append('files_', f, f.name));
    if (payload.urls) fd.append('urls', payload.urls);
    if (payload.skill) fd.append('selected_skill', payload.skill);
    if (payload.modelName) fd.append('model_name', payload.modelName);
    if (payload.thinking) fd.append('thinking', payload.thinking);
    if (conversation.taskId) fd.append('task_id', conversation.taskId);
    if (payload.questionId || question?.question_id) fd.append('question_id', payload.questionId || question.question_id);
    if (payload.choiceValue) fd.append('choice_value', payload.choiceValue);
    withRuntime(conversation, () => {
      if (question?.checkpointed) {
        // Preserve the completed plan and document while a new run segment
        // resumes the same graph. Failed submission leaves the old card usable.
        state.approvalId = null;
        state.paused = false;
        // 但工具组必须换新：下面会 createAIMessage() 开一个气泡，
        // 旧组还指向上一轮的气泡，继续往里塞工具行就会「文字在下、工具在上」。
        state.toolGroup = null;
        state.tools = new Map();
      } else resetRunUi();
      runtime.lastPayload = payload;
      state.aiEl = createAIMessage();
      setStatus('running');
      startTimer();
    });
    try {
      const res = await fetch(`${api}/api/dev/runs`, {method: 'POST', body: fd});
      const data = await res.json();
      if (!res.ok) {
        const detail = typeof data.detail === 'object' ? data.detail.message : data.detail;
        const error = new Error(detail || `HTTP ${res.status}`);
        error.status = res.status;
        throw error;
      }
      conversation.taskId = data.task_id;
      conversation.lastRunId = data.run_id;
      conversation.lastSeq = 0;
      conversation.pendingQuestion = null;
      conversation.questionDraft = null;
      const fileRefs = (payload.files || []).map(f => ({name: f.name,
        url: `${api}/api/tasks/${encodeURIComponent(data.task_id)}/files/${encodeURIComponent(f.name)}`}));
      withRuntime(conversation, () => {
        state.runId = data.run_id;
        // Insert the accepted user turn before this run's assistant container.
        const aiEl = state.aiEl;
        addUserMessage(payload.displayText || payload.text || `（已附加 ${fileRefs.length} 个文件）`, fileRefs);
        const aiRow = aiEl?.closest('.msg');
        if (aiRow) threadFor(conversation).appendChild(aiRow);
      });
      saveState();
      subscribeEvents(conversation, data.run_id);
      void maybeAutoTitle(payload.displayText || payload.text, conversation);
      return true;
    } catch (err) {
      withRuntime(conversation, () => {
        stopTimer();
        // 409 表示上一轮还没结束，不是故障：给中性提示，不要渲染成红色失败。
        if (err.status === 409) {
          if (question) setStatus('waiting'); else setStatus('idle');
          appendAIText(`上一条消息还在执行：${err.message}。等它结束后再发这条即可，内容已保留。`);
        } else if (question) {
          setStatus('waiting');
          appendAIText(`补充提交失败：${err.message}。请在原问题卡重试。`);
        } else failRun(`提交失败：${err.message}`);
      });
      return false;
    } finally { runtime.submitting = false; }
  }

  function resetRunUi() {
    state.aiEl = null;
    // 不在这里 hidePlan：第二轮往往不会重新 write_todos，清掉之后没有
    // 任何事件会再把它挂回来。保留上一版步骤，等新的 write_todos 覆盖。
    state.toolGroup = null;
    state.tools = new Map();
    state.doc = null;
    state.runId = '';
    state.approvalId = null;
    state.skill = '';
    state.paused = false;
  }

  function trimEvent(ev) {
    // Structured options and complete URLs are required to restore interactions.
    return JSON.parse(JSON.stringify(ev));
  }

  function subscribeEvents(conversation, runId) {
    const runtime = runtimeOf(conversation);
    if (runtime.es) runtime.es.close();
    const api = getApiBase();
    const es = new EventSource(`${api}/api/runs/${encodeURIComponent(runId)}/events?after_seq=${conversation.lastSeq || 0}`);
    runtime.es = es;
    runtime.runId = runId;
    es.onmessage = e => {
      if (runtime.runId !== runId || runtime.es !== es) return;
      let ev;
      try { ev = JSON.parse(e.data); } catch { return; }
      if (ev.run_id !== runId || ev.task_id !== conversation.taskId || ev.seq <= (conversation.lastSeq || 0)) return;
      conversation.lastSeq = ev.seq;
      conversation.events = conversation.events || [];
      conversation.events.push(trimEvent(ev));
      saveState();
      withRuntime(conversation, () => handleLiveEvent(ev));
      if (['run.completed', 'run.failed', 'approval.required'].includes(ev.type)) {
        es.close();
        runtime.es = null;
      }
    };
    es.onerror = () => {
      if (runtime.es !== es) return;
      if (['completed', 'failed', 'waiting', 'idle'].includes(runtime.status)) {
        es.close(); runtime.es = null;
      } else {
        if (conversation.id === ui.activeConversation) el.chatSub.textContent = '连接中断，正在恢复…';
        void reconcileConversation(conversation);
      }
    };
  }

  function failRun(message) {
    stopTimer();
    setStatus('failed');
    if (!state.silentRender) el.chatSub.textContent = '执行失败';
    if (state.aiEl) {
      const box = document.createElement('div');
      box.className = 'fail-box';
      box.innerHTML = `
        <div class="fail-title">${svg(ICON.alert)}<span>${esc(message)}</span></div>
        <div class="fail-actions"><button class="retry-btn">重试</button></div>`;
      box.querySelector('.retry-btn').addEventListener('click', () => {
        box.remove();
        const conversation = state.renderingConversation || currentConversation();
        const runtime = conversation ? runtimeOf(conversation) : null;
        if (runtime?.lastPayload) void submitLive(runtime.lastPayload, conversation);
      });
      state.aiEl.appendChild(box);
      scrollBottom();
    }
  }

  function handleLiveEvent(ev) {
    let p = ev.payload || {};
    const conversation = renderingConversation();
    if (ev.type === 'approval.required') {
      // The snapshot may have repaired an old cached event with the same id.
      if (state.replaying && conversation.pendingQuestion?.question_id === (p.question_id || p.approval_id)) {
        p = conversation.pendingQuestion;
      }
      p = normalizeQuestionPayload(p);
    }
    switch (ev.type) {
      case 'run.started':
        break;
      case 'skill.activated':
        state.skill = p.skill || 'one-pager';
        conversation.activeSkill = state.skill;
        showSkill(state.skill);
        // 恢复执行时主干会把 todo 快照放进 skill.activated 的 payload，
        // 直接用它重建计划面板；普通新任务等 agent 真正 write_todos 时再挂
        // （见 tool.started），避免先画一个空计划。
        if (p.resuming && Array.isArray(p.plan) && p.plan.length) {
          hidePlan();
          createPlan(p.plan.map(item => item.content || item.text || '任务步骤'));
          if (state.planEl) state.planEl.dataset.source = 'todos';
          p.plan.forEach((item, idx) => {
            const mapped = { completed: 'done', in_progress: 'running' }[item.status] || item.status || 'pending';
            updatePlan(idx, mapped);
          });
        }
        appendAIText(p.resuming ? `已恢复「${state.skill}」执行，继续当前步骤。` : `已启用「${state.skill}」技能，开始执行。`);
        break;
      case 'plan.updated': {
        const items = Array.isArray(p.items) ? p.items : [];
        if (!items.length) break;
        state.planEl?.remove();
        createPlan(items.map(item => item.content || item.text || '任务步骤'));
        state.planEl.dataset.source = 'todos';
        items.forEach((item, idx) => updatePlan(idx, {completed:'done', in_progress:'running'}[item.status] || item.status || 'pending'));
        break;
      }
      case 'tool.started':
        if (p.tool === 'write_todos') ensurePlan(state.skill);
        advancePlanForTool(p.tool, 'start');
        appendTool({ id: p.call_id, name: p.tool });
        break;
      case 'tool.completed':
        advancePlanForTool(p.tool, 'end');
        finishTool({ id: p.call_id, status: p.status, duration: p.duration_ms, summary: p.summary });
        break;
      case 'tool.failed':
        finishTool({ id: p.call_id, status: 'failed', summary: p.error });
        break;
      case 'approval.required':
        if (state.replaying && conversation.pendingQuestion?.question_id !== (p.question_id || p.approval_id)) break;
        state.approvalId = p.approval_id;
        conversation.pendingQuestion = p;
        stopTimer();
        if (p.kind === 'upload_prompt') {
          // "请上传材料" is a normal reply, not a decision: show the text and
          // leave the composer usable so the user can attach files.
          appendAIText(p.question);
          setStatus('waiting');
        } else {
          showApproval(p);
        }
        if (!state.replaying) saveState();
        if (!state.replaying && runtimeOf(conversation).queue.length) {
          const next = runtimeOf(conversation).queue.shift();
          setTimeout(() => { void submitLive(next, conversation); }, 200);
        }
        break;
      case 'artifact.created':
        addLiveDoc(p);
        break;
      case 'run.completed':
        if (!state.replaying) conversation.pendingQuestion = null;
        state.plan.forEach((_, idx) => updatePlan(idx, 'done'));
        finishTurn();
        if (p.assistant_text) appendAIText(p.assistant_text);
        if (!state.replaying) {
          runtimeOf(conversation).auxiliaryUntil = Date.now() + 360000;
          startAuxiliaryPolling(conversation);
        }
        break;
      case 'run.failed':
        if (!state.replaying) conversation.pendingQuestion = null;
        // message carries the human-readable cause; error is usually just the
        // exception class name (e.g. ExceptionGroup).
        failRun(p.message || p.error || '未知错误');
        break;
      default:
        break;
    }
  }



  /* ============================================================
     Auto naming
     ============================================================ */
  // 模型标题不可用时用用户原话：先剥掉「帮我/请/根据材料/生成」这类前缀，
  // 留下业务对象，再按 16 字截断。

  /**
   * Does this conversation already hold the *trace* of ``runId``?
   *
   * An ``artifact.created`` event alone does not count: reconcile synthesises
   * one from the task snapshot, so a run we never watched looks "present"
   * while its tool calls and plan are missing.
   */
  function hasRunTrace(conversation, runId) {
    if (!runId) return false;
    return (conversation.events || []).some(ev =>
      ev.run_id === runId &&
      (ev.type === 'tool.started' || ev.type === 'tool.completed' || ev.type === 'plan.updated'));
  }

  /**
   * Pull a finished run's event record from the server and replay it.
   *
   * The console only subscribes while a run is live, so the events it keeps are
   * the ones *this browser* saw. A run started elsewhere — the eval driver, a
   * script, another browser, or a reload after `localStorage` was cleared —
   * therefore rendered as "just an artifact" even though the server still holds
   * every tool call. Replay that record so the transcript matches what ran.
   */
  function backfillEvents(conversation, runId) {
    const runtime = runtimeOf(conversation);
    runtime.backfilled = runtime.backfilled || new Set();
    if (!runId || runtime.es || runtime.backfilled.has(runId)) return;
    runtime.backfilled.add(runId);

    const api = getApiBase();
    // ``seq`` is per-run, so a cursor left over from an older run would hide
    // the whole replay.
    conversation.lastSeq = 0;
    const es = new EventSource(`${api}/api/runs/${encodeURIComponent(runId)}/events?after_seq=0`);
    runtime.es = es;
    const replayed = new Map();

    const finish = () => {
      if (runtime.es !== es) return;
      try { es.close(); } catch { /* already closed */ }
      runtime.es = null;
      const keep = (conversation.events || []).filter(ev =>
        ev.run_id === runId && ev.type === 'artifact.created');
      const merged = [...replayed.values()].sort((a, b) => (a.seq || 0) - (b.seq || 0));
      for (const artifactEvent of keep) {
        if (!merged.some(ev => ev.type === 'artifact.created' &&
            ev.payload?.artifact_id === artifactEvent.payload?.artifact_id)) {
          merged.push(artifactEvent);
        }
      }
      conversation.events = (conversation.events || []).filter(ev => ev.run_id !== runId).concat(merged);
      conversation.lastSeq = merged.reduce((max, ev) => Math.max(max, ev.seq || 0), 0);
      saveState();
      replayEvents(conversation);
    };

    es.onmessage = e => {
      if (runtime.es !== es) return;
      let ev;
      try { ev = JSON.parse(e.data); } catch { return; }
      if (ev.run_id !== runId) return;
      replayed.set(ev.seq ?? replayed.size, trimEvent(ev));
      if (['run.completed', 'run.failed', 'approval.required'].includes(ev.type)) finish();
    };
    // A run whose buffer is gone (server restarted) closes without a terminal
    // event; keep whatever arrived and stop asking.
    es.onerror = () => finish();
  }

  function replayEvents(conversation) {
    withRuntime(conversation, () => {
      state.replaying = true;
      try {
        const thread = threadFor(conversation);
        thread.innerHTML = '';
        resetRunUi();
        const rendered = new Set();
        for (const message of conversation.messages || []) {
          if (message.role === 'user') {
            const row = document.createElement('div');
            row.className = 'msg user';
            row.innerHTML = `<div class="bubble">${esc(message.text)}${filesBlock(message.files)}</div>`;
            thread.appendChild(row);
            bindFileChips(row);
            const events = (conversation.events || []).filter(ev => ev.run_id && ev.run_id === message.runId);
            if (events.length) {
              resetRunUi();
              state.runId = message.runId;
              state.aiEl = createAIMessage();
              for (const ev of events) handleLiveEvent(ev);
              rendered.add(message.runId);
            }
          } else if (!rendered.has(message.runId)) {
            state.aiEl = createAIMessage();
            appendAIText(message.text);
          }
        }
        state.runId = conversation.lastRunId || '';
        state.skill = conversation.activeSkill || '';
        // Recover running tools even if the accepted user message was not saved locally.
        const latest = (conversation.events || []).filter(ev => ev.run_id === state.runId);
        if (!rendered.has(state.runId) && latest.length) {
          state.aiEl = createAIMessage();
          for (const ev of latest) handleLiveEvent(ev);
        }
        const question = conversation.pendingQuestion;
        const restoredPlan = conversation.execution?.plan;
        if (Array.isArray(restoredPlan) && restoredPlan.length) {
          if (!state.aiEl) state.aiEl = createAIMessage();
          state.planEl?.remove();
          createPlan(restoredPlan.map(item => item.content || item.text || '任务步骤'));
          state.planEl.dataset.source = 'todos';
          restoredPlan.forEach((item, idx) => updatePlan(idx, {completed:'done', in_progress:'running'}[item.status] || item.status || 'pending'));
        }
        if (question && !thread.querySelector(`[data-question="${question.question_id}"]`)) {
          state.aiEl = createAIMessage();
          handleLiveEvent({type:'approval.required', payload:question});
        }
      } finally { state.replaying = false; }
    });
  }

  async function reconcileConversation(conversation) {
    const runtime = runtimeOf(conversation);
    if (conversation.deleted || !conversation.taskId || runtime.submitting || runtime.reconciling) return;
    runtime.reconciling = true;
    try {
      const expectedRun = conversation.lastRunId;
      const res = await fetch(`${getApiBase()}/api/tasks/${encodeURIComponent(conversation.taskId)}/state`);
      if (!res.ok) return;
      const snapshot = await res.json();
      if (conversation.deleted || runtime.submitting || conversation.lastRunId !== expectedRun) return;
      const previousQuestion = JSON.stringify(conversation.pendingQuestion || null);
      if (snapshot.execution) {
        if (conversation.execution?.event_stream_id !== snapshot.execution.event_stream_id) conversation.lastSeq = 0;
        conversation.execution = snapshot.execution;
      }
      conversation.activeSkill = snapshot.active_skill || conversation.activeSkill || '';
      // 上下文占用：轮次限制改成软中断后，这是用户判断"还能聊多久"的唯一依据。
      if (snapshot.context_usage && conversation.id === ui.activeConversation) {
        renderContextUsage(snapshot.context_usage);
      }
      if (typeof snapshot.institution_workbook === 'boolean') conversation.institutionWorkbook = snapshot.institution_workbook;
      conversation.pendingQuestion = snapshot.pending_question ? normalizeQuestionPayload(snapshot.pending_question) : null;
      const questionChanged = previousQuestion !== JSON.stringify(conversation.pendingQuestion);
      if (conversation.pendingQuestion) {
        conversation.events = (conversation.events || []).map(event =>
          event.type === 'approval.required' && (event.payload?.question_id || event.payload?.approval_id) === conversation.pendingQuestion.question_id
            ? {...event, payload:conversation.pendingQuestion} : event);
      }
      conversation.lastRunId = snapshot.run_id || conversation.lastRunId || '';
      const previous = conversation.messages || [];
      if (snapshot.turns?.length) conversation.messages = snapshot.turns.map(t => ({
        role:t.role, text:t.text, runId:t.run_id,
        files: previous.find(m => m.role === t.role && m.runId === t.run_id)?.files || []
      }));
      if (Array.isArray(snapshot.artifacts) && snapshot.status !== 'running') {
        const owned = new Map(snapshot.artifacts.map(artifact => [artifact.artifact_id, artifact]));
        // Replace legacy truncated/foreign artifact events with server-owned metadata.
        conversation.events = (conversation.events || []).filter(ev => ev.type !== 'artifact.created' || owned.has(ev.payload?.artifact_id)).map(ev => {
          if (ev.type !== 'artifact.created') return ev;
          const artifact = owned.get(ev.payload.artifact_id);
          return {...ev, task_id:conversation.taskId, payload:{...artifact, size_bytes:artifact.size}};
        });
      }
      for (const artifact of snapshot.artifacts || []) {
        if (!(conversation.events || []).some(ev => ev.payload?.artifact_id === artifact.artifact_id)) {
          conversation.events = conversation.events || [];
          conversation.events.push({type:'artifact.created', run_id:snapshot.run_id,
            payload:{...artifact, size_bytes:artifact.size}});
        }
      }
      const status = snapshot.status === 'needs_input' ? 'waiting' : snapshot.status === 'cancelled' ? 'failed' : snapshot.status || 'idle';
      if (status !== 'running' && runtime.es) { runtime.es.close(); runtime.es = null; }
      // Rebuild only on load or after a terminal transition, never while a user edits a question.
      if (!runtime.restored || runtime.status !== status || questionChanged) {
        replayEvents(conversation);
        runtime.restored = true;
      }
      runtime.status = status;
      runtime.runId = conversation.lastRunId;
      runtime.skill = conversation.activeSkill;
      if (status === 'running' && !runtime.es) {
        if (!runtime.aiEl) withRuntime(conversation, () => { state.aiEl = createAIMessage(); });
        subscribeEvents(conversation, runtime.runId);
      } else if (status !== 'running' && !runtime.es &&
                 !hasRunTrace(conversation, conversation.lastRunId)) {
        // Finished run we never watched: the tool rows live only on the server.
        backfillEvents(conversation, conversation.lastRunId);
      }
      if (conversation.id === ui.activeConversation) {
        syncSkillSelect(conversation.requestedSkill);
        syncModelSelects(conversation);
        if (runtime.skill) { el.skillBadge.style.display = 'inline-flex'; el.skillName.textContent = runtime.skill; }
        syncHeader();
        renderConvoFiles(conversation);
      }
      saveState();
      if (workbookFeatureEnabled()) startAuxiliaryPolling(conversation);
    } catch (err) {
      console.warn('conversation recovery failed', err);
    } finally { runtime.reconciling = false; }
  }

  function queueHint(conversation, payload) {
    const row = document.createElement('div');
    row.className = 'msg user queued';
    row.innerHTML = `
      <div class="bubble">${esc(payload.text || '（附件）')}
        <div class="queue-tag">已排队 · 当前任务完成后自动发送</div>
      </div>`;
    threadFor(conversation).appendChild(row);
    scrollBottom();
  }

  BP.run = {
    resetAll, startMock, scheduleMock, resumeMock, handleMockEvent, finishTurn, getApiBase, submitLive, resetRunUi, trimEvent, subscribeEvents, failRun, handleLiveEvent, replayEvents, reconcileConversation, queueHint,
  };
})();
