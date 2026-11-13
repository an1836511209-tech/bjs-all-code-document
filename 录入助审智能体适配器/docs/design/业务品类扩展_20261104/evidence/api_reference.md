**北交所人工智能中台二期项目\
API接口说明文档**

目录

[第一章 智能体提供接口 [3](#第一章-智能体提供接口)](#第一章-智能体提供接口)

[1. 录入助审智能体接口 [3](#录入助审智能体接口)](#录入助审智能体接口)

[1.1 基本信息 [3](#基本信息)](#基本信息)

[1.2 接口列表 [6](#接口列表)](#接口列表)

[1.2.1 文件质量检测 [6](#heading_125)](#heading_125)

[请求参数（Body） [6](#heading_126)](#heading_126)

[1.2.2 文件分类(待更新) [10](#heading_131)](#heading_131)

[请求参数（Body） [10](#_Toc31535)](#_Toc31535)

[1.2.3 同步字段提取 [13](#heading_139)](#heading_139)

[请求参数（Body） [13](#_Toc25104)](#_Toc25104)

[1.2.4 同步规则审核 [19](#heading_145)](#heading_145)

[请求参数（Body） [20](#heading_146)](#heading_146)

[响应参数（字段响应） [23](#_Toc16702)](#_Toc16702)

[响应示例 — 成功（字段审核审核明细已节选） [35](#_Toc28565)](#_Toc28565)

[响应参数（文件审核） [39](#_Toc27488)](#_Toc27488)

[响应示例 — 成功（字段审核审核明细已节选） [40](#_Toc31168)](#_Toc31168)

[1.2.5 查询任务状态 [43](#_Toc18126)](#_Toc18126)

[请求参数（Body） [43](#_Toc16073)](#_Toc16073)

[1.2.6 取消任务 [50](#heading_158)](#heading_158)

[请求参数（Body） [50](#heading_159)](#heading_159)

[1.2.7 预览服务 [51](#heading_164)](#heading_164)

[请求参数（Body） [51](#heading_165)](#heading_165)

[2. 通用一句话找项目接口 [52](#通用一句话找项目接口)](#通用一句话找项目接口)

[2.1 基本信息 [52](#基本信息-1)](#基本信息-1)

[2.1 接口列表 [53](#接口列表-1)](#接口列表-1)

[2.1.1 智能对话(流式) [53](#_Toc7852)](#_Toc7852)

[请求参数（Body） [53](#_Toc18615)](#_Toc18615)

[响应参数 [54](#_Toc1950)](#_Toc1950)

[2.1.2 重新生成 [56](#_Toc31299)](#_Toc31299)

[请求参数（Body） [57](#_Toc8434)](#_Toc8434)

[响应参数 [58](#_Toc19198)](#_Toc19198)

[2.1.3 删除对话记录 [58](#_Toc25796)](#_Toc25796)

[请求参数（Body） [58](#_Toc14623)](#_Toc14623)

[响应参数 [59](#_Toc23224)](#_Toc23224)

[2.1.4 总结历史会话标题 [60](#_Toc20193)](#_Toc20193)

[请求参数（Body） [60](#_Toc2227)](#_Toc2227)

[响应参数 [61](#_Toc29898)](#_Toc29898)

# 第一章 智能体提供接口

## 1. 录入助审智能体接口

### **1.1 基本信息**

**请求头**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">HTTP<br />
Content-Type: application/json</td>
</tr>
</tbody>
</table>

**统一响应格式（业务接口）**

大部分接口返回如下结构：

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 200,<br />
"message": "success",<br />
"trace_id": "trace_20251022100001",<br />
"timestamp": "2025-10-22T10:00:00Z",<br />
"data": {}<br />
}</td>
</tr>
</tbody>
</table>

**错误响应格式**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 400,<br />
"message": "Bad Request",<br />
"trace_id": "trace_20251022100002",<br />
"timestamp": "2025-10-22T10:00:05Z",<br />
"error": {<br />
"error_code": "COMMON_002",<br />
"error_message": "缺少必填字段",<br />
"details": [<br />
{ "field": "files", "message": "files字段不能为空" }<br />
]<br />
}<br />
}</td>
</tr>
</tbody>
</table>

**业务类型枚举（extraction_type / audit_type）**

|              |              |
|:-------------|:-------------|
| 枚举值       | 说明         |
| 有纸大宗实物 | 大宗有纸项目 |
| 无纸大宗实物 | 大宗无纸项目 |
| 有纸小宗实物 | 小宗有纸项目 |
| 无纸小宗实物 | 小宗无纸项目 |

**文件类型字典（file_type）**

|  |  |
|:---|:---|
| 字典值 | 说明 |
| info_disclosure_application | 信息披露申请书 |
| evaluation_report | 评估报告或其他定价文件 |
| evaluation_filing | 评估备案表/核准文件 |
| internal_decision | 内部决议或有权批准机构决策文件 |
| business_license | 营业执照/事业单位法人证书/身份证 |
| asset_list | 资产清单 |
| inspection_management | 踏勘承诺函 |
| property_certificate | 房屋产权所有证/不动产权证 |
| land_use_certificate | 国有土地使用证 |
| land_use_contract | 国有建设用地使用权出让合同 |
| vehicle_certificate | 行驶证/机动车登记证书（限机动车） |
| ship_certificate | 船舶所有权证书/船舶检验证书/船舶国籍证明（限船舶） |
| aircraft_certificate | 适航证/电台执照/国籍登记证（限飞机） |
| patent_certificate | 专利证书 |
| central_asset_disposal_authorization | 中央行政事业单位国有资产处置委托书 |
| central_asset_transfer_application | 中央行政事业单位国有资产转让申请表 |
| central_asset_receipt | 中央行政事业单位国有资产接收单 |
| asset_disposal_application | 行政事业单位国有资产处置申请表 |
| asset_receipt_confirmation | 行政事业单位国有资产接收确认书 |
| asset_confirmation_form | 行政事业单位国有资产确认单 |
| project_progress_record | 项目进度记录表 |
| other_documents | 其他文件（无法识别时默认类型） |

### **1.2 接口列表**

<span id="heading_125" class="anchor"></span>**1.2.1 文件质量检测**

**接口地址**

- 智能体：POST /api/v1/file/quality-check

**接口描述**：同步检测上传附件的质量，包括清晰度、分辨率、遮挡检测。支持 PDF 和图片格式。

<span id="heading_126" class="anchor"></span>**请求参数（Body）**

|            |        |      |                              |
|:-----------|:-------|:-----|:-----------------------------|
| 参数名     | 类型   | 必填 | 说明                         |
| files      | Array  | 是   | 待检测文件列表               |
| request_id | String | 否   | 请求唯一标识，用于幂等性控制 |

**files 数组元素：**

|             |        |      |                                   |
|:------------|:-------|:-----|:----------------------------------|
| 参数名      | 类型   | 必填 | 说明                              |
| file_url    | String | 否\* | 文件 URL（与 file_stream 二选一） |
| file_stream | String | 否\* | 文件流，Base64 或 Data URI        |
| file_name   | String | 是   | 文件名称                          |
| file_type   | String | 是   | 业务文件类型（见文件类型字典）    |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">HTTP<br />
POST /api/v1/file/quality-check HTTP/1.1<br />
Content-Type: application/json<br />
<br />
{<br />
"files": [<br />
{<br />
"file_url": "https://example.com/files/application.pdf",<br />
"file_name": "信息披露申请书.pdf",<br />
"file_type": "info_disclosure_application"<br />
},<br />
{<br />
"file_stream": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",<br />
"file_name": "房屋所有权证.png",<br />
"file_type": "property_certificate"<br />
}<br />
],<br />
"request_id": "req_20251022100001"<br />
}</td>
</tr>
</tbody>
</table>

**响应参数（data）**

|        |       |              |
|:-------|:------|:-------------|
| 参数名 | 类型  | 说明         |
| data   | Array | 检测结果列表 |

**data 数组元素：**

|                |        |                                     |
|:---------------|:-------|:------------------------------------|
| 参数名         | 类型   | 说明                                |
| file_id        | String | 文件 ID                             |
| file_name      | String | 文件名称                            |
| file_type      | String | 业务文件类型                        |
| file_url       | String | 文件 URL                            |
| quality_status | String | 质量状态：passed / warning / failed |
| quality_result | Object | 质量检测详细结果                    |
| message        | String | 检测结果消息                        |

**quality_result 对象：**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| clarity | String | 清晰度：passed / warning / failed |
| clarity_score | Number | 清晰度分数（拉普拉斯方差，越高越好，通常 \>500 为良好） |
| resolution | String | 分辨率：passed / warning / failed |
| resolution_value | String | 分辨率值，如 1920x1080 |
| occlusion | String | 遮挡：passed / warning / failed |
| occlusion_score | Number | 遮挡分数（0-1，越低越好） |

**响应示例 — 成功**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 200,<br />
"message": "success",<br />
"trace_id": "trace_20251022100001",<br />
"timestamp": "2025-10-22T10:00:00Z",<br />
"data": [<br />
{<br />
"file_id": "file_20251022100001",<br />
"file_name": "信息披露申请书.pdf",<br />
"file_type": "info_disclosure_application",<br />
"quality_status": "passed",<br />
"quality_result": {<br />
"clarity": "passed",<br />
"clarity_score": 725.5,<br />
"resolution": "passed",<br />
"resolution_value": "2480x3508",<br />
"occlusion": "passed",<br />
"occlusion_score": 0.01<br />
},<br />
"message": "文件质量校验通过"<br />
},<br />
{<br />
"file_id": "file_20251022100002",<br />
"file_name": "房屋所有权证.png",<br />
"file_type": "property_certificate",<br />
"quality_status": "warning",<br />
"quality_result": {<br />
"clarity": "failed",<br />
"clarity_score": 320.0,<br />
"resolution": "passed",<br />
"resolution_value": "1920x1080",<br />
"occlusion": "passed",<br />
"occlusion_score": 0.03<br />
},<br />
"message": "图片清晰度不足，请重新上传清晰图片文件"<br />
}<br />
]<br />
}</td>
</tr>
</tbody>
</table>

**响应示例 — 参数错误**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 400,<br />
"message": "Bad Request",<br />
"trace_id": "trace_20251022100002",<br />
"timestamp": "2025-10-22T10:00:05Z",<br />
"error": {<br />
"error_code": "COMMON_002",<br />
"error_message": "缺少必填字段",<br />
"details": [<br />
{ "field": "files", "message": "files字段不能为空" }<br />
]<br />
}<br />
}</td>
</tr>
</tbody>
</table>

<span id="heading_131" class="anchor"></span>**1.2.2 文件分类(待更新)**

**接口地址**

- 智能体：POST /api/v1/file/classification

**接口描述**：对上传文件进行智能分类，返回对应的 file_type 枚举值。支持 PDF、Word、图片、Excel、CSV。

<span id="_Toc31535" class="anchor"></span>**请求参数（Body）**

|            |        |      |                |
|:-----------|:-------|:-----|:---------------|
| 参数名     | 类型   | 必填 | 说明           |
| files      | Array  | 是   | 待分类文件列表 |
| request_id | String | 否   | 请求唯一标识   |

**files 数组元素：**

|           |        |      |          |
|:----------|:-------|:-----|:---------|
| 参数名    | 类型   | 必填 | 说明     |
| file_url  | String | 是   | 文件 URL |
| file_name | String | 是   | 文件名称 |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">HTTP<br />
POST /api/v1/file/classification HTTP/1.1<br />
Content-Type: application/json<br />
<br />
{<br />
"files": [<br />
{<br />
"file_url": "https://example.com/files/doc1.pdf",<br />
"file_name": "信息披露申请书.pdf"<br />
},<br />
{<br />
"file_url": "https://example.com/files/doc2.docx",<br />
"file_name": "内部决议.docx"<br />
}<br />
],<br />
"request_id": "req_20251114100001"<br />
}</td>
</tr>
</tbody>
</table>

**响应参数（data）**

|                    |         |                  |
|:-------------------|:--------|:-----------------|
| 参数名             | 类型    | 说明             |
| results            | Array   | 分类结果列表     |
| processing_time_ms | Integer | 处理时间（毫秒） |

**results 数组元素：**

|           |        |                        |
|:----------|:-------|:-----------------------|
| 参数名    | 类型   | 说明                   |
| file_name | String | 文件名称               |
| file_url  | String | 文件 URL               |
| file_type | String | 分类后的文件类型枚举值 |

**响应示例 — 成功**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 200,<br />
"message": "success",<br />
"trace_id": "trace_20251114100001",<br />
"timestamp": "2025-11-14T10:00:00Z",<br />
"data": {<br />
"results": [<br />
{<br />
"file_name": "信息披露申请书.pdf",<br />
"file_url": "https://example.com/files/doc1.pdf",<br />
"file_type": "info_disclosure_application"<br />
},<br />
{<br />
"file_name": "内部决议.docx",<br />
"file_url": "https://example.com/files/doc2.docx",<br />
"file_type": "internal_decision"<br />
}<br />
],<br />
"processing_time_ms": 1500<br />
}<br />
}</td>
</tr>
</tbody>
</table>

<span id="heading_139" class="anchor"></span>**1.2.3 同步字段提取**

**接口地址**

- 智能体：POST /api/v1/extraction/sync

**接口描述**：从多个附件中同步提取字段信息。若在 timeout（默认 1000ms）内完成，直接返回完整提取结果（status 为 success/partial/failed）；若超时，返回 task_id 及 status=pending 的占位响应（results 为空，message 为“任务处理中，请稍后查询结果”），任务在后台继续执行，客户端需通过 GET /api/v1/task/{task_id} 轮询获取最终结果。

<span id="_Toc25104" class="anchor"></span>**请求参数（Body）**

|                 |         |      |                                   |
|:----------------|:--------|:-----|:----------------------------------|
| 参数名          | 类型    | 必填 | 说明                              |
| extraction_type | String  | 是   | 业务类型（见业务类型枚举）        |
| files           | Array   | 是   | 待提取文件列表                    |
| task_id         | String  | 否   | 任务 ID（继续未完成任务）         |
| rule_config_id  | String  | 否   | 规则配置 ID（不传则使用默认规则） |
| timeout         | Integer | 否   | 超时时间（毫秒），默认 1000       |
| request_id      | String  | 否   | 请求唯一标识                      |

**files 数组元素：**

|                   |         |      |                  |
|:------------------|:--------|:-----|:-----------------|
| 参数名            | 类型    | 必填 | 说明             |
| file_url          | String  | 是   | 文件 URL         |
| file_name         | String  | 是   | 文件名称         |
| file_type         | String  | 是   | 业务文件类型     |
| file_content_hash | String  | 否   | 文件内容 MD5     |
| file_size         | Integer | 否   | 文件大小（字节） |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">HTTP<br />
POST /api/v1/extraction/sync HTTP/1.1<br />
Content-Type: application/json<br />
<br />
{<br />
"extraction_type": "有纸大宗实物",<br />
"files": [<br />
{<br />
"file_url": "https://example.com/files/application.pdf",<br />
"file_name": "信息披露申请书.pdf",<br />
"file_type": "info_disclosure_application",<br />
"file_content_hash": "5d41402abc4b2a76b9719d911017c592",<br />
"file_size": 1024000<br />
},<br />
{<br />
"file_url": "https://example.com/files/certificate.pdf",<br />
"file_name": "房屋所有权证.pdf",<br />
"file_type": "property_certificate",<br />
"file_content_hash": "7b8f3d4e9c1a2f5b6e0d8c7a4f3e2d1b",<br />
"file_size": 2048000<br />
}<br />
],<br />
"rule_config_id": "rule_dzswv10",<br />
"timeout": 300000,<br />
"request_id": "req_20251022100002"<br />
}</td>
</tr>
</tbody>
</table>

**响应参数（data）**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| request_id | String | 请求 ID |
| task_id | String | 任务 ID（异步或超时时返回） |
| status | String | 任务状态：success / partial / pending / failed / timeout |
| extraction_type | String | 业务类型 |
| rule_config_id | String | 实际使用的规则配置 ID |
| from_cache | Boolean | 是否来自缓存 |
| cached_task_id | String | 缓存来源任务 ID |
| results | Array | 字段提取结果列表 |
| total_fields | Integer | 总字段数 |
| success_count | Integer | 成功字段数 |
| pending_count | Integer | 待确认字段数 |
| failed_count | Integer | 失败字段数 |
| processing_time_ms | Integer | 处理时间（毫秒） |
| parsed_files | Object | 解析文件内容快照 |

**results 数组元素：**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| field_id | String | 字段 ID |
| field_name | String | 字段名称（系统字段名） |
| field_type | String | 字段类型：text / single_choice / multiple_choice |
| field_status | String | 字段状态：success / pending / failed |
| values | Array | 多来源提取值列表 |
| error_message | String | 错误信息 |
| inconsistent_values | Array | 多来源值不一致时的值列表 |
| extraction_rule | Object | 对应提取规则信息 |

**values 数组元素：**

|                   |              |                            |
|:------------------|:-------------|:---------------------------|
| 参数名            | 类型         | 说明                       |
| source_file_type  | String       | 来源文件类型               |
| source_file_name  | String       | 来源文件名                 |
| source_field_name | String       | 来源字段名                 |
| extracted_value   | String/Array | 提取值                     |
| extract_status    | String       | 提取状态：success / failed |
| confidence        | Number       | 置信度（0-1）              |
| sources           | Array        | 溯源信息列表               |

**sources 数组元素：**

|                   |         |                            |
|:------------------|:--------|:---------------------------|
| 参数名            | 类型    | 说明                       |
| source_file_type  | String  | 来源文件类型               |
| source_file_name  | String  | 来源文件名                 |
| source_field      | String  | 来源字段名                 |
| source_content    | String  | 来源内容                   |
| preview_image_url | String  | 预览图片 相对路径          |
| page_number       | Integer | 页码（从 1 开始）          |
| coordinates       | Object  | 坐标 {x, y, width, height} |
| confidence        | Number  | 置信度（0-1）              |
| cross_page_info   | Object  | 跨页信息（可选）           |
| regions           | Array   | 高亮区域列表（可选）       |

**响应示例 — 成功（字段明细已节选）**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 200,<br />
"message": "success",<br />
"trace_id": "trace_20251022100003",<br />
"timestamp": "2025-10-22T10:05:30Z",<br />
"data": {<br />
"request_id": "req_20251022100002",<br />
"task_id": null,<br />
"status": "success",<br />
"extraction_type": "有纸大宗实物",<br />
"rule_config_id": "rule_dzswv10",<br />
"from_cache": false,<br />
"results": [<br />
{<br />
"field_id": "field_001",<br />
"field_name": "坐落位置",<br />
"field_type": "text",<br />
"field_status": "success",<br />
"values": [<br />
{<br />
"source_file_type": "info_disclosure_application",<br />
"source_file_name": "信息披露申请书.pdf",<br />
"source_field_name": "坐落位置",<br />
"extracted_value": "北京市朝阳区建国路1号国贸大厦A座10层",<br />
"extract_status": "success",<br />
"confidence": 0.96,<br />
"sources": [<br />
{<br />
"source_file_type": "info_disclosure_application",<br />
"source_file_name": "信息披露申请书.pdf",<br />
"source_field": "坐落位置",<br />
"source_content": "坐落位置：北京市朝阳区建国路1号国贸大厦A座10层",<br />
"preview_image_url": "/api/v1/preview/files/highlights/batch_xxx.jpg",<br />
"page_number": 2,<br />
"coordinates": { "x": 120, "y": 450, "width": 400, "height": 30 },<br />
"confidence": 0.96<br />
}<br />
]<br />
}<br />
],<br />
"error_message": null,<br />
"inconsistent_values": null<br />
},<br />
{<br />
"field_id": "field_002",<br />
"field_name": "房屋面积",<br />
"field_type": "text",<br />
"field_status": "success",<br />
"values": [<br />
{<br />
"source_file_type": "property_certificate",<br />
"source_file_name": "房屋所有权证.pdf",<br />
"source_field_name": "建筑面积",<br />
"extracted_value": "150.5平方米",<br />
"extract_status": "success",<br />
"confidence": 0.98,<br />
"sources": [<br />
{<br />
"source_file_type": "property_certificate",<br />
"source_file_name": "房屋所有权证.pdf",<br />
"source_field": "建筑面积",<br />
"source_content": "建筑面积：150.5㎡",<br />
"preview_image_url": "/api/v1/preview/files/highlights/batch_xxx.jpg",<br />
"page_number": 1,<br />
"coordinates": { "x": 150, "y": 650, "width": 200, "height": 25 },<br />
"confidence": 0.98<br />
}<br />
]<br />
}<br />
],<br />
"error_message": null<br />
}<br />
],<br />
"total_fields": 97,<br />
"success_count": 85,<br />
"pending_count": 10,<br />
"failed_count": 2,<br />
"processing_time_ms": 5230<br />
}<br />
}</td>
</tr>
</tbody>
</table>

**响应示例 — 超时（返回 task_id）**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 200,<br />
"message": "success",<br />
"trace_id": "trace_20251022100004",<br />
"timestamp": "2025-10-22T10:10:00Z",<br />
"data": {<br />
"request_id": "req_20251022100002",<br />
"task_id": "extraction_abc123",<br />
"status": "pending",<br />
"extraction_type": "有纸大宗实物",<br />
"results": [],<br />
"total_fields": 0,<br />
"success_count": 0,<br />
"pending_count": 0,<br />
"failed_count": 0<br />
}<br />
}</td>
</tr>
</tbody>
</table>

<span id="heading_145" class="anchor"></span>**1.2.4 同步规则审核**

**接口地址**

- 智能体：POST /api/v1/audit/sync

**接口描述**：对用户确认的字段和附件进行规则审核，返回完整审核结果。支持字段审核、文件审核、人工审核。

<span id="heading_146" class="anchor"></span>**请求参数（Body）**

|                  |         |      |                                           |
|:-----------------|:--------|:-----|:------------------------------------------|
| 参数名           | 类型    | 必填 | 说明                                      |
| audit_type       | String  | 是   | 业务类型（见业务类型枚举）                |
| confirmed_fields | Array   | 是   | 用户确认后的字段列表                      |
| files            | Array   | 否   | 审核参考文件列表，纯字段逻辑审核可为 \[\] |
| task_id          | String  | 否   | 任务 ID                                   |
| rule_config_id   | String  | 否   | 规则配置 ID                               |
| timeout          | Integer | 否   | 超时时间（毫秒），默认 1000               |
| request_id       | String  | 否   | 请求唯一标识                              |
| trigger_type     | String  | 否   | 触发类型，如 kafka / hand                 |

**confirmed_fields 数组元素：**

|  |  |  |  |
|:---|:---|:---|:---|
| 参数名 | 类型 | 必填 | 说明 |
| field_name | String | 是 | 字段名称（系统字段名） |
| field_value | Any | 是 | 字段值（字符串、数字、对象、数组等） |
| field_type | String | 是 | 字段类型：text / number / single_choice / multiple_choice 等 |

**files 数组元素：**

|                   |         |      |                                         |
|:------------------|:--------|:-----|:----------------------------------------|
| 参数名            | 类型    | 必填 | 说明                                    |
| file_url          | String  | 是   | 文件 URL                                |
| file_name         | String  | 是   | 文件名称                                |
| file_type         | String  | 是   | 文件类型（FileType 枚举或中台类型代码） |
| file_content_hash | String  | 否   | 文件内容 MD5                            |
| file_size         | Integer | 否   | 文件大小（字节）                        |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>HTTP<br />
POST /api/v1/audit/sync HTTP/1.1<br />
Content-Type: application/json<br />
<br />
{</p>
<p>"audit_type": "有纸大宗实物",</p>
<p>"request_id": "test_case_001",</p>
<p>"confirmed_fields": [</p>
<p>{ "field_name": "YYZZSFCQ", "field_value": "是", "field_type": "text" },</p>
<p>{ "field_name": "BDSZDS", "field_value": "云南省", "field_type": "text" },</p>
<p>{ "field_name": "ZMJZ", "field_value": "368.580000", "field_type": "text" },</p>
<p>{ "field_name": "PLGGQ", "field_value": "10", "field_type": "text" },</p>
<p>{ "field_name": "ZRDJ", "field_value": "517.59", "field_type": "text" }</p>
<p>],</p>
<p>"files": [</p>
<p>{</p>
<p>"file_url": "https://example/信息披露申请书.pdf",</p>
<p>"file_name": "信息披露申请书.pdf",</p>
<p>"file_type": "info_disclosure_application"</p>
<p>},</p>
<p>{</p>
<p>"file_url": "https://example/营业执照.pdf",</p>
<p>"file_name": "营业执照.pdf",</p>
<p>"file_type": "business_license"</p>
<p>},</p>
<p>{</p>
<p>"file_url": "https://example/房屋产权所有证.pdf",</p>
<p>"file_name": "房屋产权所有证.pdf",</p>
<p>"file_type": "property_certificate"</p>
<p>},</p>
<p>{</p>
<p>"file_url": "https://example/有权批准机构决策文件.pdf",</p>
<p>"file_name": "有权批准机构决策文件.pdf",</p>
<p>"file_type": "internal_decision"</p>
<p>}</p>
<p>]<br />
}</p></td>
</tr>
</tbody>
</table>

<span id="_Toc16702" class="anchor"></span>**响应参数（字段响应）**

**1、顶层字段：**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| code | integer | 接口响应码。200 表示本次接口调用成功，不表示所有审核项通过。审核结论需读取 data.audit_results 和 data.summary。 |
| message | string | 本次接口调用的提示信息。正常完成通常为 success；超过同步等待时间时可能为“任务处理中，请稍后查询结果”。用于提示展示，不建议通过解析此文本判断业务状态。 |
| trace_id | string | 本次接口响应的追踪标识，用于排查日志、定位问题。反馈接口问题时可提供该值。与用于查询任务的 task_id 不同。 |
| timestamp | string | 本次响应生成时间，不代表任务开始时间。 |
| data | object | 审核业务数据，包含任务状态、审核明细、提取依据及结果汇总。 |

**2、data 数组元素：**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| request_id | string，可空 | 请求关联标识，通常回传调用方传入的 request_id。完成响应中未提供请求 ID 时，服务可能使用任务 ID 等值补充。用于关联业务请求；查询任务应使用 task_id。 |
| task_id | string，可空 | 审核任务标识。同步接口超过 timeout 后，使用该 ID 查询后台任务。查询方式：GET /api/v1/task/{task_id}?type=audit。 |
| status | string | 整体执行状态。同步接口正常完成时为 completed；超过同步等待时间、后台继续执行时为 processing。completed 只表示处理结束，不代表审核通过。任务查询接口还有独立的任务状态字段。 |
| audit_type | string | 本次审核的业务类型，例如 有纸大宗实物，用于选择业务规则。注意与 audit_results\[\].audit_type 区分，后者表示单条结果属于字段审核、文件审核还是人工审核。 |
| confirmed_fields | array | 用户确认字段的回传数据，是本次审核使用的表单输入，不是从附件中提取出的值。 |
| audit_results | array | 按审核项组织的结果列表，可能同时包含字段审核、文件审核和人工审核结果。一个输入字段不一定对应一条结果；规则数量、嵌套字段展开及业务条件过滤都会影响返回数量。 |
| summary | object | 审核结论汇总。当前只统计字段审核和人工审核，不统计文件审核。 |
| processing_time_ms | integer | 处理耗时，单位为毫秒。完成响应中表示本次服务处理耗时，示例 134990 约为 134.99 秒。同步等待超时返回的处理中响应里，该值可能是等待预算，不是最终任务总耗时。 |
| trigger_type | string，可空 | 回传请求中的触发类型。服务不限定固定枚举，调用方可按业务约定传值；未传时为 null。 |

**data.confirmed_fields\[\]数组元素：**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| field_name | string | 系统字段名称或字段编码，例如 ZMJZ。审核规则通过字段名匹配用户输入值。应使用规则约定的编码，不应自行替换成中文显示名称。 |
| field_value | 任意 JSON 类型 | 用户确认或填报的值，支持字符串、数字、布尔值、对象、数组及 null。例如 "368.580000" 是字符串，可保留原始小数位数。它与附件提取值是两个独立来源。 |
| field_type | string | 字段类型描述。请求中非必填，省略时默认 "text"，正常序列化响应会包含该默认值。显式传入其他类型时保留传入值；该字段不会自动转换 field_value 的 JSON 类型。 |

**data.audit_results\[\] 数组元素：**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| audit_id | string | 本条审核结果的标识，通常由服务生成，适合用于本次结果列表中的定位和展开操作。重新执行审核时可能变化，不应当作固定规则 ID。 |
| audit_rule_id | string，可空 | 对应审核规则配置的 ID，用于关联规则配置、追踪结果来源。自动补充的人工审核项可能为 null。 |
| audit_rule_name | string | 审核规则名称。当前实现中经常使用字段编码或文件名称，例如 ZMJZ。可用于展示或关联业务字段，不保证是中文描述。 |
| audit_type | string | 本条审核项的类型：字段审核、文件审核、人工审核，决定应读取哪些明细字段。 |
| audit_result | string，可空 | 业务结论：passed、failed、pending、manual_review。文件审核通常返回 null，需查看 audit_point_details 中各要点的结论。 |
| audit_status | string | 执行状态：completed 表示已执行完成，processing 表示处理中，failed 表示执行发生异常。与业务结论 audit_result 分开判断。 |
| audit_explanation | string，可空 | 审核结论说明，例如差异内容、材料缺失原因、需要人工确认的原因。字段审核通常有值；文件审核通常在各审核要点中提供说明。用于展示，不建议解析文本提取状态。 |
| confidence | number，可空 | 审核判断的置信度，范围 0～1。文件审核通常在各要点中返回。1.0 不代表审核通过，也不等于经过统计校准的“正确率 100%”；简单对比逻辑也可能直接赋值为 1.0。 |
| related_fields | array | 关联字段信息，主要用于字段审核和人工审核。包含用户值，以及可用时的材料提取数据。文件审核通常为空数组。 |
| file_type | string，可空 | 文件审核关联的文件或材料名称标识，字段审核通常为 null。可能来自规则中的材料名称，不应一律当作 files\[\].file_type 那样的文件类型枚举值。 |
| audit_points | string，可空 | 文件审核的审核要点文本，通常来自规则中的 audit_content。字段审核通常为 null。 |
| uploaded_files | array，可空 | 文件审核实际关联到的已上传文件列表。字段审核通常为 null；文件审核时可用于打开附件。 |
| audit_point_details | array，可空 | 文件审核逐项要点的审核结果，每个要点有独立结论、说明和置信度。字段审核通常为 null。 |
| audit_rule | object，可空 | 对应的审核规则信息，用于展示审核依据。人工审核项等无对应配置规则的情况可能为 null。它是规则描述，不是最终审核结论。 |

**audit_results\[\].related_fields\[\] 数组元素：**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| field_name | string | 关联的系统字段名称或编码，例如 ZMJZ，可用于定位业务表单字段。 |
| field_value | 任意 JSON 类型 | 本条审核关联的用户输入值，例如 "368.580000"，用于与材料提取值对照。 |
| field_type | string | 关联字段的类型描述。当前自动字段审核中多处固定返回 "text"；人工审核项可沿用确认字段的类型。不能据此认定服务已转换值的实际类型。 |
| extraction_data | object，可空 | 附件提取结果，包含材料值、来源位置和提取规则。未找到关联提取结果时为 null，不代表用户字段本身不存在。 |

**related_fields\[\].extraction_data 字段提取数据**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| field_id | string | 提取字段标识，当前通常取对应提取规则 ID，不是审核规则 ID。 |
| field_name | string | 提取规则对应的系统字段名称，例如 ZMJZ。 |
| field_type | string | 提取规则配置的字段类型，例如 text、single_choice、multiple_choice，与用户确认字段的类型描述属于不同来源。 |
| field_status | string | 综合各材料来源后的提取状态：success 表示提取成功；pending 表示待确认，例如无有效值或多来源值不一致；failed 表示提取发生错误。提取成功不代表审核通过。 |
| values | array | 不同材料来源的提取结果列表。一个字段可能有多个来源，应逐项展示，不应假定只返回一个值。 |
| error_message | string，可空 | 提取阶段错误或无可用提取结果等说明。无相关错误说明时为 null。它是提取信息，不是审核不通过原因。 |
| inconsistent_values | array of string，可空 | 多来源提取值不一致时记录的值列表。为 null 表示未返回不一致值列表，不应仅凭此字段推断审核通过。 |
| extraction_rule | object，可空 | 提取规则信息，用于解释从哪些材料、按什么逻辑提取。 |

**extraction_data.values\[\] 单个材料来源值**

|  |  |  |
|----|----|----|
| source_file_type | string | 来源文件系统类型标识，例如 info_disclosure_application 表示信息披露申请书。用于来源分组或映射中文材料名称。 |
| source_file_name | string | 来源文件名称。同类型材料涉及多个文件时，可能返回组合后的文件名文本，不保证只对应一个文件。 |
| source_field_name | string | 来源提取字段名称或编码，例如 ZMJZ，不保证是原文中逐字出现的中文标题。 |
| extracted_value | 任意 JSON 类型，可空 | 从材料提取并按规则处理后的值，可能经过单位转换或内容整理，不一定等于原文完整字符串。展示时应保留原始值，避免自行转换造成精度丢失。 |
| extract_status | string | 当前来源提取状态，仅有 success、failed。与字段整体的 field_status 不同。 |
| confidence | number | 当前来源提取结果置信度，范围 0～1，不代表审核通过比例。 |
| sources | array | 当前提取值的详细溯源信息。一个值可能关联多个原文位置。空数组表示没有可直接使用的详细溯源信息。 |

**values\[\].sources\[\]：**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| source_file_type | string | 此溯源位置所属的文件类型标识。 |
| source_file_name | string | 来源文件名，可能为多个文件名的组合文本。 |
| source_field | string | 当前溯源对应的字段名称或编码，例如 ZMJZ。 |
| source_content | string | 来源内容或提取内容，用于展示材料依据。当前实现可能直接使用提取值，不保证包含完整原文上下文。 |
| preview_image_url | string | 原文高亮预览图地址。可能是 /api/v1/preview/files/highlights/xxx.jpg 等相对路径，应相对于提供该 API 的服务地址访问；也可能是完整 URL。空字符串表示未提供可用图片。 |
| page_number | integer，可空 | PDF、Word 等文档的展示页码，从 1 开始。4 表示第 4 页；Excel 等场景可能为 null。 |
| coordinates | object | 来源区域矩形坐标，由 x、y、width、height 组成。用于定位参考，不应直接认为它就是返回预览图上的可绘制坐标。 |
| confidence | number | 当前来源定位或提取依据的置信度，范围 0～1。 |
| trace_supported | boolean | 是否支持位置溯源或高亮。false 时不应提供依赖位置数据的跳转功能；true 也需结合图片地址、页码或单元格信息判断具体可用能力。 |
| document_type | string，可空 | 文档类型提示，例如 pdf、excel、text。当前 PDF 路径也可能返回 null；不能据此判断文件不是 PDF 或提取失败。 |
| sheet_name | string，可空 | Excel 工作表名称，非 Excel 场景通常为 null。 |
| sheet_index | integer，可空 | Excel 工作表索引，从 0 开始。0 表示第一个工作表。 |
| cell_ref | string，可空 | Excel 主单元格引用，例如 Sheet1!B5，用于定位主要来源单元格。 |
| cell_refs | array of string，可空 | Excel 全部关联单元格引用，多区域或多个单元格参与提取时使用。 |
| cross_page_info | object，可空 | 跨页来源补充信息。当前处理路径可能不填充，因此即使涉及多区域也可能为 null。完整位置需结合 regions 查看。 |
| regions | array，可空 | 来源区域列表，可记录多个页面或单元格区域。模型将其标记为内部使用信息，普通前端展示优先使用预览图、展示页码和单元格引用。 |

**coordinates：**

|        |         |                    |
|:-------|:--------|:-------------------|
| 参数名 | 类型    | 说明               |
| x      | integer | 矩形左上角横坐标。 |
| y      | integer | 矩形左上角纵坐标。 |
| width  | integer | 矩形宽度。         |
| height | integer | 矩形高度。         |

**regions\[\]子字段**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| page_idx | integer | 页面索引，从 0 开始；Excel 场景用于工作表索引。多文件合并解析时需结合内部文件映射理解。3 对应单文件场景的第 4 页。 |
| bbox | array of number | 顺序为 \[x0, y0, x1, y1\]，即左上角和右下角坐标。后两个数不是宽高。 |
| file_index | integer，可空 | 文件索引，用于多文件区域定位，例如多个 Excel 文件场景。未填充时为 null。 |
| sheet_name | string，可空 | 该区域对应的 Excel 工作表名称。 |
| cell_ref | string，可空 | 该区域对应的 Excel 单元格引用。 |

**cross_page_info 子字段**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| is_cross_page | boolean | 是否跨页。 |
| pages | array of integer | 关联的展示页码列表，模型示例采用从 1 开始的页码。 |
| main_page | integer | 主要来源展示页码。 |

**extraction_data.extraction_rule**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| rule_id | string，可空 | 提取规则配置 ID，用于关联规则配置；示例中与 extraction_data.field_id 一致。 |
| field_name | string | 提取的系统字段名称或编码，例如 ZMJZ。 |
| field_type | string | 提取规则配置的字段类型，例如 text、single_choice、multiple_choice。 |
| extraction_logic | string | 自然语言描述的提取逻辑，可能包含参考位置、取值条件、单位转换和空值要求。用于展示依据，不应由调用方解析文本重新计算结果。 |
| reference_materials | array of string | 配置的参考材料名称列表，不代表这些材料本次都已上传或都有成功提取值。实际来源以 values 为准。 |
| enabled | boolean | 规则启用标记，不代表提取成功或审核通过。 |

**audit_results\[\].audit_rule**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| rule_id | string，可空 | 审核规则 ID，通常与本条结果的 audit_rule_id 一致。 |
| field_name | string | 审核目标字段或文件名称，例如 ZMJZ。 |
| audit_type | string | 规则类型，配置规则通常为 字段审核 或 文件审核。 |
| audit_content | string | 规则检查内容，例如“用户填报账面价值与材料提取值是否一致”，用于展示审核依据。 |
| mapping_type | string，可空 | 数据映射方式。auto 表示通过提取规则自动关联；manual 表示使用配置的数据源；文件审核时可能为 null。这里的 manual 是手工配置映射，不是人工审核。 |
| source_field_name | string，可空 | 自动映射引用的提取字段名称。自定义映射场景即使保留该值，也应以 audit_data_sources 的实际配置为主要依据。 |
| include_user_input | boolean | 是否把用户输入纳入审核。true 时按规则目标字段名匹配确认字段，并将对应用户值用于审核。 |
| use_simple_comparison | boolean | 是否使用服务端简单对比逻辑。true 时本条审核判断使用内置规范化比较，不调用 LLM 审核 Agent；不代表整个请求的解析、提取步骤都不调用模型。 |
| auto_process_rules | string | 各种情况对应的处理规则文本，用于说明通过、不通过、待确认的判断要求。应读取已返回结论，不应由调用方再次解析文本判定。 |
| audit_data_sources | array | 自定义映射或文件审核的数据源配置列表。自动映射时可能为空列表。 |
| enabled | boolean | 审核规则是否启用，不代表本条审核通过。 |

**audit_data_sources\[\]**

|  |  |  |
|----|----|----|
| material_name | string | 参考材料名称，例如 《信息披露申请书》，由服务关联对应材料类型。 |
| field_name | string，可空 | 引用的材料提取字段，例如 ZMJZ。为 null、空字符串或 "全文" 时，表示引用材料全文。 |

<span id="_Toc28565" class="anchor"></span>**响应示例 — 成功（字段审核审核明细已节选）**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>JSON<br />
{</p>
<p>"code": 200,</p>
<p>"message": "success",</p>
<p>"trace_id": "trace_443fc07b30264f1b",</p>
<p>"timestamp": "2026-10-22T05:41:39.967322Z",</p>
<p>"data": {</p>
<p>"request_id": "test_badcase_001",</p>
<p>"task_id": "test_badcase_001",</p>
<p>"status": "completed",</p>
<p>"audit_type": "有纸大宗实物",</p>
<p>"confirmed_fields": [</p>
<p>{"field_name": "ZMJZ", "field_value": "368.580000"}</p>
<p>],</p>
<p>"audit_results": {</p>
<p>"audit_id": "audit_f8da699765fe4afc",</p>
<p>"audit_rule_id": "347fb307-1888-4370-bda7-218b2e50e34c",</p>
<p>"audit_rule_name": "ZMJZ",</p>
<p>"audit_type": "字段审核",</p>
<p>"audit_result": "failed",</p>
<p>"audit_status": "completed",</p>
<p>"audit_explanation": "字段值对比不一致，审核不通过；材料核对：✗ 《信息披露申请书》：用户填[368.580000] ≠ 材料[8530.922906]。",</p>
<p>"confidence": 1.0,</p>
<p>"related_fields": [</p>
<p>{</p>
<p>"field_name": "ZMJZ",</p>
<p>"field_value": "368.580000",</p>
<p>"field_type": "text",</p>
<p>"extraction_data": {</p>
<p>"field_id": "447dd239-fe96-48e7-bc62-42a758758dea",</p>
<p>"field_name": "ZMJZ",</p>
<p>"field_type": "text",</p>
<p>"field_status": "success",</p>
<p>"values": [</p>
<p>{</p>
<p>"source_file_type": "info_disclosure_application",</p>
<p>"source_file_name": "信息披露申请书.pdf",</p>
<p>"source_field_name": "ZMJZ",</p>
<p>"extracted_value": "8530.922906",</p>
<p>"extract_status": "success",</p>
<p>"confidence": 1.0,</p>
<p>"sources": [</p>
<p>{</p>
<p>"source_file_type": "info_disclosure_application",</p>
<p>"source_file_name": "信息披露申请书.pdf",</p>
<p>"source_field": "ZMJZ",</p>
<p>"source_content": "8530.922906",</p>
<p>"preview_image_url": "/api/v1/preview/files/highlights/batch_1792647680705_7f4552c8.jpg",</p>
<p>"page_number": 4,</p>
<p>"coordinates": {"x": 115, "y": 206, "width": 960, "height": 1000},</p>
<p>"confidence": 1.0,</p>
<p>"trace_supported": true,</p>
<p>"document_type": null,</p>
<p>"sheet_name": null,</p>
<p>"sheet_index": null,</p>
<p>"cell_ref": null,</p>
<p>"cell_refs": null,</p>
<p>"cross_page_info": null,</p>
<p>"regions": [</p>
<p>{</p>
<p>"page_idx": 3,</p>
<p>"bbox": [115.0, 206.0, 1075.0, 1206.0],</p>
<p>"file_index": null,</p>
<p>"sheet_name": null,</p>
<p>"cell_ref": null</p>
<p>}</p>
<p>]</p>
<p>}</p>
<p>]</p>
<p>}</p>
<p>],</p>
<p>"error_message": null,</p>
<p>"inconsistent_values": null,</p>
<p>"extraction_rule": {</p>
<p>"rule_id": "447dd239-fe96-48e7-bc62-42a758758dea",</p>
<p>"field_name": "ZMJZ",</p>
<p>"field_type": "text",</p>
<p>"extraction_logic": "字段名称：ZMJZ；备注：账面价值（万元）\r\n## 提取逻辑：\r\n录入参考材料\t录入参考材料类目\t录入参考材料一级字段\t录入参考材料二级字段 录入逻辑\r\n《信息披露申请书》\t一、转让标的简况\t资产评估情况\t账面价值\t根据字段值录入，提取数值，按万元单元转换。\r\n《评估备案表/核准文件》\t资产评估结果\t账面价值\t-\t提取账面价值合计值录入系统，提取数值，按万元单元转换。\r\n\r\ntips：提取转换后的数值即可，无需带单位输出，示例：“100”\r\n\r\ntips：前置条件为「是否依据评估定价」选择「是」，否则该字段提取为空字符串\"\"即可。",</p>
<p>"reference_materials": [</p>
<p>"《信息披露申请书》", "《评估备案表/核准文件》",</p>
<p>"《评估报告或其他定价文件》"</p>
<p>],</p>
<p>"enabled": true</p>
<p>}</p>
<p>}</p>
<p>}</p>
<p>],</p>
<p>"file_type": null,</p>
<p>"audit_points": null,</p>
<p>"uploaded_files": null,</p>
<p>"audit_point_details": null,</p>
<p>"audit_rule": {</p>
<p>"rule_id": "347fb307-1888-4370-bda7-218b2e50e34c",</p>
<p>"field_name": "ZMJZ",</p>
<p>"audit_type": "字段审核",</p>
<p>"audit_content": "校验用户填报账面价值（万元）与参考材料提取值是否一致。数值相等即通过，忽略小数位数差异（如368.580000与368.58视为相同）。",</p>
<p>"mapping_type": "manual",</p>
<p>"source_field_name": "ZMJZ",</p>
<p>"include_user_input": true,</p>
<p>"use_simple_comparison": true,</p>
<p>"auto_process_rules": "1. 用户填报值与材料提取值数值相等 → 审核通过（忽略小数位数差异，如368.580000与368.58视为相同）。\r\n2. 数值不一致 → 审核不通过。\r\n3. 仅当提取值为空且用户也未填时 → 待确认。\r\n4. 本规则仅校验一致性，不判断「是否不低于备案值」等业务规则。",</p>
<p>"audit_data_sources": [</p>
<p>{"material_name": "《信息披露申请书》", "field_name": "ZMJZ"}</p>
<p>],</p>
<p>"enabled": true</p>
<p>}</p>
<p>}</p>
<p>],</p>
<p>"summary": {"total": 49, "passed": 1, "failed": 4, "pending": 44, "manual_review": 0},</p>
<p>"processing_time_ms": 134990,</p>
<p>"trigger_type": null</p>
<p>}</p>
<p>}</p></td>
</tr>
</tbody>
</table>

<span id="_Toc27488" class="anchor"></span>**响应参数（文件审核）**

**文件审核字段与字段审核字段一致,以下是文件审核专用明细：**

**data.audit_results\[\].uploaded_files\[\]\**

|           |        |                                          |
|:----------|:-------|:-----------------------------------------|
| 参数名    | 类型   | 说明                                     |
| file_name | string | 关联附件名称，用于展示。                 |
| file_url  | string | 关联附件访问地址，用于打开或下载原文件。 |
| file_type | string | 关联附件的文件类型标识。                 |

**\
data.audit_results\[\].audit_point_details\[\]**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| point_index | integer | 审核要点序号，从 1 开始。 |
| point_content | string | 当前要点的审核内容。 |
| audit_result | string，可空 | 当前要点结论，使用 passed、failed、pending、manual_review 枚举；文件未上传等情形可能为 null，不能当作通过。 |
| audit_explanation | string | 当前要点的审核说明。 |
| confidence | number | 当前要点结论置信度，范围 0～1。 |

<span id="_Toc31168" class="anchor"></span>**响应示例 — 成功（字段审核审核明细已节选）**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>{</p>
<p>"code": 200,</p>
<p>"message": "success",</p>
<p>"trace_id": "trace_443fc07b30264f1b",</p>
<p>"timestamp": "2026-10-22T05:41:39.967322Z",</p>
<p>"data": {</p>
<p>"request_id": "test_badcase_001",</p>
<p>"task_id": "test_badcase_001",</p>
<p>"status": "completed",</p>
<p>"audit_type": "有纸大宗实物",</p>
<p>"confirmed_fields": [</p>
<p>{"field_name": "YYZZSFCQ", "field_value": "是", "field_type": "text"},</p>
<p>{"field_name": "BDSZDS", "field_value": "云南省", "field_type": "text"},</p>
<p>{"field_name": "ZMJZ", "field_value": "368.580000", "field_type": "text"},</p>
<p>{"field_name": "PLGGQ", "field_value": "10", "field_type": "text"},</p>
<p>{"field_name": "ZRDJ", "field_value": "517.59", "field_type": "text"}</p>
<p>],</p>
<p>"audit_results": [</p>
<p>{</p>
<p>"audit_id": "audit_e45ca08ef2cf4c0e",</p>
<p>"audit_rule_id": "6c642b6d-fa8c-427a-a85a-55700a3cb622",</p>
<p>"audit_rule_name": "信息披露申请书",</p>
<p>"audit_type": "文件审核",</p>
<p>"audit_result": null,</p>
<p>"audit_status": "completed",</p>
<p>"audit_explanation": null,</p>
<p>"confidence": null,</p>
<p>"related_fields": [],</p>
<p>"file_type": "信息披露申请书",</p>
<p>"audit_points": "1.信息披露申请书封面需加盖转让方公章",</p>
<p>"uploaded_files": [</p>
<p>{</p>
<p>"file_name": "信息披露申请书.pdf",</p>
<p>"file_url": "http:example/信息披露申请书.pdf",</p>
<p>"file_type": "info_disclosure_application"</p>
<p>}</p>
<p>],</p>
<p>"audit_details": null,</p>
<p>"audit_point_details": [</p>
<p>{</p>
<p>"point_index": 1,</p>
<p>"point_content": "1.信息披露申请书封面需加盖转让方公章",</p>
<p>"audit_result": "failed",</p>
<p>"audit_explanation": "【不一致】用户填报封面未见转让方公章，材料中仅有法定代表人或授权代表签字及一处印章，但该印章位于承诺书部分，非封面申请人处盖章。",</p>
<p>"confidence": 0.9</p>
<p>}</p>
<p>],</p>
<p>"audit_rule": {</p>
<p>"rule_id": "6c642b6d-fa8c-427a-a85a-55700a3cb622",</p>
<p>"field_name": "信息披露申请书",</p>
<p>"audit_type": "文件审核",</p>
<p>"audit_content": "1.信息披露申请书封面需加盖转让方公章",</p>
<p>"mapping_type": null,</p>
<p>"source_field_name": null,</p>
<p>"include_user_input": true,</p>
<p>"use_simple_comparison": false,</p>
<p>"auto_process_rules": "1.若无法做出判断，则审核结果为待确认\r\n2.若符合上述审核要求，则审核通过\r\n3.若不符合上述审核要求，则审核不通过",</p>
<p>"audit_data_sources": [</p>
<p>{"material_name": "《信息披露申请书》", "field_name": ""}</p>
<p>],</p>
<p>"enabled": true</p>
<p>}</p>
<p>}],</p>
<p>"summary": {"total": 49, "passed": 1, "failed": 4, "pending": 44, "manual_review": 0},</p>
<p>"processing_time_ms": 134990,</p>
<p>"trigger_type": null</p>
<p>}</p>
<p>}</p></td>
</tr>
</tbody>
</table>

<span id="_Toc18126" class="anchor"></span>**1.2.5 查询任务状态**

**接口地址**

- 智能体：GET /api/v1/task/{task_id}

**接口描述**：查询长时间运行任务的状态和结果。支持超时后继续查询完整结果。

<span id="_Toc16073" class="anchor"></span>**请求参数（Body）**

**路径参数：**

|         |        |      |                                    |
|:--------|:-------|:-----|:-----------------------------------|
| 参数名  | 类型   | 必填 | 说明                               |
| task_id | String | 是   | 任务 ID（不含内部前缀，如项目 ID） |

**Query 参数：**

|                 |         |      |                                                |
|:----------------|:--------|:-----|:-----------------------------------------------|
| 参数名          | 类型    | 必填 | 说明                                           |
| type            | String  | 否   | 任务类型：extraction / audit，用于区分同名任务 |
| include_details | Boolean | 否   | 是否包含详细结果，默认 true                    |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">HTTP<br />
GET /api/v1/task/25675?type=audit&amp;include_details=true HTTP/1.1</td>
</tr>
</tbody>
</table>

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">HTTP<br />
GET /api/v1/task/abc123?type=extraction HTTP/1.1</td>
</tr>
</tbody>
</table>

**响应参数（data）**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| task_id | String | 任务 ID |
| task_type | String | 任务类型：extraction / audit |
| status | String | 任务状态：pending / processing / completed / failed / timeout / cancelled |
| progress | Number | 进度（0-1） |
| status_message | String | 进度阶段描述 |
| total_count | Integer | 总任务数（提取=字段数，审核=规则数） |
| completed_count | Integer | 已完成数 |
| result | Object | 任务结果（结构同提取/审核接口 data） |
| error_message | String | 错误信息 |
| created_at | String | 创建时间（ISO 8601） |
| updated_at | String | 更新时间 |
| completed_at | String | 完成时间 |

**响应示例 — 任务进行中**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 200,<br />
"message": "success",<br />
"trace_id": "trace_20251022100008",<br />
"timestamp": "2025-10-22T10:30:00Z",<br />
"data": {<br />
"task_id": "25675",<br />
"task_type": "audit",<br />
"status": "processing",<br />
"progress": 0.45,<br />
"status_message": "正在执行规则审核...",<br />
"total_count": 15,<br />
"completed_count": 7,<br />
"result": null,<br />
"error_message": null,<br />
"created_at": "2025-10-22T10:10:00Z",<br />
"updated_at": "2025-10-22T10:30:00Z",<br />
"completed_at": null<br />
}<br />
}</td>
</tr>
</tbody>
</table>

**响应示例 — 任务完成（提取）**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>JSON<br />
{</p>
<p>"code": 200,</p>
<p>"message": "success",</p>
<p>"trace_id": "trace_20251022100009",</p>
<p>"timestamp": "2025-10-22T10:35:00Z",</p>
<p>"data": {</p>
<p>"task_id": "task_20251022100004",</p>
<p>"task_type": "extraction",</p>
<p>"status": "completed",</p>
<p>"progress": 1.0,</p>
<p>"status_message": "处理完成",</p>
<p>"result": {</p>
<p>"request_id": "req_20251022100004",</p>
<p>"task_id": "task_20251022100004",</p>
<p>"status": "success",</p>
<p>"extraction_type": "有纸大宗实物",</p>
<p>"rule_config_id": "rule_dzswv10",</p>
<p>"from_cache": false,</p>
<p>"cached_task_id": null,</p>
<p>"results": [</p>
<p>{</p>
<p>"field_id": "field_20251022100004_001",</p>
<p>"field_name": "坐落位置",</p>
<p>"field_type": "text",</p>
<p>"field_status": "success",</p>
<p>"values": [</p>
<p>{</p>
<p>"source_file_type": "info_disclosure_application",</p>
<p>"source_file_name": "信息披露申请书.pdf",</p>
<p>"source_field_name": "坐落位置",</p>
<p>"extracted_value": "北京市朝阳区建国路1号国贸大厦A座10层",</p>
<p>"extract_status": "success",</p>
<p>"confidence": 0.96,</p>
<p>"sources": [</p>
<p>{</p>
<p>"source_file_type": "info_disclosure_application",</p>
<p>"source_file_name": "信息披露申请书.pdf",</p>
<p>"source_field": "坐落位置",</p>
<p>"source_content": "坐落位置：北京市朝阳区建国路1号国贸大厦A座10层",</p>
<p>"preview_image_url": "/api/v1/preview/files/highlights/batch_xxx.jpg",</p>
<p>"page_number": 2,</p>
<p>"coordinates": {</p>
<p>"x": 120,</p>
<p>"y": 450,</p>
<p>"width": 400,</p>
<p>"height": 30</p>
<p>},</p>
<p>"confidence": 0.96,</p>
<p>"trace_supported": true,</p>
<p>"document_type": "pdf",</p>
<p>"sheet_name": null,</p>
<p>"sheet_index": null,</p>
<p>"cell_ref": null,</p>
<p>"cell_refs": null,</p>
<p>"cross_page_info": null,</p>
<p>"regions": [</p>
<p>{</p>
<p>"page_idx": 1,</p>
<p>"bbox": [120.0, 450.0, 520.0, 480.0],</p>
<p>"file_index": null,</p>
<p>"sheet_name": null,</p>
<p>"cell_ref": null</p>
<p>}</p>
<p>]</p>
<p>}</p>
<p>]</p>
<p>}</p>
<p>],</p>
<p>"error_message": null,</p>
<p>"inconsistent_values": null,</p>
<p>"extraction_rule": {</p>
<p>"rule_id": "rule_loc_001",</p>
<p>"rule_name": "坐落位置提取",</p>
<p>"source_file_types": ["info_disclosure_application"]</p>
<p>}</p>
<p>}</p>
<p>],</p>
<p>"total_fields": 1,</p>
<p>"success_count": 1,</p>
<p>"pending_count": 0,</p>
<p>"failed_count": 0,</p>
<p>"processing_time_ms": 15200,</p>
<p>"parsed_files": {</p>
<p>"info_disclosure_application": {</p>
<p>"file_name": "信息披露申请书.pdf",</p>
<p>"file_label": "信息披露申请书",</p>
<p>"md_content": "# 信息披露申请书\n\n## 基本信息\n\n坐落位置：北京市朝阳区建国路1号国贸大厦A座10层\n"</p>
<p>}</p>
<p>}</p>
<p>},</p>
<p>"total_count": 1,</p>
<p>"completed_count": 1,</p>
<p>"error_message": null,</p>
<p>"created_at": "2025-10-22T10:10:00Z",</p>
<p>"updated_at": "2025-10-22T10:35:00Z",</p>
<p>"completed_at": "2025-10-22T10:35:00Z"</p>
<p>}</p>
<p>}</p></td>
</tr>
</tbody>
</table>

**响应示例 — 任务完成（审核明细已省略，与审核接口一致）**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 200,<br />
"message": "success",<br />
"trace_id": "trace_20251022100009",<br />
"timestamp": "2025-10-22T10:35:00Z",<br />
"data": {<br />
"task_id": "25675",<br />
"task_type": "audit",<br />
"status": "completed",<br />
"progress": 1.0,<br />
"status_message": "处理完成",<br />
"total_count": 15,<br />
"completed_count": 15,<br />
"result": {<br />
"audit_type": "有纸大宗实物",<br />
"trigger_type": "kafka",<br />
"audit_results": [],<br />
"summary": {<br />
"total": 15,<br />
"passed": 12,<br />
"failed": 1,<br />
"pending": 1,<br />
"manual_review": 1<br />
},<br />
"processing_time_ms": 15200<br />
},<br />
"created_at": "2025-10-22T10:10:00Z",<br />
"updated_at": "2025-10-22T10:35:00Z",<br />
"completed_at": "2025-10-22T10:35:00Z"<br />
}<br />
}</td>
</tr>
</tbody>
</table>

**响应示例 — 任务不存在**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 404,<br />
"message": "Not Found",<br />
"detail": "任务不存在: 25675"<br />
}</td>
</tr>
</tbody>
</table>

<span id="heading_158" class="anchor"></span>**1.2.6 取消任务**

**接口地址**

- 智能体：POST /api/v1/task/{task_id}/cancel

**接口描述**：取消处于 pending 或 processing 状态的任务。<span id="heading_159" class="anchor"></span>

**请求参数（Body）**

**路径参数：**

|         |        |      |         |
|:--------|:-------|:-----|:--------|
| 参数名  | 类型   | 必填 | 说明    |
| task_id | String | 是   | 任务 ID |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">HTTP<br />
POST /api/v1/task/abc123/cancel HTTP/1.1</td>
</tr>
</tbody>
</table>

**响应参数（data）**

|         |        |                 |
|:--------|:-------|:----------------|
| 参数名  | 类型   | 说明            |
| task_id | String | 任务 ID         |
| status  | String | 状态：cancelled |

**响应示例 — 成功**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 200,<br />
"message": "任务已取消",<br />
"trace_id": "trace_20251022100011",<br />
"timestamp": "2025-10-22T10:45:00Z",<br />
"data": {<br />
"task_id": "abc123",<br />
"status": "cancelled"<br />
}<br />
}</td>
</tr>
</tbody>
</table>

**响应示例 — 任务无法取消**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 400,<br />
"message": "Bad Request",<br />
"detail": "任务状态为 completed，无法取消"<br />
}</td>
</tr>
</tbody>
</table>

<span id="heading_164" class="anchor"></span>**1.2.7 预览服务**

**接口地址**

- 智能体：GET /api/v1/preview/files/{file_path}

  **接口描述**：代理访问 MinIO 中的文件，用于 PDF 高亮预览图等场景。<span id="heading_165" class="anchor"></span>

**请求参数（Body）**

**路径参数**

|           |        |      |                                             |
|:----------|:-------|:-----|:--------------------------------------------|
| 参数名    | 类型   | 必填 | 说明                                        |
| file_path | String | 是   | MinIO 对象路径，如 highlights/batch_xxx.jpg |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">HTTP<br />
GET /api/v1/preview/files/highlights/batch_20251022_001.jpg HTTP/1.1</td>
</tr>
</tbody>
</table>

**响应**

返回文件二进制流，Content-Type 根据扩展名自动判断（image/jpeg、image/png、application/pdf 等）。

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">HTTP<br />
HTTP/1.1 200 OK<br />
Content-Type: image/jpeg<br />
Cache-Control: public, max-age=86400<br />
Content-Disposition: inline; filename=batch_20251022_001.jpg<br />
<br />
&lt;二进制数据&gt;</td>
</tr>
</tbody>
</table>

## 通用一句话找项目接口

### **2.1 基本信息**

**请求头**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>HTTP<br />
Content-Type: application/json</p>
<p>Apikey：xxx</p></td>
</tr>
</tbody>
</table>

**统一响应格式**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;">JSON<br />
{<br />
"code": 200,<br />
"message": "success",<br />
"trace_id": "trace_20251022100001",<br />
"timestamp": "2025-10-22T10:00:00Z",<br />
"data": {}<br />
}</td>
</tr>
</tbody>
</table>

### **2.1 接口列表** 

<span id="_Toc7852" class="anchor"></span>**2.1.1 智能对话(流式)**

**接口地址**

- 智能体：POST /openapi/agents/chat/stream/v2

**接口描述**：用户输入自然语言需求，AI进行理解、匹配，并通过流式响应返回思考过程和最终的项目列表

<span id="_Toc18615" class="anchor"></span>**请求参数（Body）**

|               |        |      |                                               |
|:--------------|:-------|:-----|:----------------------------------------------|
| 参数名        | 类型   | 必填 | 说明                                          |
| agentId       | String | 是   | 对外应用标识，映射后台Api-key                 |
| userId        | String | 是   | 当前终端用户标识，1至20字符                   |
| userChatInput | String | 是   | 本轮自然语言输入，建议去首尾空白后1至2000字符 |
| chatId        | String | 否   | 首次省略，由业务层创建；继续对话时传上次值    |
| requestId     | String | 否   | 请求去重标识，重试时复用，建议每次新操作传入  |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>HTTP<br />
POST /openapi/agents/chat/regenerate/v2</p>
<p>Host: 10.254.89.165:32300</p>
<p>Apikey: dbcn5aao0hrs72slf6qg</p>
<p>Content-Type: application/json</p>
<p>Content-Length: 127</p>
<p>{</p>
<p>"agentId":"project-finder",</p>
<p>"userId":"u1001",</p>
<p>"userChatInput":"帮我找一下北京东城区、西城区、朝阳区、海淀区、丰台区的房产转让项目",</p>
<p>"requestId":"req_chat_001"</p>
<p>}</p></td>
</tr>
</tbody>
</table>

<span id="_Toc1950" class="anchor"></span>**响应参数**

|  |  |  |
|:---|:---|:---|
| 参数名 | 类型 | 说明 |
| chatId | String | 对外会话ID |
| messageId | String | 当前轮次执行结果ID；本轮所有步骤保持一致 |
| id | String或null | 源组件消息ID；适配器生成的终态没有源组件ID时为null |
| complete | Boolean | 当前业务消息是否完整，独立于finish；标准版仅发完整可解析的节点消息，因此样例均为true |
| componentName | String | 优先取源message_title；具体名称不是判断最终结果的依据 |
| content | String | 一期形态的业务JSON字符串，包含全部原有字段与projectDetails |
| finish | Boolean | false处理中，true本轮响应结束；不代表整个会话结束 |
| code | String | 0正常处理，非0技术失败 |
| message | String | 本轮处理说明 |

**content业务字段**

|  |  |  |
|:---|:---|:---|
| qa_return | String | 无内容为""，承载QA、追问或业务拒绝提示 |
| thinkingProcess | String | 可展示的业务进度或说明，不承载模型内部推理日志 |
| isProjectQuery | String | "true"、"false"或"" |
| isBusinessLineConfir | String | 保留实测拼写；"true"、"false"或"" |
| rewrittenQuery | String | 未形成或不适用时"" |
| sql | String | 任何对外事件固定为""；原始SQL只在内部受控保存和执行 |
| projectList | String | 中间未产出时"" |
| is_violating_content | String | "true"、"false"或""；不省略该字段 |
| is_search_result_empty | String | "true"已查无结果，"false"已查有结果，""未查、未知或技术失败 |
| projectDetails | Array\<Object\> | 中间未就绪时\[\]；结果就绪时为项目详情 |

**projectDetails业务字段**

|  |  |  |
|:---|:---|:---|
| projectId | String | 项目id |
| projectCode | String | 项目编码 |
| projectName | String | 项目名称 |
| transactionBusinessType | String | "true"已查无结果，"false"已查有结果，""未查、未知或技术失败 |
| tags | Array\<Object\> | 赛道标签列表 |
| project_listing_price | String | 项目挂牌价 |
| project_disclosure_deadline | String | 项目披露截止时间 |

**响应示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>JSON<br />
data: {"chatId":"110865","messageId":"msg_001","id":"tool_001","complete":true,"componentName":"5-0 业务线匹配提示语4","content":"{\"qa_return\":\"\",\"thinkingProcess\":\"正在为您匹配对应的项目业务领域\",\"isProjectQuery\":\"true\",\"isBusinessLineConfir\":\"\",\"rewrittenQuery\":\"\",\"sql\":\"\",\"projectList\":\"\",\"is_violating_content\":\"false\",\"is_search_result_empty\":\"\",\"projectDetails\":[]}","finish":false}</p>
<p>data: {"chatId":"110865","messageId":"msg_001","id":"tool_002","complete":true,"componentName":"6-5 query改写结果输出3","content":"{\"qa_return\":\"\",\"thinkingProcess\":\"正在准备房屋土地项目资料库，即将开始检索\",\"isProjectQuery\":\"true\",\"isBusinessLineConfir\":\"true\",\"rewrittenQuery\":\"寻找位于东城区、西城区、朝阳区、海淀区、丰台区的房产转让项目\",\"sql\":\"\",\"projectList\":\"\",\"is_violating_content\":\"false\",\"is_search_result_empty\":\"\",\"projectDetails\":[]}","finish":false}</p>
<p>data: {"chatId":"110865","messageId":"msg_001","id":"tool_003","complete":true,"componentName":"项目查询结果","content":"{\"qa_return\":\"\",\"thinkingProcess\":\"已为您找到符合条件的房产转让项目\",\"isProjectQuery\":\"true\",\"isBusinessLineConfir\":\"true\",\"rewrittenQuery\":\"寻找位于东城区、西城区、朝阳区、海淀区、丰台区的房产转让项目\",\"sql\":\"\",\"projectList\":[\"PROJ001\"],\"is_violating_content\":\"false\",\"is_search_result_empty\":\"false\",\"projectDetails\":[{\"projectId\":\"PROJ001\",\"projectCode\":\"DEMO-001\",\"projectName\":\"北京市朝阳区某办公用房转让项目\",\"transactionBusinessType\":\"资产转让\",\"tags\":[\"房屋土地\",\"办公用房\",\"project_listing_price\":"5000000",\"project_disclosure_deadline\":"2026-06-25 10:31:30"]}]}","finish":false}</p>
<p>data: {"chatId":"110865","messageId":"msg_001","id":null,"complete":true,"componentName":"本轮结束","content":"{\"qa_return\":\"\",\"thinkingProcess\":\"已为您找到符合条件的房产转让项目\",\"isProjectQuery\":\"true\",\"isBusinessLineConfir\":\"true\",\"rewrittenQuery\":\"寻找位于东城区、西城区、朝阳区、海淀区、丰台区的房产转让项目\",\"sql\":\"\",\"projectList\":[\"PROJ001\"],\"is_violating_content\":\"false\",\"is_search_result_empty\":\"false\",\"projectDetails\":[{\"projectId\":\"PROJ001\",\"projectCode\":\"DEMO-001\",\"projectName\":\"北京市朝阳区某办公用房转让项目\",\"transactionBusinessType\":\"资产转让\",\"tags\":[\"房屋土地\",\"办公用房\",\"project_listing_price\":"5000000",\"project_disclosure_deadline\":"2026-06-25 10:31:30"]}]}","finish":true,"code":"0","message":"查询成功"}</p></td>
</tr>
</tbody>
</table>

<span id="_Toc31299" class="anchor"></span>**2.1.2 重新生成**

**接口地址**

- 智能体：POST /openapi/agents/chat/regenerate/v2

**接口描述**：重新生成当前对话，出参同2.1.1智能对话(流式）

<span id="_Toc8434" class="anchor"></span>**请求参数（Body）**

**路径参数：**

|           |        |      |                                |
|:----------|:-------|:-----|:-------------------------------|
| 参数名    | 类型   | 必填 | 说明                           |
| agentId   | String | 是   | 对外应用标识，映射后台Api-key  |
| userId    | String | 是   | 原终端用户，须有消息权限       |
| chatId    | String | 是   | 原会话                         |
| messageId | String | 是   | 要重新生成的业务轮次执行结果ID |
| requestId | String | 否   | 本次操作去重标识               |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>HTTP<br />
POST /api/proxy/api/v1/query_again_v2 HTTP/1.1</p>
<p>Host: 10.254.89.165:32300</p>
<p>Apikey: dbcn5aao0hrs72slf6qg</p>
<p>Content-Type: application/json</p>
<p>{<br />
"agentId":"projectfinder",</p>
<p>"userId":"u1001",</p>
<p>"chatId":"110865",</p>
<p>"messageId":"msg_001",</p>
<p>"requestId":"req_regen_001"<br />
}</p></td>
</tr>
</tbody>
</table>

<span id="_Toc19198" class="anchor"></span>**响应参数**

|         |        |                 |
|:--------|:-------|:----------------|
| 参数名  | 类型   | 说明            |
| task_id | String | 任务 ID         |
| status  | String | 状态：cancelled |

**响应示例 — 同2.1.1智能对话接口**

<span id="_Toc25796" class="anchor"></span>**2.1.3 删除对话记录**

**接口地址**

- 智能体：POST /openapi/agents/chat/records/delete/v2

**接口描述**：删除当前对话

<span id="_Toc14623" class="anchor"></span>**请求参数（Body）**

**路径参数：**

|           |        |      |                               |
|:----------|:-------|:-----|:------------------------------|
| 参数名    | 类型   | 必填 | 说明                          |
| agentId   | String | 是   | 对外应用标识，映射后台Api-key |
| userId    | String | 是   | 当前终端用户                  |
| chatId    | String | 是   | 目标会话                      |
| messageId | String | 必填 | 删除的对话标识                |
| requestId | String | 否   | 删除操作去重标识              |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>HTTP<br />
POST /openapi/agents/chat/records/delete/v2</p>
<p>HTTP/1.1</p>
<p>{</p>
<p>"agentId":"projectfinder",</p>
<p>"userId":"u1001",</p>
<p>"chatId":"110865",</p>
<p>"messageId":"msg_001",</p>
<p>"requestId":"req_del_001"</p>
<p>}</p></td>
</tr>
</tbody>
</table>

<span id="_Toc23224" class="anchor"></span>**响应参数**

|                |              |                                  |
|:---------------|:-------------|:---------------------------------|
| 参数名         | 类型         | 说明                             |
| code           | String       | 0成功，其他为错误                |
| message        | String       | 结果说明                         |
| data.chatId    | String       | 目标会话                         |
| data.messageId | String或null | 定位目标的消息ID，删除会话时null |
| data.deleted   | Boolean      | 业务记录是否已完成删除标记       |

**响应示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td><pre><code>JSON
{
&quot;code&quot;:&quot;200&quot;,
&quot;message&quot;:&quot;删除成功&quot;,
&quot;data&quot;:{
&quot;chatId&quot;:&quot;110865&quot;,
&quot;messageId&quot;:&quot;msg_001&quot;,
&quot;deleted&quot;:true
}
}</code></pre></td>
</tr>
</tbody>
</table>

<span id="_Toc20193" class="anchor"></span>**2.1.4 总结历史会话标题**

**接口地址**

- 智能体：POST /openapi/agents/chat/title/summary/v2

**接口描述**：将用户输入的内容或当前会话总结成标题

<span id="_Toc2227" class="anchor"></span>**请求参数（Body）**

**路径参数：**

|  |  |  |  |
|:---|:---|:---|:---|
| 参数名 | 类型 | 必填 | 说明 |
| agentId | String | 是 | 对外应用标识，映射后台Api-key |
| userId | String | 是 | 当前终端用户，沿用公共身份校验规则 |
| chatId | String | 条件必填（不传则必传userInput参数) | 待总结标题的业务会话ID |
| limit | String | 条件必填（传chatId时必传) | 总结的对话条数 |
| userInput | String | 条件必填(不传则必传chatId参数) | 待总结标题的消息 |
| requestId | String | 否 | 请求去重标识；同一次操作重试时复用 |

**请求示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>HTTP<br />
POST /openapi/agents/chat/title/summary/v2</p>
<p>HTTP/1.1</p>
<p>{</p>
<p>"agentId":"project-finder",</p>
<p>"userId":"u1001",</p>
<p>"userInput":"帮我找北京市朝阳区房产转让项目",</p>
<p>"requestId":"req_title_001"</p>
<p>}</p></td>
</tr>
</tbody>
</table>

<span id="_Toc29898" class="anchor"></span>**响应参数**

|             |        |                                             |
|:------------|:-------|:--------------------------------------------|
| 参数名      | 类型   | 说明                                        |
| code        | String | 0成功，其他为错误                           |
| message     | String | 结果说明                                    |
| data.chatId | String | 原业务会话ID                                |
| data.title  | String | 生成并保存的会话标题；本业务约定1至20个字符 |

**响应示例**

<table style="width:88%;">
<colgroup>
<col style="width: 88%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: left;"><p>JSON<br />
{</p>
<p>"code":"200",</p>
<p>"message":"会话标题生成成功",</p>
<p>"data":</p>
<p>{</p>
<p>"chatId":"110865",</p>
<p>"title":"北京朝阳区房转让项目筛选"</p>
<p>}</p>
<p>}</p></td>
</tr>
</tbody>
</table>
