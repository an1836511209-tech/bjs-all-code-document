/* 99-boot: 启动序列
   唯一允许依赖全部模块的文件；启动逻辑只放这里。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const createConversation = (...args) => BP.sidebar.createConversation(...args);
  const el = BP.lazy('dom', 'el');
  const findConversation = (...args) => BP.state.findConversation(...args);
  const hydrateFromBackend = (...args) => BP.session.hydrateFromBackend(...args);
  const loadModelOptions = (...args) => BP.composer.loadModelOptions(...args);
  const loadWorkbookFeature = (...args) => BP.workbook.loadWorkbookFeature(...args);
  const openConversation = (...args) => BP.sidebar.openConversation(...args);
  const renderProjects = (...args) => BP.sidebar.renderProjects(...args);
  const ui = BP.lazy('state', 'ui');

  (async () => {
    await loadWorkbookFeature();
    // Debug knobs load in parallel: a missing endpoint must not delay the
    // console, and the selects stay hidden when it is unavailable.
    await loadModelOptions();
    await hydrateFromBackend();
    renderProjects();

    const initial = findConversation(ui.activeConversation);
    if (initial) {
      openConversation(initial.conversation.id);
    } else {
      const firstLive = ui.workspaces.find((w) => !w.demo && w.conversations.length);
      if (firstLive) {
        openConversation(firstLive.conversations[0].id);
      } else {
        // A default conversation is always available, so the composer works
        // immediately instead of forcing the user to create one first.
        createConversation('ws-default');
      }
    }

    el.footerHint.textContent = '已连接本地服务';
  })();
})();
