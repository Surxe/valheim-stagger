import pytest

from valheim_stagger.calc import Conditions, evaluate, hit_stagger, threshold

PERFECT = Conditions(skill=100, roll="max")  # skill factor exactly 1.0


def creature(health=100.0, factor=0.5, mods=None):
    return {"base_health": health, "stagger_factor": factor, "damage_modifiers": mods or {}}


def weapon(damage, swings, stagger=1.0, qualities=1):
    return {
        "max_quality": qualities,
        "damage_by_quality": [damage] * qualities,
        "attacks": {"primary": {"stagger": stagger, "swings": swings}},
    }


def test_threshold_scales_with_stars():
    c = creature(health=600, factor=0.3)
    assert threshold(c, 0) == pytest.approx(180)
    assert threshold(c, 1) == pytest.approx(360)
    assert threshold(c, 2) == pytest.approx(540)


def test_skill_factor_bounds():
    assert Conditions(skill=100, roll="min").skill_factor() == pytest.approx(0.85)
    assert Conditions(skill=100, roll="max").skill_factor() == pytest.approx(1.0)
    assert Conditions(skill=0, roll="min").skill_factor() == pytest.approx(0.25)
    assert Conditions(skill=0, roll="max").skill_factor() == pytest.approx(0.55)


def test_only_physical_and_lightning_stagger():
    c = creature()
    dmg = {"blunt": 10, "fire": 100, "frost": 100, "poison": 100, "spirit": 100, "lightning": 5}
    assert hit_stagger(dmg, 1.0, 1.0, c, PERFECT) == pytest.approx(15)


def test_resistances_and_stagger_multiplier():
    c = creature(mods={"blunt": "resistant", "pierce": "weak"})
    assert hit_stagger({"blunt": 100}, 1.0, 2.0, c, PERFECT) == pytest.approx(100)  # 100*.5*2
    assert hit_stagger({"pierce": 100}, 2.0, 1.0, c, PERFECT) == pytest.approx(300)  # 100*2*1.5


def test_multiplayer_scaling():
    c = creature()
    cond = Conditions(skill=100, roll="max", players=3)
    assert hit_stagger({"slash": 100}, 1.0, 1.0, c, cond) == pytest.approx(100 / 1.6)


def test_one_swing_stagger():
    w = weapon({"blunt": 50}, [{"damage": [1], "duration_s": 1.0}])
    r = evaluate(w, 1, "primary", creature(health=100, factor=0.5), 0, PERFECT)
    assert r.staggered and r.one_shot and r.swings == 1


def test_decay_prevents_stagger_even_when_total_damage_exceeds_health():
    # threshold 50, decays 10/s. 9 stagger every 1 s never accumulates.
    w = weapon({"blunt": 9}, [{"damage": [1], "duration_s": 1.0}])
    r = evaluate(w, 1, "primary", creature(health=100, factor=0.5), 0, PERFECT)
    assert not r.staggered and r.plateaued


def test_decay_between_hits_counts():
    # threshold 50, decay 10/s. 30 per hit every 1 s: 30 -> 20 -> 50 => 2 swings.
    w = weapon({"blunt": 30}, [{"damage": [1], "duration_s": 1.0}])
    r = evaluate(w, 1, "primary", creature(health=100, factor=0.5), 0, PERFECT)
    assert r.staggered and r.swings == 2 and r.time_s == pytest.approx(1.0)
    # slower swings: 30 -> 0 (3 s of decay) -> 30 ... never
    w = weapon({"blunt": 30}, [{"damage": [1], "duration_s": 3.0}])
    r = evaluate(w, 1, "primary", creature(health=100, factor=0.5), 0, PERFECT)
    assert not r.staggered


def test_combo_last_hit_and_double_hits():
    # threshold 80, decay 16/s; 20 -> (-8) 12 -> +40 = 52 -> +40 = 92 => swing 2, hit 3
    w = weapon({"slash": 20}, [{"damage": [1], "duration_s": 0.5}, {"damage": [2, 2], "duration_s": 0.5}])
    r = evaluate(w, 1, "primary", creature(health=160, factor=0.5), 0, PERFECT)
    assert r.staggered and r.swings == 2 and r.hits == 3


def test_immune():
    w = weapon({"blunt": 1000}, [{"damage": [1], "duration_s": 1.0}])
    r = evaluate(w, 1, "primary", creature(factor=0.0), 0, PERFECT)
    assert not r.staggered and "immune" in r.notes[0]


def test_dies_first_flag():
    w = weapon({"blunt": 60}, [{"damage": [1], "duration_s": 0.1}])
    r = evaluate(w, 1, "primary", creature(health=100, factor=1.0), 0, PERFECT)
    assert r.staggered and r.dies_first  # 2 hits = 120 >= 100 hp


def test_real_data_resistances_atgeir_vs_seeker_and_troll():
    from valheim_stagger.calc import find, load_data

    weapons, creatures = load_data()
    atgeir = find(weapons, "iron atgeir")  # 65 pierce at q1
    seeker = find(creatures, "seeker")  # resistant to blunt/pierce/slash -> 0.5x
    troll = find(creatures, "troll")  # weak to pierce -> 1.5x
    dmg = atgeir["damage_by_quality"][0]
    assert hit_stagger(dmg, 1.0, 1.0, seeker, PERFECT) == pytest.approx(65 * 0.5)
    assert hit_stagger(dmg, 1.0, 6.0, seeker, PERFECT) == pytest.approx(65 * 0.5 * 6)  # secondary spin
    assert hit_stagger(dmg, 1.0, 1.0, troll, PERFECT) == pytest.approx(65 * 1.5)
