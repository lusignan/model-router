---
name: alloy-build
description: >-
  Run Protocol B: the 4-Stage Build & Verification Loop (Spec -> Build ->
  Verify || Audit -> Deliver) under Model Router with quota-aware failover,
  batching discipline, and zero coding-loop burn.
---

# Protocol B: 4-Stage Build & Verification Loop (`Spec -> Build -> Verify || Audit -> Deliver`)

> *This runbook is an optional, composable workflow layered on top of `model-router`'s deterministic `PreToolUse`/`PostToolUse` hook control plane. Under multi-provider presets (`antigravity`, `multi-provider`), build and review span different model families so no model grades its own work and **blind spots are less correlated**; under the single-provider `claude-code` preset, roles tier cleanly across `opus`, `sonnet`, and `haiku` within Anthropic's family (mapping both `architect` and `forensic` to `opus` unless paired with an external reviewer).*

## Overview

Once an unambiguous mathematical and file-level specification is locked (via Plan Mode or **`research-dyad`**), execute production delivery through four strictly separated stages governed by **Model Router** (`model_router.alloy`):

```text
[1. Architect Spec] -> [2. Builder Implementation + Canary] -> [3. Fast Verifier Sweep || 4. Gatekeeper Audit] -> [3b. Grunt Export & Commit]
```

This skill explicitly authorizes invoking `swarm(action="add", ...)` for each stage worker below (or `Task` / `Agent` subagent calls under Claude Code with the `claude-code` preset).

## The Four Stages

### Stage 1 — Architect Spec (`architect` slot, default `gemini-4-carbon-high`)
Lock every design decision **before** editing code:
- Governing mathematical equations, invariants, and edge-case semantics (zero heuristic step-function cliffs, zero silent fallbacks, zero post-hoc output patches).
- Exact file list, public signatures, schema contracts, and acceptance tests.
- On heavy threads (`>= 1 MB` transcript), the Architect may only perform a surgical inline edit if the entire fix fits in **1 parallel batch of `<= 4` files**; anything larger goes directly to Stage 2.

### Stage 2 — Primary Code Build (`builder_xhigh` slot, default `gemini-4-neon-xhigh`)
Dispatch all core module, numerical kernel, simulation, and pipeline implementation to **Builder XHigh** (`[neon]` / `[neon-kernel]`):
- Never run multi-turn Python edit-test-fix loops on the Architect (Model Router intercepts Architect coding loops via `carbon.coding_loop_redirect` and rewrites them to `builder_xhigh`).
- Never drain Grunt quota on core numerical/modeling builds (Model Router redirects non-grunt Claude builds via `sonnet.code_redirect` unless `[sonnet]` is explicitly requested).
- Run fast syntax/compile checks, 1-unit canaries, and targeted unit tests during build; leave full slow multi-suite regression sweeps to Stage 3 so heavy suites execute once rather than twice.

### Stage 3 — Parallelized Verification Sweep & Grunt Plumbing (`grunt_high`/`grunt_low` <-> `failover_grunt_*`)
Once Stage 2 freezes code and outputs, run Stage 3's parallelized verification sweep (`[grunt]`) **concurrently** with Stage 4's read-only Gatekeeper audit (`[carbon]`), then finish mechanical repository plumbing once both pass:
- `[grunt]` (`grunt_high`, auto-failing over to `failover_grunt_high` when Claude quota `<= 2%`): executes the single parallelized full `compileall && unittest/pytest && guards` verification sweep concurrently with Stage 4's audit, then runs docs/ledger/status synchronization and HTML/CSV export scripts once both Stage 3 verification and Stage 4 audit pass.
- `[grunt-low]` (`grunt_low`, auto-failing over to `failover_grunt_low`): linting, formatting, log tailing, swarm monitoring/narration, and atomic `git commit`s once both Stage 3 verification and Stage 4 audit pass.
- Under `[carbon-neon]` exclusivity, Stage 3 verification and plumbing route to `builder_xhigh` / `builder_high` rather than Grunt/Failover.

### Stage 4 — Gatekeeper Audit (`architect` slot, default `gemini-4-carbon-high`)
Dispatched **concurrently** with Stage 3's parallelized verification sweep once Stage 2 freezes outputs, **Architect** (`[carbon]`) performs a read-only audit of:
1. Full `git diff` against the Stage 1 locked specification.
2. Evaluation scorecard and quantitative test outputs.
3. Tail, boundary, and subgroup diagnostic slices to confirm zero subtle shortcuts, silent defaults, or leakage slipped into the implementation.

Once both Stage 3 verification and Stage 4 audit pass, `[grunt]` / `[grunt-low]` (or `builder_xhigh` / `builder_high` under `[carbon-neon]` exclusivity) completes export/ledger synchronization and atomic commit.

## Batching & Inline Edit Budget Discipline

| Thread Size | Max Inline Edits / User Turn | Max Planner Batches / User Turn | Required Action When Exceeded |
|---|---|---|---|
| **Lean (`< 1 MB`)** | `5` files | `2` batches | Dispatch `[neon]` builder |
| **Heavy (`>= 1 MB`)** | `4` files | `1` parallel batch | Lock spec and dispatch `[neon]` builder immediately |

Always apply three batching habits inside every stage:
1. Batch all upfront `read_file` / search calls into **1** parallel turn.
2. Batch independent `edit_file` / `write_file` calls into **1–2** parallel turns.
3. Chain `compileall && unittest/pytest && guards` into **1** shell command.

## Parallelism, Selective Rebuild & Measured-Rate ETA Discipline

1. **Disjoint-File Parallel Builds (`workspace="inherit"`):** When multiple `Builder` workers touch strictly disjoint file sets (`files_A ∩ files_B = ∅`), dispatch them in parallel so downstream module implementation and unit tests proceed simultaneously while upstream background jobs run; serialize only the final integration step.
2. **Full Authorized Core Saturation in Parameter Sweeps:** Multi-trial hyperparameter searches and multi-seed evaluations must saturate the project's authorized worker ceiling (`N_cores` isolated single-thread subprocesses) rather than running `batch_size=1` single-core loops.
3. **Selective Upstream Cache Invalidation:** Recompute only artifacts whose actual consumed inputs or schema versions changed; never force blanket cache invalidation across unaffected upstream stages.
4. **Measured-Rate Progress & ETA Formula:** Report every build/evaluation ETA strictly from `(measured_sec_per_unit * remaining_units / active_cores) + unedited_spec_files` verified against `git status` and live task logs, never static design-doc estimates.
5. **Tracked Async Execution & Multi-Core Test Fan-Out:** Never launch detached fire-and-forget background processes (`nohup ... &`, `setsid ... &`, `disown`) without `wait` before entering a board wait state, as untracked processes never emit completion wakeups; use harness-tracked async command calls or `(... & wait)` subshells, and fan independent read-only test suites across authorized worker cores rather than serial single-core loops.

## Quota Failover Regimes

Model Router tracks dual-window quota state across both `transcript_full.jsonl` (`swarm(action="models")` weekly/effective snapshots) and Language Server `GetCascadeModelConfigData` (5h window) with `resetTime`-aware caching:

| Quota Regime | Condition | Grunt Routing | Builder Routing |
|---|---|---|---|
| **Normal** | Claude `> 2%`, Gemini `>= 20%` | `grunt_high` / `grunt_low` | `builder_xhigh` |
| **Claude Exhausted** | Claude `<= 2%` (before `claude_reset_ts`), Gemini `> 5%` | `failover_grunt_high` / `failover_grunt_low` | `builder_xhigh` |
| **Gemini Constrained** | Gemini `5%–19%` | `grunt_high` / `grunt_low` | `builder_high` (or `builder_xhigh` if `>= 15%` + specialist tag/keyword) |
| **Gemini Exhausted** | Gemini `< 5%`, Claude `> 2%` | `grunt_high` / `grunt_low` | Overflow to `grunt_high` |
| **Exclusivity (`[carbon-neon]`)** | Flag or phrase active | Locked to `builder_xhigh` / `builder_high` | Locked to `builder_xhigh` / `builder_high` (zero Grunt/Failover overflow) |

## Ready-to-Use Swarm Dispatch Templates (Antigravity Preset)

### Stage 2 — Builder + Canary
```text
swarm(
  action="add",
  name="neon-builder",
  model="gemini-4-neon-xhigh",
  brief="@neon-builder [neon-kernel]\nImplement the locked spec in <spec_path> across <files>. Batch reads and edits; run fast compileall, 1-unit canary, and targeted unit tests in one command; freeze outputs and report exact test counts and diff summary to @coordinator."
)
```

### Stage 3 & Stage 4 (Concurrent on Frozen Build) — Verification Sweep || Gatekeeper Audit
```text
swarm(
  action="add",
  name="grunt-verify",
  model="claude-sonnet-5-5-high",
  workspace="inherit",
  brief="@grunt-verify [grunt]\nRun the single parallelized compileall, unittest/pytest suite, and repository guards on the frozen build without modifying tracked files; report exact pass/fail counts to @coordinator."
)

swarm(
  action="add",
  name="carbon-audit",
  model="gemini-4-carbon-high",
  workspace="inherit",
  brief="@carbon-audit [carbon]\nConcurrently audit the frozen git diff and evaluation/diagnostic slices against <spec_path>. Verify zero silent fallbacks, zero step-function cliffs, and strict boundary compliance. Do NOT call edit_file; post PASS or blocking defects to @coordinator."
)
```

### Stage 3b (Post-Audit Delivery) — Docs/Ledger Sync & Atomic Commit
```text
swarm(
  action="add",
  name="grunt-deliver",
  model="claude-sonnet-5-5-low",
  brief="@grunt-deliver [grunt-low]\nUpdate STATUS.md / CHANGELOG.md with verified results, confirm git status is clean of temporary artifacts, stage only intended files, and create an atomic git commit."
)
```
