"""Parse raw wiki wikitext into structured records.

Deliberately small hand-rolled parsers: the wiki's markup is regular enough for the
handful of templates/tables we read, and failures surface as warnings in build output.
"""

from __future__ import annotations

import re

LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
CELL_ATTRS = re.compile(r'^\s*(?:[\w-]+\s*=\s*(?:"[^"]*"|\S+)\s*)+\|(?!\|)')
DAMAGE_TYPES = ("blunt", "slash", "pierce", "fire", "frost", "lightning", "poison", "spirit")


def strip_markup(text: str) -> str:
    """Wikitext -> plain text: links to their label, drop refs/templates/html."""
    text = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = LINK.sub(lambda m: m.group(2) or m.group(1), text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("'''", "").replace("''", "").strip()


def to_float(text: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


# --- navbox -----------------------------------------------------------------------


def weapon_titles_from_nav(text: str, classes: set[str]) -> list[tuple[str, str, str | None]]:
    """WeaponsNav -> [(page title, weapon class, subgroup e.g. 'Two-handed' or None)]."""
    out: list[tuple[str, str, str | None]] = []
    cls: str | None = None
    sub: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"\|group\d+\s*=\s*(.*)$", line)
        if m:
            value = m.group(1).strip()
            link = LINK.fullmatch(value)
            if link and raw.startswith("|"):  # top-level group (no indent) names a class
                cls, sub = link.group(1).strip(), None
            else:
                sub = strip_markup(value)
            continue
        m = re.match(r"\|list\d+\s*=\s*(.*)$", line)
        if m and cls in classes:
            for link in LINK.finditer(m.group(1)):
                out.append((link.group(1).strip(), cls, sub))
    return out


# --- generic wikitable ------------------------------------------------------------


def table_rows(table: str) -> list[list[str]]:
    """Split a {| ... |} wikitable into rows of raw cell strings (headers included)."""
    rows: list[list[str]] = []
    current: list[str] = []
    for line in table.splitlines():
        s = line.strip()
        if s.startswith("{|") or s.startswith("|}"):
            continue
        if s.startswith("|-"):
            if current:
                rows.append(current)
            current = []
            continue
        if s.startswith("!") or s.startswith("|"):
            # "!a !! b" and "|a || b" are inline multi-cell rows
            for cell in re.split(r"\|\||!!", s[1:]):
                current.append(CELL_ATTRS.sub("", cell).strip())
        elif current:
            current[-1] += "\n" + s  # continuation of a multi-line cell
    if current:
        rows.append(current)
    return rows


def find_tables(text: str) -> list[str]:
    tables, depth, start = [], 0, None
    for m in re.finditer(r"^\s*(\{\||\|\})", text, flags=re.M):
        if m.group(1) == "{|":
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                tables.append(text[start : m.end()])
    return tables


# --- stagger page -----------------------------------------------------------------


def stagger_table(text: str) -> list[dict]:
    """Rows of the 'Creature stats' table on the Stagger page."""
    section = text[text.index("==Creature stats==") :]
    table = find_tables(section)[0]
    out = []
    for row in table_rows(table)[1:]:
        if len(row) < 6:
            continue
        _, creature, duration, parried, limit, base = row[:6]
        link = LINK.search(creature)
        immune = "immune" in limit.lower()
        pct = to_float(limit)
        out.append(
            {
                "name": strip_markup(creature),
                "title": link.group(1).strip() if link else None,
                "stagger_duration_s": None if immune else to_float(duration),
                "parried_duration_s": to_float(parried),
                "parried_note": strip_markup(parried) or None,
                "stagger_factor": 0.0 if immune else (pct / 100 if pct is not None else None),
                "base_limit": to_float(base),
            }
        )
    return out


def creature_titles_from_stagger(text: str) -> list[str]:
    return [r["title"] for r in stagger_table(text) if r["title"]]


# --- infobox ----------------------------------------------------------------------


def infobox(text: str, kind: str) -> dict[str, str]:
    """Params of the first {{infobox <kind> ...}} as raw strings."""
    m = re.search(r"\{\{\s*infobox[ _]+" + re.escape(kind) + r"\s*(?=\||\}\})", text, flags=re.I)
    if not m:
        return {}
    # split the template body on top-level '|' (outside nested {{ }} and [[ ]])
    parts, buf, depth, i = [], [], 0, m.end()
    while i < len(text):
        two = text[i : i + 2]
        if two in ("{{", "[["):
            depth += 1
            buf.append(two)
            i += 2
            continue
        if two in ("}}", "]]"):
            if depth == 0 and two == "}}":
                break
            depth -= 1
            buf.append(two)
            i += 2
            continue
        if text[i] == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(text[i])
        i += 1
    parts.append("".join(buf))
    params: dict[str, str] = {}
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            params[key.strip().lower()] = value.strip()
    return params


def damage_type_list(value: str) -> list[str]:
    """'[[Blunt]], Pierce' -> ['blunt', 'pierce'] (only the types we model)."""
    words = re.split(r"[,\n/•*]|\band\b", strip_markup(value).lower())
    return [w.strip() for w in words if w.strip() in DAMAGE_TYPES]


# --- weapon upgrade table ---------------------------------------------------------


def upgrade_table(text: str) -> dict[str, list[float]]:
    """'Upgrade information' table -> {'blunt': [q1, q2, ...], ...} for damage rows."""
    for table in find_tables(text):
        rows = table_rows(table)
        if not rows or strip_markup(rows[0][0]).lower() != "quality":
            continue
        qualities = [c for c in rows[0][1:] if to_float(c) is not None]
        n = len(qualities)
        out: dict[str, list[float]] = {}
        for row in rows[1:]:
            label = strip_markup(row[0]).lower()
            if label in DAMAGE_TYPES:
                vals = [to_float(strip_markup(c)) for c in row[1 : 1 + n]]
                out[label] = [v if v is not None else 0.0 for v in vals]
        return out
    return {}
