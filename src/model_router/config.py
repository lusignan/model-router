"""Immutable RouterConfig, role-slot ModelPool presets, layered JSON overrides, and state paths."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

DEFAULT_LIGHT_GRUNT_KEYWORDS: tuple[str, ...] = (
    "lint",
    "format",
    "git commit",
    "atomic commit",
    "stage and commit",
    "commit in ",
    "cleanup",
    "tail log",
    "hook guard",
    "worktree prune",
)

DEFAULT_PLUMBING_NAME_TOKENS: tuple[str, ...] = (
    "grunt",
    "plumb",
    "export",
    "doc",
    "sync",
    "status",
    "ledger",
    "roadmap",
    "registry",
    "commit",
    "guard",
    "pytest",
    "lint",
)

DEFAULT_PLUMBING_GRUNT_KEYWORDS: tuple[str, ...] = (
    "state.json",
    "decisions.md",
    "status.md",
    "readme",
    "changelog",
    "docs/readme",
    "sync docs/",
    "doc-sync",
    "docs-sync",
    "sync-docs",
    "sync-status",
    "status-sync",
    "ledger-sync",
    "sync-ledger",
    "registry-sync",
    "sync-registry",
    "roadmap-sync",
    "sync-roadmap",
    "decision ledger",
    "decision registry",
    "update ledger",
    "update registry",
    "update status",
    "project status",
    "sync status",
    "sync ledger",
    "sync registry",
    "sync docs",
    "governance persistence",
    "export html",
    "html/csv",
    "html + csv",
    "csv export",
    "run pytest",
    "py_compile",
    "guard suite",
    "repo guards",
    "boilerplate",
    "plumbing",
)

DEFAULT_CORE_CODE_BUILD_KEYWORDS: tuple[str, ...] = (
    "implement",
    "refactor",
    "vectorize",
    "quadrature",
    "kalman",
    "state-space",
    "monte carlo",
    "qmc",
    "kernel",
    "cholesky",
    "logsumexp",
    "einsum",
    "hessian",
    "jacobian",
    "copula",
    "competing-risks",
    "changepoint",
    "bocpd",
    "polars",
)

DEFAULT_CARBON_SPEC_RESEARCH_AUDIT_KEYWORDS: tuple[str, ...] = (
    "statistical law",
    "mathematical",
    "prior",
    "likelihood",
    "posterior",
    "identifiab",
    "causal",
    "hierarchical bayes",
    "empirical bayes",
    "certainty equivalent",
    "derivation",
    "math audit",
    "adversarial",
    "audit",
    "review",
    "forensic",
    "literature",
    "research",
    "hypothesis",
    "directive",
    "spec",
    "brief",
    "censoring",
    "survivorship",
    "selection bias",
    "competing-risks",
    "changepoint",
    "red-team",
    "falsification",
    "dyad",
)

DEFAULT_CARBON_CODE_LOOP_MARKERS: tuple[str, ...] = (
    "core-patches",
    "code-builder",
    "patch ",
    "patches ",
    "edit_file",
    "write_file",
    "replace_file_content",
    "multi_replace_file_content",
    "write_to_file",
    "implement wave",
    "implement phase",
    "regenerate all",
)

DEFAULT_NEON_XHIGH_KEYWORDS: tuple[str, ...] = (
    "quadrature",
    "gauss-hermite",
    "kalman",
    "rts smoother",
    "state-space",
    "cholesky",
    "logsumexp",
    "einsum",
    "monte carlo",
    "qmc",
    "vectoriz",
    "tensor",
    "numerical",
    "hessian",
    "jacobian",
    "copula",
    "competing-risks",
    "changepoint",
    "bocpd",
    "code x-ray",
    "chain-xray",
    "code-xray",
    "parquet",
    "ablation",
    "falsification",
    "cross-repo",
    "500k",
    "1m context",
    "research partner",
    "empirical sweep",
    "oos regression",
)

DEFAULT_OPUS_FORENSIC_KEYWORDS: tuple[str, ...] = (
    "root cause",
    "unknown bug",
    "forensic",
)

DEFAULT_SPECIALIST_SUBAGENTS: tuple[str, ...] = (
    "browser",
    "image-generator",
)

_KEYWORD_FIELDS: tuple[str, ...] = (
    "light_grunt_keywords",
    "plumbing_name_tokens",
    "plumbing_grunt_keywords",
    "core_code_build_keywords",
    "carbon_spec_research_audit_keywords",
    "carbon_code_loop_markers",
    "neon_xhigh_keywords",
    "opus_forensic_keywords",
    "specialist_subagents",
)

_MODEL_FIELDS: frozenset[str] = frozenset({
    "carbon",
    "neon_xhigh",
    "neon_high",
    "sonnet_high",
    "sonnet_low",
    "hydrogen_high",
    "hydrogen_low",
    "opus",
})

_MODEL_ROLE_ALIASES: dict[str, str] = {
    "architect": "carbon",
    "builder_xhigh": "neon_xhigh",
    "builder_high": "neon_high",
    "grunt_high": "sonnet_high",
    "grunt_low": "sonnet_low",
    "failover_grunt_high": "hydrogen_high",
    "failover_grunt_low": "hydrogen_low",
    "forensic": "opus",
}

_INT_THRESHOLD_FIELDS: frozenset[str] = frozenset({
    "max_inline_edits_lean",
    "max_inline_batches_lean",
    "max_inline_edits_heavy",
    "max_inline_batches_heavy",
    "heavy_transcript_bytes",
    "transcript_quota_scan_bytes",
    "opus_spec_len_max",
    "state_ttl_seconds",
})

_FLOAT_THRESHOLD_FIELDS: frozenset[str] = frozenset({
    "quota_cache_ttl_seconds",
    "legacy_exhausted_grace_seconds",
    "claude_exhausted_threshold",
    "gemini_min_fallback_quota",
    "gemini_healthy_specialist_quota",
    "gemini_neon_xhigh_floor",
})


@dataclass(frozen=True)
class ModelPool:
    """Canonical model identifiers and role-slot accessors for each stage of the Alloy stack."""

    carbon: str = "gemini-4-carbon-high"
    neon_xhigh: str = "gemini-4-neon-xhigh"
    neon_high: str = "gemini-4-neon-high"
    sonnet_high: str = "claude-sonnet-5-5-high"
    sonnet_low: str = "claude-sonnet-5-5-low"
    hydrogen_high: str = "gemini-4-hydrogen-high"
    hydrogen_low: str = "gemini-4-hydrogen-low"
    opus: str = "claude-opus-5-5-high"

    @property
    def architect(self) -> str:
        """Role-slot alias for the Architect / Gatekeeper model."""
        return self.carbon

    @property
    def builder_xhigh(self) -> str:
        """Role-slot alias for the primary high-capacity code builder & 1M research partner."""
        return self.neon_xhigh

    @property
    def builder_high(self) -> str:
        """Role-slot alias for the light-module code builder."""
        return self.neon_high

    @property
    def grunt_high(self) -> str:
        """Role-slot alias for the primary plumbing / verification grunt model."""
        return self.sonnet_high

    @property
    def grunt_low(self) -> str:
        """Role-slot alias for the mechanical / commit / monitor grunt model."""
        return self.sonnet_low

    @property
    def failover_grunt_high(self) -> str:
        """Role-slot alias for the failover plumbing grunt model when primary grunt quota is exhausted."""
        return self.hydrogen_high

    @property
    def failover_grunt_low(self) -> str:
        """Role-slot alias for the failover mechanical grunt model when primary grunt quota is exhausted."""
        return self.hydrogen_low

    @property
    def forensic(self) -> str:
        """Role-slot alias for the gated unspec'd root-cause specialist."""
        return self.opus


MODEL_PRESETS: dict[str, ModelPool] = {
    "antigravity": ModelPool(),
    "claude-code": ModelPool(
        carbon="opus",
        neon_xhigh="sonnet",
        neon_high="sonnet",
        sonnet_high="sonnet",
        sonnet_low="haiku",
        hydrogen_high="haiku",
        hydrogen_low="haiku",
        opus="opus",
    ),
    "multi-provider": ModelPool(
        carbon="o3",
        neon_xhigh="gemini-2.5-pro",
        neon_high="gemini-2.5-pro",
        sonnet_high="claude-sonnet-4-5",
        sonnet_low="claude-haiku-4-5",
        hydrogen_high="gemini-2.5-flash",
        hydrogen_low="gemini-2.5-flash",
        opus="claude-opus-4-6",
    ),
}


@dataclass(frozen=True)
class Thresholds:
    """Numeric thresholds controlling edit caps, quota floors, and scan windows."""

    max_inline_edits_lean: int = 5
    max_inline_batches_lean: int = 2
    max_inline_edits_heavy: int = 4
    max_inline_batches_heavy: int = 1
    heavy_transcript_bytes: int = 1_000_000
    transcript_quota_scan_bytes: int = 8_388_608
    opus_spec_len_max: int = 1800
    state_ttl_seconds: int = 21600
    quota_cache_ttl_seconds: float = 30.0
    legacy_exhausted_grace_seconds: float = 1800.0
    claude_exhausted_threshold: float = 0.02
    gemini_min_fallback_quota: float = 0.05
    gemini_healthy_specialist_quota: float = 0.15
    gemini_neon_xhigh_floor: float = 0.20


@dataclass(frozen=True)
class RouterConfig:
    """Complete immutable configuration for routing, quota polling, and guards."""

    models: ModelPool = ModelPool()
    thresholds: Thresholds = Thresholds()
    preset: str = "antigravity"
    light_grunt_keywords: tuple[str, ...] = DEFAULT_LIGHT_GRUNT_KEYWORDS
    plumbing_name_tokens: tuple[str, ...] = DEFAULT_PLUMBING_NAME_TOKENS
    plumbing_grunt_keywords: tuple[str, ...] = DEFAULT_PLUMBING_GRUNT_KEYWORDS
    core_code_build_keywords: tuple[str, ...] = DEFAULT_CORE_CODE_BUILD_KEYWORDS
    carbon_spec_research_audit_keywords: tuple[str, ...] = DEFAULT_CARBON_SPEC_RESEARCH_AUDIT_KEYWORDS
    carbon_code_loop_markers: tuple[str, ...] = DEFAULT_CARBON_CODE_LOOP_MARKERS
    neon_xhigh_keywords: tuple[str, ...] = DEFAULT_NEON_XHIGH_KEYWORDS
    opus_forensic_keywords: tuple[str, ...] = DEFAULT_OPUS_FORENSIC_KEYWORDS
    specialist_subagents: tuple[str, ...] = DEFAULT_SPECIALIST_SUBAGENTS
    sources: tuple[str, ...] = ("defaults",)

    @classmethod
    def default(cls, preset: str = "antigravity") -> RouterConfig:
        """Return a fresh default configuration instance for a named preset."""
        norm = preset.strip().lower() if preset else "antigravity"
        if norm in MODEL_PRESETS:
            return cls(models=MODEL_PRESETS[norm], preset=norm)
        return cls()


AlloyConfig = RouterConfig


def _union_keywords(existing: tuple[str, ...], additions: Any) -> tuple[str, ...]:
    """Union lowercase keyword strings preserving order without duplicates."""
    if not isinstance(additions, list):
        return existing
    seen: set[str] = set(existing)
    merged: list[str] = list(existing)
    for item in additions:
        if not isinstance(item, str):
            continue
        norm = item.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            merged.append(norm)
    return tuple(merged)


def _merge_override(
    cfg: RouterConfig,
    raw: dict[str, Any],
    source_label: str,
    allow_preset_change: bool = True,
    allow_model_override: bool = True,
) -> RouterConfig:
    """Merge a validated JSON override dictionary into an immutable RouterConfig."""
    preset = cfg.preset
    models = cfg.models

    raw_preset = raw.get("preset")
    if allow_preset_change and isinstance(raw_preset, str):
        norm_preset = raw_preset.strip().lower()
        if norm_preset in MODEL_PRESETS:
            preset = norm_preset
            models = MODEL_PRESETS[norm_preset]

    raw_models = raw.get("models")
    if allow_model_override and isinstance(raw_models, dict):
        model_updates: dict[str, str] = {}
        for raw_key, val in raw_models.items():
            if not isinstance(raw_key, str) or not isinstance(val, str):
                continue
            canonical_key = _MODEL_ROLE_ALIASES.get(raw_key.strip().lower(), raw_key.strip().lower())
            if canonical_key in _MODEL_FIELDS and val.strip():
                model_updates[canonical_key] = val.strip()
        if model_updates:
            models = replace(models, **model_updates)

    thresholds = cfg.thresholds
    raw_thresholds = raw.get("thresholds")
    if isinstance(raw_thresholds, dict):
        int_updates: dict[str, int] = {}
        float_updates: dict[str, float] = {}
        for field_name in _INT_THRESHOLD_FIELDS:
            val = raw_thresholds.get(field_name)
            if isinstance(val, int) and not isinstance(val, bool):
                int_updates[field_name] = int(val)
        for field_name in _FLOAT_THRESHOLD_FIELDS:
            val = raw_thresholds.get(field_name)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                float_updates[field_name] = float(val)
        if int_updates or float_updates:
            thresholds = Thresholds(
                max_inline_edits_lean=int_updates.get(
                    "max_inline_edits_lean", thresholds.max_inline_edits_lean
                ),
                max_inline_batches_lean=int_updates.get(
                    "max_inline_batches_lean", thresholds.max_inline_batches_lean
                ),
                max_inline_edits_heavy=int_updates.get(
                    "max_inline_edits_heavy", thresholds.max_inline_edits_heavy
                ),
                max_inline_batches_heavy=int_updates.get(
                    "max_inline_batches_heavy", thresholds.max_inline_batches_heavy
                ),
                heavy_transcript_bytes=int_updates.get(
                    "heavy_transcript_bytes", thresholds.heavy_transcript_bytes
                ),
                transcript_quota_scan_bytes=int_updates.get(
                    "transcript_quota_scan_bytes", thresholds.transcript_quota_scan_bytes
                ),
                opus_spec_len_max=int_updates.get("opus_spec_len_max", thresholds.opus_spec_len_max),
                state_ttl_seconds=int_updates.get("state_ttl_seconds", thresholds.state_ttl_seconds),
                quota_cache_ttl_seconds=float_updates.get(
                    "quota_cache_ttl_seconds", thresholds.quota_cache_ttl_seconds
                ),
                legacy_exhausted_grace_seconds=float_updates.get(
                    "legacy_exhausted_grace_seconds", thresholds.legacy_exhausted_grace_seconds
                ),
                claude_exhausted_threshold=float_updates.get(
                    "claude_exhausted_threshold", thresholds.claude_exhausted_threshold
                ),
                gemini_min_fallback_quota=float_updates.get(
                    "gemini_min_fallback_quota", thresholds.gemini_min_fallback_quota
                ),
                gemini_healthy_specialist_quota=float_updates.get(
                    "gemini_healthy_specialist_quota", thresholds.gemini_healthy_specialist_quota
                ),
                gemini_neon_xhigh_floor=float_updates.get(
                    "gemini_neon_xhigh_floor", thresholds.gemini_neon_xhigh_floor
                ),
            )

    kw_updates: dict[str, tuple[str, ...]] = {}
    for field_name in _KEYWORD_FIELDS:
        if field_name in raw:
            kw_updates[field_name] = _union_keywords(getattr(cfg, field_name), raw.get(field_name))

    return replace(
        cfg,
        models=models,
        thresholds=thresholds,
        preset=preset,
        sources=cfg.sources + (source_label,),
        **kw_updates,
    )


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    """Read a JSON object from disk, failing open to None on OSError or invalid JSON."""
    try:
        if not path.is_file():
            return None
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    except (OSError, ValueError):
        return None
    return None


def _global_config_candidates() -> list[tuple[Path, bool]]:
    """Resolve global JSON override file paths as (path, is_explicit) tuples."""
    explicit = (
        os.environ.get("MODEL_ROUTER_CONFIG_PATH", "").strip()
        or os.environ.get("AGY_ROUTER_CONFIG_PATH", "").strip()
    )
    if explicit:
        if explicit.lower() == "none":
            return []
        return [(Path(explicit).expanduser(), True)]

    if (
        os.environ.get("MODEL_ROUTER_DISABLE_GLOBAL_CONFIG", "").strip() == "1"
        or os.environ.get("AGY_ROUTER_DISABLE_GLOBAL_CONFIG", "").strip() == "1"
    ):
        return []

    candidates: list[tuple[Path, bool]] = []
    plugin_data = os.environ.get("PLUGIN_DATA", "").strip()
    if plugin_data:
        pd = Path(plugin_data).expanduser()
        candidates.append((pd / "alloy.json", False))
        candidates.append((pd / "model-router.json", False))
    try:
        home_cfg = Path.home() / ".gemini" / "config"
        candidates.append((home_cfg / "alloy.json", False))
        candidates.append((home_cfg / "model-router.json", False))
    except (OSError, RuntimeError):
        pass
    return candidates


def _workspace_config_candidates(cwd: str = "", workspace_paths: Sequence[str] = ()) -> list[Path]:
    """Walk upward from cwd or workspace_paths[0] up to .git (inclusive) for workspace configs."""
    start_raw = cwd.strip() if cwd else ""
    if not start_raw:
        for wp in workspace_paths:
            if isinstance(wp, str) and wp.strip():
                start_raw = wp.strip()
                break
    if not start_raw:
        return []

    try:
        start_path = Path(start_raw).expanduser()
        if start_path.exists():
            current = start_path.resolve() if start_path.is_dir() else start_path.parent.resolve()
        else:
            current = start_path
    except OSError:
        return []

    levels_bottom_up: list[list[Path]] = []
    visited: set[Path] = set()
    while current not in visited:
        visited.add(current)
        level_hits: list[Path] = []
        # Merge alloy.json before model-router.json at the same directory so model-router.json wins.
        for filename in ("alloy.json", "model-router.json"):
            candidate = current / ".agents" / filename
            try:
                if candidate.is_file():
                    level_hits.append(candidate)
            except OSError:
                continue
        if level_hits:
            levels_bottom_up.append(level_hits)
        try:
            has_git = (current / ".git").exists()
        except OSError:
            break
        if has_git:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    levels_bottom_up.reverse()
    out: list[Path] = []
    for level_hits in levels_bottom_up:
        out.extend(level_hits)
    return out


def load_config(
    cwd: str = "",
    workspace_paths: Sequence[str] = (),
    preset_override: str = "",
) -> RouterConfig:
    """Load default RouterConfig merged with optional global, workspace, and preset overrides."""
    norm_override = preset_override.strip().lower() if preset_override else ""
    has_preset_override = norm_override in MODEL_PRESETS
    cfg = RouterConfig.default(norm_override if has_preset_override else "antigravity")
    seen_resolved: set[str] = set()

    ordered_paths: list[tuple[Path, bool]] = list(_global_config_candidates())
    for wp in _workspace_config_candidates(cwd, workspace_paths):
        ordered_paths.append((wp, True))

    for path, is_explicit_or_workspace in ordered_paths:
        try:
            key = str(path.resolve()) if path.exists() else str(path)
        except OSError:
            key = str(path)
        if key in seen_resolved:
            continue
        raw = _read_json_dict(path)
        if raw is None:
            continue
        seen_resolved.add(key)

        # When CLI explicitly specifies --preset, do not let an implicit global file for a different
        # preset overwrite the requested preset's ModelPool.
        raw_preset = str(raw.get("preset") or "").strip().lower()
        allow_models = True
        if has_preset_override and not is_explicit_or_workspace:
            allow_models = raw_preset == norm_override

        cfg = _merge_override(
            cfg,
            raw,
            str(path),
            allow_preset_change=not has_preset_override,
            allow_model_override=allow_models,
        )

    return cfg


def _uid_tag() -> str:
    """Return a cross-platform per-user tag for fallback temp files."""
    if hasattr(os, "getuid"):
        return str(os.getuid())
    try:
        import getpass

        return getpass.getuser()
    except Exception:
        return "user"


def _resolve_state_path(env_vars: tuple[str, ...], filename: str, tmp_prefix: str) -> Path:
    """Resolve persistent cache/state path across env overrides, PLUGIN_DATA, home cache, or tempdir."""
    for env_var in env_vars:
        custom = os.environ.get(env_var, "").strip()
        if custom:
            return Path(custom).expanduser()

    plugin_data = os.environ.get("PLUGIN_DATA", "").strip()
    if plugin_data:
        return Path(plugin_data).expanduser() / filename

    try:
        cache_dir = Path.home() / ".gemini" / "antigravity" / "cache" / "model_router"
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(cache_dir, 0o700)
        except OSError:
            pass
        if os.access(cache_dir, os.W_OK):
            return cache_dir / filename
    except (OSError, RuntimeError):
        pass

    return Path(tempfile.gettempdir()) / f"{tmp_prefix}_{_uid_tag()}.json"


def quota_cache_path() -> Path:
    """Return the cross-platform path for the shared quota cache JSON."""
    return _resolve_state_path(
        ("MODEL_ROUTER_QUOTA_CACHE_PATH", "AGY_ROUTER_QUOTA_CACHE_PATH"),
        "quota_cache.json",
        "model_router_quota_cache",
    )


def turn_edits_state_path() -> Path:
    """Return the cross-platform path for the inline edit-budget state JSON."""
    return _resolve_state_path(
        ("MODEL_ROUTER_EDIT_STATE_PATH", "AGY_ROUTER_EDIT_STATE_PATH"),
        "turn_edits.json",
        "model_router_turn_edits",
    )
