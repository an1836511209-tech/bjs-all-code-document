/* ============================================================
   Mock script — 一段完整的对话式 Agent 运行
   事件类型：
     ai.say      AI 追加一段话
     skill       激活 Skill
     plan.add    创建执行计划卡
     plan.update 更新计划步骤
     tool.start  工具开始
     tool.end    工具结束
     approval    需要人工确认（暂停）
     doc.ready   文档生成完成，出现文档卡
     done        本回合结束
   ============================================================ */
window.MOCK_SCRIPT = {
  title: '星屿储能 · 一页纸 BP',
  sub: '上传材料后由 Agent 生成',
  userMessage: '帮我根据材料生成一页纸 BP，投给 FA 和投资人。',

  plan: [
    '初始化工作上下文',
    '解析材料 + 业务类型判定',
    '基本信息补全',
    '投资人匹配',
    '撰写正文 + 三重审查',
    '渲染 docx + 发布'
  ],

  events: [
    { at: 0, type: 'ai.say', text: '好的，我来处理。先读材料并判定业务类型，然后补全画像、匹配投资人，最后写正文并生成 Word。' },
    { at: 700, type: 'skill', name: 'one-pager', route: '关键词命中「一页纸」' },
    { at: 1000, type: 'plan.add' },

    { at: 1300, type: 'plan.update', index: 0, status: 'running' },
    { at: 1500, type: 'tool.start', id: 't1', name: 'parse_materials' },
    { at: 3000, type: 'tool.end', id: 't1', status: 'ok', duration: 1600, summary: '3 份材料 · 124 个 block' },
    { at: 3200, type: 'plan.update', index: 0, status: 'done', duration: 1600 },

    { at: 3400, type: 'plan.update', index: 1, status: 'running' },
    { at: 3600, type: 'tool.start', id: 't2', name: 'detect_one_pager_business_type' },
    { at: 4100, type: 'tool.end', id: 't2', status: 'ok', duration: 500, summary: '业务类型：增资（confidence=content）' },
    { at: 4300, type: 'plan.update', index: 1, status: 'done', duration: 2100 },

    { at: 4500, type: 'ai.say', text: '材料读完了：3 份文件、124 个 block，业务类型判定为「增资」。' },

    { at: 4800, type: 'plan.update', index: 2, status: 'running' },
    { at: 5000, type: 'tool.start', id: 't3', name: 'extract_project_profile' },
    { at: 6000, type: 'tool.end', id: 't3', status: 'partial', duration: 1300, summary: '命中 9/12 字段 · 3 项缺失' },
    { at: 6200, type: 'plan.update', index: 2, status: 'done', duration: 1800 },

    { at: 6400, type: 'ai.say', text: '画像补全了 9 个字段。注册资本、成立时间、员工数这三项材料里没有，我会在报告里写成「面议」。' },

    {
      at: 7000,
      type: 'approval',
      question: '材料里有 2 处非优质项目信息（关联方担保、未决诉讼），要放进报告的风险提示吗？',
      impact: '影响「风险提示」章节是否生成',
      options: [
        { value: 'show', label: '展示', primary: true },
        { value: 'hide', label: '不展示' }
      ]
    },

    { at: 7600, type: 'ai.say', text: '好，已记录。继续。' },

    { at: 7900, type: 'plan.update', index: 3, status: 'running' },
    { at: 8100, type: 'tool.start', id: 't4', name: 'match_investors' },
    { at: 9800, type: 'tool.end', id: 't4', status: 'ok', duration: 3000, summary: '匹配 20 家（内部 12 · 外部 8）' },
    { at: 10000, type: 'plan.update', index: 3, status: 'done', duration: 3000 },

    { at: 10200, type: 'ai.say', text: '投资人匹配到 20 家，优先推荐 5 家：红杉中国、高瓴创投、源码资本、中金资本、元禾控股。' },

    { at: 10600, type: 'plan.update', index: 4, status: 'running' },
    { at: 10800, type: 'tool.start', id: 't5', name: 'check_one_pager_outline' },
    { at: 11200, type: 'tool.end', id: 't5', status: 'ok', duration: 400, summary: '大纲 6 个标题通过' },
    { at: 11400, type: 'tool.start', id: 't6', name: 'write_file' },
    { at: 11800, type: 'tool.end', id: 't6', status: 'ok', duration: 350, summary: '项目介绍 3 段 · 约 680 字' },
    { at: 12000, type: 'tool.start', id: 't7', name: 'check_report' },
    { at: 12500, type: 'tool.end', id: 't7', status: 'ok', duration: 500, summary: 'block=0 · warn=1（已修正）' },
    { at: 12700, type: 'plan.update', index: 4, status: 'done', duration: 4000 },

    { at: 12900, type: 'ai.say', text: '正文约 1,240 字，三重审查都通过了。' },

    { at: 13200, type: 'plan.update', index: 5, status: 'running' },
    { at: 13400, type: 'tool.start', id: 't8', name: 'render_one_pager' },
    { at: 15000, type: 'tool.end', id: 't8', status: 'ok', duration: 2000, summary: 'DOCX 已生成 · 1 页 · 20 行投资人' },
    { at: 15200, type: 'plan.update', index: 5, status: 'done', duration: 2600 },

    { at: 15400, type: 'ai.say', text: 'Word 已生成，1 页。点下面的卡片预览，或直接下载。' },
    { at: 15800, type: 'doc.ready' },
    { at: 16200, type: 'done' }
  ],

  document: {
    title: '星屿储能 · 一页纸 BP',
    sub: 'Word 文档 · 1 页 · 48 KB',
    filename: '星屿储能-一页纸BP-增资.docx',
    html: `
      <div class="p-head"><span>OnePaper · <b>Confidential</b></span><span>增资 · v2</span></div>
      <h1>星屿储能 · 一页纸商业计划书</h1>
      <p class="p-lede">面向工商业储能场景的 PCS 与系统集成方案商，以「高效率 + 长寿命 + 全生命周期服务」切入高速增长的工商业储能市场。</p>

      <h2 class="p-h2">01 核心产品</h2>
      <p>公司主营 215kWh 液冷储能一体柜与自研 PCS，覆盖工商业业主与 EPC 两类客户，提供从设备到运维的一体化交付。系统效率 91.5%，循环寿命 8,000 次。</p>

      <h2 class="p-h2">02 数据分析</h2>
      <p>2024 年营收 4,100 万元，综合毛利率 38%，累计装机 1.2GWh，在手订单 3.6 亿元，可覆盖未来 14 个月收入。</p>
      <div class="kpis">
        <div class="kpi"><b>4,100 万</b><span>2024 年营收</span></div>
        <div class="kpi"><b>38%</b><span>综合毛利率</span></div>
        <div class="kpi"><b>1.2GWh</b><span>累计装机</span></div>
      </div>

      <h2 class="p-h2">03 项目亮点</h2>
      <ul>
        <li>自研三电平拓扑，单 Wh 成本较外购方案低 11%；</li>
        <li>AI 群控算法，单站收益提升 8%–12%；</li>
        <li>覆盖 26 省的本地化运维网络，故障响应 ≤ 4 小时。</li>
      </ul>

      <h2 class="p-h2">04 风险提示</h2>
      <p>材料披露 2 处非优质项目信息：关联方担保、未决诉讼，已在报告中作为风险因素列示。</p>

      <h2 class="p-h2">05 投资人匹配</h2>
      <table class="inv-table">
        <thead><tr><th>投资人</th><th>类型</th><th>匹配理由</th></tr></thead>
        <tbody>
          <tr><td>红杉中国</td><td>VC</td><td>新能源赛道 · 已投 6 家储能</td></tr>
          <tr><td>高瓴创投</td><td>VC</td><td>碳中和主题 · A 轮偏好</td></tr>
          <tr><td>源码资本</td><td>VC</td><td>硬科技 · 苏州区域覆盖</td></tr>
          <tr><td>中金资本</td><td>PE</td><td>专精特新 · 北交所协同</td></tr>
          <tr><td>元禾控股</td><td>国资</td><td>本地国资 · 制造业主投</td></tr>
        </tbody>
      </table>

      <div class="p-quote"><b>一句话总结：</b>用更高效率的系统、更聪明的控制算法、更下沉的服务网络，把工商业储能从「卖设备」做成「卖确定性收益」。</div>

      <div class="p-foot"><span>© 2025 星屿储能科技 · 本材料仅供交流使用</span><span>Page 1 / 1</span></div>
    `
  }
};
