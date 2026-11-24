"""PreToolUse guards for subagents, workflows, and inline parent-pool edit caps."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .config import RouterConfig, turn_edits_state_path
from .quota import atomic_write_json

ALLOW: dict[str, Any] = {"decision": "allow"}

EDIT_TOOLS: frozenset[str] = frozenset({
    "edit_file",
    "write_file",
    "replace_file_content",
    "multi_replace_file_content",
    "write_to_file",
})

_SWARM_TRANSCRIPT_MARKERS: tuple[str, ...] = (
    "[neon-kernel]",
    "[neon-research]",
    "[neon-dyad]",
    "[neon]",
    "[carbon-dyad]",
    "[carbon-build]",
    "[carbon]",
    "<swarm_worker>",
)


def is_gemini_parent(model_name: str) -> bool:
    """Return True when the active session model draws from the shared weekly Gemini pool."""
    m = model_name.strip().lower()
    if "claude" in m or "gpt" in m:
        return False
    return m in ("", "auto") or "gemini" in m or "orchestrator" in m


def handle_subagent(
    args: dict[str, Any],
    model_name: str,
    cfg: RouterConfig | None = None,
    transcript_path: str = "",
) -> dict[str, Any]:
    """Block unmanaged parent-pool invoke_subagent calls except configured specialist subagents."""
    del transcript_path
    if not is_gemini_parent(model_name):
        return ALLOW

    conf = cfg or RouterConfig.default()
    specialists = frozenset(s.lower() for s in conf.specialist_subagents)

    types: list[str] = []
    tn = args.get("TypeName")
    if tn:
        types.append(str(tn).strip().lower())
    subs = args.get("Subagents")
    if isinstance(subs, list):
        for item in subs:
            if isinstance(item, dict) and item.get("TypeName"):
                types.append(str(item["TypeName"]).strip().lower())

    if types and all(t in specialists for t in types):
        return ALLOW

    return {
        "decision": "deny",
        "reason": (
            "Model Router (Alloy policy): invoke_subagent inherits the parent context/pool. "
            'Use the Alloy swarm pipeline instead: Architect writes the spec -> swarm(action="add", '
            f'name="neon-builder", model="{conf.models.builder_xhigh}", brief="...") builds the code -> '
            'Grunt ("[grunt]") handles docs/exports/commits -> Architect ("[carbon]") audits.'
        ),
    }


def handle_workflow(
    args: dict[str, Any],
    model_name: str,
    cfg: RouterConfig | None = None,
    transcript_path: str = "",
) -> dict[str, Any]:
    """Block unmanaged run_workflow agent(...) calls from a Gemini parent unless [allow-gemini] is set."""
    del transcript_path
    if not is_gemini_parent(model_name):
        return ALLOW

    conf = cfg or RouterConfig.default()
    parts: list[str] = []
    if args.get("Script"):
        parts.append(str(args["Script"]))
    sp = args.get("ScriptPath")
    if sp:
        p = Path(str(sp)).expanduser()
        if p.is_file():
            try:
                parts.append(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    src = "\n".join(parts)
    if "agent(" in src and "[allow-gemini]" not in src.lower():
        return {
            "decision": "deny",
            "reason": (
                "Model Router (Alloy policy): run_workflow agent() spawns unmanaged parent-pool agents. "
                f'Fan out via swarm(action="add", ...) using Builder ("{conf.models.builder_xhigh}") for code/empirical '
                'sweeps, Grunt ("[grunt]") for grunt work, and Architect ("[carbon]") for audits.'
            ),
        }
    return ALLOW


def is_swarm_or_kernel_transcript(transcript_path: str) -> bool:
    """Return True if transcript_path belongs to a spawned swarm worker (exempt from inline parent cap)."""
    if not transcript_path:
        return False
    p = Path(transcript_path).expanduser()
    if not p.is_file():
        return False
    try:
        with p.open("r", encoding="utf-8", errors="ignore") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    low = head.lower()
    if any(t in low for t in _SWARM_TRANSCRIPT_MARKERS):
        return True
    first_line = head.splitlines()[0] if head else ""
    if first_line:
        try:
            first_obj = json.loads(first_line)
            if (
                isinstance(first_obj, dict)
                and first_obj.get("step_index") == 0
                and first_obj.get("type") == "SYSTEM_MESSAGE"
            ):
                return True
        except ValueError:
            pass
    return False


def transcript_bytes(transcript_path: str) -> int:
    """Return max byte size across the active transcript and sibling transcript_full.jsonl."""
    if not transcript_path:
        return 0
    p = Path(transcript_path).expanduser()
    mx = 0
    for cand in (p, p.with_name("transcript_full.jsonl")):
        try:
            if cand.is_file():
                mx = max(mx, int(cand.stat().st_size))
        except OSError:
            pass
    return mx


def latest_turn_and_batch_context(transcript_path: str) -> tuple[str, str]:
    """Return (user_turn_salt, batch_id) from the tail of transcriptPath."""
    if not transcript_path:
        return "", ""
    p = Path(transcript_path).expanduser()
    if not p.is_file():
        return "", ""
    user_salt = ""
    latest_planner = "init"
    saw_planner = False
    try:
        size = p.stat().st_size
        if size <= 0:
            return "", ""
        with p.open("rb") as fh:
            for window in (262_144, 2_097_152):
                offset = max(0, size - window)
                fh.seek(offset)
                chunk = fh.read(size - offset).decode("utf-8", errors="ignore")
                lines = chunk.splitlines()
                if offset > 0 and lines:
                    lines = lines[1:]
                for line in reversed(lines):
                    if not saw_planner and '"PLANNER_RESPONSE"' in line:
                        try:
                            p_obj = json.loads(line)
                            if isinstance(p_obj, dict) and p_obj.get("type") == "PLANNER_RESPONSE":
                                latest_planner = f"p{p_obj.get('step_index')}"
                                saw_planner = True
                        except ValueError:
                            pass
                    if '"USER_INPUT"' in line:
                        try:
                            u_obj = json.loads(line)
                            if isinstance(u_obj, dict) and u_obj.get("type") == "USER_INPUT":
                                user_salt = f"{u_obj.get('step_index')}:{u_obj.get('created_at') or ''}"
                                return user_salt, latest_planner
                        except ValueError:
                            pass
                if offset == 0:
                    break
    except OSError:
        return "", ""
    return user_salt, latest_planner


def handle_edit(
    args: dict[str, Any],
    model_name: str,
    conv_id: str,
    last_input: str,
    transcript_path: str,
    cfg: RouterConfig | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Enforce lean (<1 MB) and heavy (>=1 MB) inline edit and planner-batch limits on Architect parents."""
    if not is_gemini_parent(model_name):
        return ALLOW

    if args.get("ArtifactMetadata") is not None or bool(args.get("IsArtifact")):
        return ALLOW

    target_path = str(args.get("Path") or args.get("TargetFile") or "")
    normalized_target = target_path.replace("\\", "/")
    if "/.gemini/" in normalized_target or "/brain/" in normalized_target:
        return ALLOW

    if is_swarm_or_kernel_transcript(transcript_path):
        return ALLOW

    conf = cfg or RouterConfig.default()
    th = conf.thresholds

    t_bytes = transcript_bytes(transcript_path)
    is_heavy = t_bytes >= th.heavy_transcript_bytes
    turn_salt, batch_id = latest_turn_and_batch_context(transcript_path)

    if is_heavy:
        max_edits = th.max_inline_edits_heavy if batch_id else 1
        max_batches = th.max_inline_batches_heavy
    else:
        max_edits = th.max_inline_edits_lean
        max_batches = th.max_inline_batches_lean

    state_file = turn_edits_state_path()
    cur_now = time.time() if now is None else now
    try:
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}

    pruned: dict[str, dict[str, Any]] = {}
    for k, v in state.items():
        if isinstance(v, dict):
            ts = v.get("ts")
            if isinstance(ts, (int, float)) and not isinstance(ts, bool) and (cur_now - float(ts)) <= th.state_ttl_seconds:
                pruned[str(k)] = v

    key_material = f"{last_input}\0{turn_salt}" if turn_salt else last_input
    digest = hashlib.sha1(key_material.encode("utf-8", "ignore")).hexdigest()[:12]
    turn_key = f"{conv_id}:{digest}"
    raw_entry = pruned.get(turn_key)
    entry: dict[str, Any] = raw_entry if isinstance(raw_entry, dict) else {}
    prev_count = int(entry.get("count", 0))
    raw_batches = entry.get("batches", [])
    prev_batches = [str(b) for b in raw_batches if b] if isinstance(raw_batches, list) else []

    new_count = prev_count + 1
    if batch_id and batch_id not in prev_batches:
        batches = prev_batches + [batch_id]
    else:
        batches = prev_batches

    batch_ok = (len(batches) <= max_batches) if batch_id else True
    if new_count <= max_edits and batch_ok:
        pruned[turn_key] = {"count": new_count, "batches": batches, "ts": cur_now}
        atomic_write_json(state_file, pruned)
        return ALLOW

    if len(pruned) != len(state):
        atomic_write_json(state_file, pruned)

    tier_note = (
        f"heavy >=1 MB thread ({t_bytes // 1024} KB; {max_batches} parallel surgical batch / {max_edits} files max)"
        if is_heavy
        else f"lean <1 MB thread ({max_batches} batches / {max_edits} files max)"
    )
    return {
        "decision": "deny",
        "reason": (
            f"Model Router (Alloy policy): inline Architect edit limit ({tier_note}) reached. "
            "Architect owns specs, briefs, research, and adversarial review — never multi-turn edit-test loops. "
            f'Write the exact spec and dispatch code building to Builder ("{conf.models.builder_xhigh}") '
            'and grunt work (docs/exports/guards/commits) to Grunt ("[grunt]").'
        ),
    }
