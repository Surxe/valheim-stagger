"""Stagger calculator. Mirrors the game logic in assembly_valheim.dll (Character.cs):

    threshold   = MaxHealth * m_staggerDamageFactor                 (GetStaggerTreshold)
    MaxHealth   = base health * level  (level = stars + 1)          (SetupMaxHealth)
    hit stagger = (blunt + slash + pierce + lightning) * m_staggerMultiplier
                  where each damage type is already multiplied by the attack multiplier,
                  the skill roll, and the creature's resistance      (ApplyDamage)
    decay       = threshold / 5 per second                          (UpdateStagger)
    stagger when the meter reaches threshold                        (AddStaggerDamage)

Inputs come from data/weapons.json and data/creatures.json (wiki-sourced, unverified).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

from . import paths

STAGGER_TYPES = ("blunt", "slash", "pierce", "lightning")
DECAY_SECONDS = 5.0  # meter fully drains in 5 s (Character.UpdateStagger: threshold / 5f * dt)

MODIFIER_VALUES = {  # HitData.ApplyModifier
    "very_weak": 2.0,
    "weak": 1.5,
    "slightly_weak": 1.25,
    "normal": 1.0,
    "slightly_resistant": 0.75,
    "resistant": 0.5,
    "very_resistant": 0.25,
    "immune": 0.0,
}

MAX_SIM_SECONDS = 60.0  # longer than any realistic uninterrupted string of attacks


@dataclass(frozen=True)
class Conditions:
    """Player-side context. Defaults: solo, skill 100, worst-case (lowest) damage roll."""

    skill: float = 100.0  # weapon skill level 0..100
    roll: str = "min"  # "min" | "max" | "avg" of the random skill damage roll
    players: int = 1  # nearby players: enemy damage taken scales by 1/(1 + (n-1)*0.3)
    world_level: int = 0  # world modifier level: enemy HP x(2*wl), +AC; 0 = vanilla

    def skill_factor(self) -> float:
        """Skills.GetRandomSkillFactor: lerp(0.4, 1, skill/100) +-0.15, clamped 0..1."""
        center = 0.4 + 0.6 * max(0.0, min(1.0, self.skill / 100))
        lo, hi = max(0.0, center - 0.15), min(1.0, center + 0.15)
        return {"min": lo, "max": hi, "avg": (lo + hi) / 2}[self.roll]

    def player_scale(self) -> float:
        return 1.0 / (1.0 + (self.players - 1) * 0.3)


@dataclass
class Result:
    threshold: float
    swing_stagger: list[float]  # stagger added by each swing of one combo cycle
    cycle_time: float
    staggered: bool
    swings: int | None = None  # swings until stagger (counting from the first)
    hits: int | None = None  # individual hits until stagger
    time_s: float | None = None  # seconds from first hit to stagger
    peak_fraction: float = 0.0  # highest meter fill reached (1.0 = staggered)
    damage_before_stagger: float = 0.0  # physical+lightning damage dealt incl. the staggering hit
    health: float = 0.0
    # Health would hit 0 by (or on) the staggering hit, so the stagger is moot. Counts only
    # physical+lightning damage, so elemental/DoT weapons die-first even more often.
    dies_first: bool = False
    plateaued: bool = False  # False with staggered=False means the sim hit MAX_SIM_SECONDS
    notes: list[str] = field(default_factory=list)

    @property
    def one_shot(self) -> bool:
        return self.staggered and self.swings == 1


def creature_health(creature: dict, stars: int, cond: Conditions = Conditions()) -> float:
    hp = creature["base_health"] * (stars + 1)
    if cond.world_level > 0:
        hp *= cond.world_level * 2.0  # Game.m_worldLevelEnemyHPMultiplier
    return hp


def threshold(creature: dict, stars: int, cond: Conditions = Conditions()) -> float:
    return creature_health(creature, stars, cond) * (creature["stagger_factor"] or 0.0)


def hit_stagger(damage: dict, multiplier: float, attack_stagger: float, creature: dict, cond: Conditions) -> float:
    """Stagger contributed by a single hit (one entry of swing.damage).

    Order follows Character.RPC_Damage -> ApplyDamage: attack multiplier and skill roll
    (Attack.ModifyDamage), resistances, world-level armor on the whole hit, then the
    multiplayer difficulty scale, then stagger types * m_staggerMultiplier.
    """
    mods = creature.get("damage_modifiers", {})
    scale = multiplier * cond.skill_factor()
    resisted = {t: v * scale * MODIFIER_VALUES[mods.get(t, "normal")] for t, v in damage.items()}
    if cond.world_level > 0:
        total = sum(resisted.values())
        if total > 0:
            ratio = _apply_armor(total, cond.world_level * 100.0) / total  # m_worldLevelEnemyBaseAC
            resisted = {t: v * ratio for t, v in resisted.items()}
    stagger_dmg = sum(resisted.get(t, 0.0) for t in STAGGER_TYPES) * cond.player_scale()
    return stagger_dmg * attack_stagger


def _apply_armor(dmg: float, ac: float) -> float:
    """HitData.ApplyArmor(dmg, ac)."""
    if ac < dmg / 2:
        return dmg - ac
    return min(1.0, dmg / (ac * 4)) * dmg


def evaluate(weapon: dict, quality: int, attack_name: str, creature: dict, stars: int,
             cond: Conditions = Conditions()) -> Result | None:
    """Simulate repeating `attack_name` from an empty meter until stagger or steady state."""
    attack = weapon["attacks"].get(attack_name)
    if attack is None or quality > weapon["max_quality"]:
        return None
    damage = weapon["damage_by_quality"][quality - 1]
    thr = threshold(creature, stars, cond)
    health = creature_health(creature, stars, cond)
    swings = attack["swings"]
    per_swing = [[hit_stagger(damage, m, attack["stagger"], creature, cond) for m in s["damage"]] for s in swings]
    swing_totals = [sum(h) for h in per_swing]
    cycle_time = sum(s["duration_s"] for s in swings)
    res = Result(threshold=thr, swing_stagger=swing_totals, cycle_time=cycle_time,
                 staggered=False, health=health)
    if thr <= 0:
        res.notes.append("immune to stagger")
        return res
    if not any(swing_totals):
        res.notes.append("deals no staggering damage to this creature")
        return res

    decay_rate = thr / DECAY_SECONDS
    meter = t = 0.0
    swing_count = hit_count = 0
    plateaued = False
    dealt = 0.0
    stagger_mult = attack["stagger"] or 1.0
    prev_cycle_start = -1.0
    i = 0
    while t <= MAX_SIM_SECONDS:
        if i == 0:
            if meter - prev_cycle_start < 1e-9:
                plateaued = True  # steady state: the meter will never climb higher
                break
            prev_cycle_start = meter
        swing_count += 1
        for h in per_swing[i]:
            hit_count += 1
            meter += h
            dealt += h / stagger_mult
            res.peak_fraction = max(res.peak_fraction, min(1.0, meter / thr))
            if meter >= thr:
                res.staggered = True
                res.swings, res.hits, res.time_s = swing_count, hit_count, round(t, 3)
                res.damage_before_stagger = dealt
                res.dies_first = dealt >= health
                return res
        meter = max(0.0, meter - decay_rate * swings[i]["duration_s"])
        t += swings[i]["duration_s"]
        i = (i + 1) % len(swings)
    res.plateaued = plateaued
    res.notes.append(
        "decay outpaces this attack; meter plateaus below threshold" if plateaued
        else f"meter still creeping up after {MAX_SIM_SECONDS:g}s of nonstop attacks; treated as never"
    )
    return res


@lru_cache(maxsize=1)
def load_data() -> tuple[list[dict], list[dict]]:
    weapons = json.loads(paths.WEAPONS.read_text(encoding="utf-8"))
    creatures = json.loads(paths.CREATURES.read_text(encoding="utf-8"))
    return weapons, creatures


def find(records: list[dict], query: str) -> dict:
    q = query.lower().strip()
    for r in records:
        if q in (r["id"], r["name"].lower()):
            return r
    matches = [r for r in records if q in r["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    names = ", ".join(r["name"] for r in matches[:10]) or "none"
    raise SystemExit(f"'{query}' is ambiguous or unknown (matches: {names})")
