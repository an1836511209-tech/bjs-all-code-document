/* 08-files: 本对话文件区
   经典 script，无构建；对外只暴露 window.BP.files。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const $$ = (...args) => BP.util.$$(...args);
  const ICON = BP.lazy('util', 'ICON');
  const currentConversation = (...args) => BP.state.currentConversation(...args);
  const el = BP.lazy('dom', 'el');
  const esc = (...args) => BP.util.esc(...args);
  const getApiBase = (...args) => BP.run.getApiBase(...args);
  const openFilePreview = (...args) => BP.document.openFilePreview(...args);
  const openPreview = (...args) => BP.document.openPreview(...args);
  const renderingConversation = (...args) => BP.state.renderingConversation(...args);
  const showArtifact = (...args) => BP.document.showArtifact(...args);
  const state = BP.lazy('state', 'state');
  const svg = (...args) => BP.util.svg(...args);
  const ui = BP.lazy('state', 'ui');

  function fileChip(file) {
    const inner = `${svg(ICON.file)}<span class="nm">${esc(file.name)}</span>`;
    // A button (not an <a download>) so clicking opens the side preview.
    if (!file.url) return `<span class="msg-file">${inner}</span>`;
    const conversation = state.renderingConversation || currentConversation();
    const taskId = conversation?.taskId || '';
    return `<button class="msg-file" data-file-url="${esc(file.url)}" data-file-name="${esc(file.name)}" data-task-id="${esc(taskId)}">${inner}</button>`;
  }

  function bindFileChips(root) {
    $$('.msg-file[data-file-url]', root).forEach((btn) => {
      btn.addEventListener('click', () => {
        // Resolve the task id at click time: the chip is rendered before the
        // run is accepted, so its data-task-id would still be empty.
        const conversation = state.renderingConversation || currentConversation();
        openFilePreview({
          name: btn.dataset.fileName,
          url: btn.dataset.fileUrl,
          taskId: btn.dataset.taskId || conversation?.taskId || ''
        });
      });
    });
  }

  // ===== 本对话文件（上传材料 + 生成产物）=====

  function artifactDownloadUrl(artifactId) {
    if (!/^artifact_[a-f0-9]{32}$/.test(artifactId || '')) return '';
    const api = getApiBase().replace(/\/$/, '');
    return new URL(`${api}/api/artifacts/${artifactId}/content`, location.href).href;
  }

  function artifactPreviewUrl(artifactId) {
    if (!/^artifact_[a-f0-9]{32}$/.test(artifactId || '')) return '';
    const api = getApiBase().replace(/\/$/, '');
    return new URL(`${api}/api/artifacts/${artifactId}/preview.pdf`, location.href).href;
  }

  function collectConversationFiles(conversation) {
    const uploads = [];
    const seenUploads = new Set();
    (conversation?.messages || []).forEach((msg) => {
      (msg.files || []).forEach((file) => {
        const key = `${file.name}|${file.taskId || ''}`;
        if (!file.name || seenUploads.has(key)) return;
        seenUploads.add(key);
        uploads.push({
          kind: 'upload',
          name: file.name,
          taskId: file.taskId || '',
          url: file.url || ''
        });
      });
    });

    const artifacts = [];
    const seenArtifacts = new Set();
    (conversation?.events || []).forEach((evt) => {
      if (!evt || evt.type !== 'artifact.created') return;
      if (evt.task_id && evt.task_id !== conversation.taskId) return;
      const p = evt.payload || {};
      const key = p.artifact_id;
      if (!key || seenArtifacts.has(key)) return;
      seenArtifacts.add(key);
      artifacts.push({
        kind: 'artifact',
        artifactId: p.artifact_id,
        name: p.filename || '产物',
        url: artifactDownloadUrl(p.artifact_id),
        size: p.size_bytes || 0,
        sha256: p.sha256 || ''
      });
    });
    return { uploads, artifacts };
  }

  function renderConvoFiles(conversation) {
    const target = conversation || currentConversation();
    if (target?.id !== ui.activeConversation) return;
    if (!el.convoFiles || !el.convoFilesBody) return;
    const { uploads, artifacts } = collectConversationFiles(target);
    if (!uploads.length && !artifacts.length) {
      el.convoFiles.hidden = true;
      el.convoFilesBody.innerHTML = '';
      return;
    }
    el.convoFiles.hidden = false;
    if (el.convoFilesTitle) el.convoFilesTitle.textContent = '本对话文件';

    const group = (title, items, icon) => (items.length
      ? `<div class="cf-group">
           <div class="cf-label">${icon} ${title} · ${items.length}</div>
           ${items.map((item) => `
             <button class="cf-item" data-kind="${item.kind}"
                     data-name="${esc(item.name)}"
                     data-artifact="${esc(item.artifactId || '')}"
                     data-url="${esc(item.url || '')}"
                     data-task="${esc(item.taskId || '')}">
               <span class="cf-name">${esc(item.name)}</span>
               ${item.kind === 'artifact' ? '<span class="cf-badge">可下载</span>' : ''}
             </button>`).join('')}
         </div>`
      : '');

    el.convoFilesBody.innerHTML =
      group('上传材料', uploads, '📎') + group('生成产物', artifacts, '📄');

    el.convoFilesBody.querySelectorAll('.cf-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        const url = btn.dataset.url || '';
        const name = btn.dataset.name || '';
        const taskId = btn.dataset.task || '';
        if (btn.dataset.kind === 'artifact') {
          if (name.toLowerCase().endsWith('.xlsx') && showArtifact(target, btn.dataset.artifact)) return;
          if (url) window.open(url, '_blank', 'noopener');
          return;
        }
        openFilePreview({ name, url, taskId });
      });
    });
  }

  // 顶栏「文件预览」：列出本对话的上传材料与生成产物，点击即在右侧打开。

  function openFilesPanel() {
    const conversation = currentConversation();
    const { uploads, artifacts } = collectConversationFiles(conversation);
    const all = [...artifacts, ...uploads];
    if (!all.length) {
      state.doc = {
        title: '文件预览',
        sub: '本对话还没有文件',
        html: '<div class="file-meta"><p>上传材料或生成文档后，这里会出现文件。</p></div>'
      };
      openPreview();
      return;
    }
    const rows = all.map((item, index) => `
      <button class="cf-item" data-idx="${index}">
        <span class="cf-name">${item.kind === 'artifact' ? '📄' : '📎'} ${esc(item.name)}</span>
        ${item.kind === 'artifact' ? '<span class="cf-badge">可下载</span>' : ''}
      </button>`).join('');
    state.doc = {
      title: '文件预览',
      sub: `${all.length} 个文件`,
      html: `
        <div class="p-head"><span>本对话文件</span><span>${all.length}</span></div>
        <div class="files-panel">${rows}</div>`
    };
    openPreview();
    el.paper.querySelectorAll('.cf-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        const item = all[Number(btn.dataset.idx)];
        if (!item) return;
        if (item.kind === 'artifact') {
          const lower = item.name.toLowerCase();
          if (/\.(docx?|pptx?|xlsx?|pdf)$/.test(lower)
              && showArtifact(conversation, item.artifactId, item.name)) return;
          if (item.url) window.open(item.url, '_blank', 'noopener');
          return;
        }
        openFilePreview({ name: item.name, url: item.url, taskId: item.taskId });
      });
    });
  }

  BP.files = {
    fileChip, bindFileChips, artifactDownloadUrl, artifactPreviewUrl, collectConversationFiles, renderConvoFiles, openFilesPanel,
  };
})();
