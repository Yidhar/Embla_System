# NagaAgent 文档索引

本目录用于统一归档项目架构、开发 runbook、工具治理与目标态设计文档。

## 文档清单

1. `doc/00-mvp-architecture-design.md`
   - Phase 0 实施记录（含部分目标态草案，需按文中状态标记阅读）。
2. `doc/00-omni-operator-architecture.md`
   - Omni-Operator 目标态总蓝图（Phase 3 参考，不等价当前实现）。
3. `doc/01-module-overview.md`
   - 当前模块总览、运行链路与关键边界。
4. `doc/02-module-archive.md`
   - 模块职责归档、关键文件与风险点。
5. `doc/03-qt-migration-assessment.md`
   - Qt 前端迁移可行性评估与分阶段路线。
6. `doc/04-api-protocol-proxy-guide.md`
   - 模型协议、路由归一与代理行为说明。
7. `doc/05-dev-startup-and-index.md`
   - 开发启动 runbook、端口基线与排障清单。
8. `doc/06-structured-tool-calls-and-local-first-native.md`
   - 结构化工具调用链路与本地优先执行策略。
9. `doc/07-autonomous-agent-sdlc-architecture.md`
   - 自治 SDLC 架构、状态机与治理对齐。
10. `doc/08-frontend-backend-separation-plan.md`
    - 前后端边界收敛与分阶段解耦方案。
11. `doc/09-tool-execution-specification.md`
    - 工具调用规范、风控门禁与审计模板。
12. `doc/10-brainstem-layer-modules.md`
    - 目标态脑干层模块设计（Phase 2-3 规划）。
13. `doc/11-brain-layer-modules.md`
    - 目标态大脑层模块设计（Phase 3 规划）。
14. `doc/12-limbs-layer-modules.md`
    - 目标态手脚层模块设计（Phase 3 规划）。
15. `doc/13-security-blindspots-and-hardening.md`
    - 安全盲区审计与强制加固基线（覆盖命令混淆、插件隔离、锁泄漏、评测毒化等）。
16. `doc/task-autonomous-skeleton.md`
    - 自治骨架实施任务追踪与历史记录。
17. `doc/task/README.md`
    - 迁移与增量开发任务拆解总览（结构化工作流 + CSV backlog）。

## 建议阅读路径

1. 先读 `doc/01-module-overview.md` 与 `doc/05-dev-startup-and-index.md` 了解当前可运行基线。
2. 再读 `doc/02-module-archive.md`、`doc/04-api-protocol-proxy-guide.md`、`doc/06-structured-tool-calls-and-local-first-native.md` 对齐日常开发语义。
3. 涉及安全边界与风控落地时优先读 `doc/13-security-blindspots-and-hardening.md` 与 `doc/09-tool-execution-specification.md`。
4. 涉及自治与发布治理时读 `doc/07-autonomous-agent-sdlc-architecture.md` 与 `doc/10-brainstem-layer-modules.md`、`doc/11-brain-layer-modules.md`、`doc/12-limbs-layer-modules.md`。
5. 做中长期演进设计时再读 `doc/00-omni-operator-architecture.md`。
