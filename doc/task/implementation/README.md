> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# Implementation Archive Index

文档层级：`L3-ARCHIVE`  
最后更新：`2026-02-28`

## 1. 目录定位

`doc/task/implementation/` 存放各 WS 任务在不同阶段产出的实施记录与证据快照。

这些文档用于：

- 历史回溯（为什么当时这样做）
- 证据审计（当时跑了什么验证）
- 迁移对账（旧路径到新主链的映射）

这些文档不用于：

- 当前主链设计口径
- 当前运行态接口/端口权威说明
- 当前发布门禁直接放行

## 2. 使用规则

1. 先读 `L0/L2` 文档，再按需进入 `L3`。
2. 发现 `L3` 与当前行为冲突时，以 `L0/L2` 为准。
3. 需要把历史结论转为当前结论时，必须补跑当前回归并产出新证据。

## 3. 当前权威入口（非本目录）

- `doc/01-module-overview.md`
- `doc/05-dev-startup-and-index.md`
- `doc/task/25-subagent-development-fabric-status-matrix.md`
- `doc/task/runbooks/INDEX.md`
