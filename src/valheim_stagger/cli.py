"""vstagger: fetch -> build -> calc / report."""

from __future__ import annotations

import argparse


def _add_conditions(p: argparse.ArgumentParser) -> None:
    p.add_argument("--skill", type=float, default=100, help="weapon skill level 0-100 (default 100)")
    p.add_argument("--roll", choices=["min", "avg", "max"], default="min",
                   help="damage roll within the skill range (default min = guaranteed)")
    p.add_argument("--players", type=int, default=1, help="nearby players (default 1)")
    p.add_argument("--world-level", type=int, default=0, help="world modifier level (default 0)")


def _conditions(args):
    from .calc import Conditions

    return Conditions(skill=args.skill, roll=args.roll, players=args.players, world_level=args.world_level)


def cmd_calc(args) -> None:
    from .calc import evaluate, find, load_data

    weapons, creatures = load_data()
    w = find(weapons, args.weapon)
    c = find(creatures, args.creature)
    cond = _conditions(args)
    qualities = [args.quality] if args.quality else range(1, w["max_quality"] + 1)
    stars = [args.stars] if args.stars is not None else range(3)
    attacks = [args.attack] if args.attack else list(w["attacks"])
    print(f"{w['name']} vs {c['name']}  (health {c['base_health']:g}, stagger limit "
          f"{(c['stagger_factor'] or 0) * 100:g}%, mods {c['damage_modifiers'] or 'none'})")
    print(f"skill {cond.skill:g} ({cond.roll} roll x{cond.skill_factor():.2f}), players {cond.players}\n")
    print(f"{'attack':10} {'q':>2} {'star':>4} {'limit':>8} {'1st swing':>9} {'result':<34}")
    for a in attacks:
        for q in qualities:
            for s in stars:
                r = evaluate(w, q, a, c, s, cond)
                if r is None:
                    continue
                if r.staggered:
                    what = "ONE SWING" if r.one_shot else f"{r.swings} swings / {r.time_s:.2f}s"
                    if r.dies_first:
                        what += " (dies first)"
                else:
                    reason = "plateaus" if r.plateaued else "too slow"
                    what = f"never ({reason} at {r.peak_fraction:.0%})" if r.swing_stagger and any(r.swing_stagger) and r.threshold else r.notes[-1]
                print(f"{a:10} {q:>2} {s:>3}* {r.threshold:>8.1f} {r.swing_stagger[0]:>9.1f} {what:<34}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="vstagger", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download raw wiki pages into data/raw/wiki")
    sub.add_parser("build", help="parse raw wiki pages into data/*.json")

    pc = sub.add_parser("calc", help="can WEAPON stagger CREATURE? (all qualities/stars by default)")
    pc.add_argument("weapon")
    pc.add_argument("creature")
    pc.add_argument("-q", "--quality", type=int)
    pc.add_argument("-s", "--stars", type=int, choices=[0, 1, 2])
    pc.add_argument("-a", "--attack", choices=["primary", "secondary"])
    _add_conditions(pc)

    pr = sub.add_parser("report", help="write the static HTML report to out/")
    _add_conditions(pr)

    args = p.parse_args(argv)
    if args.cmd == "fetch":
        from .wiki import fetch_all

        fetch_all()
    elif args.cmd == "build":
        from .build import build_all

        build_all()
    elif args.cmd == "calc":
        cmd_calc(args)
    elif args.cmd == "report":
        from .report import write_report

        write_report(_conditions(args))


if __name__ == "__main__":
    main()
