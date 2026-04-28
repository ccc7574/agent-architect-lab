# 设计原则：为什么 Agent Architect Lab 这样拆

这个仓库的核心设计目标，是把 Agent 从“能运行的 demo”推进到“可治理的产品平台”。所以很多实现看起来比普通 demo 更重：有 trace，有 harness，有 release ledger，有 incident，有 control plane。它们不是装饰，而是在回答一个问题：Agent 变强以后，怎么让它仍然可控？

## 原则一：Runtime 和治理分开

Runtime 负责执行任务，治理层负责判断它是否可以被信任。

这两个层次不能混在一起。runtime 里应该关注 planner、tool、memory、skill；harness 和 release 系统则负责评估、比较、审批、回滚。如果把治理逻辑塞进 runtime，后面很难做独立评测和发布门禁。

## 原则二：工具能力必须通过 registry 暴露

工具不是随便调用的函数，而是 runtime 可审计的能力。`ToolRegistry` 的价值在于：

- 统一工具发现
- 统一参数和边界
- 统一 trace
- 方便接 MCP adapter

以后接更多外部工具时，不需要让 planner 知道每个工具的内部细节。

## 原则三：Skill 是工具之上的操作契约

Skill 不只是 prompt 模板。它更像“如何使用一组工具完成某类任务”的操作契约。

这个项目把 sample skill 放在 `data/skills/`，是为了让读者看到：Agent 平台能力不只在工具层，也在可复用的工作方式层。

## 原则四：Harness 是 Agent 产品的安全带

Agent 能力越强，越需要 harness。

这里的 harness 不只是跑测试，而是把任务、trace、grading、report、gate 串起来。这样每次改 runtime、planner、skill 或工具时，都能回答：

- 哪些任务变好了？
- 哪些任务退化了？
- 是否可以进入下一阶段？
- 是否需要 backfill 新 eval？

## 原则五：事故应该回流成 eval

真实系统里，事故不是一个孤立事件。一次事故如果没有变成后续的测试或 release gate，下一次很可能还会发生。

所以项目里有 incident-to-eval 的设计：事故记录不是为了归档，而是为了让 harness 变得更强。

## 原则六：模型 planner 先 shadow，再信任

Model-backed planner 很诱人，但不能直接替换 deterministic planner。

更稳的路径是：

1. deterministic planner 作为基线
2. model-backed planner 先 shadow
3. 比较报告和失败样本
4. 满足 gate 后再逐步放量

这也是 `PLANNER_PROVIDERS.md`、`SHADOW_RUNS.md` 和 `RUNTIME_REALISM_ZH.md` 要一起读的原因。

## 什么时候可以简化

如果只是个人 demo，可以不需要 release ledger、incident、control plane。但如果目标是学习 Agent 产品平台，这些模块很重要。因为真实难点往往不是“让 Agent 做一次对”，而是“让 Agent 在持续变化中可验证、可回滚、可解释”。

