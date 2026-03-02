# 规则：Conventional Commit

所有 Git 提交必须遵循 Conventional Commits 规范。

## 格式

```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

## 类型

| type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修复 bug |
| `refactor` | 重构（不改变行为） |
| `test` | 测试相关 |
| `docs` | 文档变更 |
| `chore` | 构建/工具变更 |

## 示例

```
feat(agents): add PromptAssembler for atomic prompt composition
fix(memory): correct _index.md tag dedup logic
refactor(pipeline): remove path-c gate from run_multi_agent_pipeline
```
