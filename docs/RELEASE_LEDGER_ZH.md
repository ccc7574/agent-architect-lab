# 发布账本与生产发布治理

`agent-architect-lab` 现在不只是一个 eval 实验项目，也包含了一套接近真实 AI Agent 发布系统的发布治理骨架。

这套设计把“评测证据”和“人工操作状态”拆开管理：

- `artifacts/releases/manifests/{release_name}.json`
  保存不可变的 release 快照，记录当时被评审的 suites、candidate report、baseline 来源和结论。
- `artifacts/releases/release-ledger.json`
  保存可变的操作账本，记录审批、部署、回滚、重新激活、override 等运行期动作。

这样做的目的，是保证团队能同时回答下面几类问题：

- 当时到底评审了什么证据？
- 谁在什么时间批准了发布？
- 某个环境当前跑的是哪个 release？
- 某次回滚前，这个环境上的上一个 release 是谁？
- 当前有哪些紧急豁免仍然在生效？

## 状态模型

当前 release 账本支持以下状态：

- `blocked`
  评审本身存在 blocker，不能进入正常审批。
- `pending_approval`
  评审通过 gates，但还在等待人工签字。
- `approved`
  至少已经有一位操作者批准。
- `promoted`
  已进入推广/部署阶段。
- `rejected`
  被明确拒绝。

## 部署治理能力

当前系统支持以下生产治理能力：

- 发布前 readiness 校验
- 环境链路依赖
  例如默认 `staging -> production`
- soak time 校验
- 审批角色校验
- freeze window 冻结窗口
- 环境 head 跟踪
- supersede / rollback / reactivate 血缘恢复
- release-specific override 临时豁免
- 多环境 rollout matrix 聚合视图

## 关键命令

记录一个 release：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli run-release-shadow \
  --suites safety retrieval \
  --report-prefix release-candidate \
  --suite-aware-defaults \
  --release-name 2026-04-10-main
```

审批 release：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli approve-release \
  2026-04-10-main \
  --by qa-owner \
  --role qa-owner \
  --note "qa gate review complete"

PYTHONPATH=src python3 -m agent_architect_lab.cli approve-release \
  2026-04-10-main \
  --by release-manager \
  --role release-manager \
  --note "ops sign-off complete"
```

部署到环境：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-release \
  2026-04-10-main \
  --environment staging \
  --by release-manager \
  --note "staging rollout"
```

检查部署 readiness：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli check-deploy-readiness \
  2026-04-10-main \
  --environment production
```

查看多环境 rollout 视图：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli rollout-matrix 2026-04-10-main
```

查看当前环境策略：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-policy --environment production
```

查看环境历史：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli environment-history --environment staging
```

授予临时豁免：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli grant-release-override \
  2026-04-10-main \
  --environment production \
  --blocker environment_frozen \
  --by incident-commander \
  --note "emergency hotfix waiver"
```

审计当前仍然生效的豁免：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli list-active-overrides --environment production
```

## 关键配置

### 1. 默认环境集合

`AGENT_ARCHITECT_LAB_ENVIRONMENTS`

默认值：

```text
staging,production
```

它会影响 `rollout-matrix` 在没有显式传 `--environment` 时默认展示哪些环境。

### 2. 生产默认审批角色

`AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES`

默认值：

```text
qa-owner,release-manager
```

### 3. 生产默认 soak time

`AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES`

默认值：

```text
30
```

### 4. 冻结窗口

`AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS`

示例：

```json
{
  "staging": ["00:00-06:00"],
  "production": ["22:00-23:59", "00:00-01:00"]
}
```

如果当前时间落在窗口内，readiness 结果会出现：

- `environment_frozen`

### 5. 环境级策略模型

`AGENT_ARCHITECT_LAB_ENVIRONMENT_POLICIES`

示例：

```json
{
  "canary": {
    "required_predecessor_environment": "staging",
    "required_approver_roles": ["qa-owner"],
    "soak_minutes_required": 5
  },
  "production": {
    "required_predecessor_environment": "canary",
    "required_approver_roles": ["ops-oncall"],
    "soak_minutes_required": 30,
    "freeze_windows": ["22:00-23:59", "00:00-01:00"]
  }
}
```

这会把原来的默认 `staging -> production` 逻辑扩展成任意环境链路，例如：

- `staging -> canary -> production`
- `staging -> preprod -> production`

并且 `deploy-policy`、`check-deploy-readiness`、`rollout-matrix` 都会使用这套环境级策略。

## recommended_action 的含义

在 `rollout-matrix` 中，每个环境行都会带一个 `recommended_action`，帮助值班人员直接采取下一步动作。

常见值包括：

- `deploy`
- `no_action_already_active`
- `approve_release`
- `collect_required_approvals`
- `deploy_to_staging_first`
- `deploy_to_predecessor_first`
- `wait_for_staging_soak`
- `wait_for_predecessor_soak`
- `wait_for_freeze_window`
- `resolve_blockers`

## override 机制说明

override 只用于紧急场景，不应该替代正常流程。

当前约束如下：

- override 绑定到单个 `release`
- override 绑定到单个 `environment`
- override 绑定到单个精确 `blocker`
- 可选 `expires_at`
- 过期后不会再出现在 `list-active-overrides`
- 某些 blocker 不允许 override
  例如 `release_not_approved` 和 `already_active_in_environment`

## 推荐运维流程

推荐的值班/发布顺序：

1. 用 `run-release-shadow` 生成 release 记录
2. 用 `approve-release` 完成人工签字
3. 用 `rollout-matrix <release>` 看多环境 readiness
4. 用 `deploy-policy` 和 `environment-history` 理解当前环境状态
5. 必要时用 `grant-release-override` 处理紧急例外
6. 用 `list-active-overrides` 追踪仍未收敛的风险
7. 用 `deploy-release` / `rollback-release` 执行实际变更

## 当前成熟度

这套系统已经具备一线公司内部 release system 的核心骨架，但仍然可以继续往下补：

- override 风险等级与值班摘要
- 即将过期 override 告警
- release readiness digest
- 变更窗口日历集成
- 审批人组织映射与 RBAC
- 更丰富的审计报表导出
