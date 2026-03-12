## Review Result Contract

`review_result.verdict` 只能是：

- `approve`
- `request_changes`
- `reject`

`review_result` 至少必须包含：

- `verdict`
- `requirement_alignment: [{requirement, status, details}, ...]`
- `code_quality: {status, issues, summary}`
- `regression_risk: {level, summary}`
- `test_coverage: {status, summary, missing_cases}`
- `issues: [issue, ...]`
- `suggestions: [suggestion, ...]`
