# 文件哈希功能使用说明

## 概述

文件哈希功能用于生成文件列表的唯一标识，支持结果缓存。改进后的版本使用文件内容哈希（MD5）来唯一标识文件，解决了 URL 变化和文件名重复的问题。

## 功能特性

### 文件唯一性识别策略（优先级从高到低）

1. **文件内容哈希（推荐）** - 基于文件字节流的 MD5 哈希
   - 最可靠的方式
   - 不受 URL 变化影响
   - 不受文件名变化影响
   - 相同内容的文件始终有相同的标识

2. **URL + 文件大小组合** - 使用文件 URL 和大小的组合
   - 较可靠的方式
   - 当没有内容哈希时使用
   - 可以区分大部分不同文件

3. **仅 URL（向后兼容）** - 仅使用文件 URL
   - 保证向后兼容
   - 对于旧数据仍然有效

## API 变化

### ExtractionFileInput Schema

新增了两个可选字段：

```python
class ExtractionFileInput(BaseModel):
    file_url: str                              # 文件URL（必填）
    file_name: str                             # 文件名称（必填）
    file_type: FileType                        # 文件类型（必填）
    file_content_hash: Optional[str] = None    # 文件内容哈希（可选，推荐提供）
    file_size: Optional[int] = None            # 文件大小（可选）
```

### 请求示例

**推荐方式（提供文件内容哈希）：**

```json
{
  "extraction_type": "有纸大宗实物",
  "files": [
    {
      "file_url": "https://example.com/files/application.pdf",
      "file_name": "信息披露申请书.pdf",
      "file_type": "info_disclosure_application",
      "file_content_hash": "5d41402abc4b2a76b9719d911017c592",
      "file_size": 1024000
    }
  ]
}
```

**兼容方式（不提供文件内容哈希）：**

```json
{
  "extraction_type": "有纸大宗实物",
  "files": [
    {
      "file_url": "https://example.com/files/application.pdf",
      "file_name": "信息披露申请书.pdf",
      "file_type": "info_disclosure_application"
    }
  ]
}
```

## 工具方法使用

### 计算文件内容哈希

```python
from src.utils.file_hash import FileHasher

# 计算单个文件的内容哈希
file_path = "/path/to/document.pdf"
content_hash = FileHasher.compute_file_content_hash(file_path)
print(f"文件内容哈希: {content_hash}")  # 5d41402abc4b2a76b9719d911017c592
```

### 获取文件大小

```python
from src.utils.file_hash import FileHasher

file_path = "/path/to/document.pdf"
file_size = FileHasher.compute_file_size(file_path)
print(f"文件大小: {file_size} 字节")
```

### 计算文件列表哈希

```python
from src.utils.file_hash import FileHasher
from src.schemas.extraction import ExtractionFileInput
from src.schemas.file import FileType

# 创建文件列表（推荐方式：包含内容哈希）
files = [
    ExtractionFileInput(
        file_url="https://example.com/files/app.pdf",
        file_name="申请书.pdf",
        file_type=FileType.INFO_DISCLOSURE_APPLICATION,
        file_content_hash="5d41402abc4b2a76b9719d911017c592",
        file_size=1024000
    ),
    ExtractionFileInput(
        file_url="https://example.com/files/cert.pdf",
        file_name="证书.pdf",
        file_type=FileType.PROPERTY_CERTIFICATE,
        file_content_hash="7b8f3d4e9c1a2f5b6e0d8c7a4f3e2d1b",
        file_size=2048000
    )
]

# 计算文件列表的总体哈希
files_hash = FileHasher.compute_files_hash(
    files=files,
    extraction_type="有纸大宗实物",
    rule_config_id="rule_dzswv10"
)
print(f"文件列表哈希: {files_hash}")
```

## 前端集成建议

### 在文件上传时计算哈希

**JavaScript 示例：**

```javascript
// 使用 crypto.subtle API 计算文件 MD5
async function computeFileMD5(file) {
  // 读取文件内容
  const arrayBuffer = await file.arrayBuffer();
  
  // 计算 MD5（需要引入 js-md5 或 crypto-js 库）
  const md5Hash = md5(arrayBuffer);
  
  return md5Hash;
}

// 准备文件上传
async function prepareFileUpload(file) {
  const contentHash = await computeFileMD5(file);
  
  return {
    file_url: uploadedUrl,           // 上传后的 URL
    file_name: file.name,
    file_type: detectFileType(file),
    file_content_hash: contentHash,  // 文件内容哈希
    file_size: file.size             // 文件大小
  };
}
```

**Python 示例（如果是后端上传）：**

```python
from src.utils.file_hash import FileHasher

def prepare_file_for_extraction(file_path: str, file_name: str, file_type: str):
    """准备文件用于提取请求"""
    
    # 计算文件内容哈希和大小
    content_hash = FileHasher.compute_file_content_hash(file_path)
    file_size = FileHasher.compute_file_size(file_path)
    
    return {
        "file_url": upload_file_to_storage(file_path),  # 上传并获取 URL
        "file_name": file_name,
        "file_type": file_type,
        "file_content_hash": content_hash,
        "file_size": file_size
    }
```

## 缓存机制优化

使用文件内容哈希后，缓存机制更加可靠：

### 优势

1. **URL 变化不影响缓存** - 即使文件存储位置改变，只要内容相同，仍能命中缓存
2. **跨环境缓存共享** - 开发、测试、生产环境可以共享缓存结果
3. **文件去重** - 自动识别相同内容的文件，避免重复处理

### 示例场景

```python
# 场景1：URL 变化，但内容相同
request1 = {
    "files": [{
        "file_url": "https://cdn1.example.com/file.pdf",
        "file_content_hash": "abc123...",
        ...
    }]
}

request2 = {
    "files": [{
        "file_url": "https://cdn2.example.com/file.pdf",  # URL 不同
        "file_content_hash": "abc123...",                   # 内容哈希相同
        ...
    }]
}

# 两个请求会命中相同的缓存（因为 content_hash 相同）
```

## 性能考虑

### MD5 计算性能

- 使用分块读取（8KB/块），避免大文件内存溢出
- MD5 算法速度快，10MB 文件约需 50-100ms
- 推荐在文件上传时计算，不影响提取请求性能

### 建议

1. **前端上传时计算** - 在用户上传文件时异步计算哈希，用户体验最佳
2. **后端上传时计算** - 在文件上传到存储服务时计算，集中管理
3. **懒计算** - 如果来不及计算，可以不提供 content_hash，系统会回退到 URL 方式

## 向后兼容性

### 完全兼容

现有的请求不需要任何修改即可继续使用：

```json
{
  "extraction_type": "有纸大宗实物",
  "files": [
    {
      "file_url": "https://example.com/files/app.pdf",
      "file_name": "申请书.pdf",
      "file_type": "info_disclosure_application"
      // 不提供 file_content_hash 和 file_size
    }
  ]
}
```

系统会自动使用 `file_url` 作为文件标识，保证功能正常。

### 渐进式升级

1. **阶段1**：现有代码无需修改，继续运行
2. **阶段2**：前端逐步添加 content_hash 计算
3. **阶段3**：所有新上传文件都携带 content_hash

## 常见问题

### Q: 必须提供 file_content_hash 吗？

A: 不是必须的。这两个字段都是可选的，不提供时系统会使用 URL 作为标识，保证向后兼容。

### Q: 如果 URL 和 content_hash 都变了会怎样？

A: 如果文件内容确实改变了（导致 content_hash 变化），系统会认为这是一个新文件，不会使用旧缓存。这是正确的行为。

### Q: 可以用 SHA256 代替 MD5 吗？

A: 当前实现使用 MD5 是因为速度快，且用于文件内容识别而非安全用途。如有需要可以改为 SHA256，只需修改 `compute_file_content_hash` 方法。

### Q: 远程文件（HTTP URL）如何计算哈希？

A: 当前 `compute_file_content_hash` 仅支持本地文件。对于远程文件，建议：
1. 先下载到本地临时目录
2. 计算哈希
3. 删除临时文件

或者在文件上传到存储服务时由存储服务返回哈希值。

## 监控和日志

系统会自动记录哈希计算的详细信息：

```
计算文件哈希: a1b2c3d4e5f6... (共2个文件, 2个使用内容哈希)
```

可以通过日志监控 content_hash 的使用率，逐步提升覆盖度。

## 总结

1. ✅ **推荐提供** `file_content_hash` 和 `file_size`，获得最佳缓存效果
2. ✅ **向后兼容**，不提供也能正常工作
3. ✅ **性能优化**，建议在上传时计算哈希
4. ✅ **渐进式升级**，逐步提升使用率

---

更新日期：2025-11-11










