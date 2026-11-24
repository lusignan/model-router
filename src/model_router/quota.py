"""Dual-window resetTime-aware quota polling, caching, and PostToolUse flush-race state machine."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import RouterConfig, quota_cache_path

QUOTA_ERROR_MARKERS: tuple[str, ...] = (
    "resource_exhausted",
    "quota",
    "rate limit",
    "rate_limit",
    "429",
    "too many requests",
)

_CLAUDE_OR_THIRD_PARTY_MODEL_TOKENS: tuple[str, ...] = (
    "claude",
    "sonnet",
    "opus",
    "haiku",
    "gpt",
)

_ISO_FRAC_RE = re.compile(r"\.(\d+)(?=[+-]\d\d:\d\d$)")
_UNTIL_ISO_RE = re.compile(
    r"until\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))",
    re.IGNORECASE,
)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON to path via a sibling temp file and os.replace."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}_", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        os.replace(tmp_name, path)
    except OSError:
        pass


def parse_iso_utc(raw: str) -> float | None:
    """Parse an ISO-8601 timestamp (including trailing 'Z' on Python 3.9) into UTC epoch seconds."""
    s = raw.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    s = _ISO_FRAC_RE.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), s)
    try:
        parsed = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return float(parsed.timestamp())


def parse_pct_fraction(raw: Any) -> float | None:
    """Parse a percentage string ('55%') or fractional float ('0.55') into [0.0, 1.0]."""
    s = str(raw or "").strip()
    if not s:
        return None
    if s.endswith("%"):
        s = s[:-1].strip()
        try:
            return float(s) / 100.0
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _env_first(*names: str) -> str:
    for name in names:
        val = os.environ.get(name)
        if val is not None and val.strip() != "":
            return val.strip()
    return ""


def candidate_full_transcripts(transcript_path: str, now: float) -> list[Path]:
    """Collect active and recently modified transcript_full.jsonl paths for clean hook-env quota sensing."""
    seen: set[str] = set()
    out: list[Path] = []

    if transcript_path:
        tp = Path(transcript_path).expanduser()
        for cand in (tp.with_name("transcript_full.jsonl"), tp):
            key = str(cand)
            if key not in seen and cand.is_file():
                seen.add(key)
                out.append(cand)

    brain_override = _env_first("MODEL_ROUTER_BRAIN_DIR", "AGY_ROUTER_BRAIN_DIR")
    if brain_override:
        brain_dir: Path | None = Path(brain_override).expanduser()
    elif transcript_path and "/brain/" in transcript_path:
        prefix = transcript_path.split("/brain/", 1)[0]
        brain_dir = Path(prefix) / "brain"
    else:
        try:
            brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
        except (OSError, RuntimeError):
            brain_dir = None

    if brain_dir is not None and brain_dir.is_dir():
        recent: list[tuple[float, Path]] = []
        try:
            for sub in brain_dir.iterdir():
                cand = sub / ".system_generated" / "logs" / "transcript_full.jsonl"
                try:
                    st = cand.stat()
                except OSError:
                    continue
                if (now - st.st_mtime) <= 86400.0:
                    recent.append((st.st_mtime, cand))
        except OSError:
            recent = []
        recent.sort(key=lambda item: item[0], reverse=True)
        for _, cand in recent[:6]:
            key = str(cand)
            if key not in seen:
                seen.add(key)
                out.append(cand)
    return out


def poll_transcripts_for_quota(
    transcript_path: str,
    now: float,
    cfg: RouterConfig | None = None,
    min_step_ts: float = 0.0,
) -> dict[str, Any] | None:
    """Extract the newest swarm(action='models') quota snapshot from recent transcript tails."""
    conf = cfg or RouterConfig.default()
    th = conf.thresholds
    best: dict[str, Any] | None = None
    best_ts = min_step_ts

    for cand in candidate_full_transcripts(transcript_path, now):
        try:
            size = cand.stat().st_size
            if size <= 0:
                continue
            with cand.open("rb") as fh:
                offset = max(0, size - th.transcript_quota_scan_bytes)
                fh.seek(offset)
                chunk = fh.read(size - offset).decode("utf-8", errors="ignore")
        except OSError:
            continue

        lines = chunk.splitlines()
        if offset > 0 and lines:
            lines = lines[1:]

        for line in reversed(lines):
            if "quotas" not in line or "quota_remaining" not in line:
                continue
            try:
                step_obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(step_obj, dict):
                continue
            step_ts = parse_iso_utc(str(step_obj.get("created_at") or "")) or 0.0
            if step_ts <= best_ts:
                continue
            content = str(step_obj.get("content") or "")
            for subline in content.splitlines():
                sub = subline.strip()
                if not (sub.startswith("{") and '"quotas"' in sub):
                    continue
                try:
                    q_obj = json.loads(sub)
                except ValueError:
                    continue
                if not (
                    isinstance(q_obj, dict)
                    and isinstance(q_obj.get("models"), list)
                    and isinstance(q_obj.get("display_names"), dict)
                    and isinstance(q_obj.get("quotas"), dict)
                ):
                    continue
                quotas = q_obj["quotas"]
                if not quotas:
                    continue

                claude_vals: list[float] = []
                claude_resets: list[float] = []
                gemini_vals: list[float] = []
                gemini_resets: list[float] = []
                for m_id, qinfo in quotas.items():
                    if not isinstance(qinfo, dict):
                        continue
                    rem = parse_pct_fraction(qinfo.get("quota_remaining"))
                    if rem is None:
                        continue
                    rst = parse_iso_utc(str(qinfo.get("quota_resets") or ""))
                    low_id = str(m_id).lower()
                    if "claude" in low_id:
                        claude_vals.append(rem)
                        if rst is not None:
                            claude_resets.append(rst)
                    elif "gemini" in low_id and "flash" not in low_id:
                        gemini_vals.append(rem)
                        if rst is not None:
                            gemini_resets.append(rst)

                if not claude_vals or not gemini_vals:
                    continue

                claude_rem = max(claude_vals)
                gemini_rem = max(gemini_vals)
                claude_reset_ts = max(claude_resets) if claude_resets else None
                gemini_reset_ts = max(gemini_resets) if gemini_resets else None
                exhausted = (
                    claude_rem <= th.claude_exhausted_threshold
                    and gemini_rem > th.gemini_min_fallback_quota
                    and (
                        (claude_reset_ts is not None and now < claude_reset_ts)
                        or (claude_reset_ts is None and (now - step_ts) <= th.legacy_exhausted_grace_seconds)
                    )
                )
                best_ts = step_ts
                best = {
                    "ts": step_ts,
                    "step_ts": step_ts,
                    "exhausted": exhausted,
                    "claude_rem": claude_rem,
                    "claude_reset_ts": claude_reset_ts,
                    "gemini_rem": gemini_rem,
                    "gemini_reset_ts": gemini_reset_ts,
                    "source": "transcript",
                }
                break
    return best


def poll_ls_for_quota(
    addr: str,
    tok: str,
    now: float,
    cfg: RouterConfig | None = None,
) -> dict[str, Any] | None:
    """Poll GetCascadeModelConfigData when ANTIGRAVITY_LS_* env vars are available."""
    conf = cfg or RouterConfig.default()
    th = conf.thresholds
    import urllib.request

    try:
        req = urllib.request.Request(
            f"http://{addr}/exa.language_server_pb.LanguageServerService/GetCascadeModelConfigData",
            data=b"{}",
            headers={"Content-Type": "application/json", "x-codeium-csrf-token": tok},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None

    cfgs = payload.get("clientModelConfigs")
    if not isinstance(cfgs, list) or not cfgs:
        return None

    claude_vals: list[float] = []
    claude_resets: list[float] = []
    gemini_vals: list[float] = []
    gemini_resets: list[float] = []
    for item in cfgs:
        if not isinstance(item, dict):
            continue
        lbl = str(item.get("label") or "").lower()
        qi = item.get("quotaInfo")
        rem = float((qi or {}).get("remainingFraction", 0.0)) if isinstance(qi, dict) else 0.0
        rst = parse_iso_utc(str((qi or {}).get("resetTime") or "")) if isinstance(qi, dict) else None
        if "claude" in lbl:
            claude_vals.append(rem)
            if rst is not None:
                claude_resets.append(rst)
        elif "gemini" in lbl and "flash" not in lbl:
            gemini_vals.append(rem)
            if rst is not None:
                gemini_resets.append(rst)

    if not claude_vals or not gemini_vals:
        return None

    claude_rem = max(claude_vals)
    gemini_rem = max(gemini_vals)
    claude_reset_ts = max(claude_resets) if claude_resets else None
    gemini_reset_ts = max(gemini_resets) if gemini_resets else None
    exhausted = (
        claude_rem <= th.claude_exhausted_threshold
        and gemini_rem > th.gemini_min_fallback_quota
        and (claude_reset_ts is None or now < claude_reset_ts)
    )
    return {
        "addr": addr,
        "ts": now,
        "exhausted": exhausted,
        "claude_rem": claude_rem,
        "claude_reset_ts": claude_reset_ts,
        "gemini_rem": gemini_rem,
        "gemini_reset_ts": gemini_reset_ts,
        "source": "ls",
    }


def cached_exhaustion_still_valid(
    cached: dict[str, Any],
    now: float,
    cfg: RouterConfig | None = None,
) -> bool | None:
    """Check whether cached exhaustion state remains authoritative when LS polling is unavailable."""
    conf = cfg or RouterConfig.default()
    if not bool(cached.get("exhausted", False)):
        return None
    raw_rst = cached.get("claude_reset_ts")
    if isinstance(raw_rst, (int, float)) and not isinstance(raw_rst, bool) and float(raw_rst) > 0:
        if now < float(raw_rst):
            return True
        return False
    ts = cached.get("ts")
    if (
        isinstance(ts, (int, float))
        and not isinstance(ts, bool)
        and 0.0 <= (now - float(ts)) <= conf.thresholds.legacy_exhausted_grace_seconds
    ):
        return True
    return None


def read_quota_cache(cache_file: Path | None = None) -> dict[str, Any] | None:
    """Read cached quota JSON dictionary if present and valid."""
    target = cache_file or quota_cache_path()
    try:
        if target.exists():
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
    except (OSError, ValueError):
        pass
    return None


def gemini_remaining_fraction(
    override: float | None = None,
    cache_file: Path | None = None,
) -> float:
    """Return explicit, env-overridden, or cached Gemini remaining quota fraction (defaults to 1.0)."""
    if override is not None:
        return float(override)
    env_gem = _env_first("MODEL_ROUTER_GEMINI_QUOTA", "AGY_ROUTER_GEMINI_QUOTA")
    if env_gem:
        try:
            return float(env_gem)
        except ValueError:
            pass
    cached = read_quota_cache(cache_file)
    if cached is not None:
        raw_rem = cached.get("gemini_rem")
        if isinstance(raw_rem, (int, float)) and not isinstance(raw_rem, bool):
            return float(raw_rem)
    return 1.0


def gemini_headroom_ok(
    cfg: RouterConfig | None = None,
    floor: float | None = None,
    gemini_quota_override: float | None = None,
    cache_file: Path | None = None,
) -> bool:
    """Return True unless Gemini quota is known to be below `floor`."""
    conf = cfg or RouterConfig.default()
    target_floor = conf.thresholds.gemini_healthy_specialist_quota if floor is None else floor
    return gemini_remaining_fraction(override=gemini_quota_override, cache_file=cache_file) >= target_floor


def claude_pool_exhausted(
    transcript_path: str = "",
    now: float | None = None,
    cfg: RouterConfig | None = None,
    claude_quota_override: float | None = None,
    cache_file: Path | None = None,
) -> bool:
    """Detect whether the Third-Party/Claude bucket is exhausted while Gemini has headroom."""
    conf = cfg or RouterConfig.default()
    th = conf.thresholds

    if claude_quota_override is not None:
        return float(claude_quota_override) <= th.claude_exhausted_threshold

    env_override = _env_first("MODEL_ROUTER_CLAUDE_QUOTA", "AGY_ROUTER_CLAUDE_QUOTA")
    if env_override:
        try:
            return float(env_override) <= th.claude_exhausted_threshold
        except ValueError:
            pass

    if now is None:
        now = time.time()

    target_cache = cache_file or quota_cache_path()
    cached = read_quota_cache(target_cache)

    if cached is not None and isinstance(cached.get("ts"), (int, float)) and not isinstance(cached.get("ts"), bool):
        raw_rst = cached.get("claude_reset_ts")
        reset_passed = (
            bool(cached.get("exhausted", False))
            and isinstance(raw_rst, (int, float))
            and not isinstance(raw_rst, bool)
            and float(raw_rst) > 0
            and now >= float(raw_rst)
        )
        age = now - float(cached["ts"])
        if not reset_passed and 0.0 <= age <= th.quota_cache_ttl_seconds:
            return bool(cached.get("exhausted", False))

    addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS", "").strip()
    tok = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "").strip()
    if addr and tok:
        ls_snap = poll_ls_for_quota(addr, tok, now, conf)
        if ls_snap is not None:
            # LS GetCascadeModelConfigData reports the 5h window and omits weekly Claude caps
            # enforced by swarm(models). Never clear an active swarm/weekly exhaustion before claude_reset_ts.
            if (
                not bool(ls_snap["exhausted"])
                and cached is not None
                and cached.get("source") in ("transcript", "post_tool_error")
                and cached_exhaustion_still_valid(cached, now, conf) is True
            ):
                merged = dict(cached)
                merged["gemini_rem"] = ls_snap["gemini_rem"]
                merged["gemini_reset_ts"] = ls_snap["gemini_reset_ts"]
                merged["ts"] = now
                atomic_write_json(target_cache, merged)
                return True
            ls_out = dict(ls_snap)
            if (
                cached is not None
                and isinstance(cached.get("step_ts"), (int, float))
                and not isinstance(cached.get("step_ts"), bool)
            ):
                ls_out["step_ts"] = float(cached["step_ts"])
            atomic_write_json(target_cache, ls_out)
            return bool(ls_snap["exhausted"])

    min_ts = 0.0
    if cached is not None:
        raw_step_ts = cached.get("step_ts")
        if isinstance(raw_step_ts, (int, float)) and not isinstance(raw_step_ts, bool):
            min_ts = float(raw_step_ts)
        raw_err_ts = cached.get("error_ts")
        if (
            cached.get("source") == "post_tool_error"
            and cached_exhaustion_still_valid(cached, now, conf) is True
            and isinstance(raw_err_ts, (int, float))
            and not isinstance(raw_err_ts, bool)
        ):
            min_ts = max(min_ts, float(raw_err_ts))

    tr_snap = poll_transcripts_for_quota(transcript_path, now, conf, min_step_ts=min_ts)
    if tr_snap is not None:
        out_snap = dict(tr_snap)
        out_snap["ts"] = now
        atomic_write_json(target_cache, out_snap)
        return bool(tr_snap["exhausted"])

    if cached is not None:
        still_exhausted = cached_exhaustion_still_valid(cached, now, conf)
        if still_exhausted is True:
            refreshed = dict(cached)
            refreshed["ts"] = now
            atomic_write_json(target_cache, refreshed)
            return True
        if still_exhausted is False:
            expired = dict(cached)
            expired["exhausted"] = False
            expired["ts"] = now
            atomic_write_json(target_cache, expired)
            return False
        raw_step_ts = cached.get("step_ts")
        if isinstance(raw_step_ts, (int, float)) and not isinstance(raw_step_ts, bool):
            refreshed = dict(cached)
            refreshed["ts"] = now
            atomic_write_json(target_cache, refreshed)
            return bool(cached.get("exhausted", False))

    return False


def handle_post_tool_use(
    payload: dict[str, Any],
    cfg: RouterConfig | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Update quota cache immediately after quota errors or swarm(models) calls."""
    conf = cfg or RouterConfig.default()
    th = conf.thresholds
    cur_now = time.time() if now is None else now
    transcript_path = str(payload.get("transcriptPath") or "")
    target_cache = quota_cache_path()
    cached = read_quota_cache(target_cache)
    raw_prev_step = cached.get("step_ts") if cached is not None else None
    prev_step_ts = (
        float(raw_prev_step)
        if isinstance(raw_prev_step, (int, float)) and not isinstance(raw_prev_step, bool)
        else 0.0
    )

    tool_call = payload.get("toolCall")
    tool_name = str(tool_call.get("name") or "").strip().lower() if isinstance(tool_call, dict) else ""
    raw_args = tool_call.get("args") if isinstance(tool_call, dict) else None
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except ValueError:
            raw_args = None
    is_swarm_models = (
        "swarm" in tool_name
        and isinstance(raw_args, dict)
        and str(raw_args.get("action") or "").strip().lower() == "models"
    )

    err_raw = str(payload.get("error") or "")
    err = err_raw.lower()
    req_model = str((raw_args or {}).get("model") or "").lower() if isinstance(raw_args, dict) else ""
    is_claude_or_third_party = (not req_model) or any(
        tok in req_model for tok in _CLAUDE_OR_THIRD_PARTY_MODEL_TOKENS
    )
    if err and any(m in err for m in QUOTA_ERROR_MARKERS) and is_claude_or_third_party:
        m_until = _UNTIL_ISO_RE.search(err_raw)
        parsed_rst = parse_iso_utc(m_until.group(1)) if m_until else None
        err_snap: dict[str, Any] = {
            "ts": cur_now,
            "error_ts": cur_now,
            "exhausted": True,
            "claude_rem": 0.0,
            "claude_reset_ts": parsed_rst,
            "gemini_rem": gemini_remaining_fraction(cache_file=target_cache),
            "source": "post_tool_error",
        }
        if prev_step_ts > 0.0:
            err_snap["step_ts"] = prev_step_ts
        atomic_write_json(target_cache, err_snap)
        return {}

    tr_snap = poll_transcripts_for_quota(transcript_path, cur_now, conf, min_step_ts=prev_step_ts)
    if tr_snap is not None:
        out_snap = dict(tr_snap)
        if (
            is_swarm_models
            and prev_step_ts == 0.0
            and (cur_now - float(tr_snap["step_ts"])) > th.quota_cache_ttl_seconds
        ):
            # Cold cache during un-flushed swarm(models): preserve step_ts without arming TTL on an older step.
            out_snap["ts"] = 0.0
        else:
            out_snap["ts"] = cur_now
        atomic_write_json(target_cache, out_snap)
        return {}

    if is_swarm_models and cached is not None:
        pending = dict(cached)
        pending["ts"] = 0.0
        atomic_write_json(target_cache, pending)
        return {}

    return {}


def refresh_quota_snapshot(
    cfg: RouterConfig | None = None,
    transcript_path: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Refresh and persist a combined transcript + LS quota snapshot."""
    conf = cfg or RouterConfig.default()
    cur_now = time.time() if now is None else now
    addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS", "").strip()
    tok = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "").strip()
    tr_snap = poll_transcripts_for_quota(transcript_path, cur_now, conf)
    ls_snap = poll_ls_for_quota(addr, tok, cur_now, conf) if (addr and tok) else None
    snap: dict[str, Any] | None = dict(tr_snap) if tr_snap is not None else ls_snap
    if tr_snap is not None and snap is not None:
        snap["ts"] = cur_now
    if tr_snap is not None and ls_snap is not None and snap is not None:
        # Combine authoritative weekly/effective Claude cap from swarm(models) with live LS Gemini headroom.
        snap["gemini_rem"] = ls_snap["gemini_rem"]
        snap["gemini_reset_ts"] = ls_snap["gemini_reset_ts"]
        snap["ts"] = cur_now
    target_cache = quota_cache_path()
    if snap is not None:
        atomic_write_json(target_cache, snap)
    exhausted = claude_pool_exhausted(transcript_path=transcript_path, now=cur_now, cfg=conf)
    return {
        "exhausted": exhausted,
        "cache": str(target_cache),
        "snapshot": snap,
    }
