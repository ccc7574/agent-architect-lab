# Human Feedback

`agent-architect-lab` 现在把显式的人类评审反馈当成一等治理 artifact，而不是只散落在临时备注或审批注释里。

## 覆盖范围

- release review feedback
- incident follow-up feedback
- report / artifact review feedback
- 绑定到具体 `run_id` 的 run-level feedback

反馈会存到 `artifacts/feedback/feedback-ledger.json`。

## CLI

记录一条反馈：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli record-feedback \
  --summary "release 仍然缺少 rollback 证据" \
  --actor release-manager-1 \
  --role release-manager \
  --sentiment negative \
  --actionability followup_required \
  --target-kind release \
  --release-name 2026-04-10-main \
  --label rollback \
  --label review
```

列出反馈：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli list-feedback --release-name 2026-04-10-main --limit 20
```

查看反馈摘要：

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli feedback-summary --release-name 2026-04-10-main
```

## Control Plane

读接口：

- `GET /feedback?release_name=...&incident_id=...&target_kind=...&limit=20`
- `GET /feedback-summary?release_name=...&incident_id=...&target_kind=...&limit=20`

写接口：

- `POST /feedback`

示例：

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  -H "Idempotency-Key: feedback-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/feedback \
  -d '{
    "actor": "release-manager-1",
    "role": "release-manager",
    "sentiment": "negative",
    "actionability": "followup_required",
    "target_kind": "release",
    "summary": "release 仍然缺少 rollback 证据",
    "release_name": "2026-04-10-main",
    "labels": ["rollback", "review"]
  }'
```

## 为什么重要

这个仓库原来已经能跟踪审批、incident、run trace 和 release artifact，但还缺一类关键信号：

- 人类评审到底怎么看
- 反馈是正向、中性还是负向
- 这条反馈是否要求后续跟进
- 它具体指向哪个 release、incident、report、run 或 artifact

补上这一层之后，governance summary、weekly status、release runbook、release command brief、incident bundle 都能带出显式的人类反馈信号，而不再只依赖系统自动生成的状态。
