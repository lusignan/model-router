"""Tests for code-span isolation, header tag extraction, turn-flag isolation, and negation scrubbing."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.helpers import RouterTestBase, swarm_payload

# isort: split
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

    def test_generic_turn_flags_and_exclusivity_aliases(self) -> None:
        # Generic bypass turn flags [allow-inline] and [bypass-router] skip router overrides across harnesses.
        for flag in ("[allow-inline]", "[bypass-router]"):
            with self.subTest(bypass_flag=flag):
                exp = explain_swarm_route(
                    {
                        "action": "add",
                        "name": "core-patches",
                        "model": self.models.carbon,
                        "brief": "Apply patch 1 and call edit_file on solver.py.",
                    },
                    last_input=f"{flag} run direct patch",
                )
                self.assertEqual(exp.rule_id, "turn_flag.allow_gemini")
                self.assertIsNone(exp.overwrite_model)
                self.assertEqual(
                    decide(
                        swarm_payload(
                            "core-patches",
                            "Apply patch 1 and call edit_file on solver.py.",
                            model=self.models.carbon,
                            last_input=f"{flag} run direct patch",
                        )
                    ),
                    {"decision": "allow"},
                )
                # Backticked bypass flags must NOT trigger bypass.
                self.assertEqual(
                    decide(
                        swarm_payload(
                            "core-patches",
                            "Apply patch 1 and call edit_file on solver.py.",
                            model=self.models.carbon,
                            last_input=f"Document `{flag}` in README.",
                        )
                    ),
                    {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
                )
                # Claude Code Task bypass returns {}.
                cc_bypass = decide(
                    {
                        "hook_event_name": "PreToolUse",
                        "last_user_input": f"{flag} keep requested model",
                        "tool_name": "Task",
                        "tool_input": {
                            "description": "commit-crew",
                            "model": "opus",
                            "prompt": "@commit-crew [grunt-low]\nStage and git commit.",
                        },
                    }
                )
                self.assertEqual(cc_bypass, {})

        # [primary-exhausted] triggers failover from worker header or turn input.
        exp_ex_header = explain_swarm_route(
            {
                "action": "add",
                "name": "grunt-sync",
                "model": self.models.sonnet_high,
                "brief": "@grunt-sync [grunt] [primary-exhausted]\nSync STATUS.md.",
            }
        )
        self.assertTrue(exp_ex_header.claude_exhausted)
        self.assertEqual(exp_ex_header.overwrite_model, self.models.hydrogen_high)

        exp_ex_turn = explain_swarm_route(
            {
                "action": "add",
                "name": "commit-crew",
                "model": self.models.sonnet_low,
                "brief": "@commit-crew [grunt-low]\nStage and git commit.",
            },
            last_input="[primary-exhausted] failover active",
        )
        self.assertTrue(exp_ex_turn.claude_exhausted)
        self.assertEqual(exp_ex_turn.overwrite_model, self.models.hydrogen_low)

        # [architect-builder-only] and "Architect and Builder exclusively" enforce strict exclusivity.
        for trigger in ("[architect-builder-only] lock stack", "Run with Architect and Builder exclusively."):
            with self.subTest(exclusivity_trigger=trigger):
                exp_arch = explain_swarm_route(
                    {
                        "action": "add",
                        "name": "arch-audit",
                        "model": self.models.carbon,
                        "brief": "@arch-audit [architect]\nSecurity audit of auth.py.",
                    },
                    last_input=trigger,
                )
                self.assertEqual(exp_arch.rule_id, "exclusivity.carbon")
                self.assertTrue(exp_arch.carbon_neon_exclusive)
                self.assertIsNone(exp_arch.overwrite_model)

                exp_grunt = explain_swarm_route(
                    {
                        "action": "add",
                        "name": "sync-status",
                        "model": self.models.sonnet_high,
                        "brief": "Update STATUS.md and export HTML report.",
                    },
                    last_input=trigger,
                )
                self.assertEqual(exp_grunt.rule_id, "exclusivity.neon")
                self.assertTrue(exp_grunt.carbon_neon_exclusive)
                self.assertEqual(exp_grunt.overwrite_model, self.models.neon_xhigh)

        # Worker header [architect-builder-only] also enforces exclusivity.
        exp_hdr_excl = explain_swarm_route(
            {
                "action": "add",
                "name": "sync-status",
                "model": self.models.sonnet_high,
                "brief": "@sync-status [architect-builder-only]\nUpdate STATUS.md.",
            }
        )
        self.assertEqual(exp_hdr_excl.rule_id, "exclusivity.neon")
        self.assertEqual(exp_hdr_excl.overwrite_model, self.models.neon_xhigh)

        # Backticked generic exclusivity phrase does not trigger exclusivity.
        res_quoted = decide(
            swarm_payload(
                "sync-status",
                "Update STATUS.md and export HTML report.",
                model="",
                last_input="Mention `Architect and Builder exclusively` and `[architect-builder-only]`.",
            )
        )
        self.assertEqual(res_quoted, {"decision": "allow", "overwrite": {"model": self.models.sonnet_high}})

    def test_generic_worker_role_tags_architect_builder_and_forensic(self) -> None:
        # [architect] and [architect-dyad] authorize explicit & omitted Architect role.
        for tag in ("[architect]", "[architect-dyad]"):
            with self.subTest(tag=tag):
                brief = f"@arch-review {tag}\nReview protocol spec and cite DECISIONS.md and STATUS.md."
                exp_explicit = explain_swarm_route(
                    {"action": "add", "name": "arch-review", "model": self.models.carbon, "brief": brief}
                )
                self.assertEqual(exp_explicit.rule_id, "carbon.explicit_authorized")
                self.assertIsNone(exp_explicit.overwrite_model)

                exp_omitted = explain_swarm_route({"action": "add", "name": "arch-review", "brief": brief})
                self.assertEqual(exp_omitted.rule_id, "carbon.tag_authorized")
                self.assertEqual(exp_omitted.overwrite_model, self.models.carbon)

        # [architect-build] overrides coding-loop redirect for explicit Architect.
        exp_arch_build = explain_swarm_route(
            {
                "action": "add",
                "name": "arch-patches",
                "model": self.models.carbon,
                "brief": "@arch-patches [architect-build]\nImplement Wave 5 and call edit_file on parser.py.",
            }
        )
        self.assertEqual(exp_arch_build.rule_id, "carbon.explicit_authorized")
        self.assertIsNone(exp_arch_build.overwrite_model)

        # [builder], [builder-xhigh], [builder-research], [builder-dyad] route omitted model to builder_xhigh.
        for tag in ("[builder]", "[builder-xhigh]", "[builder-research]", "[builder-dyad]"):
            with self.subTest(tag=tag):
                brief = f"@code-worker {tag}\nUpdate middleware and check STATUS.md notes."
                exp_b = explain_swarm_route({"action": "add", "name": "code-worker", "brief": brief})
                self.assertEqual(exp_b.rule_id, "neon.tag_xhigh")
                self.assertEqual(exp_b.overwrite_model, self.models.neon_xhigh)

        # [forensic] gates explicit forensic model even on >1800-char briefs and routes omitted model to forensic.
        long_brief = "@bug-hunter [forensic]\n" + ("context line " * 180)
        exp_f_explicit = explain_swarm_route(
            {"action": "add", "name": "bug-hunter", "model": self.models.opus, "brief": long_brief}
        )
        self.assertEqual(exp_f_explicit.rule_id, "opus.gated")
        self.assertIsNone(exp_f_explicit.overwrite_model)

        exp_f_omitted = explain_swarm_route({"action": "add", "name": "bug-hunter", "brief": long_brief})
        self.assertEqual(exp_f_omitted.overwrite_model, self.models.opus)


if __name__ == "__main__":
    unittest.main()
