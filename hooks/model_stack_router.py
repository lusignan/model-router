#!/usr/bin/env python3
"""Cross-harness PreToolUse/PostToolUse hook entrypoint for Model Router (Alloy Policy)."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from model_router import (  # noqa: E402
    ALLOW,
    CLAUDE_CODE_EDIT_TOOLS,
    EDIT_TOOLS,
    MODEL_PRESETS,
    AlloyConfig,
    ModelPool,
    RouteExplanation,
    RouterConfig,
    Thresholds,
    classify_alloy_worker,
    claude_pool_exhausted,
    decide,
    detect_harness,
    explain_swarm_route,
    extract_turn_flags,
    extract_worker_tags,
    format_claude_code_pre_tool_output,
    format_explanation,
    gemini_headroom_ok,
    gemini_remaining_fraction,
    handle_claude_code_payload,
    handle_edit,
    handle_post_tool_use,
    handle_subagent,
    handle_swarm,
    handle_workflow,
    is_carbon_authorized_role,
    is_carbon_coding_loop,
    is_carbon_neon_exclusive,
    is_gemini_parent,
    is_grunt_task,
    is_light_grunt,
    is_neon_xhigh_task,
    is_plumbing_grunt,
    load_config,
    main,
    mask_code_spans,
    opus_authorized,
    quota_cache_path,
    scrub_negated_coding_markers,
    strip_code_spans,
    turn_edits_state_path,
)

_DEFAULT_MODELS = ModelPool()
CARBON_WORKER = _DEFAULT_MODELS.carbon
NEON_XHIGH_WORKER = _DEFAULT_MODELS.neon_xhigh
NEON_HIGH_WORKER = _DEFAULT_MODELS.neon_high
SONNET_HIGH_WORKER = _DEFAULT_MODELS.sonnet_high
SONNET_LOW_WORKER = _DEFAULT_MODELS.sonnet_low
HYDROGEN_HIGH_WORKER = _DEFAULT_MODELS.hydrogen_high
HYDROGEN_LOW_WORKER = _DEFAULT_MODELS.hydrogen_low
OPUS_WORKER = _DEFAULT_MODELS.opus

__all__ = [
    "ALLOW",
    "AlloyConfig",
    "CARBON_WORKER",
    "CLAUDE_CODE_EDIT_TOOLS",
    "EDIT_TOOLS",
    "HYDROGEN_HIGH_WORKER",
    "HYDROGEN_LOW_WORKER",
    "MODEL_PRESETS",
    "ModelPool",
    "NEON_HIGH_WORKER",
    "NEON_XHIGH_WORKER",
    "OPUS_WORKER",
    "RouteExplanation",
    "RouterConfig",
    "SONNET_HIGH_WORKER",
    "SONNET_LOW_WORKER",
    "Thresholds",
    "classify_alloy_worker",
    "claude_pool_exhausted",
    "decide",
    "detect_harness",
    "explain_swarm_route",
    "extract_turn_flags",
    "extract_worker_tags",
    "format_claude_code_pre_tool_output",
    "format_explanation",
    "gemini_headroom_ok",
    "gemini_remaining_fraction",
    "handle_claude_code_payload",
    "handle_edit",
    "handle_post_tool_use",
    "handle_subagent",
    "handle_swarm",
    "handle_workflow",
    "is_carbon_authorized_role",
    "is_carbon_coding_loop",
    "is_carbon_neon_exclusive",
    "is_gemini_parent",
    "is_grunt_task",
    "is_light_grunt",
    "is_neon_xhigh_task",
    "is_plumbing_grunt",
    "load_config",
    "main",
    "mask_code_spans",
    "opus_authorized",
    "quota_cache_path",
    "scrub_negated_coding_markers",
    "strip_code_spans",
    "turn_edits_state_path",
]

if __name__ == "__main__":
    raise SystemExit(main())
