# 数据库表结构文档

## 表结构信息

### 债权资产表 (debt_assets)

| 字段名 | 字段类型 | 中文名称 | 备注 |
|--------|----------|----------|------|
| id | BIGINT | 主键ID | 主键ID，自增 |
| project_name | TEXT | 项目名称 |  |
| project_code | TEXT | 项目编号 |  |
| project_highlights | TEXT | 项目亮点 |  |
| project_type | TEXT | 项目类型 |  |
| asset_name | TEXT | 标的名称 |  |
| claim_book_value | TEXT | 债权账面价值 |  |
| claim_transfer_price_type | TEXT | 债权转让价格 |  |
| claim_transfer_price_min | TEXT | 债权转让价格（万元）-最小值 |  |
| claim_transfer_price_max | TEXT | 债权转让价格（万元）-最大值 |  |
| claim_transfer_price_fixed | TEXT | 债权转让价格（万元）-固定值 |  |
| claim_asset_status_desc | TEXT | 债权资产现状描述 |  |
| principal_amount | TEXT | 本金 万元 |  |
| claim_category | TEXT | 债权类别 |  |
| guarantee_category | TEXT | 担保类别 |  |
| collateral_type | TEXT | 抵质押物类型 |  |
| location | TEXT | 所在地 |  |
| other_disclosure | TEXT | 其他需要披露的内容 |  |
| transferor_name | TEXT | 转让方名称 |  |
| debtor_economic_type | TEXT | 债务人经济性质 |  |
| debtor_business_scope | TEXT | 债务人经营范围 |  |
| transferor_type | TEXT | 转让方类型 |  |
| transferor_or_financier | TEXT | 转让方/融资方（招商主体） |  |
| reference_price | TEXT | 参考价格 |  |
| region_name | TEXT | 所在地区 |  |
| project_basic_info | TEXT | 项目基本信息 |  |
| audit_year | TEXT | 年度 |  |
| audit_revenue | TEXT | 年度审计报告营业收入（万元） |  |
| audit_operating_profit | TEXT | 年度审计报告营业利润（万元） |  |
| audit_net_profit | TEXT | 年度审计报告净利润（万元） |  |
| audit_total_assets | TEXT | 年度审计报告资产总计（万元） |  |
| audit_total_liabilities | TEXT | 年度审计报告负债总计（万元） |  |
| audit_equity | TEXT | 年度审计报告所有者权益 |  |
| audit_agency | TEXT | 审计机构 |  |
| financial_stmt_date | TEXT | 财务报表出具时间 |  |
| financial_stmt_revenue | TEXT | 财务报表营业收入（万元） |  |
| financial_stmt_operating_profit | TEXT | 财务报表营业利润（万元） |  |
| financial_stmt_net_profit | TEXT | 财务报表净利润（万元） |  |
| financial_stmt_total_assets | TEXT | 财务报表资产总计（万元） |  |
| financial_stmt_total_liabilities | TEXT | 财务报表负债总计（万元） |  |
| financial_stmt_equity | TEXT | 财务报表所有者权益 |  |
| transfer_floor_price | TEXT | 转让底价 |  |
| asset_source | TEXT | 资产来源 |  |
| has_collateral | TEXT | 标的是否存在抵押物情况 |  |
| book_value | TEXT | 账面价值（万元） |  |
| has_pledge | TEXT | 是否有质押 |  |
| project_state | TEXT | 项目状态 |  |
| created_at | TIMESTAMP | 创建时间 | 系统自动维护 |
| updated_at | TIMESTAMP | 更新时间 | 系统自动维护 |

### 其他资产表 (other_assets)

| 字段名 | 字段类型 | 中文名称 | 备注 |
|--------|----------|----------|------|
| id | BIGINT | 主键ID | 主键ID，自增 |
| project_name | TEXT | 项目名称 |  |
| project_code | TEXT | 项目编号 |  |
| project_highlights | TEXT | 项目亮点 |  |
| project_type | TEXT | 项目类型 |  |
| transfer_min_price | TEXT | 转让底价 |  |
| asset_source | TEXT | 资产来源 |  |
| has_collateral | TEXT | 标的是否存在抵押物情况 |  |
| has_preemptive_right_intent | TEXT | 权利人是否有意向行使优先购买权 |  |
| equipment_name | TEXT | 机械设备名称 |  |
| equipment_location | TEXT | 机械设备所在地 |  |
| inventory_name | TEXT | 存货名称 |  |
| inventory_location | TEXT | 存货所在地 |  |
| vehicle_model | TEXT | 交通运输工具型号 |  |
| claim_name | TEXT | 债权名称 |  |
| other_asset_name | TEXT | 名称 |  |
| project_status | TEXT | 项目状态 |  |
| transferor_or_financier | TEXT | 转让方/融资方（招商主体） |  |
| reference_price | TEXT | 参考价格 |  |
| region_name | TEXT | 所在地区 |  |
| project_basic_info | TEXT | 项目基本信息 |  |
| audit_year | TEXT | 年度 |  |
| audit_revenue | TEXT | 年度审计报告营业收入（万元） |  |
| audit_operating_profit | TEXT | 年度审计报告营业利润（万元） |  |
| audit_net_profit | TEXT | 年度审计报告净利润（万元） |  |
| audit_total_assets | TEXT | 年度审计报告资产总计（万元） |  |
| audit_total_liabilities | TEXT | 年度审计报告负债总计（万元） |  |
| audit_equity | TEXT | 年度审计报告所有者权益 |  |
| audit_agency | TEXT | 审计机构 |  |
| financial_stmt_date | TEXT | 财务报表出具时间 |  |
| financial_stmt_revenue | TEXT | 财务报表营业收入（万元） |  |
| financial_stmt_operating_profit | TEXT | 财务报表营业利润（万元） |  |
| financial_stmt_net_profit | TEXT | 财务报表净利润（万元） |  |
| financial_stmt_total_assets | TEXT | 财务报表资产总计（万元） |  |
| financial_stmt_total_liabilities | TEXT | 财务报表负债总计（万元） |  |
| financial_stmt_equity | TEXT | 财务报表所有者权益 |  |
| track_tags | TEXT | 赛道标签 |  |
| trending_tags | TEXT | 热点标签 |  |
| listed_tags | TEXT | 挂牌标签 |  |
| created_at | TIMESTAMP | 创建时间 | 系统自动维护 |
| updated_at | TIMESTAMP | 更新时间 | 系统自动维护 |

### 房屋出租表 (property_rental)

| 字段名 | 字段类型 | 中文名称 | 备注 |
|--------|----------|----------|------|
| id | BIGINT | 主键ID | 主键ID，自增 |
| project_name | TEXT | 项目名称 |  |
| project_code | TEXT | 项目编号 |  |
| project_highlights | TEXT | 项目亮点 |  |
| project_type | TEXT | 项目类型 |  |
| asset_name | TEXT | 标的名称 |  |
| asset_property_type | TEXT | 标的物业类型 |  |
| asset_building_area_sqm | TEXT | 标的建筑面积（平方米） |  |
| listing_price_cny | TEXT | 挂牌价格（元） |  |
| listing_price_unit | TEXT | 挂牌价格单位 |  |
| asset_location | TEXT | 标的位置 |  |
| asset_service_life_years | TEXT | 标的使用年限 |  |
| asset_current_status_desc | TEXT | 标的现状描述 |  |
| lessor_name | TEXT | 出租方名称 |  |
| rent_area_sqm | TEXT | 出租面积 |  |
| house_location | TEXT | 出租房屋基本情况_坐落位置 |  |
| house_current_status | TEXT | 房屋使用现状 |  |
| building_area_sqm | TEXT | 建筑面积（平方米） |  |
| has_priority_lease_right | TEXT | 是否存在优先承租权 |  |
| land_location | TEXT | 出租土地基本情况_坐落位置 |  |
| land_certificate_number | TEXT | 土地证号 |  |
| land_area_sqm | TEXT | 土地面积（平方米） |  |
| usage | TEXT | 用途 |  |
| type | TEXT | 类型 |  |
| service_life_years | TEXT | 使用年限 |  |
| intended_rent_area_sqm | TEXT | 拟出租面积（平方米） |  |
| lease_term | TEXT | 租赁期 |  |
| transfer_or_financing_party | TEXT | 转让方/融资方（招商主体） |  |
| reference_price | TEXT | 参考价格 |  |
| location_name | TEXT | 所在地区 |  |
| project_basic_info | TEXT | 项目基本信息 |  |
| project_status | TEXT | 项目状态 |  |
| asset_category_name | TEXT | 资产分类名称 |  |
| house_label_code | TEXT | 房源标签 |  |
| community_name | TEXT | 所属小区 |  |
| house_layout | TEXT | 房源户型 |  |
| floor_number | TEXT | 所在楼层 |  |
| total_floors | TEXT | 总楼层 |  |
| house_orientation | TEXT | 房源朝向 |  |
| decoration_status | TEXT | 装修情况 |  |
| has_elevator | TEXT | 配备电梯 |  |
| heating_method | TEXT | 供暖方式 |  |
| house_features | TEXT | 房源特色 |  |
| elevator_type | TEXT | 电梯类型 |  |
| has_parking | TEXT | 停车场 |  |
| parking_space_type | TEXT | 车位类型 |  |
| has_charging_station | TEXT | 充电桩 |  |
| listed_tags | TEXT | 挂牌标签 |  |
| created_at | TIMESTAMP | 创建时间 | 系统自动维护 |
| updated_at | TIMESTAMP | 更新时间 | 系统自动维护 |

### 房屋土地表 (property_land)

| 字段名 | 字段类型 | 中文名称 | 备注 |
|--------|----------|----------|------|
| id | BIGINT | 主键ID | 主键ID，自增 |
| project_name | TEXT | 项目名称 |  |
| project_code | TEXT | 项目编号 |  |
| project_highlights | TEXT | 项目亮点 |  |
| project_type | TEXT | 项目类型 |  |
| asset_name | TEXT | 标的名称 |  |
| asset_property_type | TEXT | 标的物业类型 |  |
| asset_building_area | TEXT | 标的建筑面积 |  |
| asset_transfer_amount | TEXT | 标的转让金额 |  |
| asset_transfer_amount_min | TEXT | 标的转让金额（万元）-最小值 |  |
| asset_transfer_amount_max | TEXT | 标的转让金额（万元）-最大值 |  |
| asset_transfer_amount_fixed | TEXT | 标的转让金额（万元）-固定值 |  |
| asset_location | TEXT | 标的位置 |  |
| asset_unit_price_per_sqm | TEXT | 标的单价元/平米 |  |
| asset_service_life_years | TEXT | 标的使用年限 |  |
| asset_current_status_desc | TEXT | 标的现状描述 |  |
| category_name | TEXT | 分类 |  |
| disclosure_content | TEXT | 披露内容 |  |
| transfer_min_price | TEXT | 转让底价 |  |
| asset_source | TEXT | 资产来源 |  |
| has_mortgage | TEXT | 标的是否存在抵押物情况 |  |
| has_preemptive_right_intent | TEXT | 权利人是否有意向行使优先购买权 |  |
| house_location | TEXT | 房屋建筑物坐落位置 |  |
| current_house_use | TEXT | 房屋建筑物目前用途 |  |
| house_facilities | TEXT | 房屋建筑物附属设施 |  |
| house_building_area_sqm | TEXT | 建筑面积（平方米） |  |
| house_service_life_years | TEXT | 房屋建筑物使用年限（年） |  |
| house_used_years | TEXT | 房屋建筑物已用年限（年） |  |
| land_location | TEXT | 土地坐落位置 |  |
| land_area_sqm | TEXT | 土地面积 |  |
| land_use | TEXT | 土地用途 |  |
| land_type | TEXT | 土地类型 |  |
| land_service_life_years | TEXT | 土地使用年限 |  |
| land_used_years | TEXT | 土地已用年限 |  |
| land_has_mortgage | TEXT | 土地是否有抵押 |  |
| seller_name | TEXT | 转让方名称 |  |
| approval_unit_name | TEXT | 批准单位名称 |  |
| payment_method | TEXT | 价款支付方式 |  |
| project_status | TEXT | 项目状态 |  |
| asset_category_name | TEXT | 资产分类名称 |  |
| house_label_code | TEXT | 房源标签 |  |
| community_name | TEXT | 所属小区 |  |
| house_layout | TEXT | 房源户型 |  |
| floor_number | TEXT | 所在楼层 |  |
| total_floors | TEXT | 总楼层 |  |
| house_orientation | TEXT | 房源朝向 |  |
| decoration_status | TEXT | 装修情况 |  |
| has_elevator | TEXT | 配备电梯 |  |
| heating_method | TEXT | 供暖方式 |  |
| house_features | TEXT | 房源特色 |  |
| elevator_type | TEXT | 电梯类型 |  |
| has_parking | TEXT | 停车场 |  |
| parking_space_type | TEXT | 车位类型 |  |
| has_charging_station | TEXT | 充电桩 |  |
| created_at | TIMESTAMP | 创建时间 | 系统自动维护 |
| updated_at | TIMESTAMP | 更新时间 | 系统自动维护 |

### 文旅体育表 (culture_tourism_sports)

| 字段名 | 字段类型 | 中文名称 | 备注 |
|--------|----------|----------|------|
| id | BIGINT | 主键ID | 主键ID，自增 |
| project_name | TEXT | 项目名称 |  |
| project_code | TEXT | 项目编号 |  |
| project_highlights | TEXT | 项目亮点 |  |
| project_type | TEXT | 项目类型 |  |
| transfer_or_financing_party | TEXT | 转让方/融资方（招商主体） |  |
| reference_price | TEXT | 参考价格 |  |
| location_region | TEXT | 所在地区 |  |
| project_basic_info | TEXT | 项目基本信息 |  |
| audit_year | TEXT | 年度 |  |
| audit_revenue_million | TEXT | 年度审计报告营业收入（万元） |  |
| audit_operating_profit_million | TEXT | 年度审计报告营业利润（万元） |  |
| audit_net_profit_million | TEXT | 年度审计报告净利润（万元） |  |
| audit_total_assets_million | TEXT | 年度审计报告资产总计（万元） |  |
| audit_total_liabilities_million | TEXT | 年度审计报告负债总计（万元） |  |
| audit_equity | TEXT | 年度审计报告所有者权益 |  |
| audit_agency | TEXT | 审计机构 |  |
| statement_date | TEXT | 财务报表出具时间 |  |
| statement_revenue_million | TEXT | 财务报表营业收入（万元） |  |
| statement_operating_profit_million | TEXT | 财务报表营业利润（万元） |  |
| statement_net_profit_million | TEXT | 财务报表净利润（万元） |  |
| statement_total_assets_million | TEXT | 财务报表资产总计（万元） |  |
| statement_total_liabilities_million | TEXT | 财务报表负债总计（万元） |  |
| statement_equity | TEXT | 财务报表所有者权益 |  |
| project_status | TEXT | 项目状态 |  |
| track_tags | TEXT | 赛道标签 |  |
| trending_tags | TEXT | 热点标签 |  |
| listed_tags | TEXT | 挂牌标签 |  |
| created_at | TIMESTAMP | 创建时间 | 系统自动维护 |
| updated_at | TIMESTAMP | 更新时间 | 系统自动维护 |

### 股权增资表 (equity_increase)

| 字段名 | 字段类型 | 中文名称 | 备注 |
|--------|----------|----------|------|
| id | BIGINT | 主键ID | 主键ID，自增 |
| project_name | TEXT | 项目名称 |  |
| project_status | TINYINT(1) | 项目状态 |  |
| project_code | TEXT | 项目编号 |  |
| project_highlights | TEXT | 项目亮点 |  |
| project_type | TEXT | 项目类型 |  |
| financing_region | TEXT | 融资方所在地区 |  |
| intended_raise_amount | TEXT | 拟募集资金金额 |  |
| intended_investor_count | TEXT | 拟征集投资方数量 |  |
| intended_shareholding_ratio | TEXT | 拟募集资金对应持股比例或股份数 |  |
| financing_party_name | TEXT | 融资方名称 |  |
| paid_up_capital | TEXT | 实收资本 |  |
| business_scope | TEXT | 经营范围 |  |
| audit_year | TEXT | 审计报告年度 |  |
| audit_total_assets | TEXT | 年度审计报告资产总计（万元） |  |
| audit_total_liabilities | TEXT | 年度审计报告负债总计（万元） |  |
| audit_total_equity | TEXT | 年度审计报告所有者权益（万元） |  |
| audit_net_profit | TEXT | 年度审计报告净利润（万元） |  |
| audit_revenue | TEXT | 年度审计报告营业收入（万元） |  |
| financial_statement_date | TEXT | 财务数据日期 |  |
| financial_total_assets | TEXT | 财务数据资产总计（万元） |  |
| financial_total_liabilities | TEXT | 财务数据负债总计（万元） |  |
| financial_total_equity | TEXT | 财务数据所有者权益（万元） |  |
| financial_net_profit | TEXT | 财务数据净利润（万元） |  |
| financial_revenue | TEXT | 营业收入（万元） |  |
| state_invested_enterprise_or_department | TEXT | 国家出资企业或主管部门名称 |  |
| other_disclosure_items | TEXT | 其他披露事项 |  |
| investor_eligibility_criteria | TEXT | 投资方资格条件 |  |
| capital_increase_conditions | TEXT | 增资条件 |  |
| financing_main_business | TEXT | 融资方主营业务介绍 |  |
| intended_financing_amount | TEXT | 拟融资金额 |  |
| intended_financing_amount_min | TEXT | 拟融资金额（万元）-最小值 |  |
| intended_financing_amount_max | TEXT | 拟融资金额（万元）-最大值 |  |
| intended_financing_amount_fixed | TEXT | 拟融资金额（万元）-固定值 |  |
| intended_equity_release_ratio | TEXT | 拟释放股权比例 |  |
| intended_equity_release_ratio_min | TEXT | 拟释放股权比例（%）-最小值 |  |
| intended_equity_release_ratio_max | TEXT | 拟释放股权比例（%）-最大值 |  |
| intended_equity_release_ratio_fixed | TEXT | 拟释放股权比例（%）-固定值 |  |
| intended_investor_count_min | TEXT | 拟征集投资人（个）-最小值 |  |
| intended_investor_count_max | TEXT | 拟征集投资人（个）-最大值 |  |
| intended_investor_count_fixed | TEXT | 拟征集投资人（个）-固定值 |  |
| original_shareholder_participation | TEXT | 原股东是否参与增资 |  |
| financing_company_name | TEXT | 融资企业名称 |  |
| financing_company_registration_place | TEXT | 融资企业注册地 |  |
| other_conditions | TEXT | 其他情况 |  |
| transferor_or_financing_party | TEXT | 转让方/融资方（招商主体） |  |
| reference_price | TEXT | 参考价格 |  |
| location | TEXT | 所在地区 |  |
| project_basic_info | TEXT | 项目基本信息 |  |
| audit_agency | TEXT | 年度审计报告净利润（万元） |  |
| track_tags | TEXT | 赛道标签 |  |
| trending_tags | TEXT | 热点标签 |  |
| listed_tags | TEXT | 挂牌标签 |  |
| top10_shareholder_names | TEXT | 股东名称（前十位） |  |
| shareholding_percentage | TEXT | 持有比例 |  |
| created_at | TIMESTAMP | 创建时间 | 系统自动维护 |
| updated_at | TIMESTAMP | 更新时间 | 系统自动维护 |

### 股权转让表 (equity_transfer)

| 字段名 | 字段类型 | 中文名称 | 备注 |
|--------|----------|----------|------|
| id | BIGINT | 主键ID | 主键ID，自增 |
| project_name | TEXT | 项目名称 |  |
| project_status | TEXT | 项目状态 |  |
| project_code | TEXT | 项目编号 |  |
| project_highlights | TEXT | 项目亮点 |  |
| project_type | TEXT | 项目类型 |  |
| transfer_share_ratio | TEXT | 转让股权比例 |  |
| transfer_share_ratio_min | TEXT | 转让股权比例（%）—最小值 |  |
| transfer_share_ratio_max | TEXT | 转让股权比例（%）—最大值 |  |
| transfer_share_ratio_fixed | TEXT | 转让股权比例（%）-固定值 |  |
| transfer_price | TEXT | 转让股权价格 |  |
| transfer_price_min | TEXT | 转让股权价格（万元）—最小值 |  |
| transfer_price_max | TEXT | 转让股权价格（万元）—最大值 |  |
| transfer_price_fixed | TEXT | 转让股权价格（万元）-固定值 |  |
| target_company_industry | TEXT | 标的企业所在行业 |  |
| target_company_business_scope | TEXT | 标的企业经营范围 |  |
| target_company_name | TEXT | 标的企业名称 |  |
| target_company_main_business | TEXT | 标的企业主营业务介绍 |  |
| company_name | TEXT | 企业名称 |  |
| company_registered_capital | TEXT | 企业注册资本 |  |
| company_registered_location | TEXT | 企业注册地 |  |
| other_company_info | TEXT | 其他情况 |  |
| intended_transfer_ratio | TEXT | 拟转让比例 |  |
| registered_location | TEXT | 注册地（住所） |  |
| registered_capital | TEXT | 注册资本 |  |
| economic_type | TEXT | 经济类型 |  |
| business_scope | TEXT | 经营范围 |  |
| control_right_transfer | TEXT | 导致标的企业的实际控制权发生转移 |  |
| audit_year | TEXT | 年度审计报告年度 |  |
| audit_revenue | TEXT | 年度审计报告营业收入 |  |
| audit_operating_profit | TEXT | 年度审计报告营业利润 |  |
| audit_net_profit | TEXT | 年度审计报告净利润 |  |
| audit_total_assets | TEXT | 年度审计报告资产总计 |  |
| audit_total_liabilities | TEXT | 年度审计报告负债总计 |  |
| audit_equity | TEXT | 年度审计报告所有者权益 |  |
| audit_agency | TEXT | 年度审计报告审计机构 |  |
| recent_fs_date | TEXT | 近期财务报表报表日期 |  |
| recent_fs_revenue | TEXT | 近期财务报表营业收入 |  |
| recent_fs_operating_profit | TEXT | 近期财务报表营业利润 |  |
| recent_fs_net_profit | TEXT | 近期财务报表净利润 |  |
| recent_fs_total_assets | TEXT | 近期财务报表资产总计 |  |
| recent_fs_total_liabilities | TEXT | 近期财务报表负债总计 |  |
| recent_fs_equity | TEXT | 近期财务报表所有者权益 |  |
| ownership_ratio | TEXT | 持有产（股）权比例 |  |
| intended_ownership_transfer_ratio | TEXT | 拟转让产（股）权比例 |  |
| competent_department_name | TEXT | 国家出资企业或主管部门名称 |  |
| transfer_base_price | TEXT | 转让底价 |  |
| other_transfer_conditions | TEXT | 与转让相关的其他条件 |  |
| transferee_qualification | TEXT | 受让方资格条件 |  |
| reference_price | TEXT | 参考价格 |  |
| transferor_or_financier | TEXT | 转让方/融资方（招商主体） |  |
| project_basic_info | TEXT | 项目基本信息 |  |
| track_tags | TEXT | 赛道标签 |  |
| trending_tags | TEXT | 热点标签 |  |
| listed_tags | TEXT | 挂牌标签 |  |
| region | TEXT | 所在地区 |  |
| transferor_name | TEXT | 转让方名称 |  |
| created_at | TIMESTAMP | 创建时间 | 系统自动维护 |
| updated_at | TIMESTAMP | 更新时间 | 系统自动维护 |
