#!/usr/bin/env python3
"""Microbenchmark suite for Model Router (7 warm in-process workloads + cold hook subprocess)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
HOOK_PATH = REPO_ROOT / "hooks" / "model_stack_router.py"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from model_router.cli import decide  # noqa: E402
from model_router.config import RouterConfig  # noqa: E402


def _iso_utc(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _build_synthetic_transcript(path: Path, target_bytes: int, base_ts: float) -> None:
    """Create a realistic JSONL transcript of ~target_bytes ending with a swarm(models) snapshot."""
    lines: list[str] = []
    step = 1
    written = 0
    filler = "diagnostic state-space residual check " * 14
    while written < max(0, target_bytes - 4096):
        kind = "USER_INPUT" if step % 20 == 1 else ("PLANNER_RESPONSE" if step % 4 == 0 else "TOOL_RESULT")
        rec = json.dumps(
            {
                "step_index": step,
                "type": kind,
                "created_at": _iso_utc(base_ts - 600.0 + step * 0.1),
                "content": f"Step {step}: {filler}",
            },
            separators=(",", ":"),
        )
        lines.append(rec)
        written += len(rec) + 1
        step += 1

    rst_iso = _iso_utc(base_ts + 7200.0)
    models_inner = {
        "models": [
            "claude-sonnet-5-5-high",
            "claude-sonnet-5-5-low",
            "gemini-4-carbon-high",
            "gemini-4-neon-xhigh",
            "gemini-4-hydrogen-high",
        ],
        "display_names": {
            "claude-sonnet-5-5-high": "Claude Sonnet 5.5 High",
            "gemini-4-neon-xhigh": "Gemini 4 Neon XHigh",
        },
        "quotas": {
            "claude-sonnet-5-5-high": {"quota_remaining": "55%", "quota_resets": rst_iso},
            "claude-sonnet-5-5-low": {"quota_remaining": "55%", "quota_resets": rst_iso},
            "gemini-4-neon-xhigh": {"quota_remaining": "93%", "quota_resets": rst_iso},
            "gemini-4-hydrogen-high": {"quota_remaining": "93%", "quota_resets": rst_iso},
        },
    }
    lines.append(
        json.dumps(
            {
                "step_index": step,
                "type": "TOOL_RESULT",
                "created_at": _iso_utc(base_ts - 5.0),
                "content": json.dumps(models_inner, separators=(",", ":")),
            },
            separators=(",", ":"),
        )
    )
    lines.append(
        json.dumps(
            {
                "step_index": step + 1,
                "type": "PLANNER_RESPONSE",
                "created_at": _iso_utc(base_ts - 1.0),
                "content": "Dispatching next batch.",
            },
            separators=(",", ":"),
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _summarize(label: str, samples_ms: list[float], count: int) -> dict[str, Any]:
    s = sorted(samples_ms)
    total_s = sum(s) / 1000.0
    ops_per_sec = (count / total_s) if total_s > 0 else 0.0
    return {
        "label": label,
        "iterations": count,
        "p50_ms": _percentile(s, 50.0),
        "p95_ms": _percentile(s, 95.0),
        "p99_ms": _percentile(s, 99.0),
        "ops_per_sec": ops_per_sec,
    }


def run_benchmarks(warm_iterations: int = 2000, cold_iterations: int = 20) -> list[dict[str, Any]]:
    """Run 7 warm in-process workloads (Antigravity + Claude Code) and cold subprocess invocations."""
    cfg_agy = RouterConfig.default("antigravity")
    cfg_cc = RouterConfig.default("claude-code")
    now = time.time()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        cache_path = tmp_dir / "quota_cache.json"
        edit_state_path = tmp_dir / "turn_edits.json"
        brain_dir = tmp_dir / "brain"

        conv_256 = brain_dir / "conv_256k" / ".system_generated" / "logs"
        tr_256 = conv_256 / "transcript.jsonl"
        tr_256_full = conv_256 / "transcript_full.jsonl"
        _build_synthetic_transcript(tr_256_full, 256 * 1024, now)
        tr_256.write_text('{"step_index":1,"type":"USER_INPUT","created_at":"2026-11-23T12:00:00Z"}\n', encoding="utf-8")

        conv_heavy = tmp_dir / "heavy_conv" / ".system_generated" / "logs"
        tr_heavy = conv_heavy / "transcript.jsonl"
        tr_heavy_full = conv_heavy / "transcript_full.jsonl"
        _build_synthetic_transcript(tr_heavy_full, 1_050_000, now)
        tr_heavy.write_text(
            json.dumps({"step_index": 1, "type": "USER_INPUT", "created_at": _iso_utc(now - 30.0)})
            + "\n"
            + json.dumps({"step_index": 2, "type": "PLANNER_RESPONSE", "created_at": _iso_utc(now - 10.0)})
            + "\n",
            encoding="utf-8",
        )

        env_backup = dict(os.environ)
        os.environ.update(
            {
                "MODEL_ROUTER_QUOTA_CACHE_PATH": str(cache_path),
                "MODEL_ROUTER_EDIT_STATE_PATH": str(edit_state_path),
                "MODEL_ROUTER_BRAIN_DIR": str(brain_dir),
                "MODEL_ROUTER_CLAUDE_QUOTA": "0.55",
                "MODEL_ROUTER_GEMINI_QUOTA": "0.93",
                "MODEL_ROUTER_DISABLE_GLOBAL_CONFIG": "1",
                "AGY_ROUTER_DISABLE_GLOBAL_CONFIG": "1",
                "ANTIGRAVITY_LS_ADDRESS": "",
                "ANTIGRAVITY_CSRF_TOKEN": "",
            }
        )

        try:
            workloads: list[tuple[str, dict[str, Any], RouterConfig]] = [
                (
                    "PreToolUse: Antigravity dyad upgrade (`[neon-dyad]`)",
                    {
                        "hookEventName": "PreToolUse",
                        "modelName": "orchestrator (carbon)",
                        "lastUserInput": "Run full codebase diagnostics.",
                        "transcriptPath": str(tr_256),
                        "toolCall": {
                            "name": "swarm",
                            "args": {
                                "action": "add",
                                "name": "neon-xray",
                                "model": "gemini-4-neon-high",
                                "brief": "@neon-xray [neon-dyad] Run full-repo Parquet ablation across state-space filters.",
                            },
                        },
                    },
                    cfg_agy,
                ),
                (
                    "PreToolUse: Antigravity grunt (`[grunt]` + code spans)",
                    {
                        "hookEventName": "PreToolUse",
                        "modelName": "orchestrator (carbon)",
                        "lastUserInput": "Update docs for `[carbon]` and `[neon]` rules.",
                        "transcriptPath": str(tr_256),
                        "toolCall": {
                            "name": "swarm",
                            "args": {
                                "action": "add",
                                "name": "grunt-sync",
                                "model": "claude-sonnet-5-5-high",
                                "brief": "@grunt-sync [grunt]\nSync `DECISIONS.md` and `STATUS.md` referencing `[neon]` and `kalman`.",
                            },
                        },
                    },
                    cfg_agy,
                ),
                (
                    "PreToolUse: Architect coding-loop redirect",
                    {
                        "hookEventName": "PreToolUse",
                        "modelName": "orchestrator (carbon)",
                        "lastUserInput": "Build the solver update.",
                        "transcriptPath": str(tr_256),
                        "toolCall": {
                            "name": "swarm",
                            "args": {
                                "action": "add",
                                "name": "carbon-patches",
                                "model": "gemini-4-carbon-high",
                                "brief": "Apply patch 2 and call edit_file on filter.py and kernel.py.",
                            },
                        },
                    },
                    cfg_agy,
                ),
                (
                    "PreToolUse: Claude Code `Task` -> `updatedInput`",
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "cc-bench",
                        "transcript_path": str(tr_256),
                        "tool_name": "Task",
                        "tool_input": {
                            "description": "commit-crew",
                            "subagent_type": "general-purpose",
                            "model": "opus",
                            "prompt": "@commit-crew [grunt-low]\nStage and git commit.",
                        },
                    },
                    cfg_cc,
                ),
                (
                    "PreToolUse: inline heavy (`>=1 MB`) edit guard",
                    {
                        "hookEventName": "PreToolUse",
                        "modelName": "orchestrator (carbon)",
                        "conversationId": "bench-heavy",
                        "lastUserInput": "Refactor solver loop.",
                        "transcriptPath": str(tr_heavy),
                        "toolCall": {
                            "name": "edit_file",
                            "args": {"Path": "/workspace/src/solver.py"},
                        },
                    },
                    cfg_agy,
                ),
                (
                    "PreToolUse: `invoke_subagent` guard",
                    {
                        "hookEventName": "PreToolUse",
                        "modelName": "orchestrator (carbon)",
                        "lastUserInput": "Explore repo.",
                        "transcriptPath": str(tr_256),
                        "toolCall": {
                            "name": "invoke_subagent",
                            "args": {"TypeName": "research"},
                        },
                    },
                    cfg_agy,
                ),
                (
                    "PostToolUse: `256 KB` JSONL transcript quota poll",
                    {
                        "hookEventName": "PostToolUse",
                        "transcriptPath": str(tr_256),
                        "toolCall": {
                            "name": "swarm",
                            "args": {"action": "models"},
                        },
                    },
                    cfg_agy,
                ),
            ]

            results: list[dict[str, Any]] = []
            per_workload = max(1, warm_iterations // len(workloads))
            remainder = warm_iterations - per_workload * len(workloads)

            # Warmup pass
            for _, payload, conf in workloads:
                decide(payload, conf)

            all_warm_samples: list[float] = []
            for idx, (label, payload, conf) in enumerate(workloads):
                iters = per_workload + (1 if idx < remainder else 0)
                samples_ms: list[float] = []
                for _ in range(iters):
                    t0 = time.perf_counter()
                    decide(payload, conf)
                    dt_ms = (time.perf_counter() - t0) * 1000.0
                    samples_ms.append(dt_ms)
                all_warm_samples.extend(samples_ms)
                results.append(_summarize(label, samples_ms, iters))

            results.append(
                _summarize(
                    "**Aggregate warm in-process (`decide()`)**",
                    all_warm_samples,
                    len(all_warm_samples),
                )
            )

            # Cold subprocess invocations via /usr/bin/python3 (or current executable on Windows)
            py_bin = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else sys.executable
            sub_payload = json.dumps(workloads[0][1])
            clean_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "MODEL_ROUTER_QUOTA_CACHE_PATH": str(cache_path),
                "MODEL_ROUTER_EDIT_STATE_PATH": str(edit_state_path),
                "MODEL_ROUTER_BRAIN_DIR": str(brain_dir),
                "MODEL_ROUTER_CLAUDE_QUOTA": "0.55",
                "MODEL_ROUTER_GEMINI_QUOTA": "0.93",
                "MODEL_ROUTER_DISABLE_GLOBAL_CONFIG": "1",
                "AGY_ROUTER_DISABLE_GLOBAL_CONFIG": "1",
            }
            for win_key in ("SYSTEMROOT", "SystemRoot", "COMSPEC", "WINDIR", "TEMP", "TMP"):
                if win_key in os.environ:
                    clean_env[win_key] = os.environ[win_key]
            cold_samples_ms: list[float] = []
            for _ in range(cold_iterations):
                t0 = time.perf_counter()
                proc = subprocess.run(
                    [py_bin, str(HOOK_PATH)],
                    input=sub_payload,
                    text=True,
                    capture_output=True,
                    env=clean_env,
                    check=True,
                )
                dt_ms = (time.perf_counter() - t0) * 1000.0
                if not proc.stdout.strip():
                    raise RuntimeError("Empty hook stdout during cold benchmark")
                cold_samples_ms.append(dt_ms)

            results.append(
                _summarize(
                    f"Cold hook subprocess (`{Path(py_bin).name} ./hooks/model_stack_router.py`)",
                    cold_samples_ms,
                    cold_iterations,
                )
            )
            return results
        finally:
            os.environ.clear()
            os.environ.update(env_backup)


def format_markdown_table(results: list[dict[str, Any]]) -> str:
    """Format benchmark rows into a GitHub-Flavored Markdown table."""
    lines = [
        "| Workload | Iterations | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (ops/s) | LLM Tokens |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        lines.append(
            f"| {row['label']} | {row['iterations']:,} | {row['p50_ms']:.3f} | "
            f"{row['p95_ms']:.3f} | {row['p99_ms']:.3f} | {row['ops_per_sec']:,.0f} | 0 |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark Model Router latency.")
    parser.add_argument("--warm-iterations", type=int, default=2000, help="Total warm decide() iterations.")
    parser.add_argument("--cold-iterations", type=int, default=20, help="Cold hook subprocess runs.")
    parser.add_argument(
        "--assert-p99-ms",
        type=float,
        default=None,
        help="Fail with non-zero exit if any warm workload p99 exceeds this threshold (ms).",
    )
    args = parser.parse_args(argv)

    results = run_benchmarks(
        warm_iterations=args.warm_iterations,
        cold_iterations=args.cold_iterations,
    )
    print(f"Environment: Python {platform.python_version()} on {platform.system()} {platform.machine()}")
    print()
    print(format_markdown_table(results))

    if args.assert_p99_ms is not None:
        warm_rows = [r for r in results if not r["label"].startswith("Cold hook subprocess")]
        worst = max(warm_rows, key=lambda r: r["p99_ms"])
        if worst["p99_ms"] > args.assert_p99_ms:
            print(
                f"\nFAIL: '{worst['label']}' warm p99={worst['p99_ms']:.3f} ms "
                f"exceeded --assert-p99-ms {args.assert_p99_ms:.3f} ms",
                file=sys.stderr,
            )
            return 1
        print(
            f"\nPASS: max warm p99={worst['p99_ms']:.3f} ms <= {args.assert_p99_ms:.3f} ms "
            f"(worst workload: {worst['label']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
