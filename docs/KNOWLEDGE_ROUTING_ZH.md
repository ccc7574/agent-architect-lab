# Knowledge Routing

`agent-architect-lab` 现在把 note retrieval 当成一个轻量的 knowledge-routing 层，而不再只是普通的 lexical file search。

## 这次补了什么

- note search 结果现在带结构化 metadata
- retrieval ranking 现在除了 query term overlap，还会利用推断出来的 domain
- 读取 note 时现在会同时返回 provenance
- runtime 最终回答现在会显式带出它依赖的 source note

## Retrieval 返回结构

`search_notes` 现在会返回：

- `metadata.note_id`
- `metadata.title`
- `metadata.summary`
- `metadata.domains`
- `metadata.tags`
- `metadata.headings`
- `provenance.source_type`
- `provenance.score`
- `provenance.matched_terms`
- `provenance.matched_domains`
- `provenance.matched_fields`

`get_note` 现在会返回：

- note 原始内容
- 同一份 note metadata
- 标明这份答案来源文件的 provenance

## 为什么重要

一线 AI 架构师关心的从来不只是“有没有搜到一个字符串”。

更关键的是：

- 用的是哪一份知识源
- 为什么它排在其他来源前面
- 这个来源的 domain 是否和任务匹配
- 这次回答能不能回溯到一个持久化 artifact

这个仓库现在仍然没有 embedding retrieval 或完整 knowledge service，但它已经补上了更重要的一层 production 概念：retrieval 决策必须可解释、可追踪。

## 示例

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli run-task "memory retrieval system design"
```

新的 trace 里现在会看到：

- 带 provenance metadata 的 `search_notes` 排序结果
- 带 note metadata / provenance 的 `get_note`
- 显式说明 source note 的最终回答
