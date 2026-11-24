"""Tests for code-span isolation, header tag extraction, turn-flag isolation, and negation scrubbing."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.helpers import RouterTestBase, swarm_payload

from model_router import (
    RouterConfig,
    decide,
    explain_swarm_route,
    extract_worker_tags,
    mask_code_spans,
    scrub_negated_coding_markers,
)


class TestTagAndNegationSafety(RouterTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.models = RouterConfig.default().models

    def test_grunt_sync_with_backticked_and_fenced_tags_stays_on_sonnet_and_fails_over(self) -> None:
        brief = (
            "@grunt-alloy-sync [grunt]\n"
            "Sync `DECISIONS.md` and `STATUS.md` bullets describing the 4-Stage Alloy Stack:\n"
            "- Code builder uses `[neon]` / `[neon-kernel]` (`filter.py`, `kalman`).\n"
            "- Gatekeeper review uses `[carbon]`.\n"
            "```markdown\n"
            "[neon-kernel] owns `cholesky` and `quadrature` builds.\n"
            "```\n"
        )
        self.assertEqual(
            decide(swarm_payload("grunt-alloy-sync", brief, model=self.models.sonnet_high)),
            {"decision": "allow"},
        )
        self.assertEqual(
            decide(swarm_payload("grunt-alloy-sync", brief, model="")),
            {"decision": "allow", "overwrite": {"model": self.models.sonnet_high}},
        )
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CLAUDE_QUOTA": "0.0", "AGY_ROUTER_CLAUDE_QUOTA": "0.0"}):
            self.assertEqual(
                decide(swarm_payload("grunt-alloy-sync", brief, model=self.models.sonnet_high)),
                {"decision": "allow", "overwrite": {"model": self.models.hydrogen_high}},
            )

    def test_header_grunt_low_forces_low_tier_across_normal_and_exhausted_regimes(self) -> None:
        brief = "@commit-crew [grunt-low]\nStage and `git commit`; note earlier `[neon]` and `[carbon]` docs.\n"
        self.assertEqual(
            decide(swarm_payload("commit-crew", brief, model="")),
            {"decision": "allow", "overwrite": {"model": self.models.sonnet_low}},
        )
        self.assertEqual(
            decide(swarm_payload("commit-crew", brief, model=self.models.sonnet_high)),
            {"decision": "allow", "overwrite": {"model": self.models.sonnet_low}},
        )
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CLAUDE_QUOTA": "0.0", "AGY_ROUTER_CLAUDE_QUOTA": "0.0"}):
            self.assertEqual(
                decide(swarm_payload("commit-crew", brief, model="")),
                {"decision": "allow", "overwrite": {"model": self.models.hydrogen_low}},
            )

    def test_header_grunt_beats_unbackticked_body_tags_beyond_header_window(self) -> None:
        padding = "x " * 160
        brief = (
            "@ledger-grunt [grunt]\n"
            "Update STATUS.md after validation.\n"
            f"{padding}\n"
            "Note: downstream worker uses [neon] and [carbon] to verify kalman in filter.py."
        )
        res = decide(swarm_payload("ledger-grunt", brief, model=self.models.sonnet_high))
        self.assertEqual(res, {"decision": "allow"})

    def test_untagged_body_role_tag_beyond_240_chars_is_ignored(self) -> None:
        padding = "a " * 150
        brief = f"Clean up stale temp files and prune worktrees.\n{padding}\nHistorical note: [neon] ran earlier."
        self.assertEqual(extract_worker_tags("cleanup-worker", brief), set())
        res = decide(swarm_payload("cleanup-worker", brief, model=""))
        self.assertEqual(res, {"decision": "allow", "overwrite": {"model": self.models.sonnet_low}})

    def test_last_user_input_never_bleeds_worker_role_tags_while_live_turn_flags_work(self) -> None:
        last_input = "Apply [carbon], [neon], [neon-kernel], [opus], and [sonnet] policy cleanly."
        brief_grunt = "@grunt-sync [grunt]\nUpdate `DECISIONS.md` and `STATE.json`."
        self.assertEqual(
            decide(swarm_payload("grunt-sync", brief_grunt, model=self.models.sonnet_high, last_input=last_input)),
            {"decision": "allow"},
        )

        self.assertEqual(
            decide(
                swarm_payload(
                    "core-patches",
                    "Implement vectorized feature updates in pipeline.py.",
                    model=self.models.carbon,
                    last_input="Check [carbon] rules.",
                )
            ),
            {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
        )

        self.assertEqual(
            decide(
                swarm_payload(
                    "core-patches",
                    "Refactor solver.",
                    model=self.models.carbon,
                    last_input="Document `[allow-gemini]` and `[claude-exhausted]` in docs.",
                )
            ),
            {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
        )
        self.assertEqual(
            decide(
                swarm_payload(
                    "core-patches",
                    "Refactor solver.",
                    model=self.models.carbon,
                    last_input="[allow-gemini] run inline",
                )
            ),
            {"decision": "allow"},
        )

    def test_negated_edit_file_and_audit_patch_phrases_preserve_carbon(self) -> None:
        brief = "@carbon-audit [carbon]\nAudit patch 2 in filter.py; do NOT call edit_file."
        exp = explain_swarm_route(
            {"action": "add", "name": "carbon-audit", "model": self.models.carbon, "brief": brief}
        )
        self.assertEqual(exp.to_hook_response(), {"decision": "allow"})
        self.assertEqual(exp.rule_id, "carbon.explicit_authorized")

        brief_conj = (
            "@carbon-gatekeeper [carbon]\n"
            "Review the patches in kernel.py and inspect patch 3; never invoke edit_file or write_file."
        )
        exp_generic = explain_swarm_route(
            {"action": "add", "name": "carbon-gatekeeper", "model": self.models.carbon, "brief": brief_conj}
        )
        self.assertEqual(exp_generic.to_hook_response(), {"decision": "allow"})
        self.assertEqual(exp_generic.rule_id, "carbon.explicit_authorized")

    def test_positive_patch_and_edit_file_directives_redirect_carbon_to_neon_xhigh(self) -> None:
        brief = "@carbon-patches\nApply patch 2 and call edit_file on filter.py."
        exp = explain_swarm_route(
            {"action": "add", "name": "carbon-patches", "model": self.models.carbon, "brief": brief}
        )
        self.assertEqual(
            exp.to_hook_response(),
            {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
        )
        self.assertEqual(exp.rule_id, "carbon.coding_loop_redirect")

        brief_sneaky = "@carbon-audit [carbon]\nCall edit_file on filter.py to apply patch 2."
        exp_sneaky = explain_swarm_route(
            {"action": "add", "name": "carbon-audit", "model": self.models.carbon, "brief": brief_sneaky}
        )
        self.assertEqual(
            exp_sneaky.to_hook_response(),
            {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
        )
        self.assertEqual(exp_sneaky.rule_id, "carbon.coding_loop_redirect")

    def test_mask_code_spans_preserves_length_and_line_breaks(self) -> None:
        sample = "head `[neon]`\n```py\n[carbon]\nx = 1\n```\ntail"
        masked = mask_code_spans(sample)
        self.assertEqual(len(masked), len(sample))
        self.assertEqual(masked.count("\n"), sample.count("\n"))
        self.assertNotIn("[neon]", masked)
        self.assertNotIn("[carbon]", masked)
        self.assertTrue(masked.endswith("tail"))

    def test_scrub_negated_coding_markers_neutralizes_prohibitions_only(self) -> None:
        prohibited = "Must not apply any patches; avoid edit_file, write_file; red-teaming all patches."
        scrubbed = scrub_negated_coding_markers(prohibited).lower()
        self.assertNotIn("edit_file", scrubbed)
        self.assertNotIn("write_file", scrubbed)
        self.assertNotIn("patch", scrubbed)

        imperative = "Apply patch 4 and invoke edit_file on solver.py."
        kept = scrub_negated_coding_markers(imperative).lower()
        self.assertIn("patch 4", kept)
        self.assertIn("edit_file", kept)

    def test_backticked_exclusivity_phrase_does_not_trigger_carbon_neon_only(self) -> None:
        doc_brief = "Update STATUS.md and export HTML report."
        res = decide(
            swarm_payload(
                "sync-status",
                doc_brief,
                model="",
                last_input="Document `Carbon and Neon exclusively` and `[carbon-neon]` rules.",
            )
        )
        self.assertEqual(res, {"decision": "allow", "overwrite": {"model": self.models.sonnet_high}})


if __name__ == "__main__":
    unittest.main()
