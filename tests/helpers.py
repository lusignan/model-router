"""Shared fixtures and helpers for Model Router unit tests."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
HOOK_PATH = REPO_ROOT / "hooks" / "model_stack_router.py"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def iso_utc(ts: float) -> str:
    """Format a POSIX epoch timestamp as an ISO-8601 UTC string."""
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def make_swarm_models_line(
    step_ts: float,
    claude_pct: str,
    gemini_pct: str = "93%",
    claude_reset_ts: float | None = None,
    gemini_reset_ts: float | None = None,
) -> str:
    """Build a synthetic transcript_full.jsonl TOOL_RESULT line matching swarm(action='models')."""
    rst_c = iso_utc(claude_reset_ts if claude_reset_ts is not None else step_ts + 3600.0)
    rst_g = iso_utc(gemini_reset_ts if gemini_reset_ts is not None else step_ts + 3600.0)
    inner = {
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
            "claude-sonnet-5-5-high": {"quota_remaining": claude_pct, "quota_resets": rst_c},
            "claude-sonnet-5-5-low": {"quota_remaining": claude_pct, "quota_resets": rst_c},
            "gemini-4-neon-xhigh": {"quota_remaining": gemini_pct, "quota_resets": rst_g},
            "gemini-4-hydrogen-high": {"quota_remaining": gemini_pct, "quota_resets": rst_g},
        },
    }
    outer = {
        "step_index": 42,
        "type": "TOOL_RESULT",
        "created_at": iso_utc(step_ts),
        "content": json.dumps(inner),
    }
    return json.dumps(outer)


def swarm_payload(
    name: str,
    brief: str,
    model: str = "",
    last_input: str = "",
    transcript_path: str = "",
    action: str = "add",
    cwd: str = "",
) -> dict[str, Any]:
    """Build a synthetic Antigravity PreToolUse hook payload for a swarm call."""
    args: dict[str, Any] = {"action": action, "name": name, "brief": brief}
    if model:
        args["model"] = model
    payload: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "modelName": "orchestrator (carbon)",
        "lastUserInput": last_input,
        "transcriptPath": transcript_path,
        "toolCall": {"name": "swarm", "args": args},
    }
    if cwd:
        payload["cwd"] = cwd
    return payload


class RouterTestBase(unittest.TestCase):
    """Hermetic base test case isolating cache paths, env vars, and global config."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.cache_path = self.tmp_dir / "quota_cache.json"
        self.edit_state_path = self.tmp_dir / "edit_state.json"
        self.brain_dir = self.tmp_dir / "brain"
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_path = self.brain_dir / "conv1" / ".system_generated" / "logs" / "transcript.jsonl"
        self.transcript_full_path = self.transcript_path.with_name("transcript_full.jsonl")
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)

        self._env_patcher = mock.patch.dict(
            os.environ,
            {
                "MODEL_ROUTER_QUOTA_CACHE_PATH": str(self.cache_path),
                "MODEL_ROUTER_EDIT_STATE_PATH": str(self.edit_state_path),
                "MODEL_ROUTER_BRAIN_DIR": str(self.brain_dir),
                "MODEL_ROUTER_CLAUDE_QUOTA": "0.55",
                "MODEL_ROUTER_GEMINI_QUOTA": "0.93",
                "MODEL_ROUTER_DISABLE_GLOBAL_CONFIG": "1",
                "MODEL_ROUTER_CONFIG_PATH": "",
                "AGY_ROUTER_QUOTA_CACHE_PATH": str(self.cache_path),
                "AGY_ROUTER_EDIT_STATE_PATH": str(self.edit_state_path),
                "AGY_ROUTER_BRAIN_DIR": str(self.brain_dir),
                "AGY_ROUTER_CLAUDE_QUOTA": "0.55",
                "AGY_ROUTER_GEMINI_QUOTA": "0.93",
                "AGY_ROUTER_DISABLE_GLOBAL_CONFIG": "1",
                "AGY_ROUTER_CONFIG_PATH": "",
                "PLUGIN_DATA": "",
                "CLAUDE_MODEL": "",
                "ANTIGRAVITY_LS_ADDRESS": "",
                "ANTIGRAVITY_CSRF_TOKEN": "",
            },
            clear=False,
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()
        self._tmp.cleanup()
