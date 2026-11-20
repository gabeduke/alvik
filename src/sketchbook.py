# Finds the sketches installed on the robot, for the colour menu in demo.py.
#
# Each sketch is a folder on the robot:  /sketches/<name>/sketch.json  plus its .py files.
# sketch.json says {"title", "emoji", "color": [r, g, b], "entry": "<module>"} (see README).
# The flash page (or mpremote) copies the folder there; deleting the folder uninstalls it.

import json
import os
import sys

SKETCH_DIR = "/sketches"


def find():
    """Installed sketches, sorted by folder name: a list of dicts with name, title, emoji,
    color, dir and entry. Folders with a missing or broken sketch.json are skipped."""
    try:
        names = sorted(os.listdir(SKETCH_DIR))
    except OSError:
        return []          # no /sketches folder yet
    found = []
    for name in names:
        folder = SKETCH_DIR + "/" + name
        try:
            with open(folder + "/sketch.json") as f:
                meta = json.load(f)
            color = tuple(1 if c else 0 for c in meta["color"])
            if len(color) != 3:
                raise ValueError("color needs 3 numbers")
        except Exception as e:
            print("skipping sketch", name, repr(e))
            continue
        found.append({
            "name": name,
            "title": meta.get("title", name),
            "emoji": meta.get("emoji", ""),
            "color": color,
            "dir": folder,
            "entry": meta.get("entry", name),
        })
    return found


def runner(sketch):
    """A run(alvik) for the menu that imports the sketch's module the first time it's needed."""
    def run(alvik):
        if sketch["dir"] not in sys.path:
            sys.path.append(sketch["dir"])   # after the robot's own files, so it can't replace them
        return __import__(sketch["entry"]).run(alvik)
    return run


def report(e):
    """Prints what went wrong (with the line number, on the robot) for mpremote / the flash page log."""
    if hasattr(sys, "print_exception"):
        sys.print_exception(e)    # MicroPython
    else:
        print(repr(e))
