/* 06-approval: 确认卡与提问卡
   经典 script，无构建；对外只暴露 window.BP.approval。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const ICON = BP.lazy('util', 'ICON');
  const currentConversation = (...args) => BP.state.currentConversation(...args);
  const esc = (...args) => BP.util.esc(...args);
  const renderingConversation = (...args) => BP.state.renderingConversation(...args);
  const resumeMock = (...args) => BP.run.resumeMock(...args);
  const saveState = (...args) => BP.state.saveState(...args);
  const scrollBottom = (...args) => BP.dom.scrollBottom(...args);
  const send = (...args) => BP.composer.send(...args);
  const setStatus = (...args) => BP.dom.setStatus(...args);
  const state = BP.lazy('state', 'state');
  const stopTimer = (...args) => BP.dom.stopTimer(...args);
  const submitLive = (...args) => BP.run.submitLive(...args);
  const svg = (...args) => BP.util.svg(...args);

  function normalizeQuestionPayload(payload) {
    const p = {...payload};
    const question = String(p.question || '');
    const context = String(p.context || '');
    if (p.gate === 'one_pager_risk' || (question.includes('非优质') && /展示|放进|风险提示|纳入/.test(question))) {
      return {...p, gate:'one_pager_risk', kind:'risk_disclosure', allow_free_text:true,
        options:[{value:'show',label:'展示'},{value:'hide',label:'不展示'}]};
    }
    if (p.gate === 'cbex_project') return {...p, kind:'cbex_project', allow_free_text:false};
    if (p.gate === 'cbex_listing' || (question.includes('北交互联') && /是否|是不是|挂牌|披露/.test(question))) {
      return {...p, gate:'cbex_listing', kind:'cbex_listing', allow_free_text:true,
        options:[{value:'yes',label:'是，正在北交互联披露'},{value:'no',label:'不是'},
          {value:'unknown',label:'不确定，按材料继续'}]};
    }
    const business = /业务类型|交易类型|交易方式/.test(question) || (
      (question + context).includes('增资') && /产权|股权|转让/.test(question + context)
      && /类型|属于|还是|选择股权|选择增资/.test(question)
    );
    if (p.gate === 'one_pager_business_type' || p.kind === 'business_type' || (!question.includes('北交互联') && business)) {
      return {...p, kind:'business_type', gate:'one_pager_business_type', allow_free_text:true,
        options:[{value:'产权',label:'股权转让（产权）'},{value:'增资',label:'增资扩股'}]};
    }
    if (!Array.isArray(p.options) || !p.options.some(option => option?.value && option?.label)) {
      p.options = [];
      p.allow_free_text = true;
    }
    return p;
  }

  function showApproval(ev) {
    ev = normalizeQuestionPayload(ev);
    const conversation = state.renderingConversation || currentConversation();
    const registryNotice = ev.kind === 'registry_name';
    const businessTypeNotice = ev.kind === 'business_type';
    const cbexListing = ev.kind === 'cbex_listing';
    const cbexProject = ev.kind === 'cbex_project';
    const riskNotice = ev.kind === 'risk_disclosure';
    const options = Array.isArray(ev.options) ? ev.options.filter(o => o && o.label) : [];
    // The risk gate asks the user whether to disclose; without the list they
    // cannot judge what they are agreeing to.
    const riskItems = riskNotice && Array.isArray(ev.risk_items)
      ? ev.risk_items.filter(item => String(item || '').trim())
      : [];
    state.paused = true;
    setStatus('waiting');
    stopTimer();
    const card = document.createElement('div');
    card.className = 'approval is-question';
    if (cbexListing) card.classList.add('cbex-listing');
    if (riskItems.length) card.classList.add('has-risk-items');
    card.dataset.question = ev.question_id || ev.approval_id || '';
    card.innerHTML = `
      <div class="approval-title">${svg(ICON.alert)}<span>${cbexProject ? '请选择挂牌项目' : cbexListing ? '确认披露状态并填写项目全称' : businessTypeNotice ? '请选择业务类型' : registryNotice ? '工商信息补充（可跳过）' : options.length ? '请选择，也可以补充说明' : '请补充信息'}</span></div>
      <div class="approval-q">${esc(ev.question)}</div>
      ${riskItems.length ? `<ul class="approval-risk-items">${riskItems.map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : ''}
      ${ev.context ? `<div class="approval-impact">${esc(ev.context)}</div>` : ''}
      <div class="approval-opts as-list">${options.map(o => `
        <button class="approval-opt" data-value="${esc(o.value)}" aria-pressed="false">
          <span class="approval-opt-label">${esc(o.label)}</span>
          ${cbexProject ? `<span class="approval-opt-desc">项目类型：${esc(o.project_type || '未披露')}</span><span class="approval-opt-desc">信息披露截止日期：${esc(o.disclosure_end_date || '未披露')}</span>` : ''}
          ${o.description ? `<span class="approval-opt-desc">${esc(o.description)}</span>` : ''}
        </button>`).join('')}</div>
      <div class="approval-input">
        ${ev.allow_free_text !== false ? '<textarea placeholder="补充说明会加入当前对话记忆，可直接输入你的回答…"></textarea>' : ''}
        <button class="approval-send primary">继续当前任务</button>
        <button class="approval-abort" type="button">中止本次任务</button>
        <span class="approval-error" role="status"></span>
      </div>`;
    state.aiEl.appendChild(card);
    const draft = conversation.questionDraft?.questionId === card.dataset.question ? conversation.questionDraft : {};
    let selected = draft.choiceValue || '';
    const saveQuestionDraft = () => {
      conversation.questionDraft = {questionId:card.dataset.question, choiceValue:selected,
        text:card.querySelector('textarea')?.value || ''};
      saveState();
    };
    card.querySelectorAll('.approval-opt').forEach(btn => {
      btn.classList.toggle('selected', btn.dataset.value === selected);
      btn.setAttribute('aria-pressed', String(btn.dataset.value === selected));
      btn.addEventListener('click', () => {
        selected = btn.dataset.value;
        card.querySelectorAll('.approval-opt').forEach(other => {
          other.classList.toggle('selected', other === btn);
          other.setAttribute('aria-pressed', String(other === btn));
        });
        if (registryNotice || cbexListing) {
          const input = card.querySelector('textarea');
          if (input) {
            input.hidden = selected !== (cbexListing ? 'yes' : 'correct_name');
            if (!input.hidden) input.focus();
          }
        }
        saveQuestionDraft();
      });
    });
    const textarea = card.querySelector('textarea');
    if (textarea) {
      textarea.value = draft.text || '';
      if (registryNotice) {
        textarea.placeholder = '请输入企业登记的精确名称，例如：某某科技有限公司';
        textarea.hidden = selected !== 'correct_name';
      }
      if (cbexListing) {
        textarea.placeholder = '输入北交互联正在挂牌的项目全称';
        textarea.setAttribute('aria-label', '北交互联正在挂牌的项目全称');
        textarea.hidden = selected !== 'yes';
      }
      textarea.addEventListener('input', saveQuestionDraft);
    }
    const send = card.querySelector('.approval-send');
    // 卡片上要有一个明确的退出路径：用户可能发现材料不对、不想继续，此时
    // 让他只能"回答"或关页面是不对的。
    const abort = card.querySelector('.approval-abort');
    if (abort) {
      abort.addEventListener('click', () => {
        const conversation = state.renderingConversation || currentConversation();
        if (conversation) void BP.composer.cancelRun(conversation);
      });
    }
    send.addEventListener('click', async () => {
      const text = (registryNotice && selected === 'skip') || (cbexListing && selected !== 'yes') ? '' : textarea?.value.trim() || '';
      const error = card.querySelector('.approval-error');
      if (riskNotice && !selected) {
        error.textContent = '请选择展示或不展示，可同时补充说明。';
        return;
      }
      if ((cbexListing || cbexProject) && !selected) {
        error.textContent = cbexProject ? '请先选择挂牌项目。' : '请先选择披露状态。';
        return;
      }
      if (cbexListing && selected === 'yes' && !text) {
        error.textContent = '请输入北交互联正在挂牌的项目全称。';
        textarea?.focus();
        return;
      }
      if (businessTypeNotice && !selected) {
        error.textContent = '请先选择股权转让或增资扩股，可同时填写补充说明。';
        return;
      }
      if (!selected && !text) { error.textContent = '请选择一个选项，或输入补充信息。'; return; }
      if (registryNotice && selected === 'correct_name' && !text) {
        error.textContent = '请输入精确名称，或选择跳过此步骤。';
        textarea?.focus();
        return;
      }
      error.textContent = '';
      card.querySelectorAll('button').forEach(b => { b.disabled = true; });
      if (textarea) textarea.disabled = true;
      const label = options.find(o => o.value === selected)?.label || '';
      if (conversation.mode === 'mock') {
        card.textContent = [label, text].filter(Boolean).join('；');
        state.paused = false;
        resumeMock();
        return;
      }
      const ok = await submitLive({text, files: [], urls: '',
        // Resuming must continue the skill that asked the question. The
        // backend reports it through skill.activated; the stored request is
        // only a fallback for conversations that never activated a skill.
        skill: conversation.activeSkill || conversation.requestedSkill || '',
        questionId: card.dataset.question,
        choiceValue: selected, displayText: [label, text].filter(Boolean).join('；')}, conversation);
      if (ok) {
        const resolved = document.createElement('div');
        resolved.className = 'approval-resolved';
        resolved.textContent = `已补充到当前对话：${[label, text].filter(Boolean).join('；')}`;
        card.replaceWith(resolved);
      } else {
        card.querySelectorAll('button').forEach(b => { b.disabled = false; });
        if (textarea) textarea.disabled = false;
        error.textContent = '未提交成功，内容已保留，请重试。';
      }
    });
    textarea?.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send.click(); }
    });
    scrollBottom();
  }

  /* ---------- document card ---------- */

  /**
   * Remove the pending question card from the transcript.
   *
   * Called when the user aborts a task that is paused on a question: the run
   * itself already finished, so nothing else would ever take the card away.
   */
  function hideApproval() {
    const el = BP.lazy('dom', 'el');
    const scope = el.threadEl || el.thread || el.messages;
    if (scope) {
      for (const card of scope.querySelectorAll('.approval')) card.remove();
    }
    state.paused = false;
  }

  BP.approval = {
    normalizeQuestionPayload, showApproval, hideApproval,
  };
})();
