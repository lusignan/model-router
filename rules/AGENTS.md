# Model Router & Model Alloy Policy (`Architect` · `Builder` · `Fast Verifier / Grunt`)

## Control-Plane Principle

**Model Router** (`src/model_router/`) is a zero-dependency, deterministic `PreToolUse`/`PostToolUse` lifecycle hook control plane supporting **Google Antigravity**, **Claude Code**, and custom multi-provider harnesses. Its core routing policy component—**the Model Alloy (`model_router.alloy`)**—binds distinct model profiles across asymmetric lifecycle roles while protecting scarce frontier reasoning quotas: under multi-provider presets (`antigravity`, `multi-provider`, and custom multi-provider configs), roles route across different model families so no model grades its own work and **blind spots are less correlated**, while the single-provider `claude-code` preset tiers roles across `opus`, `sonnet`, and `haiku` within Anthropic's family (mapping both `architect` and `forensic` to `opus` unless paired with an external reviewer):

- **Architect & Gatekeeper (`architect` / `carbon`, e.g., `gemini-4-carbon-high`, `opus`, or `o3`):** owns causal identification, Bayesian & state-space derivations, censoring/selection diagnosis, mathematical & file-level specifications, lead research, and mandatory post-build adversarial diff/slice audits. Blocked from multi-turn code-build loops (auto-redirected to `builder_xhigh`).
- **Builder / `1M` Empirical Partner (`builder_xhigh` / `builder_high` / `neon`, e.g., `gemini-4-neon-xhigh`, `sonnet`, or `gemini-2.5-pro`):** owns simultaneous full-repo code X-ray, primary-source literature extraction, whole-population empirical ablations, and primary code implementation across all core modules, numerical kernels, and pipelines.
- **Fast Verifier / Grunt & Failover (`grunt_high`/`grunt_low` <-> `failover_grunt_high`/`failover_grunt_low`, e.g., `claude-sonnet-5-5-low/high` <-> `gemini-4-hydrogen-low/high` or `sonnet`/`haiku`):** owns all mechanical and plumbing work — documentation/ledger synchronization, HTML/CSV export scripts, test and guard sweeps (`compileall && unittest/pytest`), linting, swarm monitoring, and atomic git commits — with automatic `resetTime`-aware failover when primary verifier/grunt quota drops to `<= 2%`.

## Role Matrix (Antigravity Default Preset)

| Stage | Role Slot | Antigravity Default | Exact Scope |
|---|---|---|---|
| **1. Architect & Gatekeeper** | `architect` (`carbon`) | `gemini-4-carbon-high` | Specs, briefs, directives, statistical/physical laws, causal identification, surgical 1-batch math fixes (`<= 4` files on `>= 1 MB` threads), and mandatory post-build diff + tail/subgroup audits (`[carbon]` / `[carbon-dyad]`). |
| **2. Research & Audit Dyad** | `architect` <-> `builder_xhigh` | `gemini-4-carbon-high` <-> `gemini-4-neon-xhigh` | Live adversarial ping-pong on the swarm board before a spec exists (`skills/research-dyad/SKILL.md`): Architect frames hypotheses and censoring/leakage traps -> Builder / `1M` Empirical Partner executes full-repo code X-ray, literature harvest, and empirical ablations -> Architect red-teams residuals and locks the spec. |
| **3. Builder / 1M Empirical Partner** | `builder_xhigh` / `builder_high` | `gemini-4-neon-xhigh` / `gemini-4-neon-high` | Default builder for all core code implementation and refactoring (`[neon]` / `[neon-kernel]`), bounded upstream by Architect's locked spec and downstream by Architect's audit. |
| **4. Fast Verifier / Grunt & Failover** | `grunt_*` <-> `failover_grunt_*` | `claude-sonnet-5-5-low/high` <-> `gemini-4-hydrogen-low/high` | Mechanical & plumbing work (`[grunt]` / `[grunt-low]`): docs/ledger sync, export plumbing, test/guard execution, formatting, swarm monitoring, and atomic commits. Disabled under `[carbon-neon]` exclusivity. |
| **5. Forensic Specialist** | `forensic` (`opus`) | `claude-opus-5-5-high` | Strictly gated on explicit `[opus]` or short (`< 1,800`-char) open-ended forensic briefs when Claude quota is healthy (`> 2%`) and `[carbon-neon]` exclusivity is inactive. |

## Operating Protocols

### Protocol A — Research & Audit Dyad (`Hypothesize -> 1M X-Ray & Test -> Red-Team -> Lock Spec`)

Invoke `skills/research-dyad/SKILL.md` whenever diagnosing forecast/model misses, auditing mathematical invariants, or conducting literature + empirical research before a specification exists. Pair `[carbon-dyad]` and `[neon-dyad]` directly with `@mention` handoffs until every hypothesis is empirically resolved and a crisp spec is locked.

### Protocol B — 4-Stage Build & Verification Loop (`Spec -> Build -> Verify || Audit -> Deliver`)

Invoke `skills/alloy-build/SKILL.md` once a specification is locked:
1. **Architect** locks the mathematical and file-level spec (no heuristic step cliffs or post-hoc output patches).
2. **Builder (`builder_xhigh`)** (`[neon]` / `[neon-kernel]`) implements core code changes and runs fast compile + targeted canary/unit checks.
3. **Fast Verifier / Grunt** (`[grunt]` / `[grunt-low]`) and **4. Architect Gatekeeper** (`[carbon]`) run **concurrently** on the frozen build: Verifier executes the single parallelized test/guard sweep while Architect audits `git diff`, evaluation metrics, and tail/subgroup diagnostics; Grunt then syncs docs/exports and commits atomically (routing to Builder under `[carbon-neon]` exclusivity).

## Cross-Cutting Invariants

1. **Zero-Analysis Executor Discipline:** When an orchestrator exits planning mode, dispatch workers cleanly (`swarm(action="add", ...)`, `post_message`, `swarm_wait`) and return control to the Architect for all mathematical analysis, diff review, and next-spec decisions.
2. **Mandatory Batching:** Batch upfront reads/searches into 1 parallel turn, batch independent edits into 1–2 parallel turns (`<= 4` files in `1` batch on heavy `>= 1 MB` threads), and chain `compileall && unittest/pytest && guards` in 1 shell command.
3. **Unmanaged Subagent & Workflow Guard:** Do not call unmanaged `invoke_subagent` (except configured specialists such as `browser` and `image-generator`) or `run_workflow` `agent(...)` from a Gemini parent; use `swarm(action="add", ...)` so Model Router governs every worker's model pool.
4. **Presets, Layered Config & Escape Hatches:** Choose a built-in preset (`antigravity`, `claude-code`, `multi-provider`) and extend project keywords, role-slot `models`, or `thresholds` in `<repo>/.agents/model-router.json` (or `.agents/alloy.json`). Header role tags and turn flags (`[carbon-neon]`, `[allow-gemini]`, `[claude-exhausted]`) are always parsed safely outside markdown code spans.
5. **Zero Build-Twice, Disjoint Parallelism & Measured-Rate ETAs:** Research probes import `src/` directly via thin (`<= 300` LOC) adapters rather than standalone pipeline clones; locked specs require `1`-unit production-entry-point canary timings and selective cache-invalidation scopes; disjoint-file builders (`files_A ∩ files_B = ∅`) code and unit-test in parallel on shared checkouts; multi-trial sweeps and evaluations saturate authorized cores; all ETAs cite `(measured_sec_per_unit * remaining_units / active_cores) + unedited_spec_files` verified against `git status` and live logs; and background command fan-outs use harness-tracked async tasks or `(... & wait)` rather than untracked detached daemons.
