# Harness Practices

Harness engineering is how an agent team turns demos into a reliable product discipline.

A practical harness should:

- Keep task definitions versioned and deterministic.
- Separate grading logic from task execution.
- Record run traces, checkpoints, scores, and failure types together.
- Make regressions obvious before product launch.
- Support local smoke tests before expensive model-backed evaluations.

If a team cannot explain what regressed, on which task slice, and in which release, the harness is not mature enough.
