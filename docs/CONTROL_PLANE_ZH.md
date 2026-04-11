# Control Plane

`agent-architect-lab` 现在已经在现有 release / incident / feedback ledger 之上提供了一个轻量 HTTP control plane。

当前 control plane 内部已经拆成四层：

- `server.py`：HTTP 路由和统一响应 envelope
- `policies.py`：集中式 route / payload policy 校验
- `repositories.py`：本地 JSON 或 SQLite persistence 的 repository bundle 装配层
- `storage.py` / `jobs.py`：持久化 repository 和带 lease 的 queue-style job 执行

## 为什么要有这一层

- 让治理能力不再只停留在 CLI
- 给 dashboard 和简单自动化提供稳定的读接口
- 明确区分 read-only view 和 state-changing action

## 启动方式

```bash
cd /Volumes/ExtaData/newcode/agent-architect-lab
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_READ_TOKEN=reader-token
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN=writer-token
PYTHONPATH=src python3 -m agent_architect_lab.cli run-control-plane-server --host 127.0.0.1 --port 8080
```

如果要让 HTTP server 与 worker 分开启动：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli run-control-plane-server --host 127.0.0.1 --port 8080 --no-worker
PYTHONPATH=src python3 -m agent_architect_lab.cli run-control-plane-worker
```

如果要用 batch 风格的 worker，也可以这样：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli run-control-plane-worker --once
PYTHONPATH=src python3 -m agent_architect_lab.cli run-control-plane-worker --idle-timeout-s 30
```

如果想不启动 HTTP server，直接在本地查看 queue depth：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli control-plane-job-queue-status
```

如果想在本地查看已经注册的 worker 以及最近一次 heartbeat：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli control-plane-workers
```

如果想查看当前落入 dead-letter 视图的失败任务：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli control-plane-dead-letter-jobs
```

如果想看一份适合 dashboard 或本地排查的紧凑 metrics 快照：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli control-plane-metrics
```

如果想看一张跨 release、incident、queue、worker 的 operator alert board：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli operator-alert-board
```

这个服务只依赖 Python 标准库，底层仍然直接复用 CLI 使用的 artifact 存储。

如果要切到 SQLite 持久化后端，可以增加：

```bash
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_STORAGE_BACKEND=sqlite
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_SQLITE_PATH=/tmp/agent-architect-lab-control-plane.sqlite3
```

SQLite schema migration 会在启动时自动执行，`/health` 响应会返回当前 storage backend 和 SQLite schema version。

如果希望调整 worker 失联判定的严格程度，可以设置 `AGENT_ARCHITECT_LAB_CONTROL_PLANE_WORKER_STALE_AFTER_S`。

如果希望收紧 job admission 保护，可以设置：

- `AGENT_ARCHITECT_LAB_CONTROL_PLANE_JOB_MAX_QUEUED_PER_TYPE`
- `AGENT_ARCHITECT_LAB_CONTROL_PLANE_JOB_MAX_INFLIGHT_PER_TYPE`
- `AGENT_ARCHITECT_LAB_CONTROL_PLANE_JOB_ADMISSION_OVERRIDES`

例如：

```bash
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_JOB_MAX_QUEUED_PER_TYPE=10
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_JOB_MAX_INFLIGHT_PER_TYPE=10
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_JOB_ADMISSION_OVERRIDES='{
  "backup_control_plane_storage": {"max_inflight": 1},
  "restore_control_plane_backup": {"max_inflight": 1}
}'
```

## 鉴权规则

- `GET /health` 不需要鉴权
- 读接口接受 `Authorization: Bearer <read-token>`
- 读接口也接受 mutation token
- 受保护路由还可能要求 `X-Control-Plane-Actor` 和 `X-Control-Plane-Role`
- 写接口必须使用 `Authorization: Bearer <mutation-token>`
- 写接口还必须带上 `Idempotency-Key: <key>`
- 如果没有配置 `AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN`，所有写接口都会返回 `503`
- 成功的写请求会按 idempotency key 缓存首个响应，后续重试直接重放
- mutation 审计日志会追加写入 `artifacts/control-plane/mutation-requests.jsonl`
- 审计日志现在不仅记录成功 mutation，也记录认证失败、权限拒绝、identity 错误和 payload policy 拒绝
- idempotency 状态会持久化到 `artifacts/control-plane/idempotency-registry.json`
- 长时间运行的导出任务会持久化到 `artifacts/control-plane/job-registry.json`
- worker heartbeat 状态会持久化到 `artifacts/control-plane/worker-registry.json`
- running job 现在还会带 `worker_id`、`heartbeat_at`、`lease_expires_at`，用于 stale lease recovery
- worker registry 视图现在会基于 heartbeat 年龄把 worker 分类为 `healthy`、`stale` 或 `stopped`
- 失败任务现在会通过专门的 dead-letter 视图暴露出来，同时保留原来的手动 retry 流程
- job admission 现在会在同类任务的 queued / inflight 数量超过阈值时直接拒绝新请求，并把拒绝事件记为 `admission_denied`
- 每个 API 响应现在都会带 `_meta.request_id` 方便串联日志和审计
- policy 拒绝现在会返回结构化的 `error.details`，方便 dashboard 和审计系统直接消费
- `/health` 现在也会标明 worker 是 server 内置托管，还是应该由外部独立进程运行
- `/health` 现在还会返回 worker registry 的 totals，便于 dashboard 直接识别当前有多少运行中的独立 worker
- control-plane 的 storage status、backup archive、restore drill 以及 SQLite counts 现在都把 worker registry 纳入校验和计数范围

默认内置的 role policy key：

- `read_governance`
- `read_jobs`
- `read_storage`
- `create_export_job`
- `manage_storage`
- `restore_storage`
- `retry_job`
- `approve_release`
- `reject_release`
- `promote_release`
- `deploy_release`
- `manage_release_override`
- `open_incident`
- `transition_incident`
- `write_feedback`

可以通过 `AGENT_ARCHITECT_LAB_CONTROL_PLANE_ROLE_POLICIES` 覆盖，例如：

```bash
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_ROLE_POLICIES='{
  "read_governance": ["control-plane-admin", "release-manager", "ops-oncall"],
  "open_incident": ["control-plane-admin", "incident-commander", "ops-oncall"],
  "transition_incident": ["control-plane-admin", "incident-commander"]
}'
```

## 路由清单

### 读接口

- `GET /health`
- `GET /metrics`
- `GET /operator-alert-board?environment=production&alert_limit=20`
- `GET /storage-status`
- `GET /ledger-storage-status`
- `GET /releases?limit=50`
- `GET /releases/{release_name}`
- `GET /feedback?release_name=...&incident_id=...&target_kind=...&limit=20`
- `GET /feedback-summary?release_name=...&incident_id=...&target_kind=...&limit=20`
- `GET /release-risk-board?environment=staging&environment=production&limit=20`
- `GET /approval-review-board?environment=staging&environment=production&limit=20`
- `GET /incident-review-board?status=open&limit=20`
- `GET /governance-summary?environment=production&release_limit=20&incident_limit=20&override_limit=50`
- `GET /jobs?status=queued&job_type=export_governance_summary&request_id=req-...&operation_id=op-...&limit=50`
- `GET /jobs/{job_id}`
- `GET /job-queue-status`
- `GET /workers?status=running&health=healthy&limit=50`
- `GET /dead-letter-jobs?job_type=backup_control_plane_storage&request_id=req-...&operation_id=op-...&limit=50`
- `GET /audit-events?request_id=req-...&operation_id=op-...&event_type=authorization_denied&error_code=missing_identity&route_policy_key=read_governance&actor=...&role=...&method=POST&path=/incidents/open&status_code=201&replayed=true&conflict=false&limit=100`
- `GET /idempotency-records?method=POST&path=/jobs/export-governance-summary&operation_id=op-...&status_code=202&limit=100`
- `GET /idempotency-records/{idempotency_key}`

### 写接口

- `POST /releases/{release_name}/approve`
- `POST /releases/{release_name}/reject`
- `POST /releases/{release_name}/promote`
- `POST /releases/{release_name}/deploy`
- `POST /releases/{release_name}/rollback`
- `POST /releases/{release_name}/overrides/grant`
- `POST /releases/{release_name}/overrides/revoke`
- `POST /incidents/open`
- `POST /incidents/{incident_id}/transition`
- `POST /incidents/{incident_id}/followup-eval`
- `POST /feedback`
- `POST /jobs/export-governance-summary`
- `POST /jobs/export-weekly-status`
- `POST /jobs/record-operator-handoff`
- `POST /jobs/export-operator-handoff-report`
- `POST /jobs/export-planner-shadow`
- `POST /jobs/export-release-command-brief`
- `POST /jobs/export-release-runbook`
- `POST /jobs/backup-control-plane-storage`
- `POST /jobs/verify-control-plane-backup`
- `POST /jobs/restore-control-plane-backup`
- `POST /jobs/backup-release-and-incident-ledgers`
- `POST /jobs/verify-release-and-incident-ledger-backup`
- `POST /jobs/restore-release-and-incident-ledger-backup`
- `POST /jobs/{job_id}/retry`

## 示例请求

读取治理摘要：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/governance-summary
```

查看存储后端健康状态和计数：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/storage-status
```

查看当前已注册 worker 以及最近一次 heartbeat：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/workers?health=stale
```

查看紧凑 metrics 快照：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/metrics
```

查看 operator alert board：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/operator-alert-board?alert_limit=10
```

查看当前进入 dead-letter 视图的失败任务：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/dead-letter-jobs
```

在恢复演练前查看 release / incident ledger 的完整性：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/ledger-storage-status
```

创建 incident：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: incident-commander-1" \
  -H "X-Control-Plane-Role: incident-commander" \
  -H "Idempotency-Key: incident-open-20260410-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/incidents/open \
  -d '{
    "severity": "critical",
    "summary": "unsafe production answer",
    "owner": "incident-commander",
    "environment": "production",
    "release_name": "2026-04-10-main",
    "source_report_path": "/tmp/report.json",
    "note": "customer escalation"
  }'
```

审批 release：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: qa-owner-1" \
  -H "X-Control-Plane-Role: qa-owner" \
  -H "Idempotency-Key: approve-release-20260410-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/releases/2026-04-10-main/approve \
  -d '{
    "role": "qa-owner",
    "note": "gate review complete"
  }'
```

推进 incident 状态：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: incident-commander-1" \
  -H "X-Control-Plane-Role: incident-commander" \
  -H "Idempotency-Key: incident-transition-20260410-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/incidents/incident-20260410abcd1234/transition \
  -d '{
    "status": "acknowledged",
    "by": "incident-commander",
    "note": "triage started",
    "owner": "ops-owner"
  }'
```

给 incident 绑定 follow-up eval artifact：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: incident-commander-1" \
  -H "X-Control-Plane-Role: incident-commander" \
  -H "Idempotency-Key: incident-followup-link-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/incidents/incident-20260410abcd1234/followup-eval \
  -d '{
    "followup_eval_path": "/tmp/incident-backfill.jsonl",
    "by": "incident-commander",
    "note": "postmortem eval attached"
  }'
```

创建治理摘要导出任务：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  -H "Idempotency-Key: export-governance-summary-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/export-governance-summary \
  -d '{
    "title": "Weekly Governance Summary",
    "output": "/tmp/governance-summary.md",
    "release_limit": 20,
    "incident_limit": 20,
    "override_limit": 50
  }'
```

创建一份面向主管/经理的周报导出任务：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  -H "Idempotency-Key: export-weekly-status-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/export-weekly-status \
  -d '{
    "title": "Weekly Release Status",
    "output": "/tmp/weekly-status.md",
    "since_days": 7,
    "snapshot_limit": 20,
    "release_limit": 20,
    "incident_limit": 20,
    "override_limit": 50
  }'
```

创建 planner shadow 导出任务：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  -H "Idempotency-Key: export-planner-shadow-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/export-planner-shadow \
  -d '{
    "suite_name": "planner_shadow",
    "report_name": "planner-shadow-report.json",
    "title": "Planner Shadow Report",
    "output": "/tmp/planner-shadow.md"
  }'
```

创建 bounded release command brief 导出任务：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  -H "Idempotency-Key: export-release-command-brief-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/export-release-command-brief \
  -d '{
    "release_name": "2026-04-10-main",
    "title": "Release Command Brief",
    "output": "/tmp/release-command-brief.md",
    "history_limit": 5,
    "incident_limit": 10
  }'
```

创建 release runbook 导出任务：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  -H "Idempotency-Key: export-release-runbook-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/export-release-runbook \
  -d '{
    "release_name": "2026-04-10-main",
    "title": "Release Runbook",
    "output": "/tmp/release-runbook.md",
    "history_limit": 10,
    "incident_limit": 10
  }'
```

创建 release / incident ledger 备份任务：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: ops-oncall-1" \
  -H "X-Control-Plane-Role: ops-oncall" \
  -H "Idempotency-Key: backup-release-ledgers-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/backup-release-and-incident-ledgers \
  -d '{
    "label": "nightly",
    "output": "/tmp/release-ledgers-nightly.zip"
  }'
```

查询任务状态：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/jobs/job-abc123def456
```

## 治理摘要中的 Runtime Realism

`GET /governance-summary` 以及基于它生成的 Markdown 报告现在还会带出：

- 最新的 planner shadow artifact
- 最新的 release command brief artifact
- 这两类 runtime-realism artifact 的简单计数
- governance summary、weekly status、release runbook 导出的 JSON sidecar 与 artifact-lineage 区块

这样管理层视角的治理输出就不再只看到传统的 release / incident 状态，也能看到 model-backed planner validation 和 bounded role-handoff readiness。

依赖恢复后重试失败任务：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  -H "Idempotency-Key: retry-job-abc123def456-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/job-abc123def456/retry \
  -d '{
    "max_attempts": 2
  }'
```

创建 control plane 存储备份任务：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: ops-oncall-1" \
  -H "X-Control-Plane-Role: ops-oncall" \
  -H "Idempotency-Key: backup-control-plane-storage-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/backup-control-plane-storage \
  -d '{
    "label": "nightly",
    "output": "/tmp/control-plane-nightly.zip"
  }'
```

创建备份校验任务：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: ops-oncall-1" \
  -H "X-Control-Plane-Role: ops-oncall" \
  -H "Idempotency-Key: verify-control-plane-backup-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/verify-control-plane-backup \
  -d '{
    "backup_path": "/tmp/control-plane-nightly.zip",
    "expected_sha256": "abc123..."
  }'
```

创建一次基于备份包的 restore drill：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: ops-oncall-1" \
  -H "X-Control-Plane-Role: ops-oncall" \
  -H "Idempotency-Key: restore-control-plane-backup-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/jobs/restore-control-plane-backup \
  -d '{
    "backup_path": "/tmp/control-plane-nightly.zip",
    "output_dir": "/tmp/control-plane-restore-drill",
    "label": "drill"
  }'
```

查看最近的审计事件：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  "http://127.0.0.1:8080/audit-events?actor=incident-commander-1&method=POST&path=/incidents/open&replayed=true&limit=20"
```

查看由于 policy 或 identity 问题被拒绝的请求：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  "http://127.0.0.1:8080/audit-events?event_type=authorization_denied&error_code=missing_identity&limit=20"
```

查看一条已保存的幂等记录：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/idempotency-records/export-governance-summary-001
```

按路由或操作维度列出幂等记录：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  "http://127.0.0.1:8080/idempotency-records?method=POST&path=/jobs/export-governance-summary&status_code=202&limit=20"
```

## 当前边界

这层 control plane 是有意做窄的：

- 读模型优先服务治理、审阅和值班流程
- 当前写接口覆盖 incident 创建、状态推进、follow-up eval 绑定，以及各类导出/备份 job 提交
- 长时间运行的导出已经走持久化 leased worker，并带有自动重试、人工 requeue 和 stale-lease recovery，但还不是分布式队列
- 存储仍然是本地 artifact JSON，而不是外部数据库
- 权限现在已经通过集中式 route/payload policy engine 执行，但还不是完整统一的 RBAC 或外部 policy service
- 导出的治理 artifact 现在也会带 machine-readable lineage，但这仍然是文件级方案，还不是集中式 metadata service
- 现在已经有幂等、审计、job persistence 和 lease-based recovery，但还没有分布式队列、分布式锁和更强的一致性协调

这意味着它已经足够像一套内部生产治理服务，可以支撑本地演练和内部工具接入，同时仍然保持依赖轻、容易测试。
