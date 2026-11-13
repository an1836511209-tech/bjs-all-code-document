/* 07-message: 消息流
   经典 script，无构建；对外只暴露 window.BP.message。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const ICON = BP.lazy('util', 'ICON');
  const artifactDownloadUrl = (...args) => BP.files.artifactDownloadUrl(...args);
  const bindFileChips = (...args) => BP.files.bindFileChips(...args);
  const el = BP.lazy('dom', 'el');
  const esc = (...args) => BP.util.esc(...args);
  const fileChip = (...args) => BP.files.fileChip(...args);
  const normalizePublishedText = (...args) => BP.document.normalizePublishedText(...args);
  const recordMessage = (...args) => BP.state.recordMessage(...args);
  const renderConvoFiles = (...args) => BP.files.renderConvoFiles(...args);
  const renderingConversation = (...args) => BP.state.renderingConversation(...args);
  const saveState = (...args) => BP.state.saveState(...args);
  const scrollBottom = (...args) => BP.dom.scrollBottom(...args);
  const state = BP.lazy('state', 'state');
  const svg = (...args) => BP.util.svg(...args);
  const threadFor = (...args) => BP.state.threadFor(...args);

  function renderAIText(element, text) {
    const normalized = normalizePublishedText(text);
    element.textContent = '';
    // Hide the raw artifact URL; only service routes become a download button.
    const parts = normalized.split(/((?:下载链接[：:]\s*)?https?:\/\/[^\s<>"']*\/api\/artifacts\/artifact_[a-f0-9]{32}\/content)/g);
    for (const part of parts) {
      const match = part.match(/(?:下载链接[：:]\s*)?(https?:\/\/[^\s<>"']*\/api\/artifacts\/(artifact_[a-f0-9]{32})\/content)/);
      if (match && match[1] === artifactDownloadUrl(match[2])) {
        const link = document.createElement('a');
        link.href = match[1];
        link.className = 'dl-btn';
        link.textContent = '下载文档';
        link.target = '_blank';
        link.rel = 'noopener';
        element.appendChild(link);
      } else element.appendChild(document.createTextNode(part));
    }
  }

  function filesBlock(files) {
    return files && files.length
      ? `<div class="msg-files">${files.map(fileChip).join('')}</div>`
      : '';
  }

  function addUserMessage(text, files = []) {
    const conversation = renderingConversation();
    if (!conversation) return;
    const row = document.createElement('div');
    row.className = 'msg user';
    row.innerHTML = `<div class="bubble">${esc(text)}${filesBlock(files)}</div>`;
    threadFor(conversation).appendChild(row);
    bindFileChips(row);
    const entry = { role: 'user', text, runId: state.runId };
    if (files && files.length) entry.files = files;
    conversation.messages.push(entry);
    saveState();
    if (files && files.length) renderConvoFiles(conversation);
    scrollBottom();
  }

  function createAIMessage() {
    const conversation = renderingConversation();
    if (!conversation) return null;
    const row = document.createElement('div');
    row.className = 'msg';
    row.innerHTML = `
      <div class="ai">
        <div class="ai-head">
          <span class="ai-avatar">${svg(ICON.spark)}</span>
          <span class="ai-name">投研 Agent</span>
        </div>
        <div class="ai-body"></div>
      </div>`;
    threadFor(conversation).appendChild(row);
    scrollBottom();
    return row.querySelector('.ai-body');
  }

  function appendAIText(text) {
    if (!state.aiEl) return;
    text = normalizePublishedText(text);
    const p = document.createElement('div');
    p.className = 'ai-text';
    p.style.marginBottom = '10px';
    state.aiEl.appendChild(p);
    recordMessage('agent', text);
    if (state.replaying || /^Artifact ID[：:]/m.test(text)) { renderAIText(p, text); return; }
    let i = 0;
    const t = setInterval(() => {
      i = Math.min(i + 2, text.length);
      p.textContent = text.slice(0, i);
      scrollBottom();
      if (i >= text.length) clearInterval(t);
    }, 18);
    state.timers.push(t);
    scrollBottom();
  }

  function showSkill(name) {
    if (state.silentRender) return;
    el.skillBadge.style.display = 'inline-flex';
    el.skillName.textContent = name;
  }

  function renderHistory(conversation) {
    for (const m of conversation.messages || []) {
      if (m.role === 'user') {
        const row = document.createElement('div');
        row.className = 'msg user';
        row.innerHTML = `<div class="bubble">${esc(m.text)}${filesBlock(m.files)}</div>`;
        el.thread.appendChild(row);
        bindFileChips(row);
      } else {
        const row = document.createElement('div');
        row.className = 'msg';
        row.innerHTML = `
          <div class="ai">
            <div class="ai-head">
              <span class="ai-avatar">${svg(ICON.spark)}</span>
              <span class="ai-name">投研 Agent</span>
            </div>
            <div class="ai-body"><div class="ai-text" style="margin-bottom:10px">${esc(m.text)}</div></div>
          </div>`;
        renderAIText(row.querySelector('.ai-text'), m.text);
        el.thread.appendChild(row);
      }
    }
    scrollBottom();
  }

  /* ---------- 执行计划面板（对话区上方，可折叠） ---------- */
  // 注入时机：agent 真正调用 write_todos 时才出现。skill 激活时只记录技能名，
  // 不预先画一个空计划，避免"计划已列好但一步没跑"的假象。

  BP.message = {
    renderAIText, filesBlock, addUserMessage, createAIMessage, appendAIText, showSkill, renderHistory,
  };
})();
