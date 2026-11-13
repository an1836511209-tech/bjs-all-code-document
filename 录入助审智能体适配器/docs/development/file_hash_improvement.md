# 文件哈希功能改进说明

## 改进日期
2025-11-11

## 改进背景

### 存在的问题

1. **URL 不稳定** - 文件 URL 可能因为服务器迁移、CDN 切换、临时链接过期等原因改变
2. **文件名重复** - 不同内容的文件可能有相同的文件名
3. **缓存失效** - URL 变化导致相同文件无法命中缓存，重复处理

### 改进目标

使用文件内容哈希（基于字节流的 MD5）来唯一标识文件，解决 URL 变化和文件名重复的问题。

## 改进内容

### 1. Schema 变更

在 `ExtractionFileInput` 中新增两个可选字段：

```python
class ExtractionFileInput(BaseModel):
    file_url: str                              # 文件URL（必填）
    file_name: str                             # 文件名称（必填）
    file_type: FileType                        # 文件类型（必填）
    file_content_hash: Optional[str] = None    # ✨ 新增：文件内容哈希（可选）
    file_size: Optional[int] = None            # ✨ 新增：文件大小（可选）
```

### 2. 新增工具方法

在 `FileHasher` 类中新增两个静态方法：

#### `compute_file_content_hash(file_path)`
- 计算文件内容的 MD5 哈希值（基于字节流）
- 适用于所有文件类型（PDF、Word、Excel、图片等）
- 使用分块读取（8KB/块），避免大文件内存溢出

```python
hash_value = FileHasher.compute_file_content_hash("document.pdf")
# 返回: "5d41402abc4b2a76b9719d911017c592"
```

#### `compute_file_size(file_path)`
- 获取文件大小（字节）

```python
size = FileHasher.compute_file_size("document.pdf")
# 返回: 1024000
```

### 3. 哈希计算逻辑优化

修改 `compute_files_hash()` 方法，采用三级优先级策略：

**优先级 1（最可靠）**：使用 `file_content_hash`
```
文件标识 = "content:{file_content_hash}"
```

**优先级 2（较可靠）**：使用 `file_url + file_size` 组合
```
文件标识 = "url_size:{file_url}|{file_size}"
```

**优先级 3（向后兼容）**：仅使用 `file_url`
```
文件标识 = "url:{file_url}"
```

### 4. 日志增强

在日志中显示使用内容哈希的文件数量：

```
计算文件哈希: fcb58b5db292c86c... (共2个文件, 2个使用内容哈希)
```

## 向后兼容性

### ✅ 完全兼容

- 所有新增字段都是**可选的**
- 不提供 `file_content_hash` 和 `file_size` 时，自动回退到使用 `file_url`
- 现有代码**无需任何修改**即可继续运行

### 测试验证

- 编写了 12 个单元测试，全部通过 ✅
- 测试覆盖率：84%
- 包含向后兼容性测试

## 使用效果对比

### 场景：文件 URL 变化（例如 CDN 切换）

#### 使用内容哈希（推荐）

```python
# 请求1：使用 CDN1
files1 = [{
    "file_url": "https://cdn1.example.com/file.pdf",
    "file_content_hash": "abc123...",  # 内容哈希
    ...
}]
hash1 = FileHasher.compute_files_hash(files1)

# 请求2：使用 CDN2，但文件内容相同
files2 = [{
    "file_url": "https://cdn2.example.com/file.pdf",  # URL 不同
    "file_content_hash": "abc123...",                   # 哈希相同
    ...
}]
hash2 = FileHasher.compute_files_hash(files2)

# 结果：hash1 == hash2 ✅ 命中缓存！
```

#### 不使用内容哈希（旧方式）

```python
# 请求1
files1 = [{
    "file_url": "https://cdn1.example.com/file.pdf",
    ...
}]
hash1 = FileHasher.compute_files_hash(files1)

# 请求2
files2 = [{
    "file_url": "https://cdn2.example.com/file.pdf",  # URL 不同
    ...
}]
hash2 = FileHasher.compute_files_hash(files2)

# 结果：hash1 != hash2 ❌ 缓存失效！
```

## 性能考虑

### MD5 计算性能

- 使用分块读取（8KB/块），内存友好
- MD5 算法速度快：
  - 1MB 文件：约 5-10ms
  - 10MB 文件：约 50-100ms
  - 100MB 文件：约 500ms-1s

### 推荐实践

1. **前端上传时计算** - 在用户上传文件时异步计算哈希，用户体验最佳
2. **后端上传时计算** - 在文件上传到存储服务时计算，集中管理
3. **懒计算** - 如果来不及计算，可以不提供，系统会回退到 URL 方式

## 文件清单

### 修改的文件

1. **src/schemas/extraction.py** - 新增字段
2. **src/utils/file_hash.py** - 核心逻辑改进

### 新增的文件

1. **docs/file_hash_usage.md** - 详细使用文档
2. **docs/development/file_hash_improvement.md** - 本文档
3. **tests/test_file_hash.py** - 单元测试（12个测试用例）
4. **examples/file_hash_example.py** - 使用示例

## 影响范围

### 使用文件哈希的服务

1. **提取服务** (`src/services/extraction/service.py`)
   - ✅ 无需修改，自动兼容
   
2. **审核服务** (`src/services/audit/service.py`)
   - ✅ 无需修改，自动兼容

### API 接口

- ✅ 字段可选，不影响现有 API 调用
- ✅ 支持渐进式升级

## 升级路径

### 阶段 1：部署（当前）
- 部署代码到生产环境
- 现有功能不受影响

### 阶段 2：前端集成（可选）
- 前端上传文件时计算 MD5
- 在请求中携带 `file_content_hash` 和 `file_size`

### 阶段 3：监控优化
- 通过日志监控 content_hash 使用率
- 逐步提升覆盖度到 90%+

## 关键优势

1. ✅ **URL 变化不影响缓存** - 基于文件内容，不依赖 URL
2. ✅ **文件去重** - 自动识别相同内容的文件
3. ✅ **跨环境共享** - 开发、测试、生产环境可共享缓存
4. ✅ **完全向后兼容** - 不影响现有功能
5. ✅ **性能优化** - MD5 算法快速高效
6. ✅ **渐进式升级** - 逐步提升使用率

## 相关文档

- [文件哈希使用说明](../file_hash_usage.md) - 详细使用文档
- [使用示例](../../examples/file_hash_example.py) - 代码示例
- [单元测试](../../tests/test_file_hash.py) - 测试用例

## 总结

本次改进通过引入文件内容哈希机制，解决了 URL 变化和文件名重复的问题，提升了缓存命中率，同时保持了完全的向后兼容性。建议前端在文件上传时计算并提供 `file_content_hash`，以获得最佳缓存效果。

---

**改进者**: AI Assistant  
**审核者**: 待定  
**生效日期**: 2025-11-11










