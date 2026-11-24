"""The Model Alloy Component: 8-stage cognitive-asymmetry & Paired Research Dyad classifier."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import RouterConfig
from .quota import claude_pool_exhausted, gemini_headroom_ok, gemini_remaining_fraction
from .text import (
    extract_turn_flags,
    extract_worker_tags,
    is_carbon_neon_exclusive,
    scrub_negated_coding_markers,
    strip_code_spans,
)

ALLOW: dict[str, Any] = {"decision": "allow"}

_AUDIT_RESEARCH_NAME_TOKENS: tuple[str, ...] = (
    "audit",
    "review",
    "research",
    "spec",
    "theory",
    "math",
    "forensic",
    "dyad",
    "lead",
)
_BUILD_NAME_TOKENS: tuple[str, ...] = ("patch", "impl", "build", "boards", "coder")
_HARD_BUILD_NAME_TOKENS: tuple[str, ...] = ("patch", "impl", "builder", "coder", "boards")
_AUDIT_LOOP_DISQUALIFIERS: tuple[str, ...] = (
    "edit_file",
    "write_file",
    "replace_file_content",
    "multi_replace_file_content",
    "write_to_file",
    "implement wave",
    "implement phase",
    "regenerate all",
)
_NON_GRUNT_TAGS: frozenset[str] = frozenset({
    "[neon]",
    "[neon-kernel]",
    "[neon-research]",
    "[neon-dyad]",
    "[carbon]",
    "[carbon-dyad]",
    "[carbon-build]",
    "[carbon-neon]",
    "[dyad]",
    "[opus]",
})
_NEON_UPGRADE_TAGS: frozenset[str] = frozenset({
    "[neon-kernel]",
    "[neon-research]",
    "[neon-dyad]",
    "[dyad]",
})
_NEON_EXPLICIT_TAGS: frozenset[str] = frozenset({
    "[neon-kernel]",
    "[neon]",
    "[neon-research]",
    "[neon-dyad]",
    "[dyad]",
})


@dataclass(frozen=True)
class RouteExplanation:
    """Structured explanation of a worker routing decision under the Model Alloy policy."""

    decision: str
    rule_id: str
    reason: str
    requested_model: str = ""
    effective_model: str = ""
    overwrite_model: str | None = None
    worker_name: str = ""
    worker_tags: tuple[str, ...] = ()
    turn_flags: tuple[str, ...] = ()
    claude_exhausted: bool = False
    gemini_quota: float = 1.0
    carbon_neon_exclusive: bool = False
    preset: str = "antigravity"
    config_sources: tuple[str, ...] = ("defaults",)

    def to_hook_response(self) -> dict[str, Any]:
        """Convert this explanation into the Antigravity PreToolUse JSON response."""
        if self.decision != "allow":
            out: dict[str, Any] = {"decision": self.decision}
            if self.reason:
                out["reason"] = self.reason
            return out
        if self.overwrite_model:
            return {"decision": "allow", "overwrite": {"model": self.overwrite_model}}
        return {"decision": "allow"}

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full explanation payload for JSON CLI output and inspection."""
        return {
            "decision": self.decision,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "requested_model": self.requested_model,
            "effective_model": self.effective_model,
            "overwrite_model": self.overwrite_model,
            "worker_name": self.worker_name,
            "worker_tags": list(self.worker_tags),
            "turn_flags": list(self.turn_flags),
            "claude_exhausted": self.claude_exhausted,
            "gemini_quota": self.gemini_quota,
            "carbon_neon_exclusive": self.carbon_neon_exclusive,
            "preset": self.preset,
            "config_sources": list(self.config_sources),
            "hook_response": self.to_hook_response(),
        }


def is_light_grunt(name: str, brief: str, cfg: RouterConfig | None = None) -> bool:
    """Detect pure mechanical/monitoring/commit/lint tasks suited for Grunt Low / Failover Low."""
    conf = cfg or RouterConfig.default()
    tags = extract_worker_tags(name, brief)
    if "[grunt-low]" in tags:
        return True
    nm = name.strip().lower()
    if nm == "narrator" or nm.startswith("narrator-") or nm == "monitor" or nm.startswith("monitor-"):
        return True
    clean_txt = f"{nm}\n{strip_code_spans(brief)}".lower()
    raw_txt = f"{nm}\n{brief}".lower()
    if any(k in clean_txt for k in conf.core_code_build_keywords) and not any(
        g in nm for g in conf.plumbing_name_tokens
    ):
        return False
    if any(k in raw_txt for k in conf.plumbing_grunt_keywords):
        return False
    has_code_verbs = any(k in clean_txt for k in ("implement", "refactor", "architect", "derive"))
    if any(g in nm for g in ("lint", "commit")) and not has_code_verbs:
        return True
    return any(k in raw_txt for k in conf.light_grunt_keywords) and not has_code_verbs


def is_plumbing_grunt(name: str, brief: str, cfg: RouterConfig | None = None) -> bool:
    """Detect docs/ledger sync, HTML/CSV export plumbing, and test/guard sweep tasks for Grunt tier."""
    conf = cfg or RouterConfig.default()
    tags = extract_worker_tags(name, brief)
    if "[grunt]" in tags:
        return True
    nm = name.strip().lower()
    clean_txt = f"{nm}\n{strip_code_spans(brief)}".lower()
    raw_txt = f"{nm}\n{brief}".lower()
    if any(k in clean_txt for k in conf.core_code_build_keywords) and not any(
        g in nm for g in conf.plumbing_name_tokens
    ):
        return False
    return any(k in raw_txt for k in conf.plumbing_grunt_keywords)


def is_grunt_task(name: str, brief: str, cfg: RouterConfig | None = None) -> bool:
    """Return True when a worker brief represents mechanical or plumbing grunt work."""
    return is_light_grunt(name, brief, cfg) or is_plumbing_grunt(name, brief, cfg)


def grunt_model(name: str, brief: str, claude_exhausted: bool, cfg: RouterConfig | None = None) -> str:
    """Select the appropriate Grunt-tier model across primary (normal) and failover pools."""
    conf = cfg or RouterConfig.default()
    if is_light_grunt(name, brief, conf):
        return conf.models.failover_grunt_low if claude_exhausted else conf.models.grunt_low
    return conf.models.failover_grunt_high if claude_exhausted else conf.models.grunt_high


def is_neon_xhigh_task(name: str, brief: str, cfg: RouterConfig | None = None) -> bool:
    """Detect numerical/vectorized/modeling builds & 1M empirical research partner tasks."""
    conf = cfg or RouterConfig.default()
    tags = extract_worker_tags(name, brief)
    if tags & _NEON_EXPLICIT_TAGS:
        return True
    b_low = f"{name}\n{strip_code_spans(brief)}".lower()
    return any(k in b_low for k in conf.neon_xhigh_keywords)


def neon_builder_model(
    name: str,
    brief: str,
    cfg: RouterConfig | None = None,
    claude_exhausted: bool = False,
    gemini_quota_override: float | None = None,
) -> str:
    """Select the primary Builder tier (overflowing to Grunt High only when Builder pool is low)."""
    conf = cfg or RouterConfig.default()
    th = conf.thresholds
    gem_rem = gemini_remaining_fraction(override=gemini_quota_override)
    if gem_rem < th.gemini_min_fallback_quota and not claude_exhausted:
        return conf.models.grunt_high
    if is_neon_xhigh_task(name, brief, conf) and gem_rem >= th.gemini_healthy_specialist_quota:
        return conf.models.builder_xhigh
    if gem_rem >= th.gemini_neon_xhigh_floor:
        return conf.models.builder_xhigh
    return conf.models.builder_high


def neon_strict_gemini_model(
    name: str,
    brief: str,
    cfg: RouterConfig | None = None,
    gemini_quota_override: float | None = None,
) -> str:
    """Select Builder tier without overflowing to Grunt/Failover (for [carbon-neon] exclusivity)."""
    conf = cfg or RouterConfig.default()
    gem_rem = gemini_remaining_fraction(override=gemini_quota_override)
    if is_neon_xhigh_task(name, brief, conf) or gem_rem >= conf.thresholds.gemini_neon_xhigh_floor:
        return conf.models.builder_xhigh
    return conf.models.builder_high


def has_plumbing_only_name(name: str, cfg: RouterConfig | None = None) -> bool:
    """Return True when a worker's name signals pure plumbing rather than research/audit."""
    conf = cfg or RouterConfig.default()
    nm = name.strip().lower()
    if nm in ("monitor", "narrator") or nm.startswith(("monitor-", "narrator-")):
        return True
    has_plumb = any(g in nm for g in conf.plumbing_name_tokens)
    has_research = any(w in nm for w in _AUDIT_RESEARCH_NAME_TOKENS)
    return has_plumb and not has_research


def is_carbon_coding_loop(name: str, brief: str, cfg: RouterConfig | None = None) -> bool:
    """Detect when a coordinator tries to burn Architect turns on multi-file coding/rebuilds."""
    conf = cfg or RouterConfig.default()
    tags = extract_worker_tags(name, brief)
    if "[carbon-build]" in tags:
        return False
    nm = name.strip().lower()
    scrubbed_body = scrub_negated_coding_markers(strip_code_spans(brief))
    clean_txt = f"{nm}\n{scrubbed_body}".lower()
    is_pure_audit_or_research = any(w in nm for w in _AUDIT_RESEARCH_NAME_TOKENS) and not any(
        w in nm for w in _BUILD_NAME_TOKENS
    )
    if is_pure_audit_or_research and not any(m in clean_txt for m in _AUDIT_LOOP_DISQUALIFIERS):
        return False
    if any(w in nm for w in _HARD_BUILD_NAME_TOKENS):
        return True
    return any(m in clean_txt for m in conf.carbon_code_loop_markers)


def is_carbon_authorized_role(name: str, brief: str, cfg: RouterConfig | None = None) -> bool:
    """Allow Architect workers strictly for specs, causal/lead research, dyads, and adversarial audit."""
    conf = cfg or RouterConfig.default()
    tags = extract_worker_tags(name, brief)
    if tags & {"[grunt]", "[grunt-low]"}:
        return False
    if is_carbon_coding_loop(name, brief, conf) or has_plumbing_only_name(name, conf):
        return False
    if tags & {"[carbon]", "[carbon-dyad]"}:
        return True
    if is_grunt_task(name, brief, conf):
        return False
    b_low = f"{name}\n{strip_code_spans(brief)}".lower()
    return any(k in b_low for k in conf.carbon_spec_research_audit_keywords)


def opus_authorized(name: str, brief: str, cfg: RouterConfig | None = None) -> bool:
    """Allow Forensic specialist only when explicitly tagged [opus] or for short forensic briefs."""
    conf = cfg or RouterConfig.default()
    tags = extract_worker_tags(name, brief)
    if "[opus]" in tags:
        return True
    b_low = strip_code_spans(brief).lower()
    return len(brief) < conf.thresholds.opus_spec_len_max and any(
        k in b_low for k in conf.opus_forensic_keywords
    )


def classify_alloy_worker(
    name: str,
    brief: str,
    cfg: RouterConfig | None = None,
    claude_exhausted: bool = False,
    gemini_quota_override: float | None = None,
) -> str:
    """Route omitted/default workers under the Model Alloy cognitive-asymmetry stack."""
    conf = cfg or RouterConfig.default()
    tags = extract_worker_tags(name, brief)
    if tags & {"[grunt]", "[grunt-low]"}:
        return grunt_model(name, brief, claude_exhausted, conf)
    if is_grunt_task(name, brief, conf) and not (tags & _NON_GRUNT_TAGS):
        return grunt_model(name, brief, claude_exhausted, conf)
    if (
        (tags & {"[carbon]", "[carbon-dyad]"})
        and is_carbon_authorized_role(name, brief, conf)
        and gemini_headroom_ok(conf, gemini_quota_override=gemini_quota_override)
    ):
        return conf.models.architect
    if "[opus]" in tags and not claude_exhausted:
        return conf.models.forensic
    return neon_builder_model(
        name,
        brief,
        conf,
        claude_exhausted=claude_exhausted,
        gemini_quota_override=gemini_quota_override,
    )


def _resolve_grunt_overwrite(
    req_lower: str,
    target_grunt: str,
    exhausted: bool,
    strict_low: bool,
    cfg: RouterConfig,
) -> str | None:
    """Return None when requested grunt model is allowed as-is, else target_grunt overwrite."""
    if req_lower == target_grunt.lower():
        return None
    if not strict_low:
        sonnet_family = {
            cfg.models.grunt_low.lower(),
            cfg.models.grunt_high.lower(),
            "claude-sonnet-5-5-low",
            "claude-sonnet-5-5-high",
            "claude-sonnet-5-5-medium",
        }
        hydrogen_family = {
            cfg.models.failover_grunt_low.lower(),
            cfg.models.failover_grunt_high.lower(),
            "gemini-4-hydrogen-low",
            "gemini-4-hydrogen-high",
            "gemini-4-hydrogen-medium",
        }
        if not exhausted and req_lower in sonnet_family:
            return None
        if exhausted and req_lower in hydrogen_family:
            return None
    return target_grunt


def is_swarm_control_tool(tool_name: str) -> bool:
    """Return True strictly for the swarm control tool (excluding swarm_wait, read_board, etc.)."""
    low = tool_name.strip().lower()
    return low == "swarm" or low.endswith(("__swarm", "/swarm", ".swarm"))


def explain_swarm_route(
    args: dict[str, Any],
    last_input: str = "",
    transcript_path: str = "",
    cfg: RouterConfig | None = None,
    claude_quota_override: float | None = None,
    gemini_quota_override: float | None = None,
) -> RouteExplanation:
    """Evaluate all 8 Model Alloy precedence stages and return a structured RouteExplanation."""
    conf = cfg or RouterConfig.default()
    action = str(args.get("action") or "").strip().lower()
    req_model = str(args.get("model") or "").strip()
    req_lower = req_model.lower()
    w_name = str(args.get("name") or "").strip()
    w_lower = w_name.lower()
    brief = str(args.get("brief") or "")

    worker_tags = extract_worker_tags(w_name, brief)
    turn_flags = extract_turn_flags(last_input)
    gem_rem = gemini_remaining_fraction(override=gemini_quota_override)

    def _make(
        rule_id: str,
        reason: str,
        overwrite_model: str | None = None,
        effective_model: str | None = None,
        exhausted_state: bool = False,
        exclusive_state: bool = False,
    ) -> RouteExplanation:
        eff = effective_model if effective_model is not None else (overwrite_model or req_model)
        return RouteExplanation(
            decision="allow",
            rule_id=rule_id,
            reason=reason,
            requested_model=req_model,
            effective_model=eff,
            overwrite_model=overwrite_model,
            worker_name=w_name,
            worker_tags=tuple(sorted(worker_tags)),
            turn_flags=tuple(sorted(turn_flags)),
            claude_exhausted=exhausted_state,
            gemini_quota=gem_rem,
            carbon_neon_exclusive=exclusive_state,
            preset=conf.preset,
            config_sources=conf.sources,
        )

    if "[allow-gemini]" in turn_flags or "[inline-gemini]" in turn_flags:
        return _make(
            "turn_flag.allow_gemini",
            "Turn-level [allow-gemini]/[inline-gemini] escape hatch bypasses router overrides.",
        )

    if action not in ("add", "model"):
        return _make(
            "swarm.passthrough_action",
            f"Swarm action '{action}' does not select or switch worker models.",
        )

    if action == "model" and w_lower in ("", "coordinator"):
        return _make(
            "swarm.coordinator_self_model",
            "Coordinator self-model switches are preserved as requested.",
        )

    carbon_neon_only = is_carbon_neon_exclusive(worker_tags, turn_flags, last_input, brief)
    carbon_aliases = {
        conf.models.architect.lower(),
        "gemini-4-carbon-high",
        "gemini 4 carbon (high)",
        "gemini-pro-orchestrator",
        "orchestrator (carbon)",
    }
    neon_xhigh_aliases = {
        conf.models.builder_xhigh.lower(),
        "gemini-4-neon-xhigh",
        "gemini 4 neon (xhigh)",
    }
    neon_high_aliases = {
        conf.models.builder_high.lower(),
        "gemini-4-neon-high",
        "gemini 4 neon (high)",
        "orchestrator (neon)",
        "gemini-pro-orchestrator-neon",
    }
    is_explicit_carbon = req_lower in carbon_aliases

    # Stage 0: [carbon-neon] exclusivity regime
    if carbon_neon_only:
        wants_carbon = (
            "[carbon-build]" in worker_tags
            or (is_explicit_carbon and is_carbon_authorized_role(w_name, brief, conf))
            or (
                bool(worker_tags & {"[carbon]", "[carbon-dyad]"})
                and is_carbon_authorized_role(w_name, brief, conf)
            )
        )
        if wants_carbon and gemini_headroom_ok(
            conf,
            conf.thresholds.gemini_min_fallback_quota,
            gemini_quota_override=gemini_quota_override,
        ):
            if is_explicit_carbon:
                return _make(
                    "exclusivity.carbon",
                    "[carbon-neon] exclusivity: authorized Architect role preserved.",
                    overwrite_model=None,
                    effective_model=conf.models.architect,
                    exclusive_state=True,
                )
            return _make(
                "exclusivity.carbon",
                "[carbon-neon] exclusivity: authorized Architect tag routed to Architect pool.",
                overwrite_model=conf.models.architect,
                exclusive_state=True,
            )

        target_neon = neon_strict_gemini_model(
            w_name, brief, conf, gemini_quota_override=gemini_quota_override
        )
        if req_lower in neon_xhigh_aliases:
            return _make(
                "exclusivity.neon",
                "[carbon-neon] exclusivity: explicit Builder XHigh request preserved.",
                overwrite_model=None,
                effective_model=conf.models.builder_xhigh,
                exclusive_state=True,
            )
        if req_lower in neon_high_aliases and target_neon == conf.models.builder_high:
            return _make(
                "exclusivity.neon",
                "[carbon-neon] exclusivity: explicit Builder High request preserved.",
                overwrite_model=None,
                effective_model=conf.models.builder_high,
                exclusive_state=True,
            )
        return _make(
            "exclusivity.neon",
            f"[carbon-neon] exclusivity: non-Architect work locked to {target_neon} (zero Grunt/Failover leakage).",
            overwrite_model=target_neon,
            exclusive_state=True,
        )

    exhausted = (
        claude_pool_exhausted(
            transcript_path=transcript_path,
            cfg=conf,
            claude_quota_override=claude_quota_override,
        )
        or ("[claude-exhausted]" in worker_tags)
        or ("[claude-exhausted]" in turn_flags)
    )

    # Stage 1: Explicit header [grunt] / [grunt-low] always wins before body quotes or heuristics.
    if worker_tags & {"[grunt]", "[grunt-low]"}:
        target_grunt = grunt_model(w_name, brief, exhausted, conf)
        overwrite = _resolve_grunt_overwrite(
            req_lower, target_grunt, exhausted, "[grunt-low]" in worker_tags, conf
        )
        regime = "failover grunt tier (Claude <= 2%)" if exhausted else "primary grunt tier"
        return _make(
            "grunt.explicit_tag",
            f"Explicit grunt header tag routes to {target_grunt} ({regime}).",
            overwrite_model=overwrite,
            effective_model=overwrite or req_model or target_grunt,
            exhausted_state=exhausted,
        )

    # Stage 2: Superseded Argon -> Alloy routing
    if "argon" in req_lower:
        target = classify_alloy_worker(
            w_name,
            brief,
            conf,
            claude_exhausted=exhausted,
            gemini_quota_override=gemini_quota_override,
        )
        return _make(
            "argon.superseded",
            f"Superseded Argon model rewritten to Alloy target {target}.",
            overwrite_model=target,
            exhausted_state=exhausted,
        )

    # Stage 3: Untagged Grunt Work
    if is_grunt_task(w_name, brief, conf) and not (worker_tags & _NON_GRUNT_TAGS):
        target_grunt = grunt_model(w_name, brief, exhausted, conf)
        overwrite = _resolve_grunt_overwrite(req_lower, target_grunt, exhausted, False, conf)
        regime = "failover grunt tier (Claude <= 2%)" if exhausted else "primary grunt tier"
        return _make(
            "grunt.heuristic",
            f"Untagged plumbing/mechanical worker routed to {target_grunt} ({regime}).",
            overwrite_model=overwrite,
            effective_model=overwrite or req_model or target_grunt,
            exhausted_state=exhausted,
        )

    # Stage 4: Explicit Architect requests & explicit [carbon] / [carbon-dyad] headers
    if is_explicit_carbon:
        if "opus" in req_lower and opus_authorized(w_name, brief, conf):
            return _make(
                "opus.gated",
                "Opus request authorized via [opus] tag or short forensic root-cause brief.",
                overwrite_model=None,
                effective_model=req_model,
                exhausted_state=exhausted,
            )
        if "[carbon-build]" in worker_tags or (
            is_carbon_authorized_role(w_name, brief, conf)
            and gemini_headroom_ok(conf, gemini_quota_override=gemini_quota_override)
        ):
            return _make(
                "carbon.explicit_authorized",
                "Explicit Architect request authorized for spec/research/dyad/audit role.",
                overwrite_model=None,
                effective_model=conf.models.architect,
                exhausted_state=exhausted,
            )
        target = neon_builder_model(
            w_name,
            brief,
            conf,
            claude_exhausted=exhausted,
            gemini_quota_override=gemini_quota_override,
        )
        return _make(
            "carbon.coding_loop_redirect",
            f"Architect coding/rebuild loop redirected to {target} to protect frontier reasoning quota.",
            overwrite_model=target,
            exhausted_state=exhausted,
        )

    if (
        bool(worker_tags & {"[carbon]", "[carbon-dyad]"})
        and is_carbon_authorized_role(w_name, brief, conf)
        and gemini_headroom_ok(conf, gemini_quota_override=gemini_quota_override)
    ):
        return _make(
            "carbon.tag_authorized",
            "Explicit [carbon]/[carbon-dyad] header routed to Architect for authorized reasoning role.",
            overwrite_model=conf.models.architect,
            exhausted_state=exhausted,
        )

    # Stage 5: Explicit Builder requests & [neon-dyad]/[neon-research]/[neon-kernel]/[dyad] upgrades
    if req_lower in neon_xhigh_aliases and gemini_headroom_ok(
        conf, gemini_quota_override=gemini_quota_override
    ):
        return _make(
            "neon.explicit_xhigh",
            "Explicit Builder XHigh request preserved with healthy headroom.",
            overwrite_model=None,
            effective_model=conf.models.builder_xhigh,
            exhausted_state=exhausted,
        )

    if req_lower in neon_high_aliases:
        if (worker_tags & _NEON_UPGRADE_TAGS) and gemini_headroom_ok(
            conf, gemini_quota_override=gemini_quota_override
        ):
            return _make(
                "neon.dyad_or_kernel_upgrade",
                "Dyad/research/kernel tag on Builder High upgraded to Builder XHigh.",
                overwrite_model=conf.models.builder_xhigh,
                exhausted_state=exhausted,
            )
        if gemini_headroom_ok(
            conf,
            conf.thresholds.gemini_min_fallback_quota,
            gemini_quota_override=gemini_quota_override,
        ):
            return _make(
                "neon.explicit_high",
                "Explicit Builder High request preserved.",
                overwrite_model=None,
                effective_model=conf.models.builder_high,
                exhausted_state=exhausted,
            )

    if (worker_tags & _NEON_EXPLICIT_TAGS) and gemini_headroom_ok(
        conf, gemini_quota_override=gemini_quota_override
    ):
        return _make(
            "neon.tag_xhigh",
            "Explicit Builder/dyad worker tag routed to Builder XHigh.",
            overwrite_model=conf.models.builder_xhigh,
            exhausted_state=exhausted,
        )

    # Stage 6: Claude Exhaustion Regime
    if exhausted:
        failover_ids = {
            conf.models.failover_grunt_high.lower(),
            conf.models.failover_grunt_low.lower(),
        }
        if (
            req_lower in failover_ids
            or req_lower.startswith("gemini-4-hydrogen-")
            or req_lower.startswith("gemini 4 hydrogen")
        ):
            return _make(
                "claude.exhausted_hydrogen_allow",
                "Claude pool exhausted; explicit failover-tier request allowed.",
                overwrite_model=None,
                effective_model=req_model,
                exhausted_state=True,
            )
        target = classify_alloy_worker(
            w_name,
            brief,
            conf,
            claude_exhausted=True,
            gemini_quota_override=gemini_quota_override,
        )
        return _make(
            "claude.exhausted_failover",
            f"Claude pool exhausted (<= {conf.thresholds.claude_exhausted_threshold:.0%}); failed over to {target}.",
            overwrite_model=target,
            exhausted_state=True,
        )

    # Stage 7: Normal Regime — Explicit Claude & GPT requests
    if ("opus" in req_lower and "claude" in req_lower) or req_lower == conf.models.forensic.lower():
        if opus_authorized(w_name, brief, conf):
            return _make(
                "opus.gated",
                "Opus request authorized via [opus] tag or short forensic root-cause brief.",
                overwrite_model=None,
                effective_model=req_model,
                exhausted_state=False,
            )
        target = neon_builder_model(
            w_name,
            brief,
            conf,
            claude_exhausted=False,
            gemini_quota_override=gemini_quota_override,
        )
        return _make(
            "opus.redirect_to_neon",
            f"Ungated Opus request redirected to {target} to conserve frontier quota.",
            overwrite_model=target,
            exhausted_state=False,
        )

    if req_lower.startswith("claude-") or req_lower.startswith("claude "):
        if "[sonnet]" in worker_tags or not gemini_headroom_ok(
            conf,
            conf.thresholds.gemini_healthy_specialist_quota,
            gemini_quota_override=gemini_quota_override,
        ):
            return _make(
                "sonnet.explicit_override",
                "Explicit [sonnet] override or low Builder headroom preserves Claude request.",
                overwrite_model=None,
                effective_model=req_model,
                exhausted_state=False,
            )
        target = neon_builder_model(
            w_name,
            brief,
            conf,
            claude_exhausted=False,
            gemini_quota_override=gemini_quota_override,
        )
        return _make(
            "sonnet.code_redirect",
            f"Non-grunt Sonnet build redirected to {target} so Claude stays reserved for grunt work.",
            overwrite_model=target,
            exhausted_state=False,
        )

    if req_lower.startswith("gpt-"):
        return _make(
            "gpt.passthrough",
            "Explicit GPT model request preserved.",
            overwrite_model=None,
            effective_model=req_model,
            exhausted_state=False,
        )

    # Stage 8: Omitted / default model -> Alloy classification
    target = classify_alloy_worker(
        w_name,
        brief,
        conf,
        claude_exhausted=exhausted,
        gemini_quota_override=gemini_quota_override,
    )
    return _make(
        "default.alloy_classify",
        f"Omitted/default model classified by Model Alloy policy to {target}.",
        overwrite_model=target,
        exhausted_state=exhausted,
    )


def handle_swarm(
    args: dict[str, Any],
    last_input: str = "",
    transcript_path: str = "",
    cfg: RouterConfig | None = None,
) -> dict[str, Any]:
    """Handle a PreToolUse swarm tool call and return the Antigravity hook JSON dictionary."""
    return explain_swarm_route(
        args=args,
        last_input=last_input,
        transcript_path=transcript_path,
        cfg=cfg,
    ).to_hook_response()
