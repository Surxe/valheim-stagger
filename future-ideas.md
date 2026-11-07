# Future ideas

## 1. Authoritative data (replace the wiki)

The calculator only needs a handful of fields. Today they come from the wiki and are
unverified. All of them live in the game's own data:

| Need | Game field | Where |
|---|---|---|
| Creature base health | `Character.m_health` | creature prefab |
| Stagger factor | `Character.m_staggerDamageFactor` | creature prefab |
| Resistances | `Character.m_damageModifiers` (+ `WeakSpot.m_damageModifiers`) | creature prefab |
| Weapon damage | `ItemData.m_shared.m_damages`, `m_damagesPerLevel`, `m_maxQuality` | item prefab |
| Attack multipliers | `m_attack` / `m_secondaryAttack`: `m_damageMultiplier`, `m_lastChainDamageMultiplier` (default 2), `m_staggerMultiplier`, `m_attackChainLevels` | item prefab |
| Swing timing | animator clips / events for `m_attackAnimation` | animator controllers |

### Option A: static asset extraction (offline)
- Use UnityPy (Python, fits this repo) or AssetRipper on the game's `valheim_Data/*.assets` and
  bundles. Resolve MonoBehaviour typetrees using the `Managed/*.dll` already copied to
  `/srv/dev/scratch/valheim-mods/game-refs/Managed`.
- Produces `data/game/*.json`, which replaces wiki parsing in `build.py`. Keep the wiki as a
  cross-check: emit a diff report of wiki vs game values.
- Open question: where the game install is readable from as `dev`. The game lives in Ethan's
  Steam library, so this may need an ethan-side copy step (privilege boundary, as with the
  `valheim-mod` skill).

### Option B: runtime dump plugin (BepInEx)
- Tiny plugin: on `ObjectDB.Awake` / `ZNetScene.Awake`, walk `ObjectDB.m_items` and
  `ZNetScene.m_prefabs` and write the fields above to JSON.
- Most robust across patches, since the game resolves everything itself. Reuses the existing
  `valheim-mod` install flow. Needs a game launch per refresh.
- Could also dump attack timings by reading `Animator` clip lengths and attack-trigger events.

### Option C: in-game measurement / validation harness
- A plugin that hooks `Character.AddStaggerDamage` / `UpdateStagger` and logs
  `(time, attacker item, attack, hit stagger, m_staggerDamage, threshold)` for each hit.
- Run scripted fights (spawn a creature with `spawn <id> <level>`, swing nonstop) and compare
  the logs against `calc.evaluate`. This is the only way to confirm swing timings and the
  "hit at end of segment" assumption.

### Track mechanic changes across patches
- Keep a script that decompiles `assembly_valheim.dll` with `ilspycmd` and extracts the
  stagger-relevant methods (`Character.AddStaggerDamage`, `UpdateStagger`, `ApplyDamage`,
  `RPC_Damage`, `Attack.ModifyDamage`, `Skills.GetRandomSkillFactor`, `HitData.ApplyArmor`)
  into `data/game-code/<version>/`. A diff on patch day flags formula changes.
- Record the game version alongside the data files.

## 2. Model fidelity
- **Swing timing**: replace wiki segment timings with real hit-frame times (from the animator
  or Option C). The current assumption is that each hit lands at the end of its segment.
- **Stun-lock analysis**: after the first stagger, the meter stays clamped at the limit and
  the creature takes 2x damage. Model re-stagger cadence against stagger duration
  (`stagger_duration_s` is already in `creatures.json`) to answer "can this weapon keep it
  perma-staggered?"
- **Openers**: the sneak-attack multiplier (`m_backstabBonus`, 3x and knives 6x) on the
  first hit, and mixed sequences (e.g. 2 primaries then a secondary). Search for the fastest
  stagger sequence per matchup.
- **Weak points** (`wp weak` etc. in the wiki infobox, `WeakSpot` in game).
- **Multi-target penalty** for non-sword AoE attacks.
- **Status effects** via `SEMan.ModifyStagger` (Fader's Forsaken power halves received stagger;
  check for others).
- **Parry**: instant stagger outside the meter. Show which creatures can be parry-staggered.
- **Per-variant resistances**: Lox Calf and Asksvin Hatchling borrow their parent's page today.

## 3. Scope
- Ranged: bows + arrows (damage = bow + arrow, draw time), crossbows + bolts (high stagger,
  reload time), spear throw cadence including pickup.
- Magic (Staff of Fracturing / Dundr lightning counts toward stagger), bombs, ballista,
  catapult. The game already copies `m_staggerMultiplier` into ballista and catapult hits.
- Player-side stagger: which creature attacks stagger the player, by armor and food.

## 4. Presentation
- Publish the report (GitHub Pages or a claude.ai artifact) with state in the URL hash so
  matchups can be linked.
- "Minimum to stagger" view: for each creature x stars, the cheapest weapon/quality/skill that
  can stagger it at all, and the skill level needed.
- Plot the meter over time for a matchup (sawtooth vs threshold) to show decay visually.

## 5. Engineering
- `report/stagger.js` duplicates `calc.py` (guarded by the parity test). If the model grows,
  consider generating the JS from one spec, running Python in the browser (Pyodide), or
  precomputing the matrix in Python and keeping the browser as display only.
- `attack_profiles.json` is hand-curated. Once Option A or B lands, generate it and keep only
  documented overrides by hand.
