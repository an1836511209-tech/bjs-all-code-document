/* 09-document: 文档卡 / A4 预览 / 产物页签
   经典 script，无构建；对外只暴露 window.BP.document。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const $ = (...args) => BP.util.$(...args);
  const ICON = BP.lazy('util', 'ICON');
  const artifactDownloadUrl = (...args) => BP.files.artifactDownloadUrl(...args);
  const artifactPreviewUrl = (...args) => BP.files.artifactPreviewUrl(...args);
  const el = BP.lazy('dom', 'el');
  const esc = (...args) => BP.util.esc(...args);
  const getApiBase = (...args) => BP.run.getApiBase(...args);
  const loadWorkbookPreview = (...args) => BP.workbook.loadWorkbookPreview(...args);
  const renderConvoFiles = (...args) => BP.files.renderConvoFiles(...args);
  const renderingConversation = (...args) => BP.state.renderingConversation(...args);
  const runtimeOf = (...args) => BP.state.runtimeOf(...args);
  const state = BP.lazy('state', 'state');
  const svg = (...args) => BP.util.svg(...args);
  const ui = BP.lazy('state', 'ui');
  const withRuntime = (...args) => BP.state.withRuntime(...args);

  function normalizePublishedText(text) {
    let artifactId = '';
    return String(text || '').split('\n').map(line => {
      const match = line.match(/^Artifact ID[：:]\s*(artifact_[a-f0-9]{32})\s*$/);
      if (match) artifactId = match[1];
      if (artifactId && /^下载链接[：:]/.test(line)) return `下载链接：${artifactDownloadUrl(artifactId)}`;
      if (artifactId && /^链接到期时间[：:]/.test(line)) return null;
      return line;
    }).filter(line => line !== null).join('\n');
  }

  function openFilePreview(file) {
    const name = file.name || '附件';
    const isPdf = /\.pdf$/i.test(name);
    const isImage = /\.(png|jpe?g|gif|webp|bmp)$/i.test(name);
    const isText = /\.(txt|md|csv|json|log)$/i.test(name);
    const isOffice = /\.(docx?|pptx?|xlsx?)$/i.test(name);
    let body;

    // 有 taskId 时优先走后端：上传时的 blob URL 在刷新后就失效了，
    // 而后端的 /api/tasks/{task_id}/files/{name} 是持久的。
    const api = getApiBase();
    // 附件对象不一定带 taskId（历史会话、从服务端恢复的文件列表都可能没有），
    // 历史附件缺少 taskId 时沿用当前会话。
    const taskId = file.taskId || renderingConversation()?.taskId || '';
    const backendUrl = taskId
      ? `${api}/api/tasks/${encodeURIComponent(taskId)}/files/${encodeURIComponent(name)}`
      : '';
    const sourceUrl = backendUrl || file.url || '';

    if (isOffice && !BP.office.canRender(name)) {
      body = `<div class="file-meta"><p>该格式暂不支持在线预览。</p>`
        + `<p><a href="${esc(sourceUrl)}" target="_blank" rel="noopener" download>下载文件</a></p></div>`;
      state.doc = { title: name, sub: '上传材料', html: body };
      openPreview();
      return;
    }

    if (isOffice || isPdf) {
      state.doc = { title: name, sub: '上传材料 · 预览', renderUrl: sourceUrl, html: '' };
      openPreview();
      return;
    }

    if (isImage) {
      body = `<div class="file-image"><img src="${esc(sourceUrl)}" alt="${esc(name)}"></div>`;
    } else if (isText) {
      body = `<div class="file-meta"><p>文本文件已在新标签页打开。</p></div>`;
    } else {
      body = `<div class="file-meta"><p>浏览器无法预览该格式，可下载后查看。</p></div>`;
    }
    state.doc = { title: name, sub: '上传材料 · 预览', html: body };
    openPreview();
    if (isText) window.open(sourceUrl, '_blank', 'noopener');
  }

  function docCardEl(docData) {
    const card = document.createElement('button');
    card.className = 'doc-card';
    card.innerHTML = `
      <span class="doc-ico">${svg(ICON.file)}</span>
      <span class="doc-meta">
        <span class="doc-name">${esc(docData.title)}</span>
        <span class="doc-sub">${esc(docData.sub)}</span>
      </span>
      <span class="doc-open">查看 ${svg(ICON.chev)}</span>`;
    const conversation = renderingConversation();
    const doc = state.doc;
    card.addEventListener('click', () => withRuntime(conversation, () => { state.doc = doc; openPreview(doc, conversation); }));
    return card;
  }

  function showDocCard() {
    const doc = window.MOCK_SCRIPT.document;
    state.doc = doc;
    state.aiEl.appendChild(docCardEl({ title: doc.title, sub: doc.sub }));
    el.previewToggle.style.display = 'inline-flex';
    openPreview();
    setTimeout(() => { el.messages.scrollTop = el.messages.scrollHeight; }, 120);
  }

  /* ============================================================
     Preview
     ============================================================ */

  function openPreview(doc = state.doc, conversation = renderingConversation()) {
    if (!doc || state.silentRender || state.replaying || conversation?.id !== ui.activeConversation) return;
    if (doc.conversationId && doc.conversationId !== conversation.id) return;
    if (doc.taskId && doc.taskId !== conversation.taskId) return;
    el.shell.classList.add('has-preview');
    el.preview.classList.add('open');
    el.previewTitle.textContent = doc.title;
    el.previewSub.textContent = doc.sub;
    // 在侧栏内渲染 Word 或 PDF，保留产物下载入口。
    const canInline = doc.renderUrl
      && BP.office && BP.office.canRender(doc.renderName || doc.title || '');
    if (canInline) {
      // 保留下载工具栏，内容区下面再挂渲染容器。
      el.paper.innerHTML = doc.html || '';
      const host = document.createElement('div');
      host.className = 'office-host';
      el.paper.appendChild(host);
      BP.office.render(host, { name: doc.renderName || doc.title || '', url: doc.renderUrl });
    } else {
      el.paper.innerHTML = doc.html;
    }
    if (doc.artifactId) runtimeOf(conversation).activeArtifactId = doc.artifactId;
    renderArtifactTabs(conversation);
    el.preview.scrollTop = 0;
  }

  function closePreview() {
    el.shell.classList.remove('has-preview');
    el.preview.classList.remove('open');
  }
  $('#closePreview').addEventListener('click', closePreview);
  // 导出按钮已下线：文档一律通过「下载」链接取原件，避免把控制台 UI 打进打印件。


  /* ============================================================
     Published artifacts
     ============================================================ */

  function artifactToolbar(filename, url) {
    return `<div class="preview-toolbar">
      <a class="dl-btn" href="${esc(url)}" download>下载文档</a>
      <span class="muted">${esc(filename)}</span>
    </div>`;
  }

  function addLiveDoc(p) {
    if (!p.artifact_id || !p.filename) return;
    p = {...p, download_url: artifactDownloadUrl(p.artifact_id)};
    const size = p.size_bytes ? (p.size_bytes / 1024).toFixed(1) + ' KB' : '—';
    const conversation = renderingConversation();
    const runtime = runtimeOf(conversation);
    const previousDoc = state.doc;
    const excel = p.filename.toLowerCase().endsWith('.xlsx');
    const previewUrl = excel ? '' : artifactPreviewUrl(p.artifact_id);
    const previewName = excel ? '' : String(p.filename).replace(/\.(docx?|pptx?)$/i, '.pdf');
    state.doc = {
      artifactId: p.artifact_id,
      conversationId: renderingConversation().id,
      taskId: renderingConversation().taskId,
      title: p.filename,
      sub: `PDF 预览 · 原件 Word · ${size}`,
      renderUrl: previewUrl,
      renderName: previewName,
      html: artifactToolbar(p.filename, p.download_url)
    };
    if (excel) {
      state.doc.sub = `Excel 匹配表 · ${size}`;
      // Excel 走工作簿预览，不能再嵌 PDF iframe。
      state.doc.frameSrc = '';
      state.doc.renderUrl = '';
      state.doc.renderName = '';
      state.doc.html = `<h1>${esc(p.filename)}</h1><p>投资机构匹配表已生成。</p><p><a href="${esc(p.download_url)}" target="_blank" rel="noopener">下载 Excel →</a></p>`;
    }
    const doc = state.doc;
    runtime.artifactsById.set(p.artifact_id, doc);
    if (!excel || !previousDoc) runtime.activeArtifactId = p.artifact_id;
    if (state.aiEl) state.aiEl.appendChild(docCardEl({ title: p.filename, sub: excel ? 'Excel 匹配表 · 已发布' : 'Word 文档 · 已发布' }));
    if (excel && previousDoc) state.doc = previousDoc;
    else openPreview();
    if (excel) void loadWorkbookPreview(conversation, p.artifact_id);
    if (conversation.id === ui.activeConversation) renderArtifactTabs(conversation);
    // 产物一生成就把它加到左侧「本对话文件」，不用手动刷新。
    renderConvoFiles(renderingConversation());
    setTimeout(() => { el.messages.scrollTop = el.messages.scrollHeight; }, 120);
  }

  function renderArtifactTabs(conversation) {
    const tabs = $('#artifactTabs');
    if (!tabs || conversation?.id !== ui.activeConversation) return;
    const runtime = runtimeOf(conversation);
    tabs.hidden = runtime.artifactsById.size < 2;
    tabs.innerHTML = [...runtime.artifactsById.values()].map(doc =>
      `<button type="button" class="mini-btn" role="tab" aria-selected="${doc.artifactId === runtime.activeArtifactId}" data-artifact="${esc(doc.artifactId)}">${esc(doc.title)}</button>`).join('');
    tabs.querySelectorAll('button').forEach(button => button.addEventListener('click', () => showArtifact(conversation, button.dataset.artifact)));
  }

  function showArtifact(conversation, artifactId, filename = '文档预览') {
    if (!conversation || conversation.id !== ui.activeConversation) return false;
    let doc = runtimeOf(conversation).artifactsById.get(artifactId);
    if (!doc) {
      const url = artifactDownloadUrl(artifactId);
      const previewUrl = artifactPreviewUrl(artifactId);
      if (!url || !previewUrl) return false;
      const excel = String(filename).toLowerCase().endsWith('.xlsx');
      if (excel) {
        doc = {
          artifactId,
          conversationId: conversation.id,
          taskId: conversation.taskId,
          title: filename,
          sub: 'Excel 匹配表 · 预览',
          renderUrl: '',
          renderName: '',
          html: artifactToolbar(filename, url),
        };
      } else {
        doc = {
          artifactId,
          conversationId: conversation.id,
          taskId: conversation.taskId,
          title: filename,
          sub: 'PDF 预览 · 原件 Word',
          renderUrl: previewUrl,
          renderName: String(filename).replace(/\.(docx?|pptx?)$/i, '.pdf'),
          html: artifactToolbar(filename, url),
        };
      }
    }
    withRuntime(conversation, () => { state.doc = doc; openPreview(doc, conversation); });
    return true;
  }

  BP.document = {
    normalizePublishedText, openFilePreview, docCardEl, showDocCard, openPreview, closePreview, addLiveDoc, renderArtifactTabs, showArtifact,
  };
})();
