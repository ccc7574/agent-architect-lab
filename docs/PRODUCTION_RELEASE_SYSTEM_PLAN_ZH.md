# 生产级 Release System Review 与计划

这份文档把 `agent-architect-lab` 当成一套正在走向真实内部发布系统的工程来审视，而不是普通实验室项目。

## 当前已经具备的强项

- release candidate 用不可变 manifest 保存，后续操作状态放在独立的 mutable ledger 中
- deploy readiness 已经覆盖前置环境、soak time、required approver roles、freeze windows、override、rollback、environment lineage
- 已经有面向值班的 release risk、approval backlog、override remediation、handoff history、incident queue 等看板
- 交接数据不仅能生成 JSON，还能留档、回看，并导出为 Markdown 报告
- incident 到 eval backfill 的建议流已经存在，现在 incident 本身也有独立 ledger 和状态机
- 与治理相关的 CLI 和核心路径已经有较完整的自动化测试覆盖

## 核心结论

1. release governance 已经较强，但 control plane 仍然主要停留在 CLI 形态。
   这对本地演练足够，但距离真实生产还缺 API/service 边界、权限分层和后台处理能力。

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

### Phase 3: Service-Grade Control Plane

目标：从“本地 CLI 系统”升级到“更像内部服务”的形态。

- 提供轻量 HTTP 或 MCP control surface
- 按 operator role 做读写边界和权限分层
- 把 read-only dashboard 和 state-changing action 分开

### Phase 4: Runtime Realism

目标：让仓库更接近一线 AI 公司对 AI 架构师的真实要求。

- 把 model-backed planner provider 纳入自动化测试
- 增加 live-model shadow run 和 policy validation
- 增加受边界约束的 multi-agent orchestration 示例

## 推荐推进顺序

1. 先补 incident / governance artifact bundle 导出
2. 再把 incident close 条件和 follow-up eval 绑定做严
3. 再补主管视角的摘要层
4. 然后推进 control plane service 化
5. 最后加强 runtime realism

## 这个仓库何时算“对当前 scope 足够生产级”

当满足下面这些条件时，可以认为它对当前目标已经足够接近生产：

- 每个 operator 动作都有审计轨迹
- 每个 release blocker 都有治理路径
- 每个 incident 都有明确生命周期和 follow-up eval 关联
- 每次 shift handoff 都能被留档并导出为可读文档
- 所有关键治理路径都有自动化测试覆盖
- 剩余差距主要在部署形态，而不是 control-plane 逻辑缺失
