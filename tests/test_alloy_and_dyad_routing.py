"""Tests for 4-Stage Model Alloy classification, Research Dyad upgrades, exclusivity, and layered config."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from tests.helpers import RouterTestBase, swarm_payload

# isort: split
from model_router import AlloyConfig, RouterConfig, decide, explain_swarm_route, load_config


class TestAlloyAndDyadRouting(RouterTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.models = RouterConfig.default().models
        self.assertIs(AlloyConfig, RouterConfig)

    def test_untagged_plumbing_workers_with_modeling_terms_stay_on_grunt(self) -> None:
        summary_brief = (
            "Summarize completed Wave 3 validation covering kalman smoothing, cholesky factors, "
            "quadrature nodes, and filter.py OOS results in project notes."
        )
        for w_name in ("sync-status", "doc-sync", "registry-sync", "ledger-sync", "roadmap-sync"):
            with self.subTest(worker=w_name):
                self.assertEqual(
                    decide(swarm_payload(w_name, summary_brief, model="")),
                    {"decision": "allow", "overwrite": {"model": self.models.sonnet_high}},
                )
                with mock.patch.dict(
                    os.environ, {"MODEL_ROUTER_CLAUDE_QUOTA": "0.0", "AGY_ROUTER_CLAUDE_QUOTA": "0.0"}
                ):
                    self.assertEqual(
                        decide(swarm_payload(w_name, summary_brief, model="")),
                        {"decision": "allow", "overwrite": {"model": self.models.hydrogen_high}},
                    )

    def test_non_doc_modeling_worker_routes_to_neon_xhigh(self) -> None:
        code_brief = "Implement the kalman filter and cholesky factorization in src/sync_engine.py."
        self.assertEqual(
            decide(swarm_payload("sync-engine", code_brief, model="")),
            {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
        )

    def test_neon_high_upgraded_to_xhigh_for_dyad_research_and_kernel_tags(self) -> None:
        for tag in ("[neon-dyad]", "[neon-research]", "[neon-kernel]", "[dyad]"):
            with self.subTest(tag=tag):
                brief = f"@neon-xray {tag}\nRun full-repo Parquet ablation across state-space filters."
                exp = explain_swarm_route(
                    {"action": "add", "name": "neon-xray", "model": self.models.neon_high, "brief": brief}
                )
                self.assertEqual(
                    exp.to_hook_response(),
                    {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
                )
                self.assertEqual(exp.rule_id, "neon.dyad_or_kernel_upgrade")

        exp_plain = explain_swarm_route(
            {
                "action": "add",
                "name": "light-helper",
                "model": self.models.neon_high,
                "brief": "Add a small JSON serializer helper in utils.py.",
            }
        )
        self.assertEqual(exp_plain.to_hook_response(), {"decision": "allow"})
        self.assertEqual(exp_plain.rule_id, "neon.explicit_high")

    def test_omitted_model_with_dyad_or_neon_research_tags_routes_to_neon_xhigh(self) -> None:
        for tag in ("[dyad]", "[neon-dyad]", "[neon-research]"):
            with self.subTest(tag=tag):
                brief = f"@partner {tag}\nHarvest primary-source literature and check OOS slices."
                exp = explain_swarm_route({"action": "add", "name": "partner", "brief": brief})
                self.assertEqual(
                    exp.to_hook_response(),
                    {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
                )
                self.assertEqual(exp.rule_id, "neon.tag_xhigh")

    def test_carbon_dyad_citing_docs_stays_on_carbon_explicit_and_omitted(self) -> None:
        brief = (
            "@carbon-skill-theory [carbon-dyad]\n"
            "Diagnose censoring in filter.py and kernel.py; write spec to "
            "docs/reports/model_audit.md and cite DECISIONS.md and STATUS.md."
        )
        self.assertEqual(
            decide(swarm_payload("carbon-skill-theory", brief, model=self.models.carbon)),
            {"decision": "allow"},
        )
        self.assertEqual(
            decide(swarm_payload("carbon-skill-theory", brief, model="")),
            {"decision": "allow", "overwrite": {"model": self.models.carbon}},
        )

    def test_carbon_coding_loop_redirects_unless_carbon_build_escape_hatch(self) -> None:
        loop_brief = "Implement Wave 4 fixes in filter.py and kernel.py and regenerate all reports."
        self.assertEqual(
            decide(swarm_payload("carbon-core-patches", loop_brief, model=self.models.carbon)),
            {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
        )
        escape_brief = "@carbon-core-patches [carbon-build]\n" + loop_brief
        self.assertEqual(
            decide(swarm_payload("carbon-core-patches", escape_brief, model=self.models.carbon)),
            {"decision": "allow"},
        )

    def test_sonnet_code_build_redirects_to_neon_unless_explicit_sonnet_tag(self) -> None:
        self.assertEqual(
            decide(
                swarm_payload(
                    "feature-builder",
                    "Implement vectorized Kalman smoothing in filter.py.",
                    model=self.models.sonnet_high,
                )
            ),
            {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
        )
        self.assertEqual(
            decide(
                swarm_payload(
                    "feature-builder",
                    "@feature-builder [sonnet]\nImplement helper in feature.py.",
                    model=self.models.sonnet_high,
                )
            ),
            {"decision": "allow"},
        )

    def test_argon_superseded_and_opus_strict_gating(self) -> None:
        exp_argon = explain_swarm_route(
            {
                "action": "add",
                "name": "legacy-worker",
                "model": "gemini-4-argon-high",
                "brief": "Implement vectorized quadrature in kernel.py.",
            }
        )
        self.assertEqual(exp_argon.rule_id, "argon.superseded")
        self.assertEqual(exp_argon.overwrite_model, self.models.neon_xhigh)

        exp_opus_ok = explain_swarm_route(
            {
                "action": "add",
                "name": "bug-hunter",
                "model": self.models.opus,
                "brief": "Find root cause of intermittent NaN gradient in pipeline.py.",
            }
        )
        self.assertEqual(exp_opus_ok.rule_id, "opus.gated")
        self.assertEqual(exp_opus_ok.to_hook_response(), {"decision": "allow"})

        exp_opus_redir = explain_swarm_route(
            {
                "action": "add",
                "name": "feature-dev",
                "model": self.models.opus,
                "brief": "Implement new feature pipeline with standard logging.",
            }
        )
        self.assertEqual(exp_opus_redir.rule_id, "opus.redirect_to_neon")
        self.assertEqual(exp_opus_redir.overwrite_model, self.models.neon_xhigh)

    def test_carbon_neon_exclusivity_flag_and_phrase_lock_strictly_to_carbon_or_neon(self) -> None:
        exclusivity_triggers = (
            "[carbon-neon] Run 6h dyad audit.",
            "Both should be done with Carbon and Neon exclusively.",
        )
        carbon_audit_brief = "@carbon-forensic-audit [carbon]\nAdversarial audit of filter.py and STATUS.md."
        carbon_loop_brief = "Modify filter.py and implement new kernel fixes across pipeline."
        doc_grunt_brief = "Update STATUS.md and export HTML report."

        for last_in in exclusivity_triggers:
            with self.subTest(last_input=last_in):
                self.assertEqual(
                    decide(
                        swarm_payload(
                            "carbon-forensic-audit",
                            carbon_audit_brief,
                            model=self.models.carbon,
                            last_input=last_in,
                        )
                    ),
                    {"decision": "allow"},
                )
                self.assertEqual(
                    decide(
                        swarm_payload(
                            "carbon-core-patches",
                            carbon_loop_brief,
                            model=self.models.carbon,
                            last_input=last_in,
                        )
                    ),
                    {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}},
                )
                for req_model in ("", self.models.sonnet_high, self.models.hydrogen_high):
                    res = decide(
                        swarm_payload("sync-status", doc_grunt_brief, model=req_model, last_input=last_in)
                    )
                    self.assertEqual(res, {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}})

                with mock.patch.dict(
                    os.environ, {"MODEL_ROUTER_GEMINI_QUOTA": "0.03", "AGY_ROUTER_GEMINI_QUOTA": "0.03"}
                ):
                    res_low = decide(
                        swarm_payload(
                            "sync-status",
                            doc_grunt_brief,
                            model=self.models.sonnet_high,
                            last_input=last_in,
                        )
                    )
                    self.assertIn(
                        res_low["overwrite"]["model"],
                        (self.models.neon_xhigh, self.models.neon_high),
                    )

                deny_sub = decide(
                    {
                        "hookEventName": "PreToolUse",
                        "modelName": "orchestrator (carbon)",
                        "lastUserInput": last_in,
                        "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "research"}},
                    }
                )
                self.assertEqual(deny_sub["decision"], "deny")

    def test_gemini_low_quota_overflows_to_sonnet_or_steps_down_to_neon_high(self) -> None:
        exp_overflow = explain_swarm_route(
            {"action": "add", "name": "builder", "brief": "Implement module in solver.py."},
            claude_quota_override=0.60,
            gemini_quota_override=0.03,
        )
        self.assertEqual(exp_overflow.overwrite_model, self.models.sonnet_high)

        exp_stepdown = explain_swarm_route(
            {"action": "add", "name": "builder", "brief": "Implement module in helper.py."},
            claude_quota_override=0.60,
            gemini_quota_override=0.12,
        )
        self.assertEqual(exp_stepdown.overwrite_model, self.models.neon_high)

        exp_specialist = explain_swarm_route(
            {"action": "add", "name": "builder", "brief": "Implement cholesky quadrature solver."},
            claude_quota_override=0.60,
            gemini_quota_override=0.17,
        )
        self.assertEqual(exp_specialist.overwrite_model, self.models.neon_xhigh)

    def test_layered_config_discovery_merges_global_and_workspace_and_fails_open(self) -> None:
        repo_dir = self.tmp_dir / "demo_repo"
        nested_dir = repo_dir / "packages" / "core"
        nested_dir.mkdir(parents=True)
        (repo_dir / ".git").mkdir()
        (repo_dir / ".agents").mkdir()

        global_cfg = self.tmp_dir / "global_router.json"
        global_cfg.write_text(
            json.dumps(
                {
                    "plumbing_grunt_keywords": ["custom_release_log.md"],
                    "thresholds": {"max_inline_edits_heavy": 3},
                }
            ),
            encoding="utf-8",
        )
        workspace_alloy = repo_dir / ".agents" / "alloy.json"
        workspace_alloy.write_text(
            json.dumps({"thresholds": {"max_inline_edits_heavy": 5}}),
            encoding="utf-8",
        )
        workspace_router = repo_dir / ".agents" / "model-router.json"
        workspace_router.write_text(
            json.dumps(
                {
                    "core_code_build_keywords": ["pricing_engine.py"],
                    "carbon_code_loop_markers": ["modify pricing_engine.py"],
                    "thresholds": {"max_inline_edits_heavy": 2},
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CONFIG_PATH": str(global_cfg)}):
            cfg = load_config(cwd=str(nested_dir))

        self.assertIn("custom_release_log.md", cfg.plumbing_grunt_keywords)
        self.assertIn("pricing_engine.py", cfg.core_code_build_keywords)
        self.assertEqual(cfg.thresholds.max_inline_edits_heavy, 2)
        self.assertEqual(len(cfg.sources), 4)

        res = decide(
            swarm_payload(
                "carbon-worker",
                "Modify pricing_engine.py for Q4 rollout.",
                model=self.models.carbon,
                cwd=str(nested_dir),
            )
        )
        self.assertEqual(res, {"decision": "allow", "overwrite": {"model": self.models.neon_xhigh}})

        bad_cfg = self.tmp_dir / "broken.json"
        bad_cfg.write_text("{not valid json", encoding="utf-8")
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_CONFIG_PATH": str(bad_cfg)}):
            fallback_cfg = load_config()
        self.assertEqual(fallback_cfg.sources, ("defaults",))

    def test_mainstream_software_engineering_keywords_route_cleanly(self) -> None:
        # Core code build keywords prevent grunt misclassification even when mentioning pytest/boilerplate.
        for kw in ("endpoint", "parser", "middleware", "serializer", "schema", "migration"):
            with self.subTest(core_keyword=kw):
                exp = explain_swarm_route(
                    {
                        "action": "add",
                        "name": "service-worker",
                        "brief": f"Build the {kw} module, remove boilerplate, and run pytest.",
                    }
                )
                self.assertEqual(exp.overwrite_model, self.models.neon_xhigh)
                self.assertEqual(exp.rule_id, "default.alloy_classify")

        # Architect spec/research/audit keywords authorize explicit Architect without header tags.
        for kw in ("threat model", "consistency model", "architecture spec", "race condition", "deadlock"):
            with self.subTest(architect_keyword=kw):
                exp = explain_swarm_route(
                    {
                        "action": "add",
                        "name": "systems-review",
                        "model": self.models.carbon,
                        "brief": f"Analyze the {kw} for the payment worker queue.",
                    }
                )
                self.assertEqual(exp.rule_id, "carbon.explicit_authorized")
                self.assertIsNone(exp.overwrite_model)

        # Builder XHigh keywords stay on builder_xhigh under moderate Gemini quota (0.15 <= q < 0.20).
        for kw in ("full-repo", "call-graph", "lock-free", "distributed", "benchmark sweep"):
            with self.subTest(xhigh_keyword=kw):
                exp = explain_swarm_route(
                    {
                        "action": "add",
                        "name": "systems-worker",
                        "brief": f"Run {kw} refactoring across the transport package.",
                    },
                    claude_quota_override=0.60,
                    gemini_quota_override=0.17,
                )
                self.assertEqual(exp.overwrite_model, self.models.neon_xhigh)

    def test_builder_tag_vs_builder_upgrade_tags_on_builder_high(self) -> None:
        exp_plain_builder = explain_swarm_route(
            {
                "action": "add",
                "name": "light-builder",
                "model": self.models.neon_high,
                "brief": "@light-builder [builder]\nAdd small helper adapter in utils.py.",
            }
        )
        self.assertEqual(exp_plain_builder.rule_id, "neon.explicit_high")
        self.assertIsNone(exp_plain_builder.overwrite_model)

        for tag in ("[builder-xhigh]", "[builder-research]", "[builder-dyad]"):
            with self.subTest(tag=tag):
                exp_up = explain_swarm_route(
                    {
                        "action": "add",
                        "name": "deep-builder",
                        "model": self.models.neon_high,
                        "brief": f"@deep-builder {tag}\nRun call-graph sweep across all modules.",
                    }
                )
                self.assertEqual(exp_up.rule_id, "neon.dyad_or_kernel_upgrade")
                self.assertEqual(exp_up.overwrite_model, self.models.neon_xhigh)


if __name__ == "__main__":
    unittest.main()
