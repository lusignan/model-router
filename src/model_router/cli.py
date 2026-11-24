"""Cross-harness hook dispatcher and CLI (--explain, --refresh-quota) for Model Router."""
from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any, Sequence

from .adapters import detect_harness, format_claude_code_pre_tool_output, handle_claude_code_payload
from .alloy import ALLOW, RouteExplanation, explain_swarm_route, handle_swarm, is_swarm_control_tool
from .config import MODEL_PRESETS, RouterConfig, load_config
from .guards import EDIT_TOOLS, handle_edit, handle_subagent, handle_workflow
from .quota import handle_post_tool_use, refresh_quota_snapshot
from .text import extract_turn_flags

if TYPE_CHECKING:
    import argparse


def _handle_antigravity_payload(payload: dict[str, Any], conf: RouterConfig) -> dict[str, Any]:
    event_name = str(payload.get("hookEventName") or "PreToolUse").strip()
    if event_name == "PostToolUse":
        return handle_post_tool_use(payload, conf)

    model_name = str(payload.get("modelName") or "").strip().lower()
    last_input = str(payload.get("lastUserInput") or "")
    turn_flags = extract_turn_flags(last_input)
    if "[allow-gemini]" in turn_flags or "[inline-gemini]" in turn_flags:
        return ALLOW

    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return ALLOW

    tool_name = str(tool_call.get("name") or "").strip()
    raw_args = tool_call.get("args")
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except ValueError:
            return ALLOW
    if not isinstance(raw_args, dict):
        return ALLOW

    transcript_path = str(payload.get("transcriptPath") or "")
    if is_swarm_control_tool(tool_name):
        return handle_swarm(raw_args, last_input, transcript_path, conf)
    if tool_name == "invoke_subagent":
        return handle_subagent(raw_args, model_name, conf, transcript_path)
    if tool_name == "run_workflow":
        return handle_workflow(raw_args, model_name, conf, transcript_path)
    if tool_name in EDIT_TOOLS:
        conv_id = str(payload.get("conversationId") or "default")
        return handle_edit(raw_args, model_name, conv_id, last_input, transcript_path, conf)
    return ALLOW


def decide(
    payload: dict[str, Any],
    cfg: RouterConfig | None = None,
    harness: str = "auto",
) -> dict[str, Any]:
    """Compute PreToolUse/PostToolUse hook output for Antigravity or Claude Code payloads."""
    if cfg is None:
        cwd = str(payload.get("cwd") or "")
        raw_workspaces = payload.get("workspacePaths")
        workspaces: list[str] = (
            [str(p) for p in raw_workspaces if isinstance(p, str)]
            if isinstance(raw_workspaces, list)
            else []
        )
        conf = load_config(cwd=cwd, workspace_paths=workspaces)
    else:
        conf = cfg

    resolved_harness = detect_harness(payload, harness)
    if resolved_harness == "claude-code":
        return handle_claude_code_payload(payload, conf)
    return _handle_antigravity_payload(payload, conf)


def format_explanation(
    exp: RouteExplanation,
    harness: str = "antigravity",
    hook_response: dict[str, Any] | None = None,
) -> str:
    """Format a RouteExplanation as a clean human-readable multi-line report."""
    resp = exp.to_hook_response() if hook_response is None else hook_response
    hook_json = json.dumps(resp, separators=(",", ":"))
    tags_str = ", ".join(exp.worker_tags) if exp.worker_tags else "(none)"
    flags_str = ", ".join(exp.turn_flags) if exp.turn_flags else "(none)"
    sources_str = ", ".join(exp.config_sources)
    lines = [
        "Model Router (Alloy Policy) Explanation",
        "---------------------------------------",
        f"Harness / Preset: {harness} / {exp.preset}",
        f"Worker          : {exp.worker_name or '(unnamed)'}",
        f"Requested model : {exp.requested_model or '(omitted)'}",
        f"Effective model : {exp.effective_model or '(unchanged)'}",
        f"Overwrite model : {exp.overwrite_model or '(none — allow as requested)'}",
        f"Rule ID         : {exp.rule_id}",
        f"Reason          : {exp.reason}",
        f"Worker tags     : {tags_str}",
        f"Turn flags      : {flags_str}",
        f"Quota state     : claude_exhausted={exp.claude_exhausted}, gemini_quota={exp.gemini_quota:.2f}",
        f"Exclusivity     : carbon_neon_exclusive={exp.carbon_neon_exclusive}",
        f"Config sources  : {sources_str}",
        f"Hook response   : {hook_json}",
    ]
    return "\n".join(lines)


def _build_explain_parser() -> argparse.ArgumentParser:
    import argparse

    parser = argparse.ArgumentParser(
        prog="model-router",
        description="Inspect or run the cross-harness Model Router (Alloy policy).",
    )
    parser.add_argument("--explain", action="store_true", help="Explain routing for a worker brief.")
    parser.add_argument(
        "--preset",
        choices=tuple(sorted(MODEL_PRESETS.keys())),
        default="",
        help="Optional named model pool preset (antigravity, claude-code, multi-provider).",
    )
    parser.add_argument(
        "--harness",
        choices=("antigravity", "claude-code"),
        default="antigravity",
        help="Target wire protocol format for hook_response (default: antigravity).",
    )
    parser.add_argument("--name", default="", help="Worker roster name or Claude Code Task description.")
    parser.add_argument("--brief", default="", help="Worker brief or Claude Code Task prompt.")
    parser.add_argument("--model", default="", help="Requested worker model (omit for default).")
    parser.add_argument("--last-input", default="", help="Parent turn last user input text.")
    parser.add_argument("--claude-quota", type=float, default=None, help="Simulated Claude quota fraction (0..1).")
    parser.add_argument("--gemini-quota", type=float, default=None, help="Simulated Gemini quota fraction (0..1).")
    parser.add_argument("--cwd", default="", help="Workspace directory for .agents/model-router.json discovery.")
    parser.add_argument("--pretty", action="store_true", help="Print a human-readable explanation summary.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint for hook execution (stdin JSON), --refresh-quota, and --explain."""
    args_list = list(sys.argv[1:] if argv is None else argv)

    if "--refresh-quota" in args_list:
        cfg = load_config()
        result = refresh_quota_snapshot(cfg=cfg)
        print(json.dumps(result))
        return 0

    if "--explain" in args_list or "-h" in args_list or "--help" in args_list:
        parser = _build_explain_parser()
        parsed = parser.parse_args(args_list)
        cfg = load_config(cwd=parsed.cwd, preset_override=parsed.preset)
        swarm_args: dict[str, Any] = {
            "action": "add",
            "name": parsed.name,
            "brief": parsed.brief,
        }
        if parsed.model:
            swarm_args["model"] = parsed.model
        exp = explain_swarm_route(
            args=swarm_args,
            last_input=parsed.last_input,
            cfg=cfg,
            claude_quota_override=parsed.claude_quota,
            gemini_quota_override=parsed.gemini_quota,
        )
        if parsed.harness == "claude-code":
            task_input: dict[str, Any] = {
                "description": parsed.name or "task-worker",
                "prompt": parsed.brief,
            }
            if parsed.model:
                task_input["model"] = parsed.model
            hook_resp = format_claude_code_pre_tool_output(exp, task_input)
        else:
            hook_resp = exp.to_hook_response()

        if parsed.pretty:
            print(format_explanation(exp, harness=parsed.harness, hook_response=hook_resp))
        else:
            out_dict = exp.to_dict()
            out_dict["harness"] = parsed.harness
            out_dict["hook_response"] = hook_resp
            print(json.dumps(out_dict, indent=2))
        return 0

    raw = ""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        out = decide(payload if isinstance(payload, dict) else {})
    except Exception:
        is_empty_failopen = (
            '"PostToolUse"' in raw
            or '"hook_event_name"' in raw
            or '"tool_name"' in raw
        )
        out = {} if is_empty_failopen else ALLOW
    print(json.dumps(out))
    return 0
