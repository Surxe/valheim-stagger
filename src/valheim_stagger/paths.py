"""Repo-relative paths shared by every stage."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW_WIKI = DATA / "raw" / "wiki"
WIKI_MANIFEST = RAW_WIKI / "_manifest.json"
ATTACK_PROFILES = DATA / "attack_profiles.json"
CREATURES = DATA / "creatures.json"
WEAPONS = DATA / "weapons.json"
OUT = ROOT / "out"
