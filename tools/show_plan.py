#!/usr/bin/env python3
"""Show how a channel's current (or any) program is laid out: show parts and ad breaks, with lengths.

Usage (from the repo root, with the environment active):
    python3 tools/show_plan.py MyChannel               # what is on right now
    python3 tools/show_plan.py MyChannel "2026-10-04 20:00"   # what is on at a given time

Reads the built schedule only; it changes nothing and prints no credentials.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def mmss(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def summarize(plan):
    """Collapse a block plan into alternating show parts and breaks: [("show"|"break", seconds, count, label)]."""
    parts = []
    for e in plan:
        kind = "show" if getattr(e, "content_type", "feature") == "feature" else "break"
        label = os.path.basename(str(e.path))
        if parts and parts[-1][0] == kind:
            k, secs, count, first = parts[-1]
            parts[-1] = (k, secs + e.duration, count + 1, first)
        else:
            parts.append((kind, e.duration, 1, label))
    return parts


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    from fs42.liquid_manager import LiquidManager

    name = sys.argv[1]
    when = datetime.datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M") if len(sys.argv) > 2 else datetime.datetime.now()
    block = LiquidManager().get_programming_block(name, when)
    plan = block.plan
    parts = summarize(plan)

    print(f"{name} at {when:%a %H:%M}: block {block.start_time:%H:%M} to {block.end_time:%H:%M} "
          f"({mmss((block.end_time - block.start_time).total_seconds())} long)")
    show_total = sum(s for k, s, *_ in parts if k == "show")
    break_total = sum(s for k, s, *_ in parts if k == "break")
    breaks = [s for k, s, *_ in parts if k == "break"]
    print(f"show {mmss(show_total)} | ads and bumps {mmss(break_total)} in {len(breaks)} break(s)"
          + (f" | longest break {mmss(max(breaks))}" if breaks else ""))
    print()
    elapsed = 0.0
    for kind, secs, count, label in parts:
        start = block.start_time + datetime.timedelta(seconds=elapsed)
        what = label if kind == "show" else f"{count} clips (bumpers and commercials)"
        print(f"  {start:%H:%M:%S}  {kind.upper():5}  {mmss(secs):>6}  {what}")
        elapsed += secs


if __name__ == "__main__":
    main()
