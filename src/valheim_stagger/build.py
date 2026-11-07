"""Raw wiki snapshots + attack_profiles.json -> data/creatures.json, data/weapons.json."""

from __future__ import annotations

import copy
import json
import re

from . import parse, paths, wiki

MODIFIER_KEYS = {
    "veryweak": "very_weak",
    "weak": "weak",
    "slightlyweak": "slightly_weak",
    "neutral": "normal",
    "slightlyresistant": "slightly_resistant",
    "resistant": "resistant",
    "veryresistant": "very_resistant",
    "immune": "immune",
}

# Known biome names, in progression order, for grouping creatures in the report.
BIOMES = [
    "Meadows", "Black Forest", "Swamp", "Mountains", "Plains",
    "Mistlands", "Ashlands", "Deep North", "Ocean",
]
BIOME_ALIASES = {"Mountain": "Mountains"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("ö", "o")).strip("-")


def _first_biome(location: str, name: str) -> str | None:
    for b in BIOMES:
        if b.lower() in name.lower():
            return b
    text = parse.strip_markup(location)
    for alias, biome in BIOME_ALIASES.items():
        text = re.sub(rf"\b{alias}\b(?!s)", biome, text)
    hits = [(text.find(b), b) for b in BIOMES if b in text]
    return min(hits)[1] if hits else None


def build_creatures() -> list[dict]:
    manifest = wiki.load_manifest()["pages"]
    creatures = []
    for row in parse.stagger_table(wiki.read_raw("Stagger")):
        if row["name"] == "Player" or not row["title"]:
            continue
        warnings: list[str] = []
        ib = parse.infobox(wiki.read_raw(row["title"]), "creature")
        variant = parse.strip_markup(row["title"]) != row["name"] and "(" not in row["title"]
        if variant:
            warnings.append(
                f"No own wiki page; resistances taken from '{row['title']}' page and may differ."
            )

        ib_health = parse.to_float(parse.strip_markup(ib.get("health 0star") or ib.get("health") or "").replace(",", ""))
        factor = row["stagger_factor"]
        derived = row["base_limit"] / factor if row["base_limit"] and factor else None
        # The stagger table's base limit comes from game data; prefer the infobox health when it
        # agrees (factor rounding, e.g. 33% vs 0.33), else trust the stagger table.
        if derived and ib_health and abs(derived - ib_health) / ib_health < 0.02 and not variant:
            health, health_src = ib_health, "infobox"
        elif derived:
            health, health_src = round(derived, 2), "stagger_table"
            if ib_health and not variant:
                warnings.append(f"Infobox health {ib_health} disagrees with stagger table ({derived:g}); using table.")
        else:
            health, health_src = ib_health, "infobox"

        mods: dict[str, str] = {}
        for key, label in MODIFIER_KEYS.items():
            for dt in parse.damage_type_list(ib.get(key, "")):
                mods[dt] = label

        creatures.append(
            {
                "id": slug(row["name"]),
                "name": row["name"],
                "game_id": parse.strip_markup(ib.get("id", "")) or None,
                "biome": _first_biome(ib.get("location", ""), row["name"]),
                "base_health": health,
                "health_source": health_src,
                "stagger_factor": factor,
                "stagger_immune": not factor,
                "stagger_duration_s": row["stagger_duration_s"],
                "damage_modifiers": dict(sorted(mods.items())),
                "source": {
                    "stagger": manifest["Stagger"]["url"],
                    "page": manifest.get(row["title"], {}).get("url"),
                    "revid": manifest.get(row["title"], {}).get("revid"),
                },
                "warnings": warnings,
            }
        )
    return creatures


def _profile_for(cls: str, sub: str | None, profiles: dict) -> str | None:
    for key, prof in profiles.items():
        m = prof["match"]
        if m["class"] == cls and m.get("subgroup") in (None, sub):
            return key
    return None


def _resolve_attacks(title: str, profile: dict, overrides: dict) -> tuple[dict, list[str]]:
    attacks = copy.deepcopy(profile["attacks"])
    sources = [profile["source"]]
    ov = overrides.get(title)
    if ov:
        sources.append(ov["source"])
        for name, patch in ov.get("attacks", {}).items():
            if patch is None:
                attacks.pop(name, None)
            else:
                attacks[name] = {**attacks.get(name, {}), **patch}
    return attacks, sources


def build_weapons() -> list[dict]:
    manifest = wiki.load_manifest()["pages"]
    ap = json.loads(paths.ATTACK_PROFILES.read_text(encoding="utf-8"))
    profiles, overrides = ap["profiles"], ap["overrides"]
    weapons = []
    nav = parse.weapon_titles_from_nav(wiki.read_raw("Template:WeaponsNav"), wiki.MELEE_GROUPS)
    for title, cls, sub in nav:
        warnings: list[str] = []
        text = wiki.read_raw(title)
        ib = parse.infobox(text, "weapon")
        upgrades = parse.upgrade_table(text)
        if not upgrades:
            ib_dmg = {k: parse.to_float(ib[k]) for k in parse.DAMAGE_TYPES if parse.to_float(ib.get(k, ""))}
            upgrades = {k: [v] for k, v in ib_dmg.items()}
            warnings.append("No upgrade table; single quality level from infobox.")
        else:
            for k in parse.DAMAGE_TYPES:
                ib_v = parse.to_float(ib.get(k, ""))
                tbl = upgrades.get(k, [0])[0]
                if (ib_v or 0) != tbl and k in ("blunt", "slash", "pierce", "lightning"):
                    warnings.append(f"Infobox {k}={ib_v} vs upgrade table q1={tbl}; using upgrade table.")
        n = max(len(v) for v in upgrades.values())
        by_quality = [
            {k: v[q] for k, v in upgrades.items() if q < len(v) and v[q]} for q in range(n)
        ]

        pkey = _profile_for(cls, sub, profiles)
        if not pkey:
            warnings.append(f"No attack profile for {cls}/{sub}; skipped.")
            continue
        attacks, sources = _resolve_attacks(title, profiles[pkey], overrides)
        page = manifest.get(title, {})
        weapons.append(
            {
                "id": slug(title),
                "name": title,
                "game_id": parse.strip_markup(ib.get("id", "")) or None,
                "class": cls,
                "subgroup": sub,
                "profile": pkey,
                "max_quality": n,
                "damage_by_quality": by_quality,
                "attacks": attacks,
                "source": {
                    "page": page.get("url"),
                    "revid": page.get("revid"),
                    "attack_profile_pages": sorted(set(sources)),
                },
                "warnings": warnings,
            }
        )
    return weapons


def _write(path, records: list[dict]) -> None:
    path.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def build_all() -> None:
    creatures = build_creatures()
    weapons = build_weapons()
    _write(paths.CREATURES, creatures)
    _write(paths.WEAPONS, weapons)
    print(f"wrote {len(creatures)} creatures -> {paths.CREATURES.relative_to(paths.ROOT)}")
    print(f"wrote {len(weapons)} weapons -> {paths.WEAPONS.relative_to(paths.ROOT)}")
    for kind, recs in (("creature", creatures), ("weapon", weapons)):
        for r in recs:
            for w in r["warnings"]:
                print(f"  warn {kind} {r['name']}: {w}")
