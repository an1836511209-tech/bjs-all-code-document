/* 13-composer: 输入区、草稿、附件、发送
   经典 script，无构建；对外只暴露 window.BP.composer。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const $$ = (...args) => BP.util.$$(...args);
  const currentConversation = (...args) => BP.state.currentConversation(...args);
  const el = BP.lazy('dom', 'el');
  const esc = (...args) => BP.util.esc(...args);
  const getApiBase = (...args) => BP.run.getApiBase(...args);
  const openInputDialog = (...args) => BP.dom.openInputDialog(...args);
  const queueHint = (...args) => BP.run.queueHint(...args);
  const reconcileConversation = (...args) => BP.run.reconcileConversation(...args);
  const runtimeOf = (...args) => BP.state.runtimeOf(...args);
  const saveState = (...args) => BP.state.saveState(...args);
  const setStatus = (...args) => BP.dom.setStatus(...args);
  const startMock = (...args) => BP.run.startMock(...args);
  const state = BP.lazy('state', 'state');
  const stopTimer = (...args) => BP.dom.stopTimer(...args);
  const submitLive = (...args) => BP.run.submitLive(...args);
  const svg = (...args) => BP.util.svg(...args);

  //: Upload ceiling. Surfaced to the user instead of silently dropping files.
  const MAX_ATTACHMENTS = 5;
  let attachHint = '';
  const ui = BP.lazy('state', 'ui');
  const withRuntime = (...args) => BP.state.withRuntime(...args);

  /**
   * The only place that writes the selected skill.
   *
   * The select, the conversation record and the persisted state must never
   * disagree: the next submit reads `el.skillSelect.value`, so a value that
   * only lives in the DOM silently changes the routing of a later message —
   * and, because the DOM is shared, it also leaks one conversation's choice
   * into the next one.
   */
  function setSkill(conversation, value) {
    const select = el.skillSelect;
    if (!select) return '';
    const options = Array.from(select.options || []);
    const wanted = String(value || '').trim();
    const hit = options.find((option) => option.value === wanted);
    // Fall back to the default option, never to whatever the DOM happens to
    // hold right now: the DOM may still show the previous conversation's pick.
    const fallback = options.find((option) => option.defaultSelected) || options[0];
    const resolved = (hit || fallback || {}).value || '';
    select.value = resolved;
    if (conversation && conversation.requestedSkill !== resolved) {
      conversation.requestedSkill = resolved;
      saveState();
    }
    return resolved;
  }

  /**
   * Render the select so it matches a stored value. Never invents one.
   */
  function syncSkillSelect(value) {
    const conversation = currentConversation();
    const stored = value !== undefined && value !== null && value !== ''
      ? value
      : (conversation ? conversation.requestedSkill : '');
    return setSkill(conversation, stored);
  }

  /* ============================================================
     Sidebar（≤1023px 时侧栏移出屏幕，靠这里拉回来）
     ============================================================ */

  // 宽屏侧栏常显，这里只切 .open 与遮罩；窄屏才有视觉效果。

  /* ---------- 调试用：模型与思考模式 ----------
     候选来自 GET /api/models。拉不到（老后端 / 离线 file://）就整组隐藏，
     绝不能因为这两个控件缺数据挡住主流程。 */

  const MODEL_CACHE_KEY = 'bjs-agent-model-choice';

  function readModelChoice() {
    try {
      const raw = localStorage.getItem(MODEL_CACHE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch { return {}; }
  }

  function saveModelChoice(patch) {
    try {
      localStorage.setItem(MODEL_CACHE_KEY, JSON.stringify({ ...readModelChoice(), ...patch }));
    } catch { /* quota */ }
  }

  function fillSelect(select, items, selected) {
    if (!select) return '';
    const options = Array.isArray(items) ? items : [];
    select.innerHTML = options
      .map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`)
      .join('');
    const wanted = String(selected || '');
    const hit = options.find((item) => item.value === wanted);
    const fallback = options.find((item) => item.selected) || options[0];
    select.value = (hit || fallback || {}).value || '';
    return select.value;
  }

  /**
   * Write the debug knobs. Same contract as setSkill: the DOM, the
   * conversation and the persisted state move together, and a fallback never
   * inherits whatever the shared DOM held from another conversation.
   */
  function setModelChoice(conversation, field, value) {
    const select = field === 'modelName' ? el.modelSelect : el.thinkingSelect;
    if (!select || select.hidden) return '';
    const options = Array.from(select.options || []);
    if (!options.length) return '';
    const wanted = String(value || '').trim();
    const hit = options.find((option) => option.value === wanted);
    const fallback = options.find((option) => option.defaultSelected) || options[0];
    const resolved = (hit || fallback || {}).value || '';
    select.value = resolved;
    if (conversation && conversation[field] !== resolved) {
      conversation[field] = resolved;
      saveState();
    }
    saveModelChoice({ [field]: resolved });
    return resolved;
  }

  /** Restore both selects for a conversation. Safe to call when hidden. */
  function syncModelSelects(conversation) {
    const target = conversation || currentConversation();
    const stored = target
      ? { modelName: target.modelName, thinking: target.thinking }
      : readModelChoice();
    if (el.modelSelect && !el.modelSelect.hidden) {
      setModelChoice(target, 'modelName', stored.modelName || '');
    }
    if (el.thinkingSelect && !el.thinkingSelect.hidden) {
      setModelChoice(target, 'thinking', stored.thinking || '');
    }
  }

  async function loadModelOptions() {
    if (!el.modelSelect || !el.thinkingSelect) return;
    let payload = null;
    try {
      const res = await fetch(`${getApiBase()}/api/models`, {
        signal: AbortSignal.timeout(8000),
      });
      if (res.ok) payload = await res.json();
    } catch { /* 老后端或离线：保持隐藏 */ }
    const models = payload && Array.isArray(payload.models) ? payload.models : [];
    if (!models.length) {
      el.modelSelect.hidden = true;
      el.thinkingSelect.hidden = true;
      return;
    }
    const cached = readModelChoice();
    fillSelect(
      el.modelSelect,
      models.map((item) => ({ value: item.id, label: item.label || item.id, selected: item.is_default })),
      cached.modelName,
    );
    const modes = payload.thinking_modes || ['auto', 'on', 'off'];
    const labels = { auto: '思考：自动', on: '思考：开', off: '思考：关' };
    fillSelect(
      el.thinkingSelect,
      modes.map((mode) => ({
        value: mode,
        label: labels[mode] || `思考：${mode}`,
        selected: mode === (payload.default_thinking || 'auto'),
      })),
      cached.thinking,
    );
    el.modelSelect.hidden = false;
    el.thinkingSelect.hidden = false;
    syncModelSelects(currentConversation());
  }

  const draftFiles = new Map();

  function saveDraft() {
    const conversation = currentConversation();
    if (!conversation) return;
    conversation.draft = { text: el.input.value, urls: el.urlsInput.value };
    draftFiles.set(conversation.id, state.files.slice());
    saveState();
  }

  function loadDraft(conversation) {
    const draft = conversation.draft || {};
    el.input.value = draft.text || '';
    el.urlsInput.value = draft.urls || '';
    el.urlBox.hidden = !draft.urls;
    state.files = (draftFiles.get(conversation.id) || []).slice();
    renderAttachRow();
    autoGrow();
  }

  function clearDraft(conversation) {
    if (!conversation) return;
    conversation.draft = { text: '', urls: '' };
    draftFiles.delete(conversation.id);
    el.input.value = '';
    el.urlsInput.value = '';
    el.urlBox.hidden = true;
    state.files = [];
    renderAttachRow();
    autoGrow();
    saveState();
  }

  /* ---------- input dialog ---------- */

  function renderAttachRow() {
    el.attachRow.innerHTML = state.files.map((f, i) => `
      <span class="attach-pill">
        <span class="nm">${esc(f.name)}</span>
        <button class="rm" data-i="${i}" aria-label="移除附件">×</button>
      </span>`).join('')
      + (attachHint ? `<span class="attach-hint">${esc(attachHint)}</span>` : '');
    $$('.attach-pill .rm', el.attachRow).forEach((b) => b.addEventListener('click', () => {
      state.files.splice(Number(b.dataset.i), 1);
      renderAttachRow();
    }));
  }

  const ATTACH_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21.4 11.6l-8.5 8.5a5 5 0 0 1-7-7l8.5-8.5a3.2 3.2 0 0 1 4.5 4.5l-8.5 8.5a1.5 1.5 0 0 1-2.1-2l7.8-7.9"/></svg>';

  const STOP_ICON = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>';

  // Captured once at load so 发送 can be restored after a run stops.
  const SEND_HTML = el.sendBtn ? el.sendBtn.innerHTML : '发送';

  /**
   * The composer has exactly two shapes: idle (附件 + 发送) and busy (附件禁用 +
   * 中止). 中 approved sits where 发送 normally is, because that is the button the
   * user is already looking at when they want to stop.
   *
   * `waiting` counts as busy: the agent paused on a question, the task has not
   * finished, and the user must be able to walk away from it.
   */
  function syncComposerButton() {
    const conversation = currentConversation();
    const runtime = conversation ? runtimeOf(conversation) : null;
    const waiting = runtime?.status === 'waiting';
    const active = runtime?.status === 'running' || waiting;
    if (el.attachBtn) {
      el.attachBtn.classList.remove('is-stop');
      el.attachBtn.innerHTML = `${ATTACH_ICON} 附件`;
      el.attachBtn.title = active ? '执行中不能更换材料' : '上传材料文件';
      el.attachBtn.disabled = Boolean(active);
    }
    if (!el.sendBtn) return;
    if (active) {
      el.sendBtn.classList.add('is-stop');
      el.sendBtn.innerHTML = `${STOP_ICON} 中止`;
      el.sendBtn.title = waiting ? '中止本次任务（放弃当前提问）' : '中止当前任务';
      el.sendBtn.disabled = false;
    } else {
      el.sendBtn.classList.remove('is-stop');
      el.sendBtn.innerHTML = SEND_HTML;
      el.sendBtn.title = '发送';
      el.sendBtn.disabled = false;
    }
  }

  /** Append a one-line system note so the transcript says how the run ended. */
  function appendSystemNote(conversation, text) {
    if (!conversation || conversation.id !== ui.activeConversation) return;
    const thread = el.threadEl || el.thread || el.messages;
    if (!thread) return;
    const row = document.createElement('div');
    row.className = 'msg system';
    row.textContent = text;
    thread.appendChild(row);
    if (el.messages) el.messages.scrollTop = el.messages.scrollHeight;
  }

  async function cancelRun(conversation) {
    const runtime = runtimeOf(conversation);
    // runId 可能还没回填（页面刷新、SSE 尚未拿到 run.started）。按顺序回落。
    const runId = runtime.runId || conversation.lastRunId || state.runId || '';
    if (!runId) {
      // 没有 run 可取消：说明本地认为在执行、后端其实没有。明确告诉用户并复位。
      withRuntime(conversation, () => { stopTimer(); setStatus('idle'); });
      syncComposerButton();
      appendSystemNote(conversation, '没有找到正在执行的任务，已刷新状态。');
      void reconcileConversation(conversation);
      return;
    }
    // 立刻给反馈：按钮变成「中止中…」，避免用户以为没点上。
    if (el.sendBtn) {
      el.sendBtn.textContent = '中止中…';
      el.sendBtn.disabled = true;
    }
    if (conversation.id === ui.activeConversation) el.chatSub.textContent = '正在中止…';
    try {
      const response = await fetch(`${getApiBase()}/api/runs/${encodeURIComponent(runId)}/cancel`, {
        method: 'POST'
      });
      const result = await response.json().catch(() => ({}));
      // Clear locally even when the server reports the run had already finished:
      // a task paused on a question is "finished" server-side but the card is
      // exactly what the user asked to dismiss, and leaving it re-renders on
      // every reconcile.
      conversation.pendingQuestion = null;
      if (BP.approval && BP.approval.hideApproval) BP.approval.hideApproval();
      withRuntime(conversation, () => { stopTimer(); setStatus('idle'); });
      if (runtime.es) { runtime.es.close(); runtime.es = null; }
      runtime.runId = '';
      saveState();
      syncComposerButton();
      appendSystemNote(conversation, '已中止本次任务，本次执行未产出交付物。');
      if (conversation.id === ui.activeConversation) el.chatSub.textContent = '已中止';
      if (!response.ok || !result.cancelled) void reconcileConversation(conversation);
    } catch {
      if (conversation.id === ui.activeConversation) el.chatSub.textContent = '中止请求未送达，请重试';
    } finally {
      syncComposerButton();
    }
  }

  el.attachBtn.addEventListener('click', () => {
    const conversation = currentConversation();
    const runtime = conversation ? runtimeOf(conversation) : null;
    if (runtime?.status === 'running' || runtime?.status === 'waiting') return;
    el.fileInput.click();
  });
  el.fileInput.addEventListener('change', () => {
    const picked = [...(el.fileInput.files || [])];
    const room = Math.max(0, MAX_ATTACHMENTS - state.files.length);
    const dropped = picked.length - room;
    for (const f of picked.slice(0, room)) state.files.push(f);
    el.fileInput.value = '';
    // Silently dropping files is how "the 6th upload vanished" became a bug
    // report; say so instead.
    attachHint = dropped > 0
      ? `最多上传 ${MAX_ATTACHMENTS} 个文件，本次有 ${dropped} 个未添加`
      : '';
    renderAttachRow();
  });
  el.urlBtn.addEventListener('click', () => {
    el.urlBox.hidden = !el.urlBox.hidden;
    if (!el.urlBox.hidden) el.urlsInput.focus();
  });
  el.skillSelect.addEventListener('change', () => {
    setSkill(currentConversation(), el.skillSelect.value);
  });
  if (el.modelSelect) {
    el.modelSelect.addEventListener('change', () => {
      setModelChoice(currentConversation(), 'modelName', el.modelSelect.value);
    });
  }
  if (el.thinkingSelect) {
    el.thinkingSelect.addEventListener('change', () => {
      setModelChoice(currentConversation(), 'thinking', el.thinkingSelect.value);
    });
  }

  function autoGrow() {
    el.input.style.height = 'auto';
    el.input.style.height = Math.min(el.input.scrollHeight, 140) + 'px';
  }
  el.input.addEventListener('input', autoGrow);
  el.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  el.sendBtn.addEventListener('click', () => {
    const conversation = currentConversation();
    const runtime = conversation ? runtimeOf(conversation) : null;
    // 以**按钮当前形态**为准：以前这里读 runtime.status，一旦状态没同步（run 已结束
    // 但按钮还停在「中止」），点击会掉进 send()，空输入直接 return —— 用户看到的就是
    // "点了没反应"。
    if (el.sendBtn.classList.contains('is-stop')
        || (runtime && (runtime.status === 'running' || runtime.status === 'waiting'))) {
      void cancelRun(conversation);
      return;
    }
    send();
  });

  function send() {
    const text = el.input.value.trim();
    const urls = (el.urlsInput?.value || '').trim();
    if (!text && !state.files.length && !urls) return;

    const conversation = currentConversation();
    if (!conversation) {
      void openInputDialog({
        title: '还没有对话',
        placeholder: '',
        value: '',
        okText: '我知道了'
      });
      return;
    }
    const runtime = runtimeOf(conversation);

    const payload = {
      text,
      files: state.files.slice(),
      urls,
      skill: el.skillSelect.value,
      // Empty when the debug selects are hidden: the backend then keeps the
      // model it already stored for this conversation.
      modelName: el.modelSelect && !el.modelSelect.hidden ? el.modelSelect.value : '',
      thinking: el.thinkingSelect && !el.thinkingSelect.hidden ? el.thinkingSelect.value : '',
      institutionWorkbook: Boolean(conversation.institutionWorkbook)
    };

    if (conversation.mode === 'mock') {
      startMock(text || undefined);
      clearDraft(conversation);
      return;
    }

    // 执行中不接受新消息。
    //
    // 之前会把消息塞进队列、等本次结束自动发出：用户只是想"问一句"，结果那条
    // 消息在他没注意时被当成新任务提交，还把当前上下文带偏了。现在直接拒绝，
    // 并提示先中止——中止按钮就在发送键的位置上。
    if (runtime.status === 'running') {
      if (conversation.id === ui.activeConversation) {
        el.chatSub.textContent = '任务执行中，需先中止才能发送新消息';
      }
      return;
    }

    void submitLive(payload, conversation).then(ok => {
      if (!ok) return;
      if (currentConversation()?.id === conversation.id) {
        if (el.input.value.trim() === payload.text && el.urlsInput.value.trim() === payload.urls) clearDraft(conversation);
      } else if ((conversation.draft?.text || '').trim() === payload.text) {
        conversation.draft = {text:'', urls:''};
        draftFiles.delete(conversation.id);
        saveState();
      }
    });
  }

  $$('.chip').forEach((c) => c.addEventListener('click', () => {
    el.input.value = c.dataset.prompt;
    autoGrow();
    el.input.focus();
    // A quick phrase decides what will be produced, so it decides the route
    // too. Leaving the select alone here is how "生成一页纸 BP" ended up
    // running the investment-report skill.
    if (c.dataset.skill) setSkill(currentConversation(), c.dataset.skill);
  }));

  el.messages.addEventListener('scroll', () => {
    const nearBottom = el.messages.scrollHeight - el.messages.scrollTop - el.messages.clientHeight < 48;
    state.autoScroll = nearBottom;
  });

  /* ============================================================
     Boot
     ============================================================ */

  // 后端是对话的最终数据源：侧栏原先只依赖 localStorage，清缓存就全丢。
  // 启动时把「后端有、本地没有」的沙箱补进来，归到「历史记录」工作区。

  BP.composer = {
    syncSkillSelect, setSkill, draftFiles, saveDraft, loadDraft, clearDraft, renderAttachRow, ATTACH_ICON, STOP_ICON, syncComposerButton, cancelRun, autoGrow, send,
    loadModelOptions, syncModelSelects, setModelChoice,
  };
})();
