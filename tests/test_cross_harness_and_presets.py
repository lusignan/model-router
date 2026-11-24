"""Tests for cross-harness adapters (Claude Code <-> Antigravity), role-slot aliases, and presets."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.helpers import HOOK_PATH, RouterTestBase, iso_utc

from model_router import (
    MODEL_PRESETS,
    RouterConfig,
    decide,
    detect_harness,
    explain_swarm_route,
    load_config,
    main,
)


class TestCrossHarnessAndPresets(RouterTestBase):
    def test_detect_harness_auto_and_explicit_overrides(self) -> None:
        self.assertEqual(detect_harness({"toolCall": {"name": "swarm"}}), "antigravity")
        self.assertEqual(detect_harness({"hookEventName": "PostToolUse"}), "antigravity")
        self.assertEqual(detect_harness({"tool_name": "Task", "tool_input": {}}), "claude-code")
        self.assertEqual(detect_harness({"hook_event_name": "PreToolUse"}), "claude-code")
        self.assertEqual(detect_harness({}), "antigravity")
        self.assertEqual(detect_harness({"toolCall": {}}, harness_override="claude-code"), "claude-code")
        self.assertEqual(detect_harness({"tool_name": "Task"}, harness_override="antigravity"), "antigravity")

    def test_claude_code_task_rewrite_preserves_all_tool_input_keys(self) -> None:
        cfg = RouterConfig.default("claude-code")
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "cc-1",
            "transcript_path": str(self.transcript_path),
            "tool_name": "Task",
            "tool_input": {
                "description": "commit-crew",
                "prompt": "@commit-crew [grunt-low]\nStage and git commit.",
                "model": "opus",
                "subagent_type": "general-purpose",
                "run_in_background": True,
                "custom_meta": {"ticket": "ENG-42"},
            },
        }
        out = decide(payload, cfg=cfg)
        self.assertIn("hookSpecificOutput", out)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "allow")
        self.assertIn("grunt.explicit_tag", hso["permissionDecisionReason"])
        updated = hso["updatedInput"]
        self.assertEqual(updated["model"], "haiku")
        self.assertEqual(updated["description"], "commit-crew")
        self.assertEqual(updated["subagent_type"], "general-purpose")
        self.assertTrue(updated["run_in_background"])
        self.assertEqual(updated["custom_meta"], {"ticket": "ENG-42"})

    def test_claude_code_preset_routes_coding_loop_vs_audit_vs_forensic_opus(self) -> None:
        cfg = RouterConfig.default("claude-code")

        # Opus on multi-file coding loop redirects to sonnet.
        coding_payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {
                "description": "carbon-patches",
                "model": "opus",
                "prompt": "Implement vectorized Kalman solver in kernel.py and apply patch 2.",
            },
        }
        res_code = decide(coding_payload, cfg=cfg)
        self.assertEqual(res_code["hookSpecificOutput"]["updatedInput"]["model"], "sonnet")
        self.assertIn("carbon.coding_loop_redirect", res_code["hookSpecificOutput"]["permissionDecisionReason"])

        # Authorized forensic root-cause brief stays on opus (no rewrite -> {}).
        forensic_payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Task",
            "tool_input": {
                "description": "bug-hunter",
                "model": "opus",
                "prompt": "Find root cause of intermittent NaN gradient in pipeline.py.",
            },
        }
        self.assertEqual(decide(forensic_payload, cfg=cfg), {})

        # Authorized [carbon] audit stays on opus ({}).
        audit_payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Task",
            "tool_input": {
                "description": "carbon-audit",
                "model": "opus",
                "prompt": "@carbon-audit [carbon]\nAudit patch 2 in filter.py; do NOT call edit_file.",
            },
        }
        self.assertEqual(decide(audit_payload, cfg=cfg), {})

        # Specialist subagent_type passes through without rewrite.
        specialist_payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Task",
            "tool_input": {
                "description": "web-check",
                "subagent_type": "browser",
                "model": "opus",
                "prompt": "Open staging page.",
            },
        }
        self.assertEqual(decide(specialist_payload, cfg=cfg), {})

    def test_claude_code_architect_inline_edit_cap_vs_sonnet_passthrough(self) -> None:
        cfg = RouterConfig.default("claude-code")
        self.transcript_path.write_text(
            json.dumps({"step_index": 1, "type": "USER_INPUT", "created_at": iso_utc(1795340000.0)})
            + "\n"
            + json.dumps({"step_index": 2, "type": "PLANNER_RESPONSE", "created_at": iso_utc(1795340001.0)})
            + "\n",
            encoding="utf-8",
        )
        self.transcript_full_path.write_text("x" * 1_050_000, encoding="utf-8")

        # Default / Sonnet parent does not trigger Architect inline cap.
        with mock.patch.dict(os.environ, {"CLAUDE_MODEL": "sonnet"}):
            for i in range(6):
                res = decide(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "cc-sonnet",
                        "transcript_path": str(self.transcript_path),
                        "tool_name": "Edit",
                        "tool_input": {"file_path": f"/repo/file_{i}.py"},
                    },
                    cfg=cfg,
                )
                self.assertEqual(res, {})

        # Architect parent (CLAUDE_MODEL=opus) enforces heavy 4-file / 1-batch cap.
        with mock.patch.dict(os.environ, {"CLAUDE_MODEL": "opus"}):
            for i in range(4):
                res = decide(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "cc-opus",
                        "transcript_path": str(self.transcript_path),
                        "tool_name": "Edit",
                        "tool_input": {"file_path": f"/repo/h_{i}.py"},
                    },
                    cfg=cfg,
                )
                self.assertEqual(res, {})

            fifth = decide(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "cc-opus",
                    "transcript_path": str(self.transcript_path),
                    "tool_name": "Write",
                    "tool_input": {"file_path": "/repo/h_4.py"},
                },
                cfg=cfg,
            )
            self.assertEqual(fifth["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("inline Architect edit limit", fifth["hookSpecificOutput"]["permissionDecisionReason"])

    def test_claude_code_post_tool_use_429_tool_response_records_exhaustion(self) -> None:
        cfg = RouterConfig.default("claude-code")
        t_err = 1795342000.0
        t_reset = 1795350000.0
        with mock.patch("model_router.quota.time.time", return_value=t_err):
            out = decide(
                {
                    "hook_event_name": "PostToolUse",
                    "transcript_path": str(self.transcript_path),
                    "tool_name": "Task",
                    "tool_input": {"description": "grunt-sync", "model": "sonnet"},
                    "tool_response": {"error": f"HTTP 429 RESOURCE_EXHAUSTED until {iso_utc(t_reset)}"},
                },
                cfg=cfg,
            )
        self.assertEqual(out, {})
        snap = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(snap["source"], "post_tool_error")
        self.assertTrue(snap["exhausted"])
        self.assertAlmostEqual(snap["claude_reset_ts"], t_reset, places=2)

    def test_role_slot_json_keys_and_multi_provider_preset(self) -> None:
        self.assertEqual(set(MODEL_PRESETS.keys()), {"antigravity", "claude-code", "multi-provider"})

        custom_json = self.tmp_dir / "role_slots.json"
        custom_json.write_text(
            json.dumps(
                {
                    "preset": "multi-provider",
                    "models": {
                        "architect": "o3-pro",
                        "builder_xhigh": "gemini-2.5-pro-exp",
                        "builder_high": "gemini-2.5-pro",
                        "grunt_high": "claude-sonnet-4-5",
                        "grunt_low": "claude-haiku-4-5",
                        "failover_grunt_high": "gemini-2.5-flash",
                        "failover_grunt_low": "gemini-2.5-flash-lite",
                        "forensic": "claude-opus-4-6",
                    },
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CONFIG_PATH": str(custom_json)}):
            cfg = load_config()

        self.assertEqual(cfg.preset, "multi-provider")
        self.assertEqual(cfg.models.architect, "o3-pro")
        self.assertEqual(cfg.models.carbon, "o3-pro")
        self.assertEqual(cfg.models.builder_xhigh, "gemini-2.5-pro-exp")
        self.assertEqual(cfg.models.grunt_high, "claude-sonnet-4-5")
        self.assertEqual(cfg.models.grunt_low, "claude-haiku-4-5")
        self.assertEqual(cfg.models.failover_grunt_high, "gemini-2.5-flash")
        self.assertEqual(cfg.models.failover_grunt_low, "gemini-2.5-flash-lite")
        self.assertEqual(cfg.models.forensic, "claude-opus-4-6")

        # Architect audit preserved; coding loop redirected; grunt fails over cleanly on Claude exhaustion.
        exp_audit = explain_swarm_route(
            {
                "action": "add",
                "name": "o3-audit",
                "model": "o3-pro",
                "brief": "@o3-audit [carbon]\nAudit patch 1 in solver.py; do NOT call edit_file.",
            },
            cfg=cfg,
        )
        self.assertEqual(exp_audit.rule_id, "carbon.explicit_authorized")

        exp_loop = explain_swarm_route(
            {
                "action": "add",
                "name": "o3-patches",
                "model": "o3-pro",
                "brief": "Apply patch 1 and call edit_file on solver.py.",
            },
            cfg=cfg,
        )
        self.assertEqual(exp_loop.overwrite_model, "gemini-2.5-pro-exp")

        exp_grunt_ex = explain_swarm_route(
            {"action": "add", "name": "grunt-sync", "brief": "@grunt-sync [grunt]\nUpdate STATUS.md."},
            cfg=cfg,
            claude_quota_override=0.0,
        )
        self.assertEqual(exp_grunt_ex.overwrite_model, "gemini-2.5-flash")

    def test_cli_explain_claude_code_preset_and_harness_plus_subprocess(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(
                [
                    "--explain",
                    "--preset",
                    "claude-code",
                    "--harness",
                    "claude-code",
                    "--name",
                    "commit-crew",
                    "--model",
                    "opus",
                    "--brief",
                    "@commit-crew [grunt-low] Stage and git commit.",
                ]
            )
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["preset"], "claude-code")
        self.assertEqual(parsed["harness"], "claude-code")
        self.assertEqual(parsed["rule_id"], "grunt.explicit_tag")
        self.assertEqual(parsed["hook_response"]["hookSpecificOutput"]["updatedInput"]["model"], "haiku")

        # Verify live hook subprocess handles Claude Code wire schema cleanly via /usr/bin/python3.
        py_bin = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else sys.executable
        ws_dir = self.tmp_dir / "cc_repo"
        (ws_dir / ".git").mkdir(parents=True)
        (ws_dir / ".agents").mkdir(parents=True)
        (ws_dir / ".agents" / "model-router.json").write_text(
            json.dumps({"preset": "claude-code"}), encoding="utf-8"
        )
        cc_payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(ws_dir),
            "tool_name": "Task",
            "tool_input": {
                "description": "commit-crew",
                "prompt": "@commit-crew [grunt-low] Stage and git commit.",
                "model": "opus",
            },
        }
        clean_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "MODEL_ROUTER_QUOTA_CACHE_PATH": str(self.cache_path),
            "MODEL_ROUTER_EDIT_STATE_PATH": str(self.edit_state_path),
            "MODEL_ROUTER_CLAUDE_QUOTA": "0.55",
            "MODEL_ROUTER_GEMINI_QUOTA": "0.93",
            "MODEL_ROUTER_DISABLE_GLOBAL_CONFIG": "1",
            "AGY_ROUTER_DISABLE_GLOBAL_CONFIG": "1",
        }
        for win_key in ("SYSTEMROOT", "SystemRoot", "COMSPEC", "WINDIR", "TEMP", "TMP"):
            if win_key in os.environ:
                clean_env[win_key] = os.environ[win_key]
        proc = subprocess.run(
            [py_bin, str(HOOK_PATH)],
            input=json.dumps(cc_payload),
            text=True,
            capture_output=True,
            env=clean_env,
            check=True,
        )
        resp = json.loads(proc.stdout.strip())
        self.assertEqual(resp["hookSpecificOutput"]["updatedInput"]["model"], "haiku")


if __name__ == "__main__":
    unittest.main()
