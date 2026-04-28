# Agent Architect Lab

英文主入口见 `README.md`。

`agent-architect-lab` 是一个面向 Agent 架构能力训练的实践仓库。它不是一个一次性 demo，而是把真实 AI 产品里会遇到的核心问题放到一个小而完整的实验环境里：运行时设计、工具调用、MCP 集成、记忆、安全边界、评测 harness、技能系统、发布治理和事故复盘。

这个仓库适合想从“能拼一个 Agent demo”继续往“能设计 Agent 产品平台”升级的人。它的重点不只是让 Agent 能跑，而是让 Agent 的行为可追踪、可评测、可回滚、可发布。

## 当前包含什么

- 本地 Agent runtime，带确定性 planner
- workspace 范围内的文件和 shell 工具
- MCP note server 与工具适配器
- 带 bearer token 的 HTTP control plane
- 多套 eval、release gate、harness report 对比
- sample skill manifest、runtime skill selection、note-backed retrieval
- deterministic planner 与 model-backed planner scaffold
- planner shadow validation，用于模型 planner 灰度
- incident-to-eval，把事故转成后续评测任务
- human feedback ingestion，沉淀发布、事故、报告和运行产物上的人工反馈
- release ledger、approval、promotion、rollback、override、operator handoff

## 阅读顺序

| 顺序 | 先看哪里 | 重点看什么 | 对应文件 |
| --- | --- | --- | --- |
| 1 | 项目总览 | 先把它理解成 Agent 产品平台实验室，而不是单个 Agent demo | `README.zh-CN.md`, `README.md` |
| 2 | 学习路径 | 明确从 runtime、tool、memory、MCP、harness 到 release system 的能力路线 | `docs/LEARNING_PATH.md`, `docs/AI_ARCHITECT_COMPETENCY_MATRIX.md` |
| 3 | Runtime 架构 | 跟踪 CLI 到 runtime、planner、tool、memory、trace 的执行链路 | `docs/ARCHITECTURE.md`, `src/agent_architect_lab/agent/` |
| 4 | Skills 与知识路由 | 理解 skill 如何位于工具层之上，以及 note-backed retrieval 如何参与决策 | `data/skills/`, `data/notes/`, `docs/KNOWLEDGE_ROUTING.md`, `docs/KNOWLEDGE_ROUTING_ZH.md` |
| 5 | MCP 集成 | 看 protocol boundary、adapter、local note server 如何拆分 | `src/agent_architect_lab/mcp/`, `scripts/run_mcp_server.py` |
| 6 | Harness 与 release gate | 学习 task dataset、grading、report、gate、promotion 如何约束 Agent 迭代 | `docs/HARNESS_PRACTICES.md`, `docs/EVALS_AND_SAFEGUARDS_ROADMAP.md` |
| 7 | 事故与反馈 | 把事故、人工反馈、backfill eval 和治理摘要连接起来 | `docs/OPS_AND_INCIDENTS.md`, `docs/INCIDENT_BACKFILL.md`, `docs/HUMAN_FEEDBACK_ZH.md` |
| 8 | 发布系统 | 看 approval、promotion、rollout、rollback、override、control plane 如何组合 | `docs/RELEASE_LEDGER_ZH.md`, `docs/PRODUCTION_RELEASE_SYSTEM_PLAN_ZH.md`, `docs/CONTROL_PLANE_ZH.md` |
| 9 | 模型 planner 灰度 | 在信任 model-backed planner 之前，先理解 provider、shadow run 和 runtime realism | `docs/PLANNER_PROVIDERS.md`, `docs/SHADOW_RUNS.md`, `docs/RUNTIME_REALISM_ZH.md` |

## 快速开始

从源码运行：

```bash
cd /Volumes/ExtaData/newcode/agent-architect-lab
PYTHONPATH=src python3 -m agent_architect_lab.cli explain-patterns
PYTHONPATH=src python3 -m agent_architect_lab.cli list-skills --goal "agent skills and memory retrieval"
PYTHONPATH=src python3 -m agent_architect_lab.cli run-task "summarize 'pyproject.toml'"
PYTHONPATH=src python3 -m agent_architect_lab.cli run-evals --suite default
```

安装为本地包：

```bash
cd /Volumes/ExtaData/newcode/agent-architect-lab
python3 -m pip install -e .[dev]
agent-lab explain-patterns
agent-lab run-evals
```

## 仓库结构

```text
agent-architect-lab/
  src/agent_architect_lab/agent/      # runtime、memory、planning patterns
  src/agent_architect_lab/tools/      # local tools 和 tool registry
  src/agent_architect_lab/mcp/        # MCP protocol、client、server、adapter
  src/agent_architect_lab/harness/    # eval、grading、report、gate、promotion
  src/agent_architect_lab/evals/      # deterministic local tasks
  data/skills/                        # sample skills
  data/notes/                         # searchable architecture notes
  docs/                               # 架构、harness、治理、发布和学习路径
```

## 这套 Lab 主要训练什么

这个项目的学习目标，是把 Agent 从“能调用工具”推进到“能进入产品工程体系”：

- Runtime architecture：planning loop、tool routing、checkpoint、trace
- Skills：工具层之上的可复用操作契约
- MCP and knowledge systems：协议边界、适配器、note retrieval
- Safety：sandbox、命令校验、审批设计
- Harness engineering：任务集、评分、报告、回归闭环
- Product architecture：control plane、execution plane、knowledge plane、ops

## 架构地图

高层执行链路：

```text
CLI
  -> AgentRuntime
     -> SkillRouter
     -> MemoryManager
     -> AgentPlanner
        -> HeuristicPlanner
     -> ToolRegistry
        -> read_file / write_file / search_files / run_shell
        -> MCPToolAdapter -> MCPClient -> scripts/run_mcp_server.py -> MCP note server
     -> TraceStore + CheckpointStore

run-evals
  -> load_suite
  -> run_suite
  -> grade_trace
  -> HarnessReport
  -> compare_reports / check_gates
```

## 重点设计判断

这个仓库最重要的设计取向，是把 Agent 的“能力扩张”和“治理边界”一起训练。

很多 Agent demo 只展示它能做什么，但真实产品里还要回答：

- 行为能不能被 trace？
- 改动能不能被 eval gate 挡住？
- 事故能不能变成后续测试？
- 人类反馈能不能进入治理视图？
- 发布能不能 approval、promotion、rollback？
- model-backed planner 能不能先 shadow，再 rollout？

如果你想练的是 Agent 产品架构，而不是单点 demo，这个仓库的价值主要就在这里。
