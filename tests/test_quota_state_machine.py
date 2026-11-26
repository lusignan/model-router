"""Tests for the dual-window resetTime-aware quota polling and PostToolUse flush-race state machine."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from tests.helpers import RouterTestBase, iso_utc, make_swarm_models_line

# isort: split
from model_router import (
    RouterConfig,
    claude_pool_exhausted,
    decide,
    parse_iso_utc,
    parse_pct_fraction,
    refresh_quota_snapshot,
)


class TestQuotaStateMachine(RouterTestBase):
    def test_post_tool_use_flush_race_picks_up_newly_flushed_exhausted_step(self) -> None:
        t_step1 = 1795342586.0
        t_post = 1795343186.83
        t_step2 = 1795343186.60
        t_reset = 1795350000.0

        self.transcript_full_path.write_text(
            make_swarm_models_line(t_step1, "55%", "93%", claude_reset_ts=t_reset) + "\n",
            encoding="utf-8",
        )

        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CLAUDE_QUOTA": "", "AGY_ROUTER_CLAUDE_QUOTA": ""}):
            self.assertFalse(claude_pool_exhausted(str(self.transcript_path), now=t_step1 + 5.0))
            warm_cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.assertAlmostEqual(warm_cache["step_ts"], t_step1, places=3)

            with mock.patch("model_router.quota.time.time", return_value=t_post):
                out = decide(
                    {
                        "hookEventName": "PostToolUse",
                        "transcriptPath": str(self.transcript_path),
                        "toolCall": {"name": "swarm", "args": {"action": "models"}},
                    }
                )
            self.assertEqual(out, {})
            post_cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.assertAlmostEqual(post_cache["step_ts"], t_step1, places=3)
            self.assertEqual(post_cache["ts"], 0.0)

            self.transcript_full_path.write_text(
                make_swarm_models_line(t_step1, "55%", "93%", claude_reset_ts=t_reset)
                + "\n"
                + make_swarm_models_line(t_step2, "0%", "93%", claude_reset_ts=t_reset)
                + "\n",
                encoding="utf-8",
            )

            self.assertTrue(claude_pool_exhausted(str(self.transcript_path), now=t_post + 0.2))
            after_cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.assertAlmostEqual(after_cache["step_ts"], t_step2, places=3)
            self.assertTrue(after_cache["exhausted"])
            self.assertTrue(claude_pool_exhausted(str(self.transcript_path), now=t_post + 35.0))

    def test_reverse_recovery_from_exhausted_to_100pct_with_prestamped_cache(self) -> None:
        t_step1 = 1795340000.0
        t_step2 = 1795343186.60
        t_post = 1795343186.83
        t_reset = 1795350000.0

        self.transcript_full_path.write_text(
            make_swarm_models_line(t_step1, "0%", "93%", claude_reset_ts=t_reset)
            + "\n"
            + make_swarm_models_line(t_step2, "100%", "93%", claude_reset_ts=t_reset)
            + "\n",
            encoding="utf-8",
        )
        self.cache_path.write_text(
            json.dumps(
                {
                    "ts": t_post - 40.0,
                    "step_ts": t_step1,
                    "exhausted": True,
                    "claude_rem": 0.0,
                    "claude_reset_ts": t_reset,
                    "gemini_rem": 0.93,
                    "source": "transcript",
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CLAUDE_QUOTA": "", "AGY_ROUTER_CLAUDE_QUOTA": ""}):
            self.assertFalse(claude_pool_exhausted(str(self.transcript_path), now=t_post + 1.0))
            updated = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.assertAlmostEqual(updated["step_ts"], t_step2, places=3)
            self.assertEqual(updated["claude_rem"], 1.0)

    def test_cold_cache_post_tool_use_does_not_arm_ttl_on_stale_step(self) -> None:
        t_old = 1795340000.0
        t_post = t_old + 500.0
        t_reset = t_post + 3600.0
        self.transcript_full_path.write_text(
            make_swarm_models_line(t_old, "80%", "90%", claude_reset_ts=t_reset) + "\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CLAUDE_QUOTA": "", "AGY_ROUTER_CLAUDE_QUOTA": ""}):
            with mock.patch("model_router.quota.time.time", return_value=t_post):
                decide(
                    {
                        "hookEventName": "PostToolUse",
                        "transcriptPath": str(self.transcript_path),
                        "toolCall": {"name": "swarm", "args": {"action": "models"}},
                    }
                )
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.assertEqual(cached["ts"], 0.0)
            self.assertAlmostEqual(cached["step_ts"], t_old, places=3)

    def test_asymmetric_ls_5h_window_never_clears_active_weekly_transcript_exhaustion(self) -> None:
        now = 1795343000.0
        t_reset = now + 7200.0
        self.cache_path.write_text(
            json.dumps(
                {
                    "ts": now - 60.0,
                    "step_ts": now - 120.0,
                    "exhausted": True,
                    "claude_rem": 0.0,
                    "claude_reset_ts": t_reset,
                    "gemini_rem": 0.50,
                    "source": "transcript",
                }
            ),
            encoding="utf-8",
        )
        ls_healthy = {
            "addr": "127.0.0.1:9999",
            "ts": now,
            "exhausted": False,
            "claude_rem": 1.0,
            "claude_reset_ts": now + 1800.0,
            "gemini_rem": 0.87,
            "gemini_reset_ts": now + 3600.0,
            "source": "ls",
        }
        with mock.patch.dict(
            os.environ,
            {
                "MODEL_ROUTER_CLAUDE_QUOTA": "",
                "AGY_ROUTER_CLAUDE_QUOTA": "",
                "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:9999",
                "ANTIGRAVITY_CSRF_TOKEN": "tok",
            },
        ), mock.patch("model_router.quota.poll_ls_for_quota", return_value=ls_healthy):
            self.assertTrue(claude_pool_exhausted(str(self.transcript_path), now=now))
            merged = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.assertTrue(merged["exhausted"])
            self.assertAlmostEqual(merged["gemini_rem"], 0.87, places=3)
            self.assertEqual(merged["source"], "transcript")

    def test_claude_reset_ts_expiration_auto_clears_exhaustion_without_polling(self) -> None:
        now = 1795350100.0
        t_reset = 1795350000.0
        self.cache_path.write_text(
            json.dumps(
                {
                    "ts": now - 5.0,
                    "step_ts": t_reset - 600.0,
                    "exhausted": True,
                    "claude_rem": 0.0,
                    "claude_reset_ts": t_reset,
                    "gemini_rem": 0.90,
                    "source": "transcript",
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CLAUDE_QUOTA": "", "AGY_ROUTER_CLAUDE_QUOTA": ""}):
            self.assertFalse(claude_pool_exhausted(str(self.transcript_path), now=now))
            expired = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.assertFalse(expired["exhausted"])

    def test_post_tool_use_quota_error_parses_until_iso_and_blocks_older_transcripts(self) -> None:
        t_old_step = 1795340000.0
        t_err = 1795342000.0
        t_reset = 1795350000.0
        self.transcript_full_path.write_text(
            make_swarm_models_line(t_old_step, "85%", "92%", claude_reset_ts=t_reset) + "\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CLAUDE_QUOTA": "", "AGY_ROUTER_CLAUDE_QUOTA": ""}):
            with mock.patch("model_router.quota.time.time", return_value=t_err):
                decide(
                    {
                        "hookEventName": "PostToolUse",
                        "transcriptPath": str(self.transcript_path),
                        "error": f"HTTP 429 RESOURCE_EXHAUSTED until {iso_utc(t_reset)}",
                        "toolCall": {
                            "name": "swarm",
                            "args": {"action": "add", "name": "grunt-sync", "model": "claude-sonnet-5-5-high"},
                        },
                    }
                )
            snap = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.assertEqual(snap["source"], "post_tool_error")
            self.assertTrue(snap["exhausted"])
            self.assertAlmostEqual(snap["claude_reset_ts"], t_reset, places=2)
            self.assertTrue(claude_pool_exhausted(str(self.transcript_path), now=t_err + 45.0))

    def test_legacy_exhaustion_without_reset_ts_honors_grace_window(self) -> None:
        t0 = 1795340000.0
        self.cache_path.write_text(
            json.dumps(
                {
                    "ts": t0,
                    "exhausted": True,
                    "claude_rem": 0.0,
                    "claude_reset_ts": None,
                    "gemini_rem": 0.90,
                    "source": "post_tool_error",
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CLAUDE_QUOTA": "", "AGY_ROUTER_CLAUDE_QUOTA": ""}):
            self.assertTrue(claude_pool_exhausted(str(self.transcript_path), now=t0 + 600.0))
            self.cache_path.write_text(
                json.dumps(
                    {
                        "ts": t0,
                        "exhausted": True,
                        "claude_rem": 0.0,
                        "claude_reset_ts": None,
                        "gemini_rem": 0.90,
                        "source": "post_tool_error",
                    }
                ),
                encoding="utf-8",
            )
            self.assertFalse(claude_pool_exhausted(str(self.transcript_path), now=t0 + 2500.0))

    def test_parse_iso_utc_and_pct_fraction_python39_edge_cases(self) -> None:
        ts_z = parse_iso_utc("2026-11-23T20:00:00Z")
        ts_ns = parse_iso_utc("2026-11-23T20:00:00.123456789Z")
        ts_short = parse_iso_utc("2026-11-23T20:00:00.5+00:00")
        self.assertIsNotNone(ts_z)
        self.assertIsNotNone(ts_ns)
        self.assertIsNotNone(ts_short)
        assert ts_z is not None and ts_ns is not None and ts_short is not None
        self.assertAlmostEqual(ts_ns - ts_z, 0.123456, places=6)
        self.assertAlmostEqual(ts_short - ts_z, 0.5, places=6)
        self.assertIsNone(parse_iso_utc("not-a-timestamp"))
        self.assertAlmostEqual(parse_pct_fraction("55%") or 0.0, 0.55, places=6)
        self.assertAlmostEqual(parse_pct_fraction("0.2") or 0.0, 0.2, places=6)
        self.assertIsNone(parse_pct_fraction(""))

    def test_refresh_quota_snapshot_merges_transcript_claude_with_ls_gemini(self) -> None:
        now = 1795343000.0
        t_reset = now + 7200.0
        self.transcript_full_path.write_text(
            make_swarm_models_line(now - 60.0, "0%", "60%", claude_reset_ts=t_reset) + "\n",
            encoding="utf-8",
        )
        ls_snap = {
            "addr": "127.0.0.1:9999",
            "ts": now,
            "exhausted": False,
            "claude_rem": 1.0,
            "claude_reset_ts": now + 1800.0,
            "gemini_rem": 0.91,
            "gemini_reset_ts": now + 3600.0,
            "source": "ls",
        }
        with mock.patch.dict(
            os.environ,
            {
                "MODEL_ROUTER_CLAUDE_QUOTA": "",
                "AGY_ROUTER_CLAUDE_QUOTA": "",
                "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:9999",
                "ANTIGRAVITY_CSRF_TOKEN": "tok",
            },
        ), mock.patch("model_router.quota.poll_ls_for_quota", return_value=ls_snap):
            refreshed = refresh_quota_snapshot(
                cfg=RouterConfig.default(),
                transcript_path=str(self.transcript_path),
                now=now,
            )
            self.assertTrue(refreshed["exhausted"])
            self.assertAlmostEqual(refreshed["snapshot"]["gemini_rem"], 0.91, places=3)
            self.assertEqual(refreshed["snapshot"]["claude_rem"], 0.0)


if __name__ == "__main__":
    unittest.main()
