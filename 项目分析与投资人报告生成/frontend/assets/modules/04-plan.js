/* 04-plan: 执行计划面板
   经典 script，无构建；对外只暴露 window.BP.plan。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const SKILL_PLANS = BP.lazy('config', 'SKILL_PLANS');
  const TOOL_STEP_HINTS = BP.lazy('config', 'TOOL_STEP_HINTS');
  const currentConversation = (...args) => BP.state.currentConversation(...args);
  const el = BP.lazy('dom', 'el');
  const esc = (...args) => BP.util.esc(...args);
  const runtimeOf = (...args) => BP.state.runtimeOf(...args);
  const scrollBottom = (...args) => BP.dom.scrollBottom(...args);
  const state = BP.lazy('state', 'state');

  function createPlan(stepsArg) {
    const steps = stepsArg || window.MOCK_SCRIPT?.plan || [];
    const panel = el.taskPanel;
    const body = el.taskBody;
    if (!panel || !body) return null;

    body.innerHTML = steps.map((s, i) => `
      <div class="plan-step" data-step="${i}">
        <span class="step-dot">${i + 1}</span>
        <span class="step-body">
          <div class="step-name">${esc(s)}</div>
          <div class="step-note"></div>
        </span>
        <span class="step-time"></span>
      </div>`).join('');
    if (el.taskProgress) el.taskProgress.textContent = `0 / ${steps.length}`;
    panel.hidden = false;
    panel.classList.remove('collapsed');
    state.planEl = panel;
    state.plan = steps.map(() => ({ status: 'pending', duration: 0 }));
    // 步骤快照跟着会话走：第二轮对话通常不会重新 write_todos，
    // 只把面板挂在这一轮的 DOM 上，切回来或重新渲染就没了。
    state.planSteps = steps.slice();
    const planOwner = state.planOwner || currentConversation();
    if (planOwner) runtimeOf(planOwner).planSteps = steps.slice();
    scrollBottom();
    return panel;
  }

  function hidePlan() {
    state.planEl = null;
    state.plan = [];
    state.planSteps = [];
    const planOwner = state.planOwner || currentConversation();
    if (planOwner) runtimeOf(planOwner).planSteps = [];
    if (el.taskPanel) {
      el.taskPanel.hidden = true;
      el.taskPanel.classList.remove('collapsed');
    }
    if (el.taskBody) el.taskBody.innerHTML = '';
    if (el.taskProgress) el.taskProgress.textContent = '0 / 0';
  }

  function restorePlan(runtime) {
    const steps = (runtime && runtime.planSteps) || state.planSteps || [];
    const saved = (runtime && runtime.plan) || [];
    if (!steps.length) {
      hidePlan();
      return;
    }
    createPlan(steps);
    saved.forEach((item, index) => {
      if (item && item.status && item.status !== 'pending') {
        updatePlan(index, item.status, item.duration);
      }
    });
  }

  function updatePlan(index, status, duration) {
    if (!state.planEl) return;
    const node = state.planEl.querySelector(`[data-step="${index}"]`);
    if (!node) return;
    node.className = 'plan-step ' + status;
    const dot = node.querySelector('.step-dot');
    dot.textContent = status === 'done' ? '✓' : status === 'failed' ? '!' : String(index + 1);
    if (status === 'running') node.querySelector('.step-note').textContent = '执行中…';
    if (status === 'done') node.querySelector('.step-note').textContent = '已完成';
    if (duration) node.querySelector('.step-time').textContent = (duration / 1000).toFixed(1) + 's';
    state.plan[index] = { status, duration: duration || 0 };
    const done = state.plan.filter((p) => p.status === 'done').length;
    const prog = state.planEl.querySelector('[data-progress], .task-progress');
    if (prog) prog.textContent = `${done} / ${state.plan.length}`;
    scrollBottom();
  }

  /* ---------- tool rows ---------- */
  // 工具调用统一收进一个可折叠容器：默认折叠，只留一行摘要。
  // 运行中标题栏做动画提示（脉动圆点 + 计数 + 流光），失败时自动展开，
  // 避免一长串工具行把对话泡顶走。

  function ensurePlan(skill) {
    // 面板已在且已有步骤 → 不重建。切换会话时会话运行时里存的 planEl 可能指向
    // 刚被 hidePlan 清空的面板，用「有没有子节点」兜住，避免出现空计划。
    if (state.planEl && el.taskBody && el.taskBody.children.length) return;
    createPlan(SKILL_PLANS[skill] || SKILL_PLANS['one-pager']);
  }

  function advancePlanForTool(tool, phase) {
    if (!state.planEl || state.planEl.dataset.source === 'todos') return;
    const map = TOOL_STEP_HINTS[state.skill || 'one-pager'] || {};
    const idx = map[tool];
    if (idx === undefined) return;
    if (phase === 'start') {
      updatePlan(idx, 'running');
    }
  }

  BP.plan = {
    createPlan, hidePlan, restorePlan, updatePlan, ensurePlan, advancePlanForTool,
  };
})();
