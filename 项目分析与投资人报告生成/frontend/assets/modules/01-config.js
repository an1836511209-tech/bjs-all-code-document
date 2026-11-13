/* 01-config: 常量表：执行计划、工具提示、本地存储键
   经典 script，无构建；对外只暴露 window.BP.config。
   跨模块引用走 lazy 绑定，加载顺序不影响正确性（调用发生在 boot 之后）。 */
(function () {
  'use strict';
  const BP = (window.BP = window.BP || {});
  const state = BP.lazy('state', 'state');

  const SKILL_PLANS = {
    'one-pager': [
      '初始化工作上下文',
      '解析材料 + 业务类型判定',
      '基本信息补全',
      '投资人匹配',
      '撰写正文 + 三重审查',
      '渲染 docx + 发布'
    ],
    'investment-report': [
      '初始化工作上下文',
      '解析材料',
      '五项数据获取',
      '撰写投资人匹配报告',
      '审查 + Word + 发布'
    ]
  };

  const TOOL_STEP_HINTS = {
    'one-pager': {
      get_working_context: 0, list_context_indexes: 0,
      parse_materials: 1, read_material_chunk: 1, detect_one_pager_business_type: 1,
      extract_project_profile: 2,
      match_investors: 3,
      check_one_pager_outline: 4, write_file: 4, edit_file: 4, check_report: 4, review_ideological_text: 4,
      render_one_pager: 5, validate_and_publish_one_pager: 5
    },
    'investment-report': {
      get_working_context: 0, list_context_indexes: 0,
      parse_materials: 1, read_material_chunk: 1,
      extract_project_profile: 2, query_track_labels: 2, match_listed_peers: 2,
      query_comparable_valuation: 2, match_investors: 2,
      write_file: 3, edit_file: 3,
      check_report: 4, create_word_from_md: 4, add_report_comments: 4, validate_and_publish_word: 4
    }
  };

  /* ============================================================
     Persisted workspace state
     ============================================================ */

  const STORAGE_KEY = 'bjs-console-v2';

  const TITLE_LEADING = [
    '请帮我', '帮我', '麻烦', '请', '帮忙', '给我', '我要', '我想', '需要',
    '根据材料', '根据附件', '基于材料', '按照材料',
    '生成', '写一份', '写个', '做一个', '做个', '出一份', '出个', '整理一份'
  ];

  BP.config = {
    SKILL_PLANS, TOOL_STEP_HINTS, STORAGE_KEY, TITLE_LEADING,
  };
})();
