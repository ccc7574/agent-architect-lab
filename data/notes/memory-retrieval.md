# Memory Retrieval

Memory retrieval design should separate fast working memory from durable knowledge.

A useful pattern is:

- Working memory: last few steps, compressed for planning.
- Checkpoints: durable snapshots of a run for audit and resume.
- Notes or knowledge base: curated long-term concepts and architectural principles.
- Retrieval policy: choose notes based on query overlap, task state, and confidence.

High-performing agents do not simply store more context. They retrieve the right context with predictable latency and clear provenance.
