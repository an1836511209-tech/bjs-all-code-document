# 北交所录入助审系统API接口文档

## 文档信息

- **版本**: 1.0.0
- **联系方式**: support@example.com
- **最后更新**: 2025-10-22

## 系统概述

北交所信息披露智能录入和助审系统接口文档

### 主要功能模块
- 服务健康检查
- 文件质量检测
- 字段信息提取（同步/流式）
- 字段规则审核（同步/流式）
- 任务管理
- 规则配置管理

### 技术特点
- RESTful API设计
- 支持SSE流式响应
- 统一的响应格式
- 完善的错误处理
- JWT身份认证

## 服务器地址

| 环境 | 地址 |
|------|------|
| 生产环境 | https://api.example.com/api/v1 |
| 测试环境 | https://api-staging.example.com/api/v1 |
| 开发环境 | http://localhost:8580/api/v1 |

## 认证方式

所有接口都需要JWT Token认证，在请求头中添加：

```
Authorization: Bearer <token>
```

## 通用响应格式

### 成功响应

```json
{
  "code": 200,
  "message": "success",
  "traceId": "trace_20251022100001",
  "timestamp": "2025-10-22T10:00:00Z",
  "data": {
    // 业务数据
  }
}
```

### 错误响应

```json
{
  "code": 400,
  "message": "Bad Request",
  "traceId": "trace_20251022100001",
  "timestamp": "2025-10-22T10:00:00Z",
  "error": {
    "errorCode": "INVALID_PARAMETER",
    "errorMessage": "请求参数验证失败",
    "details": [
      {
        "field": "files",
        "message": "files字段不能为空"
      }
    ]
  }
}
```

---

# 接口列表

## 0. 服务健康检查

### 0.1 智能体健康检查

**接口地址**: `GET /health`

**接口描述**: 检查智能体服务是否正常运行，用于负载均衡探活、部署验收和运维监控。该接口挂载在服务根路径，不在 `/api/v1` 前缀下。

**请求方式**: GET

**认证要求**: 无需 JWT Token

**请求参数**: 无

**请求示例**:

```http
GET /health HTTP/1.1
Host: localhost:8580
```

```bash
curl http://localhost:8580/health
```

**响应参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| status | String | 服务状态，正常时为 `healthy` |
| service | String | 服务名称 |
| version | String | 服务版本号 |
| timestamp | String | 响应时间（UTC，ISO 8601 格式） |

**响应示例 - 成功**:

```json
{
  "status": "healthy",
  "service": "北交所录入助审系统",
  "version": "1.0.0",
  "timestamp": "2025-10-22T10:00:00Z"
}
```

**响应示例 - 服务不可用**:

服务进程未启动或端口不可达时，请求方将收到连接失败（如 HTTP 502/504），不会返回上述 JSON 结构。

**各环境地址**:

| 环境 | 地址 |
|------|------|
| 开发环境 | http://localhost:8580/health |
| 测试环境 | https://api-staging.example.com/health |
| 生产环境 | https://api.example.com/health |

---

## 1. 文件质量检测

### 1.1 文件质量检测

**接口地址**: `POST /file/quality-check`

**接口描述**: 同步检测上传附件的质量，包括清晰度、分辨率、遮挡检测等。支持PDF和图片格式文件。

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| files | Array | 是 | 待检测的文件列表（FileInput对象数组） |
| requestId | String | 否 | 请求唯一标识，用于幂等性控制 |

**files数组元素**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| fileUrl | String | 否 | 文件URL地址（与fileStream二选一，必须提供其中一个） |
| fileStream | String | 否 | 文件流（Base64编码或Data URI，与fileUrl二选一） |
| fileName | String | 是 | 文件名称 |
| fileType | String | 否 | 业务文件类型（见下方文件类型字典）；未传时响应回显为 null |

**文件类型字典**:

| 字典值 | 说明 |
|--------|------|
| info_disclosure_application | 信息披露申请书 |
| evaluation_report | 评估报告或其他定价文件 |
| evaluation_filing | 评估备案表/核准文件 |
| internal_decision | 内部决议或有权批准机构决策文件 |
| business_license | 营业执照/事业单位法人证书 |
| asset_list | 资产清单 |
| inspection_management | 踏勘管理办法/踏勘确认书 |
| property_certificate | 房屋产权所有证/不动产权证/国有土地使用证 |
| land_use_contract | 国有建设用地使用权出让合同 |
| vehicle_certificate | 行驶证/机动车登记证书（限机动车） |
| ship_certificate | 船舶所有权证书/船舶检验证书/船舶国籍证明（限船舶） |
| aircraft_certificate | 适航证/电台执照/国籍登记证（限飞机） |
| patent_certificate | 专利证书 |

**请求示例**:

```json
{
  "files": [
    {
      "fileUrl": "https://example.com/files/application.pdf",
      "fileName": "信息披露申请书.pdf",
      "fileType": "info_disclosure_application"
    },
    {
      "fileStream": "data:image/png;base64,iVBORw0KGgoAAAANS...",
      "fileName": "房屋所有权证.png",
      "fileType": "property_certificate"
    }
  ],
  "requestId": "req_20251022100001"
}
```

**响应参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| data | Array | 检测结果列表 |

**data数组元素**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| fileId | String | 文件ID |
| fileName | String | 文件名称 |
| qualityStatus | String | 质量状态：passed, warning, failed |
| qualityResult | Object | 质量检测详细结果 |
| message | String | 检测结果消息 |

**qualityResult对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| clarity | String | 清晰度检测结果：passed, failed |
| clarityScore | Number | 清晰度分数（BRISQUE: 0-100，越低越好） |
| resolution | String | 分辨率检测结果：passed, failed |
| resolutionValue | String | 分辨率值，如"1920x1080" |
| occlusion | String | 遮挡检测结果：passed, failed |
| occlusionScore | Number | 遮挡分数（0-1，越低越好） |

**响应示例**:

```json
{
  "code": 200,
  "message": "success",
  "traceId": "trace_20251022100001",
  "timestamp": "2025-10-22T10:00:00Z",
  "data": [
    {
      "fileId": "file_20251022100001",
      "fileName": "信息披露申请书.pdf",
      "qualityStatus": "passed",
      "qualityResult": {
        "clarity": "passed",
        "clarityScore": 32.5,
        "resolution": "passed",
        "resolutionValue": "2480x3508",
        "occlusion": "passed",
        "occlusionScore": 0.01
      },
      "message": "文件质量校验通过"
    }
  ]
}
```

### 1.2 文件预览

**接口地址**: `GET /file/preview`

**接口描述**: 生成文件预览图片，支持坐标标注和高亮。用于展示字段提取和审核的来源位置。

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| fileUrl | String | 是 | 文件URL |
| coordinates | String | 否 | 坐标信息（JSON格式） |
| highlight | Boolean | 否 | 是否高亮标注，默认true |

**请求示例**:

```
GET /file/preview?fileUrl=https://example.com/file.pdf&coordinates={"x":100,"y":200,"width":300,"height":50}&highlight=true
```

**响应**: 返回图片二进制数据（image/png 或 image/jpeg）

---

## 2. 字段信息提取

### 2.1 同步字段提取

**接口地址**: `POST /extraction/sync`

**接口描述**: 从多个附件中同步提取字段信息，返回完整结果。如果处理时间超过timeout，将返回taskId供后续查询。

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| extractionType | String | 是 | 业务类型枚举值：有纸大宗实物、无纸大宗实物、有纸小宗实物、无纸小宗实物 |
| files | Array | 是 | 待提取的文件列表（FileInput对象数组） |
| taskId | String | 否 | 任务ID（用于继续未完成的任务） |
| ruleConfigId | String | 否 | 规则配置ID（不传则使用默认规则） |
| timeout | Integer | 否 | 超时时间（毫秒），默认1000 |
| requestId | String | 否 | 请求唯一标识 |

**请求示例**:

```json
{
  "extractionType": "有纸大宗实物",
  "files": [
    {
      "fileUrl": "https://example.com/files/application.pdf",
      "fileName": "信息披露申请书.pdf",
      "fileType": "info_disclosure_application"
    },
    {
      "fileUrl": "https://example.com/files/certificate.pdf",
      "fileName": "房屋所有权证.pdf",
      "fileType": "property_certificate"
    }
  ],
  "ruleConfigId": "rule_dzswv10",
  "timeout": 1000,
  "requestId": "req_20251022100002"
}
```

**响应参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| data | Object | 提取结果 |

**data对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| taskId | String | 任务ID |
| status | String | 任务状态：completed, timeout, failed |
| extractionType | String | 业务类型 |
| fields | Array | 提取的字段列表 |
| processingTime | Integer | 处理时间（毫秒） |

**fields数组元素**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| fieldId | String | 字段ID |
| fieldName | String | 字段名称（系统字段名） |
| fieldType | String | 字段类型：text, single_choice, multiple_choice |
| values | Array | 从不同来源提取的值列表（ExtractedFieldValue对象数组） |

**values数组元素（ExtractedFieldValue）**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| sourceFileType | String | 来源文件类型 |
| sourceFileName | String | 来源文件名 |
| sourceFieldName | String | 来源字段名（原文件中的字段名） |
| extractedValue | String/Array | 提取的值（text类型为String，single_choice为String，multiple_choice为String数组） |
| extractStatus | String | 提取状态：success, failed, partial |
| confidence | Number | 置信度（0-1） |
| sources | Array | 详细溯源信息列表 |

**sources数组元素**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| sourceFileType | String | 来源文件类型 |
| sourceFileName | String | 来源文件名 |
| sourceField | String | 来源字段名 |
| sourceContent | String | 来源内容 |
| previewImageUrl | String | 文档原文预览图片URL |
| coordinates | Object | 坐标信息{x: Integer, y: Integer, width: Integer, height: Integer} |
| confidence | Number | 置信度（0-1） |

**响应示例**:

```json
{
  "code": 200,
  "message": "success",
  "traceId": "trace_20251022100002",
  "timestamp": "2025-10-22T10:05:00Z",
  "data": {
    "taskId": "task_20251022100002",
    "status": "completed",
    "extractionType": "有纸大宗实物",
    "fields": [
      {
        "fieldId": "field_20251022100001",
        "fieldName": "坐落位置",
        "fieldType": "text",
        "values": [
          {
            "sourceFileType": "info_disclosure_application",
            "sourceFileName": "信息披露申请书.pdf",
            "sourceFieldName": "坐落位置",
            "extractedValue": "北京市朝阳区建国路1号",
            "extractStatus": "success",
            "confidence": 0.95,
            "sources": [
              {
                "sourceFileType": "info_disclosure_application",
                "sourceFileName": "信息披露申请书.pdf",
                "sourceField": "坐落位置",
                "sourceContent": "坐落位置:北京市朝阳区建国路1号",
                "previewImageUrl": "https://example.com/preview/file1_page1.png",
                "coordinates": {
                  "x": 100,
                  "y": 200,
                  "width": 300,
                  "height": 50
                },
                "confidence": 0.95
              }
            ]
          },
          {
            "sourceFileType": "property_certificate",
            "sourceFileName": "房屋所有权证.pdf",
            "sourceFieldName": "房屋坐落",
            "extractedValue": "北京市朝阳区建国路1号",
            "extractStatus": "success",
            "confidence": 0.92,
            "sources": [
              {
                "sourceFileType": "property_certificate",
                "sourceFileName": "房屋所有权证.pdf",
                "sourceField": "房屋坐落",
                "sourceContent": "房屋坐落:北京市朝阳区建国路1号",
                "previewImageUrl": "https://example.com/preview/file2_page1.png",
                "coordinates": {
                  "x": 150,
                  "y": 250,
                  "width": 280,
                  "height": 45
                },
                "confidence": 0.92
              }
            ]
          }
        ]
      }
    ],
    "processingTime": 5200
  }
}
```

### 2.2 流式字段提取

**接口地址**: `POST /extraction/stream`

**接口描述**: 使用Server-Sent Events (SSE)流式返回字段提取结果。客户端需要处理SSE事件流。

**请求参数**: 与同步提取接口相同

**响应格式**: `text/event-stream`

**事件类型**:

| 事件类型 | 说明 | 数据格式 |
|---------|------|---------|
| task_start | 任务开始 | `{"taskId":"task_123","totalFields":10}` |
| field_progress | 字段处理进度 | `{"fieldId":"field_1","fieldName":"坐落位置","progress":0.3}` |
| field_complete | 单个字段完成 | 完整的字段结果对象 |
| task_complete | 任务完成 | `{"taskId":"task_123","status":"completed"}` |
| error | 错误事件 | `{"fieldId":"field_1","error":"错误信息"}` |

**响应示例**:

```
event: task_start
data: {"taskId":"task_123","totalFields":10}

event: field_progress
data: {"fieldId":"field_1","fieldName":"坐落位置","progress":0.3}

event: field_complete
data: {"fieldId":"field_1","fieldName":"坐落位置","extractedValue":"北京市朝阳区xxx","confidence":0.95}

event: task_complete
data: {"taskId":"task_123","status":"completed"}
```

---

## 3. 字段规则审核

### 3.1 同步规则审核

**接口地址**: `POST /audit/sync`

**接口描述**: 对用户确认的字段和附件进行规则审核，返回完整审核结果。支持数据交叉验证、字段值内容审核、字段值交叉验证等多种审核类型。

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| auditType | String | 是 | 业务类型枚举值：有纸大宗实物、无纸大宗实物、有纸小宗实物、无纸小宗实物 |
| confirmedFields | Array | 是 | 用户确认后的字段列表 |
| files | Array | 否 | 审核参考文件列表（FileInput对象数组），可为空。某些审核类型（如纯字段逻辑审核）可能不需要附件 |
| taskId | String | 否 | 任务ID |
| ruleConfigId | String | 否 | 规则配置ID |
| timeout | Integer | 否 | 超时时间（毫秒），默认1000 |
| requestId | String | 否 | 请求唯一标识 |

**confirmedFields数组元素**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| fieldName | String | 是 | 字段名称（系统字段名） |
| fieldType | String | 是 | 字段类型：text, single_choice, multiple_choice |
| values | Array | 是 | 不同来源的字段值列表 |

**values数组元素**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| sourceFileType | String | 是 | 来源文件类型 |
| sourceFileName | String | 否 | 来源文件名 |
| sourceFieldName | String | 否 | 来源字段名 |
| fieldValue | String/Array | 是 | 字段值（text类型为String，single_choice为String，multiple_choice为String数组）。注意：该字段接收文本内容，非字典数值 |

**请求示例**:

示例1：带附件的审核请求

```json
{
  "auditType": "有纸大宗实物",
  "confirmedFields": [
    {
      "fieldName": "坐落位置",
      "fieldType": "text",
      "values": [
        {
          "sourceFileType": "info_disclosure_application",
          "sourceFileName": "信息披露申请书.pdf",
          "sourceFieldName": "坐落位置",
          "fieldValue": "北京市朝阳区建国路1号"
        },
        {
          "sourceFileType": "property_certificate",
          "sourceFileName": "房屋所有权证.pdf",
          "sourceFieldName": "房屋坐落",
          "fieldValue": "北京市朝阳区建国路1号"
        }
      ]
    },
    {
      "fieldName": "房屋面积",
      "fieldType": "text",
      "values": [
        {
          "sourceFileType": "property_certificate",
          "sourceFileName": "房屋所有权证.pdf",
          "sourceFieldName": "建筑面积",
          "fieldValue": "150.5"
        }
      ]
    }
  ],
  "files": [
    {
      "fileUrl": "https://example.com/files/certificate.pdf",
      "fileName": "房屋所有权证.pdf",
      "fileType": "property_certificate"
    }
  ],
  "ruleConfigId": "rule_dzswv10",
  "timeout": 1000
}
```

示例2：不传附件的审核请求（纯字段逻辑审核）

```json
{
  "auditType": "有纸大宗实物",
  "confirmedFields": [
    {
      "fieldName": "房屋面积",
      "fieldType": "text",
      "fieldValue": 150.5
    },
    {
      "fieldName": "土地面积",
      "fieldType": "text",
      "fieldValue": 120.0
    }
  ],
  "files": [],
  "requestId": "req_20251209100001"
}
```

**响应参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| data | Object | 审核结果 |

**data对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| taskId | String | 任务ID |
| status | String | 任务状态：completed, timeout, failed |
| auditType | String | 业务类型 |
| auditResults | Array | 审核结果列表 |
| summary | Object | 审核结果汇总 |
| processingTime | Integer | 处理时间（毫秒） |

**auditResults数组元素**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| auditId | String | 审核ID |
| auditRuleName | String | 审核规则名称 |
| relatedFields | Array | 关联字段列表（支持多来源） |
| auditResult | String | 审核结果：passed, failed, pending |

**relatedFields数组元素**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| fieldName | String | 字段名称 |
| sources | Array | 涉及的来源列表（可选） |

**sources数组元素（在relatedFields中）**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| sourceFileType | String | 来源文件类型 |
| sourceFileName | String | 来源文件名 |
| sourceFieldName | String | 来源字段名 |

**继续auditResults字段说明**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| auditStatus | String | 审核状态：completed, processing, failed |
| auditExplanation | String | 审核说明（不通过或待确认时提供） |
| comparisonType | String | 比对方式：字段值比对, 内容审核, 交叉验证 |
| sources | Array | 审核依据溯源信息 |
| confidence | Number | 置信度（0-1） |

**sources数组元素（审核依据溯源信息）**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| sourceFileType | String | 来源文件类型 |
| sourceFileName | String | 来源文件名 |
| sourceField | String | 来源字段名 |
| sourceContent | String | 来源内容 |
| previewImageUrl | String | 文档原文预览图片URL |
| coordinates | Object | 坐标信息{x: Integer, y: Integer, width: Integer, height: Integer} |
| confidence | Number | 置信度（0-1） |

**summary对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| total | Integer | 总数 |
| passed | Integer | 通过数量 |
| failed | Integer | 不通过数量 |
| pending | Integer | 待确认数量 |

**响应示例**:

```json
{
  "code": 200,
  "message": "success",
  "traceId": "trace_20251022100003",
  "timestamp": "2025-10-22T10:10:00Z",
  "data": {
    "taskId": "task_20251022100003",
    "status": "completed",
    "auditType": "有纸大宗实物",
    "auditResults": [
      {
        "auditId": "audit_20251022100001",
        "auditRuleName": "坐落位置一致性校验",
        "relatedFields": [
          {
            "fieldName": "坐落位置",
            "sources": [
              {
                "sourceFileType": "info_disclosure_application",
                "sourceFileName": "信息披露申请书.pdf",
                "sourceFieldName": "坐落位置"
              },
              {
                "sourceFileType": "property_certificate",
                "sourceFileName": "房屋所有权证.pdf",
                "sourceFieldName": "房屋坐落"
              }
            ]
          }
        ],
        "auditResult": "passed",
        "auditStatus": "completed",
        "auditExplanation": "",
        "comparisonType": "字段值比对",
        "sources": [
          {
            "sourceFileType": "info_disclosure_application",
            "sourceFileName": "信息披露申请书.pdf",
            "sourceField": "坐落位置",
            "sourceContent": "坐落位置:北京市朝阳区建国路1号",
            "previewImageUrl": "https://example.com/preview/file1_page1.png",
            "coordinates": {
              "x": 100,
              "y": 200,
              "width": 300,
              "height": 50
            },
            "confidence": 0.95
          },
          {
            "sourceFileType": "property_certificate",
            "sourceFileName": "房屋所有权证.pdf",
            "sourceField": "房屋坐落",
            "sourceContent": "房屋坐落:北京市朝阳区建国路1号",
            "previewImageUrl": "https://example.com/preview/file2_page1.png",
            "coordinates": {
              "x": 150,
              "y": 250,
              "width": 280,
              "height": 45
            },
            "confidence": 0.92
          }
        ],
        "confidence": 0.93
      }
    ],
    "summary": {
      "total": 15,
      "passed": 12,
      "failed": 1,
      "pending": 2
    },
    "processingTime": 8500
  }
}
```

### 3.2 流式规则审核

**接口地址**: `POST /audit/stream`

**接口描述**: 使用Server-Sent Events (SSE)流式返回审核结果。每完成一条审核规则就推送一次结果。

**请求参数**: 与同步审核接口相同

**响应格式**: `text/event-stream`

**事件类型**:

| 事件类型 | 说明 | 数据格式 |
|---------|------|---------|
| task_start | 任务开始 | `{"taskId":"task_456","totalRules":15}` |
| audit_progress | 审核进度 | `{"auditId":"audit_1","auditRuleName":"坐落位置校验","progress":0.5}` |
| audit_complete | 单个审核完成 | 完整的审核结果对象 |
| task_complete | 任务完成 | `{"taskId":"task_456","status":"completed","summary":{...}}` |
| error | 错误事件 | `{"auditId":"audit_1","error":"错误信息"}` |

---

## 4. 任务管理

### 4.1 查询任务状态

**接口地址**: `GET /task/{taskId}`

**接口描述**: 查询长时间运行任务的状态和结果。支持超时后继续查询完整结果。

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| taskId | String | 是 | 任务ID |

**查询参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| includeDetails | Boolean | 否 | 是否包含详细结果，默认true |

**请求示例**:

```
GET /task/task_20251022100001?includeDetails=true
```

**响应参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| data | Object | 任务信息 |

**data对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| taskId | String | 任务ID |
| taskType | String | 任务类型：extraction, audit |
| status | String | 任务状态：pending, processing, completed, failed, timeout, cancelled |
| progress | Number | 进度（0-1） |
| result | Object | 任务结果（根据taskType不同，结构不同，extraction时为ExtractionResponse.data，audit时为AuditResponse.data） |
| createdAt | String | 创建时间（ISO 8601格式） |
| updatedAt | String | 更新时间（ISO 8601格式） |
| completedAt | String | 完成时间（ISO 8601格式） |

### 4.2 取消任务

**接口地址**: `POST /task/{taskId}/cancel`

**接口描述**: 取消正在执行的任务

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| taskId | String | 是 | 任务ID |

**响应参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| data | Object | 取消结果 |

**data对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| taskId | String | 任务ID |
| status | String | 状态：cancelled |

---

## 5. 规则配置管理

### 5.1 查询规则配置列表

**接口地址**: `GET /rules`

**接口描述**: 查询规则配置列表，支持分页和多条件筛选。可按规则类型、业务类型、状态等条件过滤。

**查询参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| ruleType | String | 否 | 规则类型：extraction, audit |
| businessType | String | 否 | 业务类型枚举值：有纸大宗实物、无纸大宗实物、有纸小宗实物、无纸小宗实物 |
| status | String | 否 | 规则状态：active, inactive |
| keyword | String | 否 | 关键字搜索 |
| page | Integer | 否 | 页码（从1开始），默认1 |
| pageSize | Integer | 否 | 每页数量，默认20，最大100 |

**请求示例**:

```
GET /rules?ruleType=extraction&businessType=有纸大宗实物&status=active&page=1&pageSize=20
```

**响应参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| data | Object | 分页结果 |

**data对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| total | Integer | 总数 |
| page | Integer | 当前页码 |
| pageSize | Integer | 每页数量 |
| items | Array | 规则列表 |

**items数组元素**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| ruleId | String | 规则ID |
| ruleName | String | 规则名称 |
| ruleType | String | 规则类型：extraction, audit |
| businessType | String | 业务类型 |
| status | String | 状态：active, inactive |
| version | String | 版本号 |
| createdBy | String | 创建人 |
| createdAt | String | 创建时间（ISO 8601格式） |
| updatedAt | String | 更新时间（ISO 8601格式） |

### 5.2 获取规则配置详情

**接口地址**: `GET /rules/{ruleId}`

**接口描述**: 获取指定规则配置的详细信息

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| ruleId | String | 是 | 规则ID |

**响应参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| data | Object | 规则详情 |

**data对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| ruleId | String | 规则ID |
| ruleName | String | 规则名称 |
| ruleType | String | 规则类型：extraction, audit |
| businessType | String | 业务类型 |
| status | String | 状态：active, inactive |
| version | String | 版本号 |
| ruleConfig | Object | 规则配置详情 |
| createdBy | String | 创建人 |
| createdAt | String | 创建时间（ISO 8601格式） |
| updatedAt | String | 更新时间（ISO 8601格式） |

**ruleConfig对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| fields | Array | 字段配置列表（用于提取规则） |
| auditRules | Array | 审核规则列表（用于审核规则） |

**fields数组元素**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| fieldName | String | 字段名称 |
| fieldType | String | 字段类型：text, single_choice, multiple_choice |
| required | Boolean | 是否必填 |
| extractionLogic | String | 提取逻辑（自然语言描述） |
| sourceFiles | Array | 来源文件名列表（字符串数组） |
| sourceFieldNames | Array | 来源字段名列表（字符串数组） |
| validationRules | Array | 校验规则（字符串数组） |
| defaultValue | String | 默认值 |
| priority | Integer | 优先级 |

**auditRules数组元素**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| auditRuleName | String | 审核规则名称 |
| relatedFields | Array | 关联字段（字符串数组） |
| referenceFiles | Array | 审核参考文件（字符串数组） |
| referenceFieldNames | Array | 参考字段名（字符串数组） |
| auditContent | String | 审核内容（自然语言描述） |
| comparisonType | String | 比对方式：字段值比对, 内容审核, 交叉验证 |
| autoProcessingLogic | String | 自动处理逻辑 |

### 5.3 创建规则配置

**接口地址**: `POST /rules`

**接口描述**: 创建新的规则配置

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| ruleName | String | 是 | 规则名称 |
| ruleType | String | 是 | 规则类型：extraction, audit |
| businessType | String | 是 | 业务类型枚举值：有纸大宗实物、无纸大宗实物、有纸小宗实物、无纸小宗实物 |
| ruleConfig | Object | 是 | 规则配置详情 |
| status | String | 否 | 状态，默认active |
| version | String | 否 | 版本号 |

**请求示例**:

```json
{
  "ruleName": "有纸大宗实物提取规则v1.0",
  "ruleType": "extraction",
  "businessType": "有纸大宗实物",
  "status": "active",
  "version": "1.0",
  "ruleConfig": {
    "fields": [
      {
        "fieldName": "坐落位置",
        "fieldType": "text",
        "required": true,
        "extractionLogic": "从《信息披露申请书》中按字段值录入坐落位置信息",
        "sourceFiles": ["信息披露申请书.pdf"],
        "sourceFieldNames": ["坐落位置", "房屋坐落"],
        "validationRules": ["非空校验"],
        "priority": 1
      }
    ]
  }
}
```

**响应参数**: 返回创建成功的完整规则信息

### 5.4 更新规则配置

**接口地址**: `PUT /rules/{ruleId}`

**接口描述**: 更新规则配置，支持部分更新。只需传入需要更新的字段。

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| ruleId | String | 是 | 规则ID |

**请求参数**: 与创建接口类似，但所有字段都是可选的

**响应参数**: 返回更新后的完整规则信息

### 5.5 删除规则配置

**接口地址**: `DELETE /rules/{ruleId}`

**接口描述**: 删除规则配置，默认软删除。设置hardDelete=true进行物理删除。

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| ruleId | String | 是 | 规则ID |

**查询参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| hardDelete | Boolean | 否 | 是否物理删除，默认false |

**响应参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| data | Object | 删除结果 |

**data对象**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| ruleId | String | 规则ID |
| deleted | Boolean | 是否删除成功 |

---

## 错误码说明

### HTTP状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 201 | 创建成功 |
| 400 | 请求参数错误 |
| 401 | 未授权 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

### 业务错误码

详细的业务错误码请参考 [错误码规范.md](./错误码规范.md)

---

## 使用示例

### JavaScript示例

```javascript
// 文件质量检测
const checkQuality = async (files) => {
  const response = await fetch('/api/v1/file/quality-check', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ files })
  });
  return await response.json();
};

// 同步字段提取
const extractFields = async (extractionType, files) => {
  const response = await fetch('/api/v1/extraction/sync', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      extractionType,
      files,
      requestId: `req_${Date.now()}`
    })
  });
  return await response.json();
};

// 流式字段提取
const extractFieldsStream = async (extractionType, files, onEvent) => {
  const response = await fetch('/api/v1/extraction/stream', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ extractionType, files })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (line.startsWith('event:')) {
        const eventType = line.substring(6).trim();
        const dataLine = lines[lines.indexOf(line) + 1];
        if (dataLine && dataLine.startsWith('data:')) {
          const data = JSON.parse(dataLine.substring(5).trim());
          onEvent(eventType, data);
        }
      }
    }
  }
};
```

### Python示例

```python
import requests
import json

class BeijiaoAPIClient:
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    
    def check_file_quality(self, files):
        """文件质量检测"""
        response = requests.post(
            f'{self.base_url}/file/quality-check',
            headers=self.headers,
            json={'files': files}
        )
        return response.json()
    
    def extract_fields_sync(self, extraction_type, files, rule_config_id=None):
        """同步字段提取"""
        payload = {
            'extractionType': extraction_type,
            'files': files,
            'requestId': f'req_{int(time.time() * 1000)}'
        }
        if rule_config_id:
            payload['ruleConfigId'] = rule_config_id
            
        response = requests.post(
            f'{self.base_url}/extraction/sync',
            headers=self.headers,
            json=payload
        )
        return response.json()
    
    def get_task_status(self, task_id):
        """查询任务状态"""
        response = requests.get(
            f'{self.base_url}/task/{task_id}',
            headers={'Authorization': f'Bearer {self.token}'}
        )
        return response.json()

# 使用示例
client = BeijiaoAPIClient('https://api.example.com/api/v1', 'your-token')

# 检测文件质量
files = [
    {
        'fileUrl': 'https://example.com/file.pdf',
        'fileName': 'application.pdf',
        'fileType': 'pdf'
    }
]
result = client.check_file_quality(files)
print(result)
```

---

## 更多信息

- 完整的接口示例：[接口示例文档.md](./接口示例文档.md)
- 认证授权详情：[认证授权规范.md](./认证授权规范.md)
- 错误处理指南：[错误码规范.md](./错误码规范.md)
- 技术架构说明：[技术架构说明.md](./技术架构说明.md)
- Postman测试集合：[Postman_Collection.json](./Postman_Collection.json)

---

**文档版本**: v1.0.0  
**最后更新**: 2025-10-22  
**联系方式**: support@example.com
