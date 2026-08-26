"""
Expression resolver — inline harvested dataset-object definitions into MSTR
metric formula text.

Ground truth source: dossier instance payload `datasets{dsId}.att[]` entries
(subType 3077 = derived attribute) and `.mx[]` metric entries, both carrying a
native `f` formula. The MicroStrategy Model API cannot serve derived objects
(HTTP 500 `DssSubTypeAttributeDerived not supported`; dataset-local metrics are
404), so this payload is the ONLY REST surface where their definitions exist.

Design invariants (honesty guards):
  * NEVER invent a definition — unknown references stay untouched.
  * Each definition is expanded AT MOST ONCE. A reference that survives after
    its definition was already used is a cycle (self or mutual); it is left
    verbatim and reported in `unresolved`.
  * The output stays in the MSTR dialect; `IRCompilerAgent._compile_expression`
    remains the single translator to Tableau syntax.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

# [Name] or [Name]@ID / [Name]@DESC — bracketed reference form.
_BRACKETED_REF_RE = re.compile(r"\[([^\[\]]+)\](?:@(?:ID|DESC)\b)?")
# BareName@ID / BareName@DESC — MSTR writes derived refs unbracketed with an
# explicit form suffix inside definition bodies (e.g. Concat(Loss_Year@ID,…)).
_BARE_FORM_RE = re.compile(r"\b([A-Za-z_][\w ]*?)@(?:ID|DESC)\b")


@dataclass
class ResolvedExpression:
    """Outcome of resolution against harvested definitions."""

    text: str                                  # MSTR-dialect text after inlining
    chain: list = field(default_factory=list)  # [{"name","formula"}] expansion order
    unresolved: list = field(default_factory=list)  # names blocked as cycles


_AGG_DECOR_RE = re.compile(
    r"\b(Sum|Avg|Count|Min|Max|Median|Stdev|Stdevp|Var|Varp)\s*<([^<>]*)>\s*\(",
    re.IGNORECASE,
)


def _normalize_agg_decorations(text: str) -> str:
    """
    Resolve MSTR `Agg<params>(…)` decorations at ANY depth (inlined bodies
    nest them). Semantics-aware:
      * Count<…Distinct=True…>( → COUNTD(   (the flag IS the meaning)
      * everything else          → plain AGG(  (VLDB hints like
        UseLookupForAttributes carry no Tableau meaning)
    """

    def _repl(m: "re.Match") -> str:
        fn, params = m.group(1), m.group(2) or ""
        if fn.lower() == "count" and re.search(r"distinct\s*=\s*true", params, re.I):
            return "COUNTD("
        return f"{fn.upper()}("

    prev = None
    while prev != text:                      # nested Agg<Agg<…>>> forms unwrap left-to-right
        prev = text
        text = _AGG_DECOR_RE.sub(_repl, text)
    # Estate convention (matches the accepted workbook + cache): plain Count()
    # stays COUNT — only an explicit Distinct=True decoration promotes to
    # COUNTD. 'Count (Claim ID)' is COUNT; 'States'/'Claim_Count_2' are COUNTD.
    # any leftover angle hints (non-aggregation positions)
    return re.sub(r"<[^<>]*>", "", text)


def _substitute(body: str) -> str:
    """Wrap a definition body for safe splicing into an outer expression."""
    b = body.strip()
    b = re.sub(r"\{[^{}]*\}", "", b).strip()   # drop dimty fragments anywhere
    # Call-shape probe must ignore VLDB hints sitting between the function
    # name and its parenthesis: Count<hints>(…) is still a call.
    probe = re.sub(r"<[^<>]*>", "", b)
    if probe.startswith("(") or re.match(r"^[A-Za-z_]\w*\s*\(", probe):
        return b          # already grouped or a call — splice verbatim
    return f"({b})"       # arithmetic bodies need grouping: A - B → (A - B)


def resolve_expression(
    text: str,
    defs_by_did: Optional[dict] = None,
    defs_by_name_lower: Optional[dict] = None,
    *,
    max_depth: int = 8,
) -> ResolvedExpression:
    """
    Inline dataset-derived object definitions into `text` (MSTR dialect).

    defs_by_did:        {did: {"name": str, "formula": str, ...}}
    defs_by_name_lower: {"high fraud flag": {...}, ...}   (same records)
    """
    defs_by_did = defs_by_did or {}
    defs_by_name_lower = defs_by_name_lower or {}

    out = text or ""
    chain: list = []
    seen: set = set()
    unresolved: list = []

    def _lookup(name: str):
        return defs_by_name_lower.get(name.strip().lower())

    def _expand(name: str) -> Optional[str]:
        """Return replacement body for `name`, or None to keep the ref."""
        d = _lookup(name)
        if d is None:
            return None                      # not ours — physical ref / foreign
        key = name.strip().lower()
        if key in seen:
            if key not in unresolved:
                unresolved.append(key)       # cycle: already expanded once
            return None
        seen.add(key)
        body = d["formula"]
        chain.append({"name": d.get("name") or name.strip(), "formula": body})
        return _substitute(body)

    for _pass in range(max_depth):
        before = out

        # 1. Bracketed refs: [High Fraud Flag] / [Net Loss]@ID …
        def _repl_bracketed(m: "re.Match") -> str:
            if _lookup(m.group(1)) is None:
                return m.group(0)
            repl = _expand(m.group(1))
            return repl if repl is not None else m.group(0)

        out = _BRACKETED_REF_RE.sub(_repl_bracketed, out)

        # 2. Bare@FORM refs inside definition bodies: Loss_Year@ID …
        def _repl_bare_form(m: "re.Match") -> str:
            repl = _expand(m.group(1))
            return repl if repl is not None else m.group(0)

        out = _BARE_FORM_RE.sub(_repl_bare_form, out)

        # 3. Bare tokens matching a definition name exactly (ratio denominators).
        for lname, d in list(defs_by_name_lower.items()):
            rx = re.compile(r"(?<![\[@\w])" + re.escape(d.get("name") or lname) + r"\b(?!\])")
            out = rx.sub(lambda nm: (_expand(nm.group(0)) or nm.group(0)), out)

        if out == before:
            break   # fixpoint

    return ResolvedExpression(
        text=_normalize_agg_decorations(out), chain=chain, unresolved=unresolved,
    )
