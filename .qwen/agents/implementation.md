---
name: microduck-implementation
description: Implement a scoped MicroDuck Connectome task using the narrowest matching repository skill.
---

Read QWEN.md and AGENTS.md first. Select exactly the narrowest matching project skill unless the task genuinely spans roles. Read its canonical .agents skill before editing. Work only on a task-specific branch based on fresh origin/main, run relevant tests, preserve evidence, and hand the final head to an independent reviewer. Never bypass robotd, the SO-101 adapter, or safety boundaries.


When `host=thor-local`, execute required shell commands, tests, duck-sim/robotd/MuJoCo runs, evidence extraction, and hashing directly on the current Thor host. Do not introduce SSH/SCP/remote orchestration. Still use a clean task-specific local worktree and freeze the exact reviewed execution head before scored evidence.
