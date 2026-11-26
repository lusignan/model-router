"""Code-span masking, header tag extraction, and negation-safe text scrubbing."""
from __future__ import annotations

import re

_CODE_SPAN_RE = re.compile(r"```.*?```|`[^`]*`", re.DOTALL)

BYPASS_TURN_FLAGS: frozenset[str] = frozenset({
    "[allow-gemini]",
    "[inline-gemini]",
    "[allow-inline]",
    "[bypass-router]",
})

EXHAUSTED_FLAGS: frozenset[str] = frozenset({
    "[claude-exhausted]",
    "[primary-exhausted]",
})

EXCLUSIVITY_FLAGS: frozenset[str] = frozenset({
    "[carbon-neon]",
    "[architect-builder-only]",
})

_WORKER_TAG_RE = re.compile(
    r"\[(?:grunt-low|grunt"
    r"|neon-kernel|neon-research|neon-dyad|neon"
    r"|builder-xhigh|builder-research|builder-dyad|builder"
    r"|carbon-build|carbon-dyad|carbon-neon|carbon"
    r"|architect-build|architect-dyad|architect-builder-only|architect"
    r"|dyad|opus|forensic|sonnet|claude-exhausted|primary-exhausted)\]",
    re.IGNORECASE,
)

_TURN_FLAG_RE = re.compile(
    r"\[(?:allow-gemini|inline-gemini|allow-inline|bypass-router"
    r"|claude-exhausted|primary-exhausted"
    r"|carbon-neon|architect-builder-only|dyad)\]",
    re.IGNORECASE,
)

_CARBON_NEON_PHRASE_RE = re.compile(
    r"\b(?:carbon\s*(?:and|\+|&|/)\s*neon|architect\s*(?:and|\+|&|/)\s*builder)\s+exclusively\b",
    re.IGNORECASE,
)

_TOOL_OR_PATCH_TERM = (
    r"(?:edit_file|write_file|replace_file_content|multi_replace_file_content"
    r"|write_to_file|file\s+edits?|patches\b|patch\b)"
)

_NEGATED_CODING_RE = re.compile(
    r"\b(?:do\s+not|don't|never|must\s+not|without|forbid\w*|prohibit\w*|avoid|no)\s+"
    r"(?:call\w*|us\w*|run\w*|invok\w*|mak\w*|perform\w*|apply\w*|touch\w*)?\s*"
    r"(?:any\s+)?"
    + _TOOL_OR_PATCH_TERM
    + r"(?:\s*(?:,|/|\bor\b|\band\b|\bnor\b)\s*"
    + _TOOL_OR_PATCH_TERM
    + r")*",
    re.IGNORECASE,
)

_AUDIT_PATCH_NOUN_RE = re.compile(
    r"\b(?:audit\w*|review\w*|inspect\w*|verif\w*|check\w*|red-team\w*"
    r"|evaluat\w*|diagnos\w*|critiqu\w*)\s+(?:the\s+|this\s+|each\s+|all\s+)?patch(?:es)?\b",
    re.IGNORECASE,
)


def strip_code_spans(text: str) -> str:
    """Strip fenced (```...```) and inline (`...`) markdown code spans."""
    return _CODE_SPAN_RE.sub(" ", text or "")


def mask_code_spans(text: str) -> str:
    """Blank markdown code spans while preserving character offsets and line breaks."""
    return _CODE_SPAN_RE.sub(
        lambda m: "".join("\n" if ch == "\n" else " " for ch in m.group(0)),
        text or "",
    )


def scrub_negated_coding_markers(text: str) -> str:
    """Neutralize negated edit/tool prohibitions and audit/review noun phrases referencing patches."""
    if not text:
        return ""
    scrubbed = _NEGATED_CODING_RE.sub(" ", text)
    return _AUDIT_PATCH_NOUN_RE.sub(" ", scrubbed)


def extract_worker_tags(worker_name: str, brief: str) -> set[str]:
    """Extract explicit worker role tags from worker_name + brief header (first non-empty line / 240 chars)."""
    clean_name = strip_code_spans(worker_name)
    raw_stripped = (brief or "").lstrip()
    masked_brief = mask_code_spans(raw_stripped)
    head_window = masked_brief[:240]
    first_line = ""
    if "\n" in raw_stripped:
        first_raw_line = next((ln for ln in raw_stripped.splitlines() if ln.strip()), "")
        first_line = strip_code_spans(first_raw_line)[:240]
    header_text = f"{clean_name}\n{first_line}\n{head_window}".lower()
    return {m.lower() for m in _WORKER_TAG_RE.findall(header_text)}


def extract_turn_flags(last_input: str) -> set[str]:
    """Extract turn-level escape flags from last_input (never worker role tags or code spans)."""
    clean_input = strip_code_spans(last_input).lower()
    return {m.lower() for m in _TURN_FLAG_RE.findall(clean_input)}


def is_carbon_neon_exclusive(
    worker_tags: set[str],
    turn_flags: set[str],
    last_input: str,
    brief: str,
) -> bool:
    """Return True when the user or worker header explicitly requests strict Architect/Builder exclusivity."""
    if (worker_tags & EXCLUSIVITY_FLAGS) or (turn_flags & EXCLUSIVITY_FLAGS):
        return True
    clean_in = strip_code_spans(last_input)
    if clean_in and _CARBON_NEON_PHRASE_RE.search(clean_in):
        return True
    clean_brief_head = strip_code_spans((brief or "").lstrip())[:400]
    return bool(clean_brief_head and _CARBON_NEON_PHRASE_RE.search(clean_brief_head))
