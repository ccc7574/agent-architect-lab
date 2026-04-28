# Lab 01：跑通最小 Agent 执行链路

## 目标

用 15 分钟跑通一次任务执行和一次 eval，建立对 runtime、tool、trace、harness 的直觉。

## 运行命令

```bash
cd /Volumes/ExtaData/newcode/agent-architect-lab
PYTHONPATH=src python3 -m agent_architect_lab.cli explain-patterns
PYTHONPATH=src python3 -m agent_architect_lab.cli run-task "summarize 'pyproject.toml'"
PYTHONPATH=src python3 -m agent_architect_lab.cli run-evals --suite default
```

## 观察点

- `run-task` 是否调用了 planner 和 tool
- 输出里是否能看到任务结果
- `run-evals` 是否生成 report
- report 里是否包含任务、评分和 trace 信息

## 读代码

按这个顺序读：

1. `src/agent_architect_lab/cli.py`
2. `src/agent_architect_lab/agent/`
3. `src/agent_architect_lab/tools/`
4. `src/agent_architect_lab/harness/`

## 思考题

- 如果要新增一个工具，应该改 runtime 还是 tool registry？
- 如果一次任务失败，应该在哪里留下 trace？
- 如果一个失败案例以后不能再出现，应该怎么变成 eval？

