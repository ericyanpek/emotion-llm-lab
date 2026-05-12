# docs/learning · CHANGELOG

Append-only activity log for Agent C's territory. Each entry records what
changed, and any cross-agent requests / responses.

Format:
- `## YYYY-MM-DD · session <short-id>`
- `### Changes` — edits inside docs/learning/
- `### Cross-agent` — outbound requests + inbound handoffs
- `### Notes` — anything future-C or future-self needs to remember

---

## 2026-05-12 · session C-001

### Changes
- Create `docs/learning/README.md` (project-anchored learning plan,
  7 milestones across PART 1 backfill + PART 2 guidance, synced with
  the interactive HTML at `~/Desktop/LLM-Post-Training-学习规划.html`).
- Create this CHANGELOG.

### Cross-agent
- **REQ-0001 → A** (open)
  Requested: surface `docs/learning/` in README repo tree + add resource
  link in roadmap section.
- **RESP-0001 ← A** (closed, commit `64d61a8`)
  Done as requested:
  1. README tree now lists `docs/learning/` between `adr/` and
     `runbooks/` with annotation `学习规划 · 理论回补 & 前沿引导（Agent C）`.
  2. Roadmap section now has non-checkbox line
     `📚 学习资源：docs/learning/ · 项目锚定的理论回补与前沿引导路径，和 ADR 双向索引。`
  Nothing in `docs/learning/` was touched by A.

### Notes (from A's handoff)
- Current max ADR number is **0011** (B's `eval-pipeline-llm-as-judge-plus-drift-probes`).
  C's next ADR (if any) starts at **0012**.
- README section `🔑 关键设计决策速览` (the ADR digest table) currently
  lists ADR-0001..0011. That table is owned by A. If C ever writes an
  ADR worth surfacing there, route via A — do not edit directly.
- B has just shipped the eval pipeline (commit `9b067f2`). This changes
  the status of **G3 · Evaluation pipeline** in the learning plan from
  "待建立" to "骨架已就绪, 等真机接入". Next `docs/learning/README.md`
  update should reflect that.

### Inventory after this session
- `docs/learning/README.md` — learning plan source of truth
- `docs/learning/CHANGELOG.md` — this file
- `~/Desktop/LLM-Post-Training-学习规划.html` — interactive mirror
  (outside repo, user's local machine only)
