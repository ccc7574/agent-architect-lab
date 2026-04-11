# Runtime Realism

这个仓库现在已经不只是 provider scaffold，而是补上了更接近真实生产形态的 runtime realism 能力。

## Planner Shadow Validation

当你想在真正把 model-backed planner 放进发布流程之前，先验证它第一步决策是否可靠时，用 `run-planner-shadow`。

```bash
AGENT_ARCHITECT_LAB_PLANNER_PROVIDER=openai_compatible \
PYTHONPATH=src python3 -m agent_architect_lab.cli run-planner-shadow \
  --suite planner_shadow \
  --report-name planner-shadow-report.json \
  --markdown-output ./planner-shadow.md
```

它重点检查：

- task 级的 allowed / blocked tools
- `tool` 与 `answer` 这类 action type 是否符合预期
- 候选 planner 和 heuristic baseline 的第一步漂移
- 对高风险破坏性请求是否会停在 approval-style answer

默认的 `planner_shadow` suite 故意保持范围可控。它的目标是在 rollout 前产出可审阅的 shadow artifact，而不是替代完整回归集。

## Bounded Role Orchestration

当你想生成一个更接近真实 release command 体系的多角色交接产物时，用 `export-release-command-brief`。

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli export-release-command-brief release-a \
  --title "Release Command Brief"
```

它会做的事情：

- 构建 `qa-owner`、`ops-oncall`、`incident-commander`、`release-manager` 四个固定角色包
- 保持角色所有权边界清晰，而不是让每个角色拿到全部上下文
- 把 release blocker、override、incident、rollout readiness 汇总成一份可读 artifact
- 给出确定性的最终建议，例如 `promote`、`promote_with_review`、`hold_release`

它还不是分布式 worker plane，但已经体现出真实 release command system 里的职责边界。

## 为什么重要

高级 AI 架构师的要求，不只是“把模型接进去能跑”。

还要体现你能否：

- 在 rollout 前验证 model-backed planner 的行为
- 定义工具与审批边界
- 用稳定 baseline 对候选 planner 做对照
- 在 QA、Ops、Incident、Release 之间建立明确 ownership
- 产出便于人类快速做发布决策的 artifact
