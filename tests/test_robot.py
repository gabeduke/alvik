"""Robot-side tests under CPython: the colour menu (src/demo.py), sketch discovery (src/sketchbook.py),
the sketches and the shared dance, with a pretend Alvik and a pretend clock.

    python3 tests/test_robot.py

The fake ArduinoAlvik plays a script of button presses against a virtual clock (sleep_ms moves it on).
When the script runs out, sleep_ms raises KeyboardInterrupt, which is what Ctrl-C over USB does on the
real robot, so the menu stops the way it does when the flash page interrupts it.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFF, RED, WHITE, YELLOW, BLUE, PURPLE = (0, 0, 0), (1, 0, 0), (1, 1, 1), (1, 1, 0), (0, 0, 1), (1, 0, 1)


# ---------- pretend MicroPython ----------

class Clock:
    def __init__(self):
        self.now = 0
        self.end = None

    def sleep_ms(self, ms):
        self.now += ms
        if self.end is not None and self.now > self.end:
            self.end = None
            raise KeyboardInterrupt

    def ticks_ms(self):
        return self.now


CLOCK = Clock()
time.sleep_ms = CLOCK.sleep_ms
time.ticks_ms = CLOCK.ticks_ms
time.ticks_diff = lambda a, b: a - b
time.ticks_add = lambda a, b: a + b
sys.modules["micropython"] = types.SimpleNamespace(const=lambda x: x)


class FakeBLE:
    def __getattr__(self, name):
        return lambda *a, **k: ((1, 2),) if name == "gatts_register_services" else None


sys.modules["bluetooth"] = types.SimpleNamespace(
    UUID=lambda s: s.encode(), FLAG_NOTIFY=1, FLAG_WRITE=2, FLAG_WRITE_NO_RESPONSE=4, BLE=FakeBLE)


class Led:
    def __init__(self, robot, side):
        self.robot, self.side = robot, side

    def set_color(self, r, g, b):
        self.robot.leds.append((CLOCK.now, self.side, (int(r), int(g), int(b))))


class FakeAlvik:
    """Buttons: presses = [(start_ms, end_ms, name)]. distance(t) -> 5 readings."""
    current = None

    def __init__(self):
        FakeAlvik.current = self
        self.presses = []
        self.leds = []
        self.drives = []
        self.stopped = False
        self.distance = lambda t: (None,) * 5
        self.left_led = Led(self, "L")
        self.right_led = Led(self, "R")

    def begin(self):
        return 0

    def _touch(self, name):
        return any(a <= CLOCK.now < b and n == name for a, b, n in self.presses)

    def get_touch_ok(self): return self._touch("ok")
    def get_touch_cancel(self): return self._touch("cancel")
    def get_touch_up(self): return self._touch("up")
    def get_touch_down(self): return self._touch("down")
    def get_touch_left(self): return self._touch("left")
    def get_touch_right(self): return self._touch("right")
    def get_distance(self): return self.distance(CLOCK.now)
    def get_line_sensors(self): return (0, 0, 0)

    def drive(self, linear, angular):
        self.drives.append((CLOCK.now, linear, angular))

    def brake(self):
        self.drive(0, 0)

    def set_wheels_speed(self, l, r):
        self.drive(l, 0)

    def stop(self):
        self.stopped = True

    # helpers for the tests
    def colour_at(self, t):
        """(left, right) colours at time t."""
        cols = {"L": None, "R": None}
        for when, side, rgb in self.leds:
            if when <= t:
                cols[side] = rgb
        return cols["L"], cols["R"]


sys.modules["arduino_alvik"] = types.SimpleNamespace(ArduinoAlvik=FakeAlvik)

ROBOT_MODULES = ["demo", "sketchbook", "dance", "remote_control", "line_follower", "touch_move", "hand_follower"]


class Script:
    """Builds a timeline of button presses: s.press('up').wait(500)..."""
    def __init__(self, start=1000):
        self.t = start
        self.presses = []

    def press(self, name, hold=300, gap=500):
        self.presses.append((self.t, self.t + hold, name))
        self.t += hold + gap
        return self

    def wait(self, ms):
        self.t += ms
        return self


class RobotTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="alvik-fs-")
        for n in os.listdir(os.path.join(REPO, "src")):
            if n.endswith(".py"):
                shutil.copy(os.path.join(REPO, "src", n), self.root)
        self.sketch_dir = os.path.join(self.root, "sketches")
        self._path = list(sys.path)
        sys.path.insert(0, self.root)
        for m in ROBOT_MODULES + ["disco", "follow_me", "boom", "ghost"] + ["s%d" % i for i in range(20)]:
            sys.modules.pop(m, None)
        CLOCK.now = 0
        CLOCK.end = None

    def tearDown(self):
        sys.path[:] = self._path
        shutil.rmtree(self.root, ignore_errors=True)

    def install(self, name, meta=None, files=None):
        """Installs a sketch on the pretend robot: the real one from sketches/<name>, or a made-up one."""
        dest = os.path.join(self.sketch_dir, name)
        if meta is None:
            shutil.copytree(os.path.join(REPO, "sketches", name), dest)
            return
        os.makedirs(dest)
        with open(os.path.join(dest, "sketch.json"), "w") as f:
            f.write(meta if isinstance(meta, str) else json.dumps(meta))
        for n, body in (files or {}).items():
            with open(os.path.join(dest, n), "w") as f:
                f.write(body)

    def boot(self, script, setup=None):
        """Imports demo.py (it runs the menu) with the button script; returns (robot, demo, printed)."""
        import sketchbook
        sketchbook.SKETCH_DIR = self.sketch_dir
        CLOCK.end = script.t
        out = io.StringIO()
        robot = None
        orig_init = FakeAlvik.__init__

        def init(a):
            orig_init(a)
            a.presses = script.presses
            if setup:
                setup(a)
        FakeAlvik.__init__ = init
        try:
            with redirect_stdout(out):
                import demo
        finally:
            FakeAlvik.__init__ = orig_init
        robot = FakeAlvik.current
        self.assertTrue(robot.stopped, "menu ended by KeyboardInterrupt (Ctrl-C)")
        return robot, demo, out.getvalue()

    def entry_colours(self, robot, script_marks):
        return [robot.colour_at(t)[0] for t in script_marks]


def made_up(i, color=(0, 1, 1)):
    return ({"title": "S%d" % i, "emoji": "x", "description": "d", "color": list(color), "entry": "s%d" % i},
            {"s%d.py" % i: "def run(alvik):\n    return -1\n"})


class Discovery(RobotTest):
    def test_no_sketch_folder(self):
        robot, demo, _ = self.boot(Script())
        self.assertEqual(len(demo.MENU), 4)
        self.assertEqual(robot.colour_at(900), (BLUE, BLUE), "starts on blue")

    def test_finds_sketches_sorted_and_skips_broken_ones(self):
        self.install("follow_me")
        self.install("disco")
        self.install("aaa_broken", meta="{not json")
        self.install("bad_colour", meta={"title": "x", "color": [1, 1], "entry": "x"})
        os.makedirs(os.path.join(self.sketch_dir, "empty_folder"))
        with open(os.path.join(self.sketch_dir, "stray.txt"), "w") as f:
            f.write("not a sketch")
        import sketchbook
        sketchbook.SKETCH_DIR = self.sketch_dir
        with redirect_stdout(io.StringIO()) as out:
            found = sketchbook.find()
        self.assertEqual([s["name"] for s in found], ["disco", "follow_me"])
        self.assertEqual(found[0]["color"], WHITE)
        self.assertEqual(found[0]["dir"], self.sketch_dir + "/disco")
        self.assertEqual(found[1]["entry"], "follow_me")
        self.assertIn("skipping sketch aaa_broken", out.getvalue())
        self.assertIn("skipping sketch empty_folder", out.getvalue())

        robot, demo, printed = self.boot(Script())
        self.assertEqual([c for c, _ in demo.MENU], [RED, BLUE, (0, 1, 0), PURPLE, WHITE, YELLOW])
        self.assertIn("sketch 4 disco", printed)


class Menu(RobotTest):
    def test_up_down_and_limits(self):
        self.install("disco")
        self.install("follow_me")
        s = Script()
        marks = []
        for _ in range(6):            # blue -> green -> purple -> disco -> follow_me -> (stays)
            s.press("up")
            marks.append(s.t - 100)
        for _ in range(7):            # all the way back down to red, then stays
            s.press("down")
            marks.append(s.t - 100)
        robot, demo, _ = self.boot(s)
        got = self.entry_colours(robot, marks)
        self.assertEqual(got, [(0, 1, 0), PURPLE, WHITE, YELLOW, YELLOW, YELLOW,
                               WHITE, PURPLE, (0, 1, 0), BLUE, RED, RED, RED])

    def test_more_than_six_entries_blink_by_page(self):
        for i in range(9):            # 4 built in + 9 = 13 entries: pages 1, 2 and 3
            self.install("s%d" % i, *made_up(i))
        import sketchbook
        sketchbook.SKETCH_DIR = self.sketch_dir
        s = Script()
        for _ in range(5):            # blue (1) -> entry 6, the first one on page 2
            s.press("up", hold=200, gap=200)
        page2 = s.t
        s.wait(4000)
        for _ in range(6):            # -> entry 12, page 3
            s.press("up", hold=200, gap=200)
        page3 = s.t
        s.wait(4000)
        robot, demo, _ = self.boot(s)
        self.assertEqual(len(demo.MENU), 13)

        def offs(t0, t1):
            """How many times the lights went off between t0 and t1."""
            return sum(1 for when, side, rgb in robot.leds if t0 <= when < t1 and side == "L" and rgb == OFF)
        # whole 2 s cycles inside each window
        start2 = (page2 // 2000 + 1) * 2000
        start3 = (page3 // 2000 + 1) * 2000
        self.assertEqual(offs(0, 1000), 0, "page 1 doesn't blink")
        self.assertEqual(offs(start2, start2 + 2000), 1, "page 2 blinks once per 2 s")
        self.assertEqual(offs(start3, start3 + 2000), 2, "page 3 blinks twice per 2 s")
        self.assertEqual(robot.colour_at(start2 + 1500)[0], (0, 1, 1), "page 2 shows its colour between blinks")

        demo_light = demo.menu_light
        CLOCK.now = 4100          # first blink slot: off on page 2+, on for page 1
        self.assertEqual(demo_light(1), BLUE)
        self.assertEqual(demo_light(6), OFF)
        CLOCK.now = 4300
        self.assertEqual(demo_light(6), (0, 1, 1))
        CLOCK.now = 4500          # second blink slot: only page 3
        self.assertEqual(demo_light(6), (0, 1, 1))
        self.assertEqual(demo_light(12), OFF)


class Sketches(RobotTest):
    def test_disco_dances_then_cancel_returns_to_menu(self):
        self.install("disco")
        s = Script().press("up").press("up").press("up")       # blue -> green -> purple -> disco
        s.press("ok")
        ok_at = s.t
        s.wait(6000)                   # one 4 s dance, then waiting (white)
        s.press("cancel")
        back = s.t
        s.wait(1000)
        s.press("down")               # menu still works afterwards
        down = s.t - 100
        robot, demo, _ = self.boot(s)
        angular = {a for t, l, a in robot.drives if ok_at - 800 < t < ok_at + 4000}
        self.assertTrue({120, -120, 360} <= angular, angular)
        self.assertEqual(robot.colour_at(ok_at + 5500), (WHITE, WHITE), "white: ready to dance again")
        self.assertEqual(robot.colour_at(back + 900)[0], WHITE, "back on the disco menu entry")
        self.assertEqual(robot.drives[-1][1:], (0, 0), "stopped")
        self.assertEqual(robot.colour_at(down)[0], PURPLE)

    def test_disco_ok_dances_again(self):
        self.install("disco")
        s = Script().press("up").press("up").press("up").press("ok").wait(5000)
        again = s.t
        s.press("ok").wait(5000).press("cancel")
        robot, _, _ = self.boot(s)
        spins = [t for t, l, a in robot.drives if a == 360]
        self.assertTrue(any(t > again + 2000 for t in spins), "second dance")

    def test_follow_me(self):
        self.install("disco")
        self.install("follow_me")

        def distances(t):
            if t < 8000:
                return (None, None, 30, None, None)     # hand ahead, a bit far: go forward
            if t < 10000:
                return (8, 50, 60, 70, 80)              # hand close on the far left: back up, turn left
            return (None, 200, 300, 250, None)          # nobody there: sit and wait
        s = Script().press("up").press("up").press("up").press("up")  # -> follow_me
        s.press("ok").wait(8000).press("cancel")
        robot, _, _ = self.boot(s, setup=lambda a: setattr(a, "distance", distances))
        drives = {(l, a) for t, l, a in robot.drives}
        self.assertIn((10, 0), drives)
        self.assertIn((-7, 80), drives)
        self.assertEqual(robot.colour_at(7900), ((0, 1, 0), (0, 1, 0)), "green while following")
        self.assertEqual(robot.colour_at(11000), (YELLOW, YELLOW), "yellow while waiting")

    def test_crashing_and_missing_sketches_flash_red_and_return(self):
        self.install("boom", {"title": "Boom", "emoji": "x", "description": "d", "color": [0, 1, 1], "entry": "boom"},
                     {"boom.py": "def run(alvik):\n    return 1 / 0\n"})
        self.install("ghost", {"title": "Ghost", "emoji": "x", "description": "d", "color": [1, 1, 0], "entry": "ghost"})
        s = Script().press("up").press("up").press("up")       # -> boom
        s.press("ok")
        crash = s.t
        s.wait(2000).press("up").press("ok")                     # -> ghost (no ghost.py)
        missing = s.t
        s.wait(2000).press("down")
        down = s.t - 100
        robot, demo, printed = self.boot(s)
        reds = lambda t0, t1: sum(1 for w, side, c in robot.leds if t0 <= w < t1 and side == "L" and c == RED)
        self.assertEqual(reds(crash - 800, crash + 2000), 3)
        self.assertEqual(reds(missing - 800, missing + 2000), 3)
        self.assertIn("ZeroDivisionError", printed)
        self.assertIn("ghost", printed)
        self.assertEqual(robot.colour_at(down)[0], (0, 1, 1), "menu still works")

    def test_ctrl_c_inside_a_sketch_stops_the_menu(self):
        self.install("disco")
        s = Script().press("up").press("up").press("up").press("ok", hold=200, gap=0)
        robot, _, _ = self.boot(s)    # the script ends mid-dance: KeyboardInterrupt
        self.assertTrue(robot.stopped)

    def test_sketch_modules_cannot_replace_robot_files(self):
        self.install("disco")
        import sketchbook
        sketchbook.SKETCH_DIR = self.sketch_dir
        run = sketchbook.runner(sketchbook.find()[0])
        robot = FakeAlvik()
        robot.presses = [(0, 10 ** 9, "cancel")]   # ✗ held: the dance stops at once
        run(robot)
        self.assertEqual(sys.path[-1], self.sketch_dir + "/disco")
        self.assertLess(sys.path.index(self.root), sys.path.index(self.sketch_dir + "/disco"))


class Remote(RobotTest):
    def test_button_3_still_dances(self):
        import remote_control

        class Link:
            conn = 1
            lost = False
            events = [(3, True)]
            def start(self): pass
            def stop(self): pass
        remote_control._link = Link()
        robot = FakeAlvik()
        robot.presses = [(6000, 10 ** 9, "cancel")]
        self.assertEqual(remote_control.run_remote(robot), -1)
        angular = {a for t, l, a in robot.drives}
        self.assertTrue({120, -120} <= angular, angular)
        self.assertEqual(robot.drives[-1][1:], (0, 0))
        self.assertEqual(robot.colour_at(5000)[0], WHITE, "headlights back after the dance")

class TimedLink:
    """A pretend phone: timeline = [(ms, event)], handed to the robot when the clock gets there."""
    conn = 1
    lost = False

    def __init__(self, timeline):
        self.timeline = sorted(timeline, key=lambda e: e[0])
        self._events = []

    @property
    def events(self):
        while self.timeline and self.timeline[0][0] <= CLOCK.now:
            event = self.timeline.pop(0)[1]
            if event == "lost":            # the phone went away (and a new one may connect)
                self.lost = True
            else:
                self._events.append(event)
        return self._events

    def start(self): pass
    def stop(self): pass


class RemoteDriving(RobotTest):
    def drive(self, timeline, until=4000, distance=None):
        import remote_control
        remote_control._link = TimedLink(timeline)
        robot = FakeAlvik()
        if distance:
            robot.distance = distance
        robot.presses = [(until, 10 ** 9, "cancel")]
        self.assertEqual(remote_control.run_remote(robot), -1)
        return robot, remote_control

    def at(self, robot, t):
        return [d for d in robot.drives if d[0] <= t][-1][1:]

    def test_parser_buttons_joystick_and_junk(self):
        import remote_control as rc

        def pkt(a, b, c):
            body = bytes((0x21, a, b, c))
            return body + bytes(((~sum(body)) & 0xFF,))
        ev = []
        data = b"xx" + pkt(66, 53, 49) + b"!?" + pkt(74, 50, 156) + pkt(74, 0x21, 0x42) + b"!B5"
        left = rc.parse_packets(data[:7], ev)          # packets can arrive in pieces
        left = rc.parse_packets(left + data[7:], ev)
        self.assertEqual(ev, [(5, True), ("J", 50, -100), ("J", 33, 66)])
        self.assertEqual(left, b"!B5")
        bad = bytearray(pkt(74, 10, 10)); bad[4] ^= 1
        ev = []
        self.assertEqual(rc.parse_packets(bytes(bad) + pkt(66, 49, 49), ev), b"")
        self.assertEqual(ev, [(1, True)])

    def test_arrow_speeds_up_gently_and_stops_quicker(self):
        robot, rc = self.drive([(0, (5, True)), (2000, (5, False))])
        speeds = [l for t, l, a in robot.drives if t <= 2000]
        self.assertLess(speeds[1], 2, "no jump to full speed")
        self.assertEqual(speeds, sorted(speeds), "only ever speeds up")
        self.assertEqual(self.at(robot, 1000)[0], rc.SPEED)
        up_ms = next(t for t, l, a in robot.drives if l == rc.SPEED)
        down_ms = next(t for t, l, a in robot.drives if t > 2000 and l == 0) - 2000
        self.assertLess(down_ms, up_ms)
        self.assertGreater(down_ms, 60, "but no instant stop either")

    def test_joystick_is_proportional_and_curves(self):
        beats = [(t, ("J", 0, 50)) for t in range(0, 1500, 150)]      # the page repeats itself while held
        beats += [(t, ("J", 100, 100)) for t in range(1500, 2000, 150)]
        robot, rc = self.drive(beats + [(2000, ("J", 0, 0))])
        self.assertAlmostEqual(self.at(robot, 1400)[0], rc.SPEED / 2)
        linear, angular = self.at(robot, 1990)
        self.assertAlmostEqual(linear, rc.SPEED)
        self.assertAlmostEqual(angular, -rc.TURN, msg="stick right = turn right")
        self.assertEqual(self.at(robot, 3000), (0, 0))

    def test_joystick_going_quiet_stops_the_robot(self):
        robot, rc = self.drive([(0, ("J", 0, 100))])
        self.assertEqual(self.at(robot, 500)[0], rc.SPEED)
        self.assertEqual(self.at(robot, rc.STICK_TIMEOUT_MS + 400), (0, 0))

    def test_reversing_direction_goes_through_zero(self):
        robot, rc = self.drive([(0, (5, True)), (1000, (5, False)), (1000, (6, True))])
        after = [l for t, l, a in robot.drives if t > 1000]
        self.assertIn(0, after[:after.index(-rc.SPEED)])

    def test_bumper_slows_then_stops_at_once_and_lights_red(self):
        def distance(t):                      # a wall coming closer, then gone
            d = 100 if t < 1000 else 21 if t < 2000 else 5 if t < 3000 else 100
            return (None, d, d, d, None)
        robot, rc = self.drive([(0, (5, True))], until=3900, distance=distance)
        self.assertEqual(self.at(robot, 900)[0], rc.SPEED)
        self.assertAlmostEqual(self.at(robot, 1500)[0], rc.SPEED / 2)
        self.assertEqual(self.at(robot, 2040)[0], 0, "stops at once")
        self.assertEqual(robot.colour_at(2500)[0], RED)
        self.assertEqual(robot.colour_at(3800)[0], WHITE)
        self.assertGreater(self.at(robot, 3800)[0], 0, "drives on when the way is clear")

    def test_a_new_phone_starts_with_turbo_off(self):
        robot, rc = self.drive([(0, (2, True)), (100, (5, True)), (1500, "lost"), (1600, (5, True))])
        self.assertEqual(self.at(robot, 1400)[0], rc.TURBO_SPEED)
        self.assertEqual(self.at(robot, 3900)[0], rc.SPEED, "turbo is off again after reconnecting")

    def test_bumper_does_not_stop_reversing(self):
        robot, rc = self.drive([(0, (6, True))], distance=lambda t: (5,) * 5)
        self.assertEqual(self.at(robot, 1000)[0], -rc.SPEED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
