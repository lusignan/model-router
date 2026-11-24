---
name: research-dyad
description: >-
  Run Protocol A: the Research & Audit Dyad (Architect <-> 1M Empirical
  Partner, e.g., Carbon <-> Neon XHigh) on the swarm board to diagnose model
  misses, audit mathematical invariants, harvest primary-source literature, and
  falsify hypotheses across large codebases and datasets before locking a spec.
---

# Protocol A: Research & Audit Dyad (`Architect` <-> `1M Empirical Partner`)

> *This runbook is an optional, composable workflow layered on top of `model-router`'s deterministic `PreToolUse`/`PostToolUse` hook control plane. Use it before locking a specification when causal/empirical falsification across large codebases is needed.*

## When to Invoke vs. Direct Build

Invoke this skill **before** writing production code whenever any of the following hold:
- You are diagnosing a forecast miss, calibration drift, subgroup residual anomaly, or silent selection/censoring bias.
- You are auditing numerical, statistical, or causal mechanisms spanning multiple modules where no locked specification exists yet.
- You need primary-source domain/statistical literature reconciled directly against whole-codebase call graphs and out-of-sample data slices.

Skip this skill and go straight to **`alloy-build`** (`Protocol B`) when an unambiguous, mathematically verified file-level specification is already locked.

## Why Cognitive Asymmetry Beats Homogeneous Ensembles

Spawning two copies of the same model produces heavily correlated blind spots and redundant token burn. Pairing the **Architect** (`architect` slot) with the **1M Empirical Partner** (`builder_xhigh` slot) exploits complementary strengths: under **multi-provider presets** (`antigravity`, `multi-provider`, e.g., `gemini-4-carbon-high` <-> `gemini-4-neon-xhigh` or `o3` <-> `gemini-2.5-pro`), cross-family pairing ensures **blind spots are less correlated**, while under the single-provider `claude-code` preset the dyad tiers `opus` framing/review against `sonnet` exploration and empirical checks:

| Dimension | Architect (`[carbon-dyad]`) | Empirical Partner (`[neon-dyad]` / `[neon-research]`) |
|---|---|---|
| **Primary Strength** | Causal identification, hierarchical Bayesian / non-stationary state-space derivations, censoring & survivorship traps, hostile red-teaming | `1M`-token simultaneous full-repository code X-ray, primary-source literature extraction, multi-million-row Parquet/OOS empirical ablations |
| **Failure Mode Caught by Partner** | Over-theorizing an unverified code assumption without reading every downstream consumer | Accepting an empirical correlation or quick patch that masks selection bias, leakage, or a hidden discontinuity |
| **Forbidden Work** | Multi-turn Python implementation loops or broad mechanical data-wrangling | Inventing post-hoc output caps, heuristic step gates, or unverified causal claims |

## Authorization for Swarm Dispatch

This skill explicitly authorizes invoking `swarm(action="add", ...)` to spawn the paired dyad workers (`carbon-dyad` and `neon-dyad`) on the shared swarm message board.

- Pass `workspace="inherit"` for read-only research/audit dyads (no working-tree edits).
- Pass `workspace="share"` only if an empirical probe requires isolated scratch build artifacts.
- To prevent any Grunt/Failover leakage during a high-stakes research sprint, include `[carbon-neon]` in the parent turn or worker header.

## Exact 4-Step Swarm Board Ping-Pong Loop

Do not run isolated monologues. Route the dyad through four structured board exchanges where partners `@mention` each other directly:

### Step 1 — Architect Frame & Falsifiable Predictions (`[carbon-dyad]`)
The Architect formulates:
1. The exact mechanistic hypothesis and mathematical equations (likelihood, state transition, censoring boundary, or variance decomposition).
2. Explicit **falsifiable predictions** that must hold on held-out / out-of-sample slices if the hypothesis is true.
3. Concrete diagnostic queries and code-path invariants for `@neon-dyad` to verify.

### Step 2 — Full-Repo X-Ray, Literature Harvest & Empirical Ablation (`[neon-dyad]`)
The `builder_xhigh` partner ingests the full call graph in parallel, harvests primary-source literature (if external grounding is required), runs exact OOS/Parquet diagnostics, and posts back to `@carbon-dyad`:
1. Verified file:line trace of every upstream producer and downstream consumer (confirming liveness and zero silent fallbacks).
2. Quantitative diagnostic tables (subgroup splits, tail quantiles, ablation deltas, uncertainty intervals — never anecdotal examples).
3. Direct pass/fail status against each of the Architect's Step 1 predictions.
4. Thin-adapter probe discipline (`<= 300` LOC): import production modules (`src/...`) directly and isolate only the candidate mechanism in a thin adapter rather than cloning `1,000+`-line standalone pipeline copies that must be re-ported from scratch in Protocol B.

### Step 3 — Hostile Red-Team & Subgroup/Tail Audit (`[carbon-dyad]`)
The Architect actively tries to break the empirical findings:
1. Checks for time-boundary leakage, survivorship/truncation bias, duplicate joins, zero-variance/dead wires, or step-function cliffs.
2. Either requests **one targeted follow-up falsification test** from `@neon-dyad` (returning to Step 2) or certifies that the mechanism survives adversarial scrutiny.

### Step 4 — Locked Mathematical & File-Level Specification (`[carbon-dyad]` -> `@coordinator`)
Once Step 3 passes with zero open falsification traps, the Architect writes the locked specification artifact containing:
- Exact governing equations and parameter/identifiability constraints.
- File-by-file change list and invariants (`no-step-gate`, `as-of` boundary, zero output patches).
- Mandatory acceptance tests and tail/subgroup audit gates for **Protocol B (`alloy-build`)**.
- **1-Unit Production Canary Timing:** Time `1` real unit (`1` partition, `1` shard, or `1` trial) through the **actual production entry point** before stating any rebuild or sweep schedule (`measured_sec_per_unit * total_units / authorized_cores`); never extrapolate production schedules from simplified prototype shortcuts.
- **Selective Cache-Invalidation Scope:** Name the exact upstream/downstream artifacts whose consumed inputs or schema versions changed and forbid blanket cache invalidation across unaffected stages.

## Structured Dispatch & Board Templates

### Spawning the Dyad (`swarm(action="add", ...)`)

```text
swarm(
  action="add",
  name="carbon-dyad",
  model="gemini-4-carbon-high",
  workspace="inherit",
  brief="@carbon-dyad [carbon-dyad]\nFrame the causal/statistical hypotheses for <problem>, define falsifiable OOS predictions, and hand off concrete code-path and dataset checks to @neon-dyad. Do NOT call edit_file; write only the diagnostic frame and later the locked spec."
)

swarm(
  action="add",
  name="neon-dyad",
  model="gemini-4-neon-xhigh",
  workspace="inherit",
  brief="@neon-dyad [neon-dyad]\nWait for @carbon-dyad's Step 1 hypotheses (or start parallel full-repo code X-ray across <modules>). Run primary-source literature verification and whole-population OOS/Parquet ablations, then report exact tables and file:line findings to @carbon-dyad."
)
```

> **Model Router guarantee:** Even if a coordinator passes `builder_high` (`gemini-4-neon-high`) with `[neon-dyad]`, `[neon-research]`, or `[dyad]`, Model Router's Alloy policy automatically upgrades it to `builder_xhigh` (`neon.dyad_or_kernel_upgrade`). Negated prohibitions such as `"do NOT call edit_file"` or `"Audit patch 2"` in the Architect's brief are scrubbed safely so the Architect is never falsely redirected.

### Board Ping-Pong Post Formats

**Step 1 (`carbon-dyad` -> `@neon-dyad`):**
```markdown
@neon-dyad [step-1-frame]
- Hypothesis H1: <mechanistic equation / bias mechanism>
- Falsifiable prediction P1: <exact quantitative sign/magnitude on held-out slice S>
- X-ray targets: <module_a.py -> module_b.py call chain>
- Empirical check requested: <exact ablation / subgroup table>
```

**Step 2 (`neon-dyad` -> `@carbon-dyad`):**
```markdown
@carbon-dyad [step-2-evidence]
- Code X-ray: <file:line findings, dead/live wire confirmation>
- Literature check: <primary-source citation + equation mapping>
- Prediction P1 verdict: PASS | FAIL (<exact table with N, metric, CI>)
- Surprises / anomalies: <unexpected subgroup or tail behavior>
```

**Step 3/4 (`carbon-dyad` -> `@coordinator`):**
```markdown
@coordinator [done] [spec-locked]
- Mechanism verified: <1-sentence summary>
- Falsification checks passed: <list>
- Locked spec path: <path/to/spec.md>
- Ready for Protocol B (`alloy-build`): dispatch Builder against locked spec.
```

## Strict Exclusivity Mode (`[carbon-neon]`)

When a research/audit sprint must run **exclusively** on the Architect and Builder pools with zero Grunt or Failover leakage, include `[carbon-neon]` in the turn or worker header (or state *"Carbon and Neon exclusively"*). Model Router locks all authorized reasoning roles to `architect` and all other work strictly to `builder_xhigh` / `builder_high`, even under low quota.
