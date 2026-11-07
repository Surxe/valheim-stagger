// Browser port of valheim_stagger/calc.py (the Python module is canonical).
// Kept in lockstep by tests/test_js_parity.py, which runs this file under node.
(function (root) {
  "use strict";

  const STAGGER_TYPES = ["blunt", "slash", "pierce", "lightning"];
  const DECAY_SECONDS = 5.0;
  const MAX_SIM_SECONDS = 60.0;
  const MODIFIER_VALUES = {
    very_weak: 2.0, weak: 1.5, slightly_weak: 1.25, normal: 1.0,
    slightly_resistant: 0.75, resistant: 0.5, very_resistant: 0.25, immune: 0.0,
  };

  function skillFactor(cond) {
    const center = 0.4 + 0.6 * Math.max(0, Math.min(1, cond.skill / 100));
    const lo = Math.max(0, center - 0.15), hi = Math.min(1, center + 0.15);
    return cond.roll === "min" ? lo : cond.roll === "max" ? hi : (lo + hi) / 2;
  }

  function playerScale(cond) { return 1 / (1 + (cond.players - 1) * 0.3); }

  function creatureHealth(c, stars, cond) {
    let hp = c.base_health * (stars + 1);
    if (cond.world_level > 0) hp *= cond.world_level * 2.0;
    return hp;
  }

  function threshold(c, stars, cond) {
    return creatureHealth(c, stars, cond) * (c.stagger_factor || 0);
  }

  function applyArmor(dmg, ac) {
    if (ac < dmg / 2) return dmg - ac;
    return Math.min(1, dmg / (ac * 4)) * dmg;
  }

  function hitStagger(damage, mult, attackStagger, c, cond) {
    const mods = c.damage_modifiers || {};
    const scale = mult * skillFactor(cond);
    const resisted = {};
    for (const t in damage) resisted[t] = damage[t] * scale * MODIFIER_VALUES[mods[t] || "normal"];
    if (cond.world_level > 0) {
      let total = 0;
      for (const t in resisted) total += resisted[t];
      if (total > 0) {
        const ratio = applyArmor(total, cond.world_level * 100) / total;
        for (const t in resisted) resisted[t] *= ratio;
      }
    }
    let s = 0;
    for (const t of STAGGER_TYPES) s += resisted[t] || 0;
    return s * playerScale(cond) * attackStagger;
  }

  function evaluate(w, quality, attackName, c, stars, cond) {
    const attack = w.attacks[attackName];
    if (!attack || quality > w.max_quality) return null;
    const damage = w.damage_by_quality[quality - 1];
    const thr = threshold(c, stars, cond);
    const health = creatureHealth(c, stars, cond);
    const swings = attack.swings;
    const perSwing = swings.map((s) => s.damage.map((m) => hitStagger(damage, m, attack.stagger, c, cond)));
    const totals = perSwing.map((h) => h.reduce((a, b) => a + b, 0));
    const res = {
      threshold: thr, swing_stagger: totals, staggered: false, swings: null, hits: null,
      time_s: null, peak_fraction: 0, damage_before_stagger: 0, health: health,
      dies_first: false, plateaued: false, immune: thr <= 0, no_damage: false,
    };
    if (thr <= 0) return res;
    if (!totals.some((x) => x > 0)) { res.no_damage = true; return res; }

    const decay = thr / DECAY_SECONDS;
    const sm = attack.stagger || 1;
    let meter = 0, t = 0, swingCount = 0, hitCount = 0, dealt = 0, prev = -1, i = 0;
    while (t <= MAX_SIM_SECONDS) {
      if (i === 0) {
        if (meter - prev < 1e-9) { res.plateaued = true; break; }
        prev = meter;
      }
      swingCount++;
      for (const h of perSwing[i]) {
        hitCount++;
        meter += h;
        dealt += h / sm;
        res.peak_fraction = Math.max(res.peak_fraction, Math.min(1, meter / thr));
        if (meter >= thr) {
          res.staggered = true;
          res.swings = swingCount; res.hits = hitCount;
          res.time_s = Math.round(t * 1000) / 1000;
          res.damage_before_stagger = dealt;
          res.dies_first = dealt >= health;
          return res;
        }
      }
      meter = Math.max(0, meter - decay * swings[i].duration_s);
      t += swings[i].duration_s;
      i = (i + 1) % swings.length;
    }
    return res;
  }

  const api = { evaluate, threshold, hitStagger, skillFactor, creatureHealth };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Stagger = api;
})(this);
