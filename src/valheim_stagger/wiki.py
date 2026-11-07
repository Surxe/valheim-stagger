"""Fetch raw wikitext from the Valheim Wiki (valheim.weirdgloop.org) into data/raw/wiki.

The raw snapshots are checked in so parsing is reproducible offline and diffs show
exactly what changed upstream. Wiki content is CC BY-SA; see README for attribution.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import paths

API = "https://valheim.weirdgloop.org/api.php"
USER_AGENT = "valheim-stagger/0.1 (https://github.com/Surxe/valheim-stagger)"
BATCH = 50

# Seed pages: the stagger table, the weapon navbox, and the weapon-class pages whose
# "Properties" tables hold attack timings / multipliers.
SEED_PAGES = [
    "Stagger",
    "Template:WeaponsNav",
    "Axes",
    "Clubs",
    "Swords",
    "Spears",
    "Polearms",
    "Knives",
    "Fists",
]

# WeaponsNav groups that are melee weapon classes (v1 scope; ranged/magic are future work).
MELEE_GROUPS = {"Axes", "Clubs", "Swords", "Spears", "Polearms", "Knives", "Fists"}


def page_filename(title: str) -> str:
    return re.sub(r"[^\w\-.()' ]", "_", title).replace(" ", "_") + ".wikitext"


def read_raw(title: str) -> str:
    return (paths.RAW_WIKI / page_filename(title)).read_text(encoding="utf-8")


def load_manifest() -> dict:
    if paths.WIKI_MANIFEST.exists():
        return json.loads(paths.WIKI_MANIFEST.read_text(encoding="utf-8"))
    return {"pages": {}}


def _api(params: dict) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    req = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_pages(titles: list[str]) -> dict[str, dict]:
    """Fetch latest revision wikitext for titles (redirects followed). Returns title -> info."""
    result: dict[str, dict] = {}
    titles = list(dict.fromkeys(titles))
    for i in range(0, len(titles), BATCH):
        chunk = titles[i : i + BATCH]
        data = _api(
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "ids|timestamp|content",
                "rvslots": "main",
                "redirects": "1",
                "titles": "|".join(chunk),
            }
        )
        q = data["query"]
        # requested title -> final title, through normalization and redirects
        alias = {t: t for t in chunk}
        for n in q.get("normalized", []):
            for k, v in alias.items():
                if v == n["from"]:
                    alias[k] = n["to"]
        for r in q.get("redirects", []):
            for k, v in alias.items():
                if v == r["from"]:
                    alias[k] = r["to"]
        pages = {p["title"]: p for p in q["pages"]}
        for requested, final in alias.items():
            page = pages.get(final)
            if not page or page.get("missing"):
                result[requested] = {"missing": True}
                continue
            rev = page["revisions"][0]
            result[requested] = {
                "title": final,
                "revid": rev["revid"],
                "timestamp": rev["timestamp"],
                "content": rev["slots"]["main"]["content"],
            }
        time.sleep(0.5)  # be polite
    return result


def save_pages(fetched: dict[str, dict]) -> list[str]:
    paths.RAW_WIKI.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    missing = []
    for requested, info in fetched.items():
        if info.get("missing"):
            missing.append(requested)
            continue
        (paths.RAW_WIKI / page_filename(requested)).write_text(info["content"], encoding="utf-8")
        manifest["pages"][requested] = {
            "resolved_title": info["title"],
            "revid": info["revid"],
            "timestamp": info["timestamp"],
            "url": f"https://valheim.weirdgloop.org/w/{urllib.parse.quote(info['title'].replace(' ', '_'))}",
        }
    manifest["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest["pages"] = dict(sorted(manifest["pages"].items()))
    paths.WIKI_MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return missing


def fetch_all() -> None:
    """Fetch seeds, then every melee weapon and every creature they reference."""
    from .parse import creature_titles_from_stagger, weapon_titles_from_nav

    print(f"fetching {len(SEED_PAGES)} seed pages")
    missing = save_pages(fetch_pages(SEED_PAGES))

    weapons = weapon_titles_from_nav(read_raw("Template:WeaponsNav"), MELEE_GROUPS)
    creatures = [t for t in creature_titles_from_stagger(read_raw("Stagger")) if t]
    print(f"fetching {len(weapons)} weapon pages, {len(creatures)} creature pages")
    missing += save_pages(fetch_pages([w for w, _, _ in weapons] + creatures))
    if missing:
        print("missing pages:", ", ".join(missing))
