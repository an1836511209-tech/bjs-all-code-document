/* 14-session: 会话恢复与标题
   经典 script，无构建；对外只暴露 window.BP.session。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const TITLE_LEADING = BP.lazy('config', 'TITLE_LEADING');
  const currentConversation = (...args) => BP.state.currentConversation(...args);
  const el = BP.lazy('dom', 'el');
  const findConversation = (...args) => BP.state.findConversation(...args);
  const getApiBase = (...args) => BP.run.getApiBase(...args);
  const renderProjects = (...args) => BP.sidebar.renderProjects(...args);
  const saveState = (...args) => BP.state.saveState(...args);
  const ui = BP.lazy('state', 'ui');

  function fallbackTitle(text) {
    let clean = String(text || '').replace(/\s+/g, ' ').trim();
    if (!clean) return '新对话';
    clean = clean.split(/[。！？!?\n]/)[0].trim();
    let changed = true;
    while (changed) {
      changed = false;
      for (const prefix of TITLE_LEADING) {
        if (clean.startsWith(prefix)) {
          clean = clean.slice(prefix.length).replace(/^[ ，,：:、]+/, '');
          changed = true;
        }
      }
    }
    clean = clean.replace(/^[ ，,：:、。.!?！？]+|[ ，,：:、。.!?！？]+$/g, '');
    if (!clean) return '新对话';
    return clean.length > 16 ? clean.slice(0, 16) + '…' : clean;
  }

  async function maybeAutoTitle(firstMessage, conversationArg) {
    const conversation = conversationArg || currentConversation();
    if (!conversation) return;
    if (conversation.titleAttempted || conversation.title !== '新对话' || !firstMessage) return;
    // Set the fallback before awaiting I/O so follow-up turns cannot start
    // duplicate model requests while the first title is still pending.
    conversation.titleAttempted = true;
    const fallback = fallbackTitle(firstMessage);
    conversation.title = fallback;
    saveState();
    renderProjects();
    if (ui.activeConversation === conversation.id) el.chatTitle.textContent = fallback;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 65000);
    let title = '';
    try {
      const res = await fetch(`${getApiBase()}/api/conversations/title`, {
        method: 'POST',
        signal: controller.signal,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ message: firstMessage })
      });
      if (res.ok) {
        const data = await res.json();
        title = String(data.title || '').trim();
      }
    } catch { /* fallback is already visible */ }
    finally { clearTimeout(timeout); }
    // A user rename or another recovered title must win over a late response.
    if (conversation.deleted || !title || conversation.title !== fallback) return;
    conversation.title = title.slice(0, 40);
    saveState();
    renderProjects();
    if (ui.activeConversation === conversation.id) el.chatTitle.textContent = conversation.title;
  }

  /* ============================================================
     Projects
     ============================================================ */

  async function hydrateFromBackend() {
    try {
      const api = getApiBase();
      const res = await fetch(`${api}/api/conversations?limit=100`);
      if (!res.ok) return;
      const data = await res.json();
      const items = Array.isArray(data.items) ? data.items : [];
      const deleted = new Set(data.deleted_task_ids || []);
      ui.workspaces.forEach(ws => {
        ws.conversations = ws.conversations.filter(c => !deleted.has(c.taskId));
      });
      if (!findConversation(ui.activeConversation)) ui.activeConversation = '';
      if (deleted.size) saveState();
      if (!items.length) return;

      const known = new Set();
      ui.workspaces.forEach((ws) => (ws.conversations || []).forEach((c) => {
        if (c.taskId) known.add(c.taskId);
      }));

      const unknown = items.filter((it) => it && it.task_id && !known.has(it.task_id));
      if (!unknown.length) return;

      let ws = ui.workspaces.find((w) => w.id === 'ws-history');
      if (!ws) {
        ws = { id: 'ws-history', name: '历史记录', demo: false, collapsed: false, conversations: [] };
        ui.workspaces.push(ws);
      }
      unknown.forEach((it) => {
        const turns = Array.isArray(it.turns) ? it.turns : [];
        ws.conversations.push({
          id: `c_hist_${it.task_id}`,
          title: it.title || it.task_id,
          mode: 'live',
          createdAt: Date.parse(it.updated_at) || Date.now(),
          messages: turns
            .filter((t) => t && (t.role === 'user' || t.role === 'assistant') && t.text)
            .map((t) => ({ role: t.role, text: t.text, runId: t.run_id })),
          events: [],
          taskId: it.task_id,
          fromBackend: true
        });
      });
      saveState();
    } catch { /* 离线或后端未启动时保持本地状态 */ }
  }

  BP.session = {
    fallbackTitle, maybeAutoTitle, hydrateFromBackend,
  };
})();
