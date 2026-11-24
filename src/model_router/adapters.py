"""Multi-harness wire protocol adapter for Google Antigravity and Claude Code."""
from __future__ import annotations

import os
from typing import Any

from .alloy import RouteExplanation, explain_swarm_route, is_swarm_control_tool
from .config import RouterConfig
from .guards import handle_edit
from .quota import QUOTA_ERROR_MARKERS, handle_post_tool_use
from .text import extract_turn_flags

CLAUDE_CODE_EDIT_TOOLS: frozenset[str] = frozenset({
    "Edit",
    "MultiEdit",
    "Write",
    "NotebookEdit",
})


def detect_harness(payload: dict[str, Any], harness_override: str = "auto") -> str:
    """Detect whether a hook JSON payload uses Antigravity or Claude Code wire schema."""
    override = (harness_override or "auto").strip().lower()
    if override in ("antigravity", "claude-code"):
        return override
    if "toolCall" in payload or "hookEventName" in payload:
        return "antigravity"
    if "tool_name" in payload or "hook_event_name" in payload or "tool_input" in payload:
        return "claude-code"
    return "antigravity"


def format_claude_code_pre_tool_output(
    explanation: RouteExplanation,
    tool_input: dict[str, Any],
) -> dict[str, Any]:
    """Translate a RouteExplanation into a Claude Code PreToolUse hookSpecificOutput response."""
    req_model = str(tool_input.get("model") or "")
    if explanation.overwrite_model and explanation.overwrite_model != req_model:
        updated = dict(tool_input)
        updated["model"] = explanation.overwrite_model
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": f"Model Router [{explanation.rule_id}]: {explanation.reason}",
                "updatedInput": updated,
            }
        }
    return {}


def _is_claude_code_architect_parent(parent_model: str, cfg: RouterConfig) -> bool:
    """Return True when a Claude Code parent model is explicitly running an Architect-tier model."""
    pm = parent_model.strip().lower()
    if not pm:
        return False
    return (
        pm == cfg.models.architect.lower()
        or "opus" in pm
        or "carbon" in pm
        or "orchestrator" in pm
        or pm.startswith("o3")
    )


def _extract_claude_code_post_error(payload: dict[str, Any]) -> str:
    """Extract quota/rate-limit error text from Claude Code PostToolUse payload fields."""
    raw_err = payload.get("error")
    if raw_err:
        return str(raw_err)
    tool_resp = payload.get("tool_response")
    if isinstance(tool_resp, dict):
        nested = tool_resp.get("error")
        if nested:
            return str(nested)
    elif isinstance(tool_resp, str):
        low = tool_resp.lower()
        if any(marker in low for marker in QUOTA_ERROR_MARKERS):
            return tool_resp
    return ""


def handle_claude_code_payload(payload: dict[str, Any], cfg: RouterConfig) -> dict[str, Any]:
    """Handle a Claude Code PreToolUse or PostToolUse hook payload."""
    event = str(payload.get("hook_event_name") or "PreToolUse").strip()
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_input = payload.get("tool_input")
    transcript_path = str(payload.get("transcript_path") or "")

    if event == "PostToolUse":
        err_str = _extract_claude_code_post_error(payload)
        norm_post: dict[str, Any] = {
            "hookEventName": "PostToolUse",
            "transcriptPath": transcript_path,
            "toolCall": {
                "name": tool_name,
                "args": tool_input if isinstance(tool_input, dict) else {},
            },
            "error": err_str,
        }
        handle_post_tool_use(norm_post, cfg)
        return {}

    last_input = str(payload.get("last_user_input") or "")
    turn_flags = extract_turn_flags(last_input)
    if "[allow-gemini]" in turn_flags or "[inline-gemini]" in turn_flags:
        return {}

    if not isinstance(tool_input, dict):
        return {}

    # Case A: Claude Code Task / Agent subagent dispatch
    if tool_name in ("Task", "Agent"):
        sub_type = str(tool_input.get("subagent_type") or "").strip().lower()
        if sub_type and sub_type in {s.lower() for s in cfg.specialist_subagents}:
            return {}
        name = str(
            tool_input.get("description")
            or tool_input.get("name")
            or tool_input.get("subagent_type")
            or "task-worker"
        )
        brief = str(tool_input.get("prompt") or tool_input.get("brief") or "")
        req_model = str(tool_input.get("model") or "")
        exp = explain_swarm_route(
            {"action": "add", "name": name, "brief": brief, "model": req_model},
            last_input=last_input,
            transcript_path=transcript_path,
            cfg=cfg,
        )
        return format_claude_code_pre_tool_output(exp, tool_input)

    # Case B: MCP or native swarm tool calls inside Claude Code (excluding swarm_wait)
    if is_swarm_control_tool(tool_name):
        exp = explain_swarm_route(
            tool_input,
            last_input=last_input,
            transcript_path=transcript_path,
            cfg=cfg,
        )
        return format_claude_code_pre_tool_output(exp, tool_input)

    # Case C: Inline file edits when an Architect-tier parent is active
    if tool_name in CLAUDE_CODE_EDIT_TOOLS:
        parent_model = str(payload.get("model") or os.environ.get("CLAUDE_MODEL") or "").strip().lower()
        if not _is_claude_code_architect_parent(parent_model, cfg):
            return {}
        target = str(
            tool_input.get("file_path")
            or tool_input.get("notebook_path")
            or tool_input.get("Path")
            or ""
        )
        res = handle_edit(
            {"Path": target},
            model_name="gemini-4-carbon-high",
            conv_id=str(payload.get("session_id") or "default"),
            last_input=last_input,
            transcript_path=transcript_path,
            cfg=cfg,
        )
        if res.get("decision") == "deny":
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": str(
                        res.get("reason") or "Inline Architect edit cap reached."
                    ),
                }
            }
        return {}

    return {}
