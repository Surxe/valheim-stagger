"""The report's JS calculator must agree with the canonical Python one on real data."""

import json
import random
import shutil
import subprocess

import pytest

from valheim_stagger import paths
from valheim_stagger.calc import Conditions, evaluate, load_data

JS = paths.ROOT / "src" / "valheim_stagger" / "report" / "stagger.js"
NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_js_matches_python():
    weapons, creatures = load_data()
    rng = random.Random(1234)
    cases = []
    for _ in range(600):
        w = rng.choice(weapons)
        cases.append({
            "w": weapons.index(w),
            "q": rng.randint(1, w["max_quality"]),
            "a": rng.choice(list(w["attacks"])),
            "c": rng.randrange(len(creatures)),
            "s": rng.randint(0, 2),
            "cond": {"skill": rng.choice([0, 15, 50, 100]), "roll": rng.choice(["min", "avg", "max"]),
                     "players": rng.randint(1, 4), "world_level": rng.choice([0, 0, 0, 2])},
        })
    script = f"""
const S = require({json.dumps(str(JS))});
const W = require({json.dumps(str(paths.WEAPONS))});
const C = require({json.dumps(str(paths.CREATURES))});
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(cases.map(k => S.evaluate(W[k.w], k.q, k.a, C[k.c], k.s, k.cond))));
"""
    out = subprocess.run([NODE, "-e", script], input=json.dumps(cases), capture_output=True,
                         text=True, check=True)
    js_results = json.loads(out.stdout)
    for case, js in zip(cases, js_results):
        py = evaluate(weapons[case["w"]], case["q"], case["a"], creatures[case["c"]], case["s"],
                      Conditions(**case["cond"]))
        assert js["staggered"] == py.staggered, case
        assert js["swings"] == py.swings, case
        assert js["hits"] == py.hits, case
        assert js["dies_first"] == py.dies_first, case
        assert js["threshold"] == pytest.approx(py.threshold), case
        assert js["peak_fraction"] == pytest.approx(py.peak_fraction), case
        if py.staggered:
            assert js["time_s"] == pytest.approx(py.time_s), case
        else:
            assert js["plateaued"] == py.plateaued, case
