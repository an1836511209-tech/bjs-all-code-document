# Git 分支管理指南

 git stash pop

## 分支结构

本项目采用 Gitflow 工作流进行分支管理：

```
main (正式版本)  ─────────────────────────────────────────────>
    │                           │
    │ hotfix/*                  │ release/*
    │ (紧急修复)                 │ (发布)
    │                           │
    └───────────────────────────┘
                                ↑
develop (开发版本) ────────────────────────────────────────────>
    │
    feature/* (功能开发)
```

## 分支说明

| 分支 | 用途 | 命名规范 |
|------|------|----------|
| `main` | 正式版本，生产环境代码 | - |
| `develop` | 开发版本，最新开发代码 | - |
| `feature/*` | 新功能开发 | `feature/功能名称` |
| `release/*` | 版本发布准备 | `release/vX.Y.Z` |
| `hotfix/*` | 紧急修复 | `hotfix/vX.Y.Z` |

## 版本标签

使用语义化版本号：`vMAJOR.MINOR.PATCH`

- **MAJOR**: 不兼容的 API 变更
- **MINOR**: 向后兼容的功能新增
- **PATCH**: 向后兼容的 Bug 修复

## 常用操作

### 1. 正式版本 Bug 修复（Hotfix）

```bash
# 从 main 创建 hotfix 分支
git checkout main
git checkout -b hotfix/v1.0.1

# 修复并提交
git add .
git commit -m "fix: 修复xxx问题"

# 合并回 main 并打标签
git checkout main
git merge hotfix/v1.0.1
git tag -a v1.0.1 -m "修复xxx问题"

# 同步到 develop
git checkout develop
git merge hotfix/v1.0.1

# 清理
git branch -d hotfix/v1.0.1
```

### 2. 新功能开发（Feature）

```bash
# 从 develop 创建功能分支
git checkout develop
git checkout -b feature/新功能名称

# 开发完成后合并回 develop
git checkout develop
git merge feature/新功能名称
git branch -d feature/新功能名称
```

### 3. 发布新版本（Release）

```bash
# 从 develop 创建发布分支
git checkout develop
git checkout -b release/v1.1.0

# 测试稳定后合并到 main
git checkout main
git merge release/v1.1.0
git tag -a v1.1.0 -m "发布版本 v1.1.0"

# 同步到 develop
git checkout develop
git merge release/v1.1.0

# 清理
git branch -d release/v1.1.0
```

## 提交信息规范

格式：`type(scope): description`

| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档变更 |
| `style` | 代码格式调整 |
| `refactor` | 代码重构 |
| `test` | 添加测试 |
| `chore` | 维护任务 |

示例：
```
feat(extraction): 添加表格识别功能
fix(paddle): 修复坐标转换错误
docs: 更新 API 文档
```

## 注意事项

1. **不要直接提交到 `main` 和 `develop` 分支**
2. 合并前确保代码已测试通过
3. 每次发布到 `main` 后必须打版本标签
4. `hotfix` 修复后需同步合并到 `develop`

