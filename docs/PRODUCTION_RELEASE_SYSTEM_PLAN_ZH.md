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

1. 现在已经有 service 边界，而且 mutation 已经具备幂等、审计、route-level role policy、持久化导出任务语义，以及显式的 policy/storage 分层，但这层还比较窄。
   仓库已经具备内部 HTTP surface、读写分离的 token 边界、请求重放保护、mutation 审计轨迹、按路由校验 actor/role 的能力、集中式的内置 policy engine、repository 风格的 persistence boundary，以及持久化的内置导出 worker，但还缺分布式队列和覆盖全部状态流转的后台 worker。

2. incident 管理已经落地，但 incident closure loop 还不够完整。
   现在可以记录 incident、推进状态、挂 follow-up eval 路径，但还没有形成完整的 incident artifact bundle。

3. 治理数据已经很多，但主管/经理视角的摘要层还不够。
   目前更适合值班人员操作，还缺“本周有哪些长期卡住的 release / incident / override”这类汇总视图。

4. 仓库当前在“发布治理正确性”上强于“运行时真实感”。
   这意味着它已经很适合训练 AI 架构师的 control plane 思维，但还没完全覆盖 model-backed planner、服务化 control plane、多角色协同这些真实平台问题。

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
- 中英文 operator 文档

## 后续完整计划

### Phase 1: 治理 Artifact Bundle

目标：所有关键治理流程都能稳定产出可复用文档，而不是只给 JSON。

- 把 incident review board 导出为 Markdown
- 增加跨 release 的治理汇总报告导出
- 增加面向主管/经理的周报级状态摘要

### Phase 2: Incident Closure Loop

目标：把 incident 真正接回改进闭环。

- 增加 incident bundle 导出，关联 release、report、handoff、follow-up eval
- 在 incident close 前检查是否挂上 follow-up eval
- 增加给 incident 绑定已有 eval artifact 的 CLI 能力

### Phase 3: 加固 Service-Grade Control Plane

目标：把已经存在的内部服务边界继续加固成更像真实生产系统的控制面。

- 在 bearer token 之上继续补 role-aware policy enforcement
- 给 state-changing request 增加幂等与审计 envelope
- 给慢操作增加队列或后台 worker

### Phase 4: Runtime Realism

目标：让仓库更接近一线 AI 公司对 AI 架构师的真实要求。

- 把 model-backed planner provider 纳入自动化测试
- 增加 live-model shadow run 和 policy validation
- 增加受边界约束的 multi-agent orchestration 示例

## 推荐推进顺序

1. 先补 incident / governance artifact bundle 导出
2. 再把 incident close 条件和 follow-up eval 绑定做严
3. 再补主管视角的摘要层
4. 然后继续加固 control plane 的权限、请求语义和后台执行
5. 最后加强 runtime realism

## 这个仓库何时算“对当前 scope 足够生产级”

当满足下面这些条件时，可以认为它对当前目标已经足够接近生产：

- 每个 operator 动作都有审计轨迹
- 每个 release blocker 都有治理路径
- 每个 incident 都有明确生命周期和 follow-up eval 关联
- 每次 shift handoff 都能被留档并导出为可读文档
- 所有关键治理路径都有自动化测试覆盖
- 剩余差距主要在部署形态，而不是 control-plane 逻辑缺失
