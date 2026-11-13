/* 16-office-preview: 在浏览器里直接渲染 docx / xlsx / pdf
   经典 script，无构建；对外暴露 window.BP.office。

   为什么不转 PDF、不用 iframe：
   - 转 PDF 再塞 iframe，等于把浏览器原生 PDF 查看器整个搬进来（打印按钮、
     工具栏、缩略图栏都在），客户看到的是"打印对话框"，不是文档预览。
   - 业界做法是客户端解析渲染：docx 用 docx-preview，xlsx 用 SheetJS 出表格，
     pdf 用 pdf.js 画到 canvas——预览面板里只有内容，没有别人的 UI。
   - 老二进制格式（.doc/.ppt）浏览器无法解析，主流方案只有 OnlyOffice/Collabora
     这类服务端套件，成本高；这里如实降级为"下载查看"。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});

  const DOCX = /\.docx$/i;
  const SHEET = /\.(xlsx|xls|csv)$/i;
  const PDF = /\.pdf$/i;
  const LEGACY = /\.(doc|ppt)$/i;
  const PPTX = /\.pptx$/i;
  const WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
  const COMPAT_NS = 'http://schemas.openxmlformats.org/markup-compatibility/2006';
  const WORD_BLOCKS = new Map([['p', 'p'], ['tbl', 'table'], ['tr', 'tr'], ['tc', 'td']]);

  function assetUrl(path) {
    return new URL(`assets/vendor/${path}`, document.baseURI).href;
  }

  function message(container, text, { downloadUrl } = {}) {
    const { esc } = BP.util;
    const link = downloadUrl
      ? `<p><a href="${esc(downloadUrl)}" download>下载文件</a></p>`
      : '';
    container.innerHTML = `<div class="file-meta"><p>${esc(text)}</p>${link}</div>`;
  }

  async function fetchBuffer(url) {
    const response = await fetch(url, { credentials: 'same-origin' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.arrayBuffer();
  }

  /* ---------------- docx ---------------- */

  function appendWordContent(source, target) {
    for (const child of source.children) {
      if (child.namespaceURI === COMPAT_NS && child.localName === 'AlternateContent') {
        // Word stores the same shape in two branches for modern and legacy readers.
        const branch = Array.from(child.children).find(node => node.getElementsByTagNameNS(WORD_NS, 't').length);
        if (branch) appendWordContent(branch, target);
        continue;
      }
      const name = child.namespaceURI === WORD_NS ? child.localName : '';
      if (name === 't') {
        target.append(child.textContent);
      } else if (name === 'br' || name === 'cr' || name === 'tab') {
        target.append(name === 'tab' ? '\t' : '\n');
      } else if (name === 'txbxContent') {
        // Place the box's paragraphs beside the paragraph that anchors the shape.
        appendWordContent(child, target.closest('p')?.parentElement || target);
      } else if (WORD_BLOCKS.has(name)) {
        const block = document.createElement(WORD_BLOCKS.get(name));
        target.appendChild(block);
        appendWordContent(child, block);
        if (name === 'p' && !block.textContent.trim()) block.remove();
      } else {
        appendWordContent(child, target);
      }
    }
  }

  async function renderDocx(container, url) {
    if (!window.docx || typeof window.docx.renderAsync !== 'function') {
      throw new Error('docx-preview 未加载');
    }
    const buffer = await fetchBuffer(url);
    const zip = await window.JSZip.loadAsync(buffer);
    const documentPart = zip.file('word/document.xml');
    if (!documentPart) throw new Error('Word 文档缺少正文');
    const xml = await documentPart.async('string');
    const word = new DOMParser().parseFromString(xml, 'application/xml');
    const body = word.getElementsByTagNameNS(WORD_NS, 'body')[0];
    if (!body) throw new Error('Word 文档缺少正文');

    if (body.getElementsByTagNameNS(WORD_NS, 'txbxContent').length) {
      // docx-preview can clip floating text boxes in the BP templates.
      const host = document.createElement('div');
      host.className = 'office-docx-content';
      appendWordContent(body, host);
      if (!host.textContent.trim()) throw new Error('Word 文档没有可预览的文字');
      container.replaceChildren(host);
      return;
    }

    const host = document.createElement('div');
    host.className = 'office-docx';
    container.innerHTML = '';
    container.appendChild(host);
    await window.docx.renderAsync(buffer, host, null, {
      className: 'docx',
      inWrapper: true,
      breakPages: true,
      ignoreWidth: false,
      ignoreHeight: false,
      useBase64URL: true,
      renderAltChunks: false,
    });
  }

  /* ---------------- xlsx / xls / csv ---------------- */

  function cellText(cell) {
    if (!cell) return '';
    if (cell.w != null) return String(cell.w);
    if (cell.v == null) return '';
    return String(cell.v);
  }

  function sheetTable(workbook, sheetName) {
    const sheet = workbook.Sheets[sheetName];
    const range = window.XLSX.utils.decode_range(sheet['!ref'] || 'A1');
    const merges = sheet['!merges'] || [];
    const table = document.createElement('table');
    table.className = 'office-sheet-table';
    let skip = new Set();
    for (let r = range.s.r; r <= range.e.r; r += 1) {
      const tr = document.createElement('tr');
      for (let c = range.s.c; c <= range.e.c; c += 1) {
        const key = `${r}:${c}`;
        if (skip.has(key)) continue;
        const cell = sheet[window.XLSX.utils.encode_cell({ r, c })];
        const td = document.createElement('td');
        td.textContent = cellText(cell);
        const merge = merges.find((m) => m.s.r === r && m.s.c === c);
        if (merge) {
          td.colSpan = merge.e.c - merge.s.c + 1;
          td.rowSpan = merge.e.r - merge.s.r + 1;
          for (let rr = merge.s.r; rr <= merge.e.r; rr += 1) {
            for (let cc = merge.s.c; cc <= merge.e.c; cc += 1) {
              if (rr !== r || cc !== c) skip.add(`${rr}:${cc}`);
            }
          }
        }
        if (r === range.s.r) td.classList.add('is-header');
        tr.appendChild(td);
      }
      table.appendChild(tr);
    }
    return table;
  }

  async function renderSheet(container, url) {
    if (!window.XLSX) throw new Error('SheetJS 未加载');
    const buffer = await fetchBuffer(url);
    const workbook = window.XLSX.read(new Uint8Array(buffer), { type: 'array' });
    container.innerHTML = '';
    if (!workbook.SheetNames.length) {
      message(container, '这个工作簿里没有工作表。');
      return;
    }
    const tabs = document.createElement('div');
    tabs.className = 'office-sheet-tabs';
    const body = document.createElement('div');
    body.className = 'office-sheet-body';
    container.appendChild(tabs);
    container.appendChild(body);

    const paint = (name) => {
      tabs.querySelectorAll('button').forEach((b) => {
        b.classList.toggle('is-active', b.dataset.sheet === name);
      });
      body.innerHTML = '';
      body.appendChild(sheetTable(workbook, name));
    };
    workbook.SheetNames.forEach((name) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = name;
      button.dataset.sheet = name;
      button.addEventListener('click', () => paint(name));
      tabs.appendChild(button);
    });
    paint(workbook.SheetNames[0]);
  }

  /* ---------------- pdf ---------------- */

  async function renderPdf(container, url) {
    if (!window.pdfjsLib) throw new Error('pdf.js 未加载');
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = assetUrl('pdf.worker.min.js');
    const buffer = await fetchBuffer(url);
    const pdf = await window.pdfjsLib.getDocument({ data: new Uint8Array(buffer) }).promise;
    container.innerHTML = '';
    const host = document.createElement('div');
    host.className = 'office-pdf';
    container.appendChild(host);
    // 逐页画到 canvas：不进入浏览器自带查看器，预览面板里只有内容。
    const width = Math.max(320, container.clientWidth - 24);
    for (let pageNo = 1; pageNo <= pdf.numPages; pageNo += 1) {
      const page = await pdf.getPage(pageNo);
      const base = page.getViewport({ scale: 1 });
      const scale = width / base.width;
      const viewport = page.getViewport({ scale });
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.className = 'office-pdf-page';
      host.appendChild(canvas);
      await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
    }
  }

  /* ---------------- 入口 ---------------- */

  async function render(container, { name, url }) {
    if (!container) return;
    if (!url) {
      message(container, '缺少文件地址，无法预览。');
      return;
    }
    if (!canRender(name)) {
      message(container, '该格式暂不支持在线预览。', { downloadUrl: url });
      return;
    }
    message(container, '正在渲染…');
    try {
      if (DOCX.test(name)) await renderDocx(container, url);
      else if (SHEET.test(name)) await renderSheet(container, url);
      else if (PDF.test(name)) await renderPdf(container, url);
      else if (LEGACY.test(name)) {
        message(container, '浏览器无法直接解析旧版 Word / PowerPoint 格式。', { downloadUrl: url });
      } else if (PPTX.test(name)) {
        message(container, '演示文稿暂不支持在线预览。', { downloadUrl: url });
      } else {
        message(container, '该格式暂不支持在线预览。', { downloadUrl: url });
      }
    } catch (err) {
      message(container, `渲染失败（${err && err.message ? err.message : err}）。`, { downloadUrl: url });
    }
  }

  function canRender(name) {
    return DOCX.test(name) || PDF.test(name);
  }

  BP.office = { render, canRender };
})();
