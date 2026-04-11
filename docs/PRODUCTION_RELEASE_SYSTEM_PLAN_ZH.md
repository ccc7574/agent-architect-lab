# 生产级 Release System Review 与计划

这份文档把 `agent-architect-lab` 当成一套正在走向真实内部发布系统的工程来审视，而不是普通实验室项目。

## 当前已经具备的强项

- release candidate 用不可变 manifest 保存，后续操作状态放在独立的 mutable ledger 中
- deploy readiness 已经覆盖前置环境、soak time、required approver roles、freeze windows、override、rollback、environment lineage
- 已经有面向值班的 release risk、approval backlog、override remediation、handoff history、incident queue 等看板
- 现在已经有轻量 HTTP control plane，并且把 read / write 路由放在 bearer token 边界之后
- mutation 路由现在也已经有 idempotency key 和请求审计能力
- 受保护路由现在也已经支持 route-level actor / role policy
- 长时间运行的导出任务现在已经走持久化 job registry + 内置 worker
- control plane 的 policy 与 mutation persistence 现在也已经拆成独立层
- 交接数据不仅能生成 JSON，还能留档、回看，并导出为 Markdown 报告
- incident 到 eval backfill 的建议流已经存在，现在 incident 本身也有独立 ledger 和状态机
- 与治理相关的 CLI 和核心路径已经有较完整的自动化测试覆盖

## 核心结论

1. 对这个仓库当前的本地/内部演练范围来说，治理 artifact 层已经基本成形。
   incident bundle、governance summary、weekly status、release runbook、operator handoff snapshot、planner shadow、release command brief 都已经能稳定导出。新一批导出还会同时产出 Markdown 和 JSON sidecar，并带显式 artifact lineage。

2. control plane 已经足够支撑 production-style drill，但仍然是单机、刻意收窄的边界。
   现在已经有 token 边界、请求重放保护、审计轨迹、route-level actor/role policy、持久化 job、lease-based worker recovery、follow-up eval linkage、backup/restore 工作流，但仍缺分布式队列、共享锁、外部数据库，以及更完整的 release-state HTTP mutation surface。

3. runtime realism 已经不再只是脚手架，但仍不是完整的 hosted release path。
   planner shadow 能验证 planner 第一步行为，bounded role handoff 也已经能把 release command ownership 结构化表达出来，但默认执行仍然以 heuristic runtime 为主，多角色模式也还停留在 artifact-level，而不是 worker-execution-level。

4. 剩余最大的缺口现在集中在 retrieval 深度和平台部署形态，feedback learning 已经从被动记录推进到了优先级层。
   当前已经把 human feedback 作为一等治理信号记录下来，并接进了 incident eval ranking 与 rollout review 上下文。retrieval 仍然主要是本地 note 的 lexical search，而且系统仍未建成分布式 control plane 或更真实的多租户服务形态。

## 已完成里程碑

- immutable release manifests + mutable release ledger
- approve / promote / deploy / rollback / lineage tracking
- environment policy inspection + rollout matrix
- override grant / review / active audit / revoke
- release readiness digest + release risk board
- approval review board
- 轻量 HTTP control plane，支持治理读接口和 incident 写接口
- operator handoff 生成、留档、历史浏览、Markdown 导出
- incident ledger、incident 状态流转、incident review board
- incident bundle 导出，关联 release、handoff、follow-up eval artifact
- governance summary、weekly status、release runbook 导出
- planner shadow validation 与 bounded release command brief 导出
- 关键治理与 runtime-realism 导出内置 artifact lineage
- 中英文 operator 文档

## 后续完整计划

### Phase 1: 加固 Control Plane 的部署形态

目标：把现在已经很强的本地 control plane，继续推进成更像真实多节点服务的形态。

- 用真实队列 + 独立 worker 进程替换当前单机 leased worker
- 把存储从本地 artifact JSON 继续推进到更真实的服务后端
- 把鉴权和策略继续升级到更完整的 RBAC 或外部 policy integration
- 增强重试、锁、恢复和一致性协调语义

### Phase 2: 深化 Runtime Realism

目标：让 hosted planner 和多角色 runtime 更接近真实发布系统。

- 把 model-backed planner provider 从 first-step shadow 扩展到端到端 release flow
- 增加在线 shadow run 和 live-model policy validation
- 把 bounded role handoff 扩展为真正的 role-specialized worker execution

### Phase 3: 加强 Knowledge 与 Feedback Loop

目标：补齐一线 AI 架构师最常被要求承担的 retrieval 与学习闭环能力。

- 把 retrieval 从 note 搜索继续推进到 provenance-aware knowledge routing
- 在已经接入 ranking 的基础上，继续把新的 human feedback ledger 扩展到更丰富的 eval generation 与 regression prioritization
- 把 prompts、tools、notes、traces、checkpoints、review decisions 继续串成更强的 lineage/analytics 视图

## 推荐推进顺序

1. 先把 control plane 的部署形态继续做实
2. 再深化 hosted planner 和多角色 runtime realism
3. 再补 retrieval provenance 与更深入的 feedback learning
4. 最后再继续扩大服务边界

## 这个仓库何时算“对当前 scope 足够生产级”

当满足下面这些条件时，可以认为它对当前目标已经足够接近生产：

- 每个 operator 动作都有审计轨迹
- 每个 release blocker 都有治理路径
- 每个 incident 都有明确生命周期和 follow-up eval 关联
- 每次 shift handoff 都能被留档并导出为可读文档
- 主要治理导出都同时带有 machine-readable lineage
- 所有关键治理路径都有自动化测试覆盖
- 剩余差距主要在部署形态，而不是 control-plane 逻辑缺失
