"""Tests for PreToolUse guards, CLI (--explain / --refresh-quota), hook subprocess, schemas, and hygiene."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.helpers import HOOK_PATH, REPO_ROOT, RouterTestBase, iso_utc, swarm_payload

# isort: split
from model_router import (
    RouterConfig,
    decide,
    load_config,
    main,
    quota_cache_path,
    turn_edits_state_path,
)


class TestGuardsAndCli(RouterTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.models = RouterConfig.default().models

    def test_swarm_wait_and_non_control_tools_never_rewritten(self) -> None:
        wait_res = decide(
            {
                "hookEventName": "PreToolUse",
                "modelName": "gemini-4-carbon-high",
                "toolCall": {"name": "swarm_wait", "args": {"since": 3}},
            }
        )
        self.assertEqual(wait_res, {"decision": "allow"})

        cc_wait_res = decide(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "mcp__swarm__swarm_wait",
                "tool_input": {"since": 3},
            }
        )
        self.assertEqual(cc_wait_res, {})

    def test_invoke_subagent_guard_blocks_unmanaged_and_allows_specialists_and_claude_parent(self) -> None:
        deny_sub = decide(
            {
                "hookEventName": "PreToolUse",
                "modelName": "orchestrator (carbon)",
                "lastUserInput": "",
                "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "research"}},
            }
        )
        self.assertEqual(deny_sub["decision"], "deny")

        allow_browser = decide(
            {
                "hookEventName": "PreToolUse",
                "modelName": "orchestrator (carbon)",
                "lastUserInput": "",
                "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "browser"}},
            }
        )
        self.assertEqual(allow_browser, {"decision": "allow"})

        allow_claude_parent = decide(
            {
                "hookEventName": "PreToolUse",
                "modelName": "claude-sonnet-5-5-high",
                "lastUserInput": "",
                "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "research"}},
            }
        )
        self.assertEqual(allow_claude_parent, {"decision": "allow"})

    def test_run_workflow_guard_blocks_agent_calls_unless_allow_gemini(self) -> None:
        blocked = decide(
            {
                "hookEventName": "PreToolUse",
                "modelName": "orchestrator (carbon)",
                "toolCall": {
                    "name": "run_workflow",
                    "args": {"Script": "res = parallel([agent('check file') for _ in range(3)])"},
                },
            }
        )
        self.assertEqual(blocked["decision"], "deny")

        allowed_tool_only = decide(
            {
                "hookEventName": "PreToolUse",
                "modelName": "orchestrator (carbon)",
                "toolCall": {
                    "name": "run_workflow",
                    "args": {"Script": "res = call_tool('read_file', Path='/tmp/a.txt')"},
                },
            }
        )
        self.assertEqual(allowed_tool_only, {"decision": "allow"})

        for flag in ("[allow-gemini]", "[allow-inline]", "[bypass-router]"):
            with self.subTest(flag=flag):
                allowed_escape = decide(
                    {
                        "hookEventName": "PreToolUse",
                        "modelName": "orchestrator (carbon)",
                        "toolCall": {
                            "name": "run_workflow",
                            "args": {"Script": f"# {flag}\nres = agent('ok')"},
                        },
                    }
                )
                self.assertEqual(allowed_escape, {"decision": "allow"})

    def test_inline_edit_guard_lean_and_heavy_caps_plus_exemptions(self) -> None:
        self.transcript_path.write_text(
            json.dumps({"step_index": 1, "type": "USER_INPUT", "created_at": iso_utc(1795340000.0)})
            + "\n"
            + json.dumps({"step_index": 2, "type": "PLANNER_RESPONSE", "created_at": iso_utc(1795340001.0)})
            + "\n",
            encoding="utf-8",
        )
        for i in range(5):
            res = decide(
                {
                    "hookEventName": "PreToolUse",
                    "modelName": "orchestrator (carbon)",
                    "conversationId": "conv-lean",
                    "lastUserInput": "Small edit",
                    "transcriptPath": str(self.transcript_path),
                    "toolCall": {"name": "edit_file", "args": {"Path": f"/repo/file_{i}.py"}},
                }
            )
            self.assertEqual(res, {"decision": "allow"})

        sixth = decide(
            {
                "hookEventName": "PreToolUse",
                "modelName": "orchestrator (carbon)",
                "conversationId": "conv-lean",
                "lastUserInput": "Small edit",
                "transcriptPath": str(self.transcript_path),
                "toolCall": {"name": "edit_file", "args": {"Path": "/repo/file_5.py"}},
            }
        )
        self.assertEqual(sixth["decision"], "deny")
        self.assertIn('Grunt ("[grunt]", "claude-sonnet-5-5-high")', sixth["reason"])
        self.assertNotIn("\u2014", sixth["reason"])

        # Denied PreToolUse attempts must not inflate persisted count or trigger redundant disk writes.
        lean_state = json.loads(self.edit_state_path.read_text(encoding="utf-8"))
        self.assertEqual(max(v["count"] for v in lean_state.values()), 5)
        with mock.patch("model_router.guards.atomic_write_json") as mock_write:
            seventh = decide(
                {
                    "hookEventName": "PreToolUse",
                    "modelName": "orchestrator (carbon)",
                    "conversationId": "conv-lean",
                    "lastUserInput": "Small edit",
                    "transcriptPath": str(self.transcript_path),
                    "toolCall": {"name": "edit_file", "args": {"Path": "/repo/file_6.py"}},
                }
            )
            self.assertEqual(seventh["decision"], "deny")
            mock_write.assert_not_called()

        artifact_res = decide(
            {
                "hookEventName": "PreToolUse",
                "modelName": "orchestrator (carbon)",
                "conversationId": "conv-lean",
                "lastUserInput": "Small edit",
                "transcriptPath": str(self.transcript_path),
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": "/repo/plan.md", "ArtifactMetadata": {"UserFacing": True}},
                },
            }
        )
        self.assertEqual(artifact_res, {"decision": "allow"})

        self.transcript_full_path.write_text("x" * 1_050_000, encoding="utf-8")
        for i in range(4):
            res = decide(
                {
                    "hookEventName": "PreToolUse",
                    "modelName": "orchestrator (carbon)",
                    "conversationId": "conv-heavy",
                    "lastUserInput": "Surgical batch",
                    "transcriptPath": str(self.transcript_path),
                    "toolCall": {"name": "edit_file", "args": {"Path": f"/repo/h_{i}.py"}},
                }
            )
            self.assertEqual(res, {"decision": "allow"})

        with self.transcript_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"step_index": 3, "type": "PLANNER_RESPONSE", "created_at": iso_utc(1795340005.0)}) + "\n")
        second_batch = decide(
            {
                "hookEventName": "PreToolUse",
                "modelName": "orchestrator (carbon)",
                "conversationId": "conv-heavy",
                "lastUserInput": "Surgical batch",
                "transcriptPath": str(self.transcript_path),
                "toolCall": {"name": "edit_file", "args": {"Path": "/repo/h_next.py"}},
            }
        )
        self.assertEqual(second_batch["decision"], "deny")

    def test_swarm_worker_transcript_exempt_from_inline_edit_cap(self) -> None:
        self.transcript_path.write_text(
            json.dumps({"step_index": 0, "type": "SYSTEM_MESSAGE", "content": "<swarm_worker> [neon-kernel]"}) + "\n",
            encoding="utf-8",
        )
        self.transcript_full_path.write_text("x" * 1_100_000, encoding="utf-8")
        for i in range(8):
            res = decide(
                {
                    "hookEventName": "PreToolUse",
                    "modelName": "gemini-4-neon-xhigh",
                    "conversationId": "worker-1",
                    "lastUserInput": "",
                    "transcriptPath": str(self.transcript_path),
                    "toolCall": {"name": "edit_file", "args": {"Path": f"/repo/mod_{i}.py"}},
                }
            )
            self.assertEqual(res, {"decision": "allow"})

        # Generic role markers ([builder], [architect], [forensic]) also exempt workers without SYSTEM_MESSAGE.
        for marker in ("[builder]", "[builder-xhigh]", "[architect]", "[forensic]"):
            with self.subTest(marker=marker):
                self.transcript_path.write_text(
                    json.dumps({"step_index": 1, "type": "USER_INPUT", "content": f"@worker {marker}\nTask"}) + "\n",
                    encoding="utf-8",
                )
                for i in range(6):
                    res = decide(
                        {
                            "hookEventName": "PreToolUse",
                            "modelName": "gemini-4-neon-xhigh",
                            "conversationId": f"worker-{marker}",
                            "lastUserInput": "",
                            "transcriptPath": str(self.transcript_path),
                            "toolCall": {"name": "edit_file", "args": {"Path": f"/repo/g_{i}.py"}},
                        }
                    )
                    self.assertEqual(res, {"decision": "allow"})

    def test_cross_platform_state_paths_respect_plugin_data_and_env_overrides(self) -> None:
        plugin_dir = self.tmp_dir / "plugin_data"
        with mock.patch.dict(
            os.environ,
            {
                "MODEL_ROUTER_QUOTA_CACHE_PATH": "",
                "MODEL_ROUTER_EDIT_STATE_PATH": "",
                "AGY_ROUTER_QUOTA_CACHE_PATH": "",
                "AGY_ROUTER_EDIT_STATE_PATH": "",
                "PLUGIN_DATA": str(plugin_dir),
            },
        ):
            self.assertEqual(quota_cache_path(), plugin_dir / "quota_cache.json")
            self.assertEqual(turn_edits_state_path(), plugin_dir / "turn_edits.json")

    def test_cli_explain_json_and_pretty_output(self) -> None:
        buf_json = io.StringIO()
        with redirect_stdout(buf_json):
            rc = main(
                [
                    "--explain",
                    "--name",
                    "neon-xray",
                    "--model",
                    "gemini-4-neon-high",
                    "--brief",
                    "@neon-xray [neon-dyad] Run full-repo Parquet ablation across state-space filters.",
                    "--claude-quota",
                    "0.55",
                    "--gemini-quota",
                    "0.93",
                ]
            )
        self.assertEqual(rc, 0)
        parsed = json.loads(buf_json.getvalue())
        self.assertEqual(parsed["rule_id"], "neon.dyad_or_kernel_upgrade")
        self.assertEqual(parsed["overwrite_model"], self.models.neon_xhigh)
        self.assertEqual(
            parsed["hook_response"],
            {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
        )

        buf_pretty = io.StringIO()
        with redirect_stdout(buf_pretty):
            rc_pretty = main(
                [
                    "--explain",
                    "--pretty",
                    "--name",
                    "neon-xray",
                    "--model",
                    "gemini-4-neon-high",
                    "--brief",
                    "@neon-xray [neon-dyad] Run full-repo Parquet ablation across state-space filters.",
                ]
            )
        self.assertEqual(rc_pretty, 0)
        pretty_txt = buf_pretty.getvalue()
        self.assertIn("neon.dyad_or_kernel_upgrade", pretty_txt)
        self.assertIn("gemini-4-neon-xhigh", pretty_txt)

    def test_cli_refresh_quota_and_malformed_stdin_fail_open(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--refresh-quota"])
        self.assertEqual(rc, 0)
        snap = json.loads(buf.getvalue())
        self.assertIn("exhausted", snap)
        self.assertIn("cache", snap)

        for raw_in, expected in (
            ("{broken", {"decision": "allow"}),
            ('{"hookEventName":"PostToolUse",broken', {}),
            ('{"hook_event_name":"PreToolUse","tool_name":"Task",broken', {}),
        ):
            buf_err = io.StringIO()
            with mock.patch.object(sys, "stdin", io.StringIO(raw_in)), redirect_stdout(buf_err):
                rc_err = main([])
            self.assertEqual(rc_err, 0)
            self.assertEqual(json.loads(buf_err.getvalue()), expected)

    def test_clean_env_usr_bin_python3_hook_subprocess(self) -> None:
        py_bin = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else sys.executable
        payload = swarm_payload(
            "grunt-alloy-sync",
            "@grunt-alloy-sync [grunt]\nSync `DECISIONS.md` mentioning `[neon]` and `[carbon]`.",
            model=self.models.sonnet_high,
            last_input="Review `[carbon]` docs.",
        )
        clean_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "MODEL_ROUTER_QUOTA_CACHE_PATH": str(self.cache_path),
            "MODEL_ROUTER_EDIT_STATE_PATH": str(self.edit_state_path),
            "MODEL_ROUTER_BRAIN_DIR": str(self.brain_dir),
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
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=clean_env,
            check=True,
        )
        self.assertEqual(json.loads(proc.stdout.strip()), {"decision": "allow"})

    def test_plugin_hooks_and_example_json_schemas(self) -> None:
        allowed_plugin_keys = {
            "name",
            "displayName",
            "version",
            "description",
            "author",
            "repository",
            "homepage",
            "logo",
            "suggestedPrompts",
            "disabled",
        }
        plugin_manifest = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertTrue(set(plugin_manifest.keys()).issubset(allowed_plugin_keys))
        self.assertEqual(plugin_manifest["name"], "model-router")
        self.assertEqual(plugin_manifest["author"]["name"], "Zac de Lusignan")
        self.assertEqual(len(plugin_manifest["suggestedPrompts"]), 3)
        self.assertTrue((REPO_ROOT / plugin_manifest["logo"]).is_file())

        hooks_cfg = json.loads((REPO_ROOT / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(list(hooks_cfg.keys()), ["model-router"])
        hook_spec = hooks_cfg["model-router"]
        self.assertIn("PreToolUse", hook_spec)
        self.assertIn("PostToolUse", hook_spec)
        for ev in ("PreToolUse", "PostToolUse"):
            entry = hook_spec[ev][0]
            self.assertIn("matcher", entry)
            self.assertEqual(entry["hooks"][0]["command"], "python3 ./hooks/model_stack_router.py")
            self.assertEqual(entry["hooks"][0]["timeout"], 10)

        ws_example = REPO_ROOT / "examples" / "workspace-model-router.example.json"
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CONFIG_PATH": str(ws_example)}):
            loaded_ws = load_config()
        self.assertIn("pricing_engine.py", loaded_ws.core_code_build_keywords)
        self.assertIn(str(ws_example), loaded_ws.sources)

        mp_example = REPO_ROOT / "examples" / "multi-provider.example.json"
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CONFIG_PATH": str(mp_example)}):
            loaded_mp = load_config()
        self.assertEqual(loaded_mp.preset, "multi-provider")
        self.assertEqual(loaded_mp.models.architect, "o3")
        self.assertEqual(loaded_mp.models.builder_xhigh, "gemini-2.5-pro")

        cc_example = json.loads(
            (REPO_ROOT / "examples" / "claude-code-settings.example.json").read_text(encoding="utf-8")
        )
        self.assertIn("hooks", cc_example)
        self.assertIn("PreToolUse", cc_example["hooks"])
        self.assertIn("PostToolUse", cc_example["hooks"])

    def test_repo_hygiene_paths_and_svg_safety(self) -> None:
        patterns: list[str] = [
            r"/(?:Users|home)/[A-Za-z0-9._-]+/",
            r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\",
        ]
        extra_file = Path(
            os.environ.get(
                "MODEL_ROUTER_HYGIENE_PATTERNS_FILE",
                str(Path.home() / ".config" / "model-router" / "private-hygiene-patterns.txt"),
            )
        )
        if extra_file.is_file():
            patterns.extend(
                line.strip()
                for line in extra_file.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
        checker = re.compile("|".join(patterns), re.IGNORECASE)
        hits: list[str] = []
        for path in REPO_ROOT.rglob("*"):
            if (
                ".git" in path.parts
                or "__pycache__" in path.parts
                or any(part.endswith(".egg-info") for part in path.parts)
                or not path.is_file()
            ):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = path.relative_to(REPO_ROOT)
            m = checker.search(text)
            if m is not None:
                hits.append(f"{rel}: matched '{m.group(0)}'")
        self.assertEqual(hits, [], f"Repository hygiene check failed: {hits}")

        # Enforce zero U+2014 em-dash characters across README.md, docs/, rules/, skills/, and src/.
        em_dash_targets: list[Path] = []
        readme_path = REPO_ROOT / "README.md"
        if readme_path.is_file():
            em_dash_targets.append(readme_path)
        for subdir in ("docs", "rules", "skills", "src"):
            sub_root = REPO_ROOT / subdir
            if not sub_root.is_dir():
                continue
            for p in sorted(sub_root.rglob("*")):
                if (
                    "__pycache__" in p.parts
                    or any(part.endswith(".egg-info") for part in p.parts)
                    or not p.is_file()
                ):
                    continue
                em_dash_targets.append(p)
        em_dash_hits: list[str] = []
        for p in em_dash_targets:
            try:
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "\u2014" in content:
                em_dash_hits.append(str(p.relative_to(REPO_ROOT)))
        self.assertEqual(em_dash_hits, [], f"Found forbidden U+2014 em-dash characters in: {em_dash_hits}")

        # Enforce zero <text> elements in SVG assets (GitHub Camo web-font safety).
        for svg_path in sorted((REPO_ROOT / "assets").glob("*.svg")):
            svg_txt = svg_path.read_text(encoding="utf-8")
            self.assertNotIn("<text", svg_txt.lower(), f"SVG contains <text> element: {svg_path.name}")


if __name__ == "__main__":
    unittest.main()
