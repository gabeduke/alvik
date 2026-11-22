#!/usr/bin/env python3
"""Record what the robot's sensors read on a floor, so the bumper and the 3D robot can be tuned
from real numbers instead of guesses (#11).

    .venv/bin/python scripts/floor_log.py wood-floor.csv            # robot creeps forward 8 s
    .venv/bin/python scripts/floor_log.py desk.csv --still          # robot stays put (lift and tip it by hand)

Robot on USB, on the floor with about 50 cm clear ahead (it creeps forward at 4 cm/s, so the USB
cable comes along; nothing in front, please: this does not use the bumper). Touch ✗ on the robot
to stop early. Close Arduino Lab for MicroPython first. The robot's menu is interrupted and
restarted afterwards.

One row per new set of distance readings: time (ms), the five distance zones left to right (cm,
blank = nothing), the bottom and top distances, roll and pitch (degrees), and how far it has
driven (cm, from the wheels). Send the CSV back and the numbers in remote_control.py and
docs/sensing.js can be checked against it.
"""
import argparse
import os
import subprocess
import sys

ON_ROBOT = r"""
from arduino_alvik import ArduinoAlvik
from time import ticks_ms, ticks_diff, sleep_ms
a = ArduinoAlvik()
a.begin()
sleep_ms(500)
def cm(v):
    return '' if v is None else '%.1f' % v
print('ms,d0,d1,d2,d3,d4,bottom,top,roll,pitch,driven_cm')
start = ticks_ms()
x0 = a.get_pose()[0]
last = None
try:
    if SPEED:
        a.drive(SPEED, 0)
    while ticks_diff(ticks_ms(), start) < SECONDS * 1000 and not a.get_touch_cancel():
        d = tuple(a.get_distance())
        if d != last:
            last = d
            roll, pitch, _ = a.get_orientation()
            row = [str(ticks_diff(ticks_ms(), start))] + [cm(v) for v in d]
            row += [cm(a.get_distance_bottom()), cm(a.get_distance_top()),
                    '%.1f' % roll, '%.1f' % pitch, '%.1f' % (a.get_pose()[0] - x0)]
            print(','.join(row))
        sleep_ms(10)
finally:
    a.brake()
    a.stop()
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="CSV file to write")
    ap.add_argument("--seconds", type=float, default=8)
    ap.add_argument("--still", action="store_true", help="don't drive; lift or tip the robot by hand")
    ap.add_argument("--port", help="e.g. /dev/cu.usbmodem1234561 (found by itself if left out)")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    mpremote = os.path.join(here, "..", ".venv", "bin", "mpremote")
    if not os.path.exists(mpremote):
        mpremote = "mpremote"
    code = "SPEED = %d\nSECONDS = %g\n" % (0 if args.still else 4, args.seconds) + ON_ROBOT
    cmd = [mpremote] + (["connect", args.port] if args.port else []) + ["exec", code, "+", "reset"]
    rows = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True) as run:
        for line in run.stdout:
            line = line.strip()
            if line.startswith("ms,") or (line[:1].isdigit() and line.count(",") == 10):
                rows.append(line)
                print(line)
    if len(rows) < 2:
        sys.exit("No readings came back: is the robot plugged in, and Arduino Lab closed?")
    with open(args.out, "w") as f:
        f.write("\n".join(rows) + "\n")
    print("%d readings -> %s" % (len(rows) - 1, args.out), file=sys.stderr)


if __name__ == "__main__":
    main()
