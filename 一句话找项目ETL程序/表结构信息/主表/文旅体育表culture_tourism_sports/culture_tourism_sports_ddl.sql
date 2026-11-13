-- MySQL DDL语句
-- 自动生成时间: 2025/09/05 周五

-- 来源文件: 文旅体育表_culture_tourism_sports.json
CREATE TABLE `culture_tourism_sports` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
  `project_name` TEXT COMMENT '项目名称',
  `project_code` VARCHAR(100) COMMENT '项目编号',
  `project_highlights` TEXT COMMENT '项目亮点',
  `project_type` VARCHAR(100) COMMENT '项目类型',
  `transfer_or_financing_party` TEXT COMMENT '转让方/融资方（招商主体）',
  `reference_price` TEXT COMMENT '参考价格',
  `location_region` TEXT COMMENT '所在地区',
  `project_basic_info` TEXT COMMENT '项目基本信息',
  `audit_year` TEXT COMMENT '年度',
  `audit_revenue_million` TEXT COMMENT '年度审计报告营业收入（万元）',
  `audit_operating_profit_million` TEXT COMMENT '年度审计报告营业利润（万元）',
  `audit_net_profit_million` TEXT COMMENT '年度审计报告净利润（万元）',
  `audit_total_assets_million` TEXT COMMENT '年度审计报告资产总计（万元）',
  `audit_total_liabilities_million` TEXT COMMENT '年度审计报告负债总计（万元）',
  `audit_equity` TEXT COMMENT '年度审计报告所有者权益',
  `audit_agency` TEXT COMMENT '审计机构',
  `statement_date` TEXT COMMENT '财务报表出具时间',
  `statement_revenue_million` TEXT COMMENT '财务报表营业收入（万元）',
  `statement_operating_profit_million` TEXT COMMENT '财务报表营业利润（万元）',
  `statement_net_profit_million` TEXT COMMENT '财务报表净利润（万元）',
  `statement_total_assets_million` TEXT COMMENT '财务报表资产总计（万元）',
  `statement_total_liabilities_million` TEXT COMMENT '财务报表负债总计（万元）',
  `statement_equity` TEXT COMMENT '财务报表所有者权益',
  `project_status` TEXT COMMENT '项目状态',
  `track_tags` TEXT COMMENT '赛道标签',
  `trending_tags` TEXT COMMENT '热点标签',
  `listed_tags` TEXT COMMENT '挂牌标签',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文旅体育表';

