#!/usr/bin/env python3
"""Checks every sketch folder in OUT_SKETCHES and writes OUT_SKETCHES/index.json for the flash page:
    {"sketches": [{name, title, emoji, description, color, hardware, entry}]}
A broken sketch fails the build (exit 1) so it can't reach the robot. Called by build_site.sh:
    scripts/sketch_index.py _site/sketches src
"""
import json
import os
import re
import sys

REQUIRED = ("title", "emoji", "description", "color", "entry")


def check(folder, name, core):
    def bad(msg):
        sys.exit(f"sketches/{name}: {msg}")

    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        bad("folder name must be lowercase letters, digits and _ (starting with a letter)")
    try:
        with open(os.path.join(folder, "sketch.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError) as e:
        bad(f"can't read sketch.json: {e}")
    for key in REQUIRED:
        if not meta.get(key):
            bad(f"sketch.json needs {key!r}")
    color = meta["color"]
    if not (isinstance(color, list) and len(color) == 3 and all(c in (0, 1) for c in color) and any(color)):
        bad("color must be [r, g, b], each 0 or 1, not all 0")
    hardware = meta.get("hardware", [])
    if not (isinstance(hardware, list) and all(isinstance(h, str) for h in hardware)):
        bad("hardware must be a list of strings")
    entry = meta["entry"]
    path = os.path.join(folder, entry + ".py")
    if not os.path.isfile(path):
        bad(f"entry module {entry}.py is missing")
    if entry in core:
        bad(f"entry module {entry}.py has the same name as src/{entry}.py; rename it")
    with open(path, encoding="utf-8") as f:
        if not re.search(r"^def run\(", f.read(), re.M):
            bad(f"{entry}.py needs a run(alvik) function")
    return {"name": name, "title": meta["title"], "emoji": meta["emoji"],
            "description": meta["description"], "color": color, "hardware": hardware, "entry": entry}


def main(out, src):
    core = {n[:-3] for n in os.listdir(src) if n.endswith(".py")}
    sketches, entries = [], {}
    for name in sorted(os.listdir(out)):
        folder = os.path.join(out, name)
        if not os.path.isdir(folder):
            continue
        s = check(folder, name, core)
        if s["entry"] in entries:   # the robot imports by module name, so they must differ
            sys.exit(f"sketches/{name}: entry {s['entry']!r} is also used by sketches/{entries[s['entry']]}")
        entries[s["entry"]] = name
        sketches.append(s)
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"sketches": sketches}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"{out}/index.json: {len(sketches)} sketches")


if __name__ == "__main__":
    main(*sys.argv[1:])
