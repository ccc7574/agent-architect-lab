# Control Plane

`agent-architect-lab` 现在已经在现有 release / incident ledger 之上提供了一个轻量 HTTP control plane。

当前 control plane 内部已经拆成四层：

- `server.py`：HTTP 路由和统一响应 envelope
- `policies.py`：集中式 route / payload policy 校验
- `repositories.py`：本地 JSON 或 SQLite persistence 的 repository bundle 装配层
- `storage.py` / `jobs.py`：持久化 repository 和持久化的内置 job 执行

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

这个服务只依赖 Python 标准库，底层仍然直接复用 CLI 使用的 artifact 存储。

如果要切到 SQLite 持久化后端，可以增加：

```bash
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_STORAGE_BACKEND=sqlite
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_SQLITE_PATH=/tmp/agent-architect-lab-control-plane.sqlite3
```

SQLite schema migration 会在启动时自动执行，`/health` 响应会返回当前 storage backend 和 SQLite schema version。

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
- 每个 API 响应现在都会带 `_meta.request_id` 方便串联日志和审计
- policy 拒绝现在会返回结构化的 `error.details`，方便 dashboard 和审计系统直接消费

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
- `GET /storage-status`
- `GET /ledger-storage-status`
- `GET /releases?limit=50`
- `GET /releases/{release_name}`
- `GET /release-risk-board?environment=staging&environment=production&limit=20`
- `GET /approval-review-board?environment=staging&environment=production&limit=20`
- `GET /incident-review-board?status=open&limit=20`
- `GET /governance-summary?environment=production&release_limit=20&incident_limit=20&override_limit=50`
- `GET /jobs?status=queued&job_type=export_governance_summary&request_id=req-...&operation_id=op-...&limit=50`
- `GET /jobs/{job_id}`
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
- `POST /jobs/export-governance-summary`
- `POST /jobs/record-operator-handoff`
- `POST /jobs/export-operator-handoff-report`
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
- 当前写接口只覆盖 incident 创建与状态推进
- 长时间运行的导出已经走持久化 worker，并带有自动重试和人工 requeue，但还不是分布式队列
- 存储仍然是本地 artifact JSON，而不是外部数据库
- 权限现在已经通过集中式 route/payload policy engine 执行，但还不是完整统一的 RBAC 或外部 policy service
- 现在已经有幂等、审计和 job persistence，但还没有分布式队列、分布式锁和更强的一致性协调

这意味着它已经足够像一套内部生产治理服务，可以支撑本地演练和内部工具接入，同时仍然保持依赖轻、容易测试。
