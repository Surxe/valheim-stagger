"""Static, self-contained HTML report: data + JS calculator inlined into template.html."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import paths, wiki

HERE = Path(__file__).parent
OUT_FILE = paths.OUT / "report.html"


def render(defaults: dict | None = None) -> str:
    weapons = json.loads(paths.WEAPONS.read_text(encoding="utf-8"))
    creatures = json.loads(paths.CREATURES.read_text(encoding="utf-8"))
    manifest = wiki.load_manifest()
    payload = {
        "weapons": weapons,
        "creatures": creatures,
        "defaults": defaults or {},
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "wiki_fetched_at": manifest.get("fetched_at"),
        },
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (HERE / "template.html").read_text(encoding="utf-8")
    return (
        html.replace("/*__STAGGER_JS__*/", (HERE / "stagger.js").read_text(encoding="utf-8"))
        .replace("/*__DATA__*/null", data)
    )


def write_report(cond=None) -> Path:
    defaults = {}
    if cond is not None:
        defaults = {"skill": cond.skill, "roll": cond.roll, "players": cond.players,
                    "world_level": cond.world_level}
    paths.OUT.mkdir(exist_ok=True)
    OUT_FILE.write_text(render(defaults), encoding="utf-8")
    print(f"wrote {OUT_FILE}")
    print(f"open: file://{OUT_FILE}")
    return OUT_FILE
