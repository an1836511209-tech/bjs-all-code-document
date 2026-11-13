/* 11-workbook: 投资机构匹配表附件
   经典 script，无构建；对外只暴露 window.BP.workbook。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const $ = (...args) => BP.util.$(...args);
  const addLiveDoc = (...args) => BP.document.addLiveDoc(...args);
  const artifactDownloadUrl = (...args) => BP.files.artifactDownloadUrl(...args);
  const currentConversation = (...args) => BP.state.currentConversation(...args);
  const el = BP.lazy('dom', 'el');
  const esc = (...args) => BP.util.esc(...args);
  const getApiBase = (...args) => BP.run.getApiBase(...args);
  const openPreview = (...args) => BP.document.openPreview(...args);
  const renderConvoFiles = (...args) => BP.files.renderConvoFiles(...args);
  const runtimeOf = (...args) => BP.state.runtimeOf(...args);
  const saveState = (...args) => BP.state.saveState(...args);
  const state = BP.lazy('state', 'state');
  const syncHeader = (...args) => BP.dom.syncHeader(...args);
  const ui = BP.lazy('state', 'ui');
  const withRuntime = (...args) => BP.state.withRuntime(...args);

  let workbookFeatureEnabled = false;

  let workbookWorkerOnline = false;

  let workbookFeatureError = '';

  let workbookFeatureRequest = null;

  let workbookFeatureCheckedAt = 0;

  async function loadWorkbookPreview(conversation, artifactId) {
    const runtime = runtimeOf(conversation);
    const taskId = conversation.taskId;
    const doc = runtime.artifactsById.get(artifactId);
    if (!doc || doc.previewLoaded || doc.previewLoading) return;
    doc.previewLoading = true;
    try {
      const response = await fetch(`${getApiBase()}/api/artifacts/${encodeURIComponent(artifactId)}/preview`, {signal:AbortSignal.timeout(10000)});
      if (!response.ok) return;
      const preview = await response.json();
      if (taskId !== conversation.taskId || !Array.isArray(preview.columns) || !Array.isArray(preview.rows)) return;
      doc.html = `<h1>${esc(doc.title)}</h1><p>${esc(preview.company_name || '')} · 共 ${esc(preview.row_count)} 家，预览前 20 行</p>
        <p>查询标签：${(preview.query_tags || []).map(esc).join('、')}</p>
        <p class="muted">来源：${esc(runtime.artifactsById.get(preview.source_docx_artifact_id)?.title || '当前任务材料')} · 材料版本 ${esc((preview.context_fingerprint || '').slice(0,12))}</p>
        <p class="muted">${esc(preview.note || '')}</p>
        ${(preview.unverified_row_count || preview.count_mismatch_row_count) ? `<p>未完整核验 ${esc(preview.unverified_row_count)} 行；数量口径不一致 ${esc(preview.count_mismatch_row_count)} 行，详见 Excel 注释。</p>` : ''}
        <div class="workbook-table"><table><thead><tr>${preview.columns.slice(0,4).map(v => `<th>${esc(v)}</th>`).join('')}</tr></thead>
        <tbody>${preview.rows.slice(0,20).map(row => `<tr>${row.slice(0,4).map(v => `<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
        <p><a href="${esc(artifactDownloadUrl(artifactId))}" target="_blank" rel="noopener">下载 Excel →</a></p>`;
      doc.previewLoaded = true;
      if (conversation.id === ui.activeConversation && runtime.activeArtifactId === artifactId && el.preview.classList.contains('open')) {
        withRuntime(conversation, () => { state.doc = doc; openPreview(doc, conversation); });
      }
    } catch { /* Keep the verified download available when preview is offline. */ }
    finally { doc.previewLoading = false; }
  }

  function renderWorkbookStatus(conversation) {
    const box = $('#workbookStatus');
    if (!box || conversation?.id !== ui.activeConversation) return;
    const runtime = runtimeOf(conversation);
    const jobs = conversation.auxiliaryJobs || [];
    const latest = jobs[0];
    box.hidden = false;
    const labels = {queued:'排队中',running:'生成中',succeeded:'已生成',failed:'生成失败',skipped:'已跳过',cancelled:'已取消'};
    let summary = latest ? `投资机构匹配表：${labels[latest.status] || latest.status}${latest.reason ? ' · ' + latest.reason : ''}`
      : conversation.institutionWorkbook ? '已选择附带匹配表，报告完成后独立生成。' : '可选择随报告附带投资机构匹配表。';
    if (!workbookFeatureEnabled) summary = workbookFeatureError || '当前服务未启用投资机构匹配附件，请重启服务后刷新状态。';
    else {
      if (runtime.status === 'running') summary += ' 当前报告执行中，附件选项已锁定。';
      if (!workbookWorkerOnline) summary += ' 附件生成服务未启动，启动后才会处理匹配表；报告可正常生成。';
    }
    const signature = JSON.stringify([conversation.taskId,runtime.status,latest?.job_id,latest?.status,latest?.stage,summary,runtime.auxiliaryError,Boolean(workbookFeatureRequest)]);
    if (runtime.workbookStatusSignature === signature) return;
    runtime.workbookStatusSignature = signature;
    const terminal = latest && ['failed','skipped','cancelled'].includes(latest.status);
    const choices = terminal ? (latest.candidate_tags || []).slice(0,100) : [];
    const busy = !workbookFeatureEnabled || runtime.status === 'running' || jobs.some(job => ['queued','running'].includes(job.status));
    box.innerHTML = `<span>${esc(runtime.auxiliaryError || summary)}</span>
      ${!workbookFeatureEnabled || !workbookWorkerOnline ? `<button class="mini-btn" type="button" data-workbook="status" ${workbookFeatureRequest ? 'disabled' : ''}>${workbookFeatureRequest ? '检查中…' : '刷新状态'}</button>` : ''}
      ${workbookFeatureEnabled && latest && ['queued','running'].includes(latest.status) ? '<button class="mini-btn" type="button" data-workbook="cancel">取消附件</button>' : ''}
      ${conversation.taskId && !busy ? `<button class="mini-btn" type="button" data-workbook="export">${terminal ? '重试附件' : '生成匹配表'}</button>` : ''}
      ${conversation.taskId && terminal && !busy ? '<button class="mini-btn" type="button" data-workbook="refresh">更新标签后重试</button>' : ''}
      ${workbookFeatureEnabled && terminal && choices.length ? `<details><summary>手动选择标签（最多 ${esc(latest.max_selected_tags || 5)} 个）</summary>
        <div class="tag-choices">${choices.map(tag => `<label><input type="checkbox" value="${esc(tag)}">${esc(tag)}</label>`).join('')}</div>
        <button class="mini-btn" type="button" data-workbook="selected">使用所选标签重试</button></details>` : ''}`;
    box.querySelectorAll('[data-workbook]').forEach(button => button.addEventListener('click', () => {
      if (button.dataset.workbook === 'status') {
        void loadWorkbookFeature().then(() => startAuxiliaryPolling(conversation));
        return;
      }
      if (button.dataset.workbook === 'cancel') {
        void fetch(`${getApiBase()}/api/tasks/${encodeURIComponent(conversation.taskId)}/auxiliary-jobs/${encodeURIComponent(latest.job_id)}/cancel`, {method:'POST',signal:AbortSignal.timeout(10000)})
          .then(async (response) => {
            const body = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '取消附件失败');
            if (Array.isArray(body.jobs)) conversation.auxiliaryJobs = body.jobs;
            runtime.auxiliaryError = body.cancelled ? '' : '附件已结束或无法取消，已刷新状态。';
            saveState();
            renderWorkbookStatus(conversation);
            runtime.auxiliaryUntil = Date.now() + 360000;
            void pollAuxiliary(conversation);
          })
          .catch(error => { runtime.auxiliaryError = error.message; renderWorkbookStatus(conversation); });
        return;
      }
      const selected = button.dataset.workbook === 'selected' ? [...box.querySelectorAll('input:checked')].map(input => input.value) : undefined;
      if (selected && (!selected.length || selected.length > (latest?.max_selected_tags || 5))) {
        runtime.auxiliaryError = `请选择 1～${latest?.max_selected_tags || 5} 个标签。`;
        renderWorkbookStatus(conversation);
        return;
      }
      void requestWorkbook(conversation, selected, button.dataset.workbook === 'refresh');
    }));
  }

  async function requestWorkbook(conversation, selectedTags, refreshTags = false) {
    const runtime = runtimeOf(conversation);
    if (runtime.auxiliarySubmitting) return;
    runtime.auxiliarySubmitting = true;
    runtime.auxiliaryError = '';
    try {
      const response = await fetch(`${getApiBase()}/api/tasks/${encodeURIComponent(conversation.taskId)}/institution-workbook`, {
        method:'POST', headers:{'Content-Type':'application/json'}, signal:AbortSignal.timeout(15000),
        body:JSON.stringify({client_request_id:crypto.randomUUID(), ...(selectedTags ? {selected_tags:selectedTags} : {}), ...(refreshTags ? {refresh_tags:true} : {})})
      });
      const job = await response.json();
      if (!response.ok) throw new Error(typeof job.detail === 'string' ? job.detail : '附件请求失败');
      conversation.auxiliaryJobs = [job, ...(conversation.auxiliaryJobs || []).filter(item => item.job_id !== job.job_id)];
      runtime.auxiliaryUntil = Date.now() + 360000;
      saveState();
      startAuxiliaryPolling(conversation);
    } catch (error) { runtime.auxiliaryError = error.message; }
    finally { runtime.auxiliarySubmitting = false; renderWorkbookStatus(conversation); }
  }

  function startAuxiliaryPolling(conversation) {
    if (!workbookFeatureEnabled || !conversation?.taskId || conversation.deleted || conversation.mode === 'mock') return;
    const runtime = runtimeOf(conversation);
    runtime.auxiliaryUntil = Math.max(runtime.auxiliaryUntil || 0, Date.now() + 360000);
    if (runtime.auxiliaryPolling) return;
    if (runtime.auxiliaryTimer) return;
    runtime.auxiliaryTimer = setTimeout(() => { runtime.auxiliaryTimer = null; void pollAuxiliary(conversation); }, 1000);
  }

  async function pollAuxiliary(conversation) {
    if (conversation.deleted) return;
    const runtime = runtimeOf(conversation);
    if (document.hidden || conversation.id !== ui.activeConversation || Date.now() > runtime.auxiliaryUntil) return;
    runtime.auxiliaryPolling = true;
    let pending = false;
    try {
      const taskId = conversation.taskId;
      const response = await fetch(`${getApiBase()}/api/tasks/${encodeURIComponent(taskId)}/auxiliary-jobs`, {signal:AbortSignal.timeout(10000)});
      if (!response.ok) {
        runtime.auxiliaryError = '暂时无法读取附件状态，将自动重试。';
        pending = true;
        return;
      }
      const result = await response.json();
      if (conversation.deleted || taskId !== conversation.taskId) return;
      if (result.unavailable) runtime.auxiliaryError = result.reason;
      else { conversation.auxiliaryJobs = result.jobs || []; runtime.auxiliaryError = ''; }
      for (const artifact of result.artifacts || []) {
        if ((conversation.events || []).some(event => event.payload?.artifact_id === artifact.artifact_id)) continue;
        const event = {type:'artifact.created',task_id:taskId,run_id:conversation.lastRunId,payload:{...artifact,size_bytes:artifact.size}};
        conversation.events = [...(conversation.events || []), event];
        withRuntime(conversation, () => { addLiveDoc(event.payload); });
      }
      renderConvoFiles(conversation);
      renderWorkbookStatus(conversation);
      saveState();
      pending = Boolean(result.unavailable || (result.jobs || []).some(job => ['queued','running'].includes(job.status))
        || (!result.jobs?.length && conversation.institutionWorkbook && runtime.status === 'completed'));
    } catch {
      runtime.auxiliaryError = runtime.auxiliaryError || '附件状态请求失败，将自动重试。';
      pending = true;
    }
    finally {
      runtime.auxiliaryPolling = false;
      if (pending && conversation.id === ui.activeConversation && Date.now() < runtime.auxiliaryUntil) {
        runtime.auxiliaryTimer = setTimeout(() => { runtime.auxiliaryTimer = null; void pollAuxiliary(conversation); }, 3000);
      }
    }
  }

  $('#institutionWorkbook')?.addEventListener('change', event => {
    const conversation = currentConversation();
    if (!conversation) return;
    conversation.institutionWorkbook = event.target.checked;
    saveState();
    renderWorkbookStatus(conversation);
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      const conversation = currentConversation();
      if (Date.now() - workbookFeatureCheckedAt > 15000) void loadWorkbookFeature().then(() => startAuxiliaryPolling(conversation));
      else if (conversation) startAuxiliaryPolling(conversation);
    }
  });

  async function loadWorkbookFeature() {
    if (workbookFeatureRequest) return workbookFeatureRequest;
    workbookFeatureRequest = (async () => {
      try {
        const response = await fetch(`${getApiBase()}/api/features`, {cache:'no-store', signal:AbortSignal.timeout(5000)});
        if (!response.ok) throw new Error('feature unavailable');
        const feature = (await response.json()).institution_workbook;
        workbookFeatureEnabled = Boolean(feature?.enabled);
        workbookWorkerOnline = Boolean(feature?.worker_online);
        workbookFeatureError = '';
      } catch {
        workbookFeatureEnabled = false;
        workbookWorkerOnline = false;
        workbookFeatureError = '暂时无法读取附件功能状态，请确认服务已启动后刷新状态。';
      } finally {
        workbookFeatureCheckedAt = Date.now();
        workbookFeatureRequest = null;
        syncHeader();
      }
    })();
    syncHeader();
    return workbookFeatureRequest;
  }

  // Primitive feature flags must be live getters: a plain object snapshot would
  // freeze the initial `false`/`null` values, so syncHeader would keep the
  // "附带投资机构匹配表" checkbox disabled even after /api/features succeeds.
  BP.workbook = {
    get workbookFeatureEnabled() { return workbookFeatureEnabled; },
    get workbookWorkerOnline() { return workbookWorkerOnline; },
    get workbookFeatureError() { return workbookFeatureError; },
    get workbookFeatureRequest() { return workbookFeatureRequest; },
    get workbookFeatureCheckedAt() { return workbookFeatureCheckedAt; },
    loadWorkbookPreview, renderWorkbookStatus, requestWorkbook, startAuxiliaryPolling, pollAuxiliary, loadWorkbookFeature,
  };
})();
