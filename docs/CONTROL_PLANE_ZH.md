# Control Plane

`agent-architect-lab` 现在已经在现有 release / incident ledger 之上提供了一个轻量 HTTP control plane。

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
- idempotency 状态会持久化到 `artifacts/control-plane/idempotency-registry.json`

默认内置的 role policy key：

- `read_governance`
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
- `GET /release-risk-board?environment=staging&environment=production&limit=20`
- `GET /approval-review-board?environment=staging&environment=production&limit=20`
- `GET /incident-review-board?status=open&limit=20`
- `GET /governance-summary?environment=production&release_limit=20&incident_limit=20&override_limit=50`

### 写接口

- `POST /incidents/open`
- `POST /incidents/{incident_id}/transition`

## 示例请求

读取治理摘要：

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  http://127.0.0.1:8080/governance-summary
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

## 当前边界

这层 control plane 是有意做窄的：

- 读模型优先服务治理、审阅和值班流程
- 当前写接口只覆盖 incident 创建与状态推进
- 存储仍然是本地 artifact JSON，而不是外部数据库
- 权限现在已经是 token + route-level role policy，但还不是完整统一的 RBAC / policy engine
- 现在已经有幂等和审计，但还没有后台队列、分布式锁和更强的一致性协调

这意味着它已经足够像一套内部生产治理服务，可以支撑本地演练和内部工具接入，同时仍然保持依赖轻、容易测试。
