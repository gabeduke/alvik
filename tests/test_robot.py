"""Robot-side tests under CPython: the colour menu (src/demo.py), sketch discovery (src/sketchbook.py),
the sketches and the shared dance, with a pretend Alvik and a pretend clock.

    python3 tests/test_robot.py

The fake ArduinoAlvik plays a script of button presses against a virtual clock (sleep_ms moves it on).
When the script runs out, sleep_ms raises KeyboardInterrupt, which is what Ctrl-C over USB does on the
real robot, so the menu stops the way it does when the flash page interrupts it.
"""
import io
import json
import math
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
        self.heading = lambda t: 0
        self.tilt = (0, 0)                 # roll, pitch
        self.battery = 80
        self.lines = (0, 0, 0)             # line sensors: left, centre, right
        self.colour = (None, None, None)   # floor colour, each 0..1
        self.bottom = self.top = None      # cm: what the distance sensor sees low down and high up
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
    FRAME_MS = 60                         # like the real sensor: new readings now and then, the same ones in between

    def get_distance(self):
        frame = CLOCK.now // self.FRAME_MS                              # and they are never quite the same twice
        return tuple(None if d is None else d + 0.1 * (frame % 2) for d in self.distance(frame * self.FRAME_MS))
    def get_line_sensors(self): return self.lines
    def get_color(self, color_format="rgb"):
        if self.colour == "broken":        # a calibration with white = black: the library divides by zero
            raise ZeroDivisionError("divide by zero")
        return self.colour
    def get_distance_bottom(self): return self.bottom
    def get_distance_top(self): return self.top
    def get_pose(self): return (0, 0, self.heading(CLOCK.now))
    def get_orientation(self): return self.tilt + (self.heading(CLOCK.now),)
    def get_battery_charge(self): return self.battery

    def drive(self, linear, angular):
        self.drives.append((CLOCK.now, linear, angular))

    def brake(self):
        self.drive(0, 0)

    def set_wheels_speed(self, l, r):
        self.drive(l, 0)

    def stop(self):
        self.stopped = True

    # helpers for the tests
    def travelled(self, t):
        """cm driven forward by time t (ms), from the speeds the robot was told to drive at."""
        cm, was, speed = 0, 0, 0
        for when, linear, angular in self.drives:
            if when > t:
                break
            cm += speed * (when - was) / 1000
            was, speed = when, linear
        return cm + speed * (t - was) / 1000

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
        for m in ROBOT_MODULES + ["disco", "doodle", "follow_me", "scaredy_cat", "boom", "ghost"] + ["s%d" % i for i in range(20)]:
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

    def test_scaredy_cat(self):
        self.install("scaredy_cat")

        def distances(t):
            if t < 6000:
                return (17, 16.5, 17.2, 16.8, 17)       # open floor: the floor's reading is not scary
            if t < 8000:
                return (40, 30, 9, 30, 40)              # a hand right in front: back away
            return (None,) * 5                          # nothing there at all
        s = Script().press("up").press("up").press("up")  # -> scaredy_cat, the only sketch
        s.press("ok").wait(8000).press("cancel")
        robot, _, _ = self.boot(s, setup=lambda a: setattr(a, "distance", distances))
        self.assertEqual({(l, a) for t, l, a in robot.drives if 4500 < t < 6000}, {(0, 0)})
        self.assertEqual(robot.colour_at(5900), ((0, 1, 0), (0, 1, 0)), "green while calm")
        self.assertEqual({(l, a) for t, l, a in robot.drives if 6100 < t < 8000}, {(-8, 0)})
        self.assertEqual(robot.colour_at(7900), (RED, RED), "red while backing away")
        self.assertEqual(robot.colour_at(9000), ((0, 1, 0), (0, 1, 0)), "calm again")

    # ----- doodle: the robot draws with a pen held beside its right wheel -----
    PEN_CM = 5.7

    @staticmethod
    def pen_path(robot, t0, t1, pen_cm, step=5):
        """Where the pen's tip goes (cm) between t0 and t1, worked out from the speeds the robot was told."""
        x = y = heading = 0.0
        path, i, linear, angular = [], 0, 0, 0
        for t in range(0, t1, step):
            while i < len(robot.drives) and robot.drives[i][0] <= t:
                linear, angular = robot.drives[i][1:]
                i += 1
            heading += math.radians(angular) * step / 1000
            x += linear * math.cos(heading) * step / 1000
            y += linear * math.sin(heading) * step / 1000
            if t >= t0:
                path.append((x + pen_cm * math.sin(heading), y - pen_cm * math.cos(heading)))
        return path

    @staticmethod
    def odometry(a):
        """The pretend robot knows which way it points, as the real one does: -180..180, left counts up."""
        def heading(t):
            deg, was, angular = 0.0, 0, 0
            for when, _, turn in a.drives:
                if when > t:
                    break
                deg += angular * (when - was) / 1000
                was, angular = when, turn
            return (deg + angular * (t - was) / 1000 + 180) % 360 - 180
        a.heading = heading

    def doodle(self, script):
        self.install("doodle")
        return self.boot(script, setup=self.odometry)[0]

    def test_doodle_square_has_sharp_corners_and_closes(self):
        s = Script().press("up").press("up").press("up")      # -> doodle, the only sketch
        s.press("ok", hold=1500)      # a long press on the menu's ✓ must not start a drawing
        go = s.t
        s.press("ok").wait(20000)
        end = s.t
        s.press("cancel")
        robot = self.doodle(s)
        self.assertEqual([d for d in robot.drives if d[0] < go and d[1:] != (0, 0)], [], "waits for its own ✓")
        self.assertEqual(robot.colour_at(go - 100), ((0, 1, 0), (0, 1, 0)), "green = square")
        moves = [(l, a) for t, l, a in robot.drives if t >= go and (l, a) != (0, 0)]
        self.assertEqual(len(moves), 8, moves)
        self.assertEqual(moves[0::2], [(6, 0)] * 4, "four lines")
        for l, a in moves[1::2]:
            self.assertEqual(a, -45)
            self.assertAlmostEqual(l, math.radians(45) * self.PEN_CM, places=3)
        path = self.pen_path(robot, go, end, self.PEN_CM)
        xs, ys = [p[0] for p in path], [p[1] for p in path]
        self.assertAlmostEqual(max(xs) - min(xs), 12, delta=0.4)
        self.assertAlmostEqual(max(ys) - min(ys), 12, delta=0.4)
        self.assertLess(math.dist(path[0], path[-1]), 0.5, "the pen ends where it began")
        self.assertEqual(robot.drives[-1][1:], (0, 0), "stopped")

    def test_doodle_picks_shapes_with_left_and_right(self):
        s = Script().press("up").press("up").press("up").press("ok")
        s.press("right").press("right")                        # square -> triangle -> star
        star = s.t - 100
        s.press("ok").wait(32000)
        s.press("left").press("left").press("left")            # star -> triangle -> square -> ring
        ring = s.t - 100
        s.press("ok").wait(9000)
        end = s.t
        s.press("cancel")
        robot = self.doodle(s)
        self.assertEqual(robot.colour_at(star), (PURPLE, PURPLE))
        self.assertEqual(robot.colour_at(ring), (BLUE, BLUE))
        corners = [t for t, l, a in robot.drives if star < t < ring and a == -45]
        self.assertEqual(len(corners), 5, "a star has five points")
        spins = [(l, a) for t, l, a in robot.drives if t > ring and (l, a) != (0, 0)]
        self.assertEqual(spins, [(0, -45)], "the ring is one spin on the spot")
        path = self.pen_path(robot, ring, end, self.PEN_CM)
        xs = [p[0] for p in path]
        self.assertAlmostEqual(max(xs) - min(xs), 2 * self.PEN_CM, delta=0.3)

    def test_doodle_cancel_stops_in_the_middle_of_a_drawing(self):
        s = Script().press("up").press("up").press("up").press("ok").press("ok").wait(3000)
        s.press("cancel")
        back = s.t
        s.wait(1000).press("down")
        down = s.t - 100
        robot = self.doodle(s)
        self.assertEqual([d[1:] for d in robot.drives if d[0] > back and d[1:] != (0, 0)], [], "nothing after ✗")
        self.assertEqual(robot.colour_at(back + 900)[0], YELLOW, "back on the doodle menu entry")
        self.assertEqual(robot.colour_at(down)[0], PURPLE)

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
        self.sent = []                     # (ms, bytes) the robot notified

    @property
    def events(self):
        while self.timeline and self.timeline[0][0] <= CLOCK.now:
            event = self.timeline.pop(0)[1]
            if event == "lost":            # the phone went away (and a new one may connect)
                self.lost = True
            else:
                self._events.append(event)
        return self._events

    def send(self, data):
        self.sent.append((CLOCK.now, bytes(data)))

    def start(self): pass
    def stop(self): pass


class RemoteDriving(RobotTest):
    def drive(self, timeline, until=4000, distance=None, heading=None):
        import remote_control
        CLOCK.now = 0
        remote_control._link = TimedLink(timeline)
        robot = FakeAlvik()
        if distance:
            robot.distance = distance
        if heading:
            robot.heading = heading
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
        def distance(t):                      # a wall 55 cm ahead that the robot drives up to; at 14 s it is taken away
            d = 55 - FakeAlvik.current.travelled(t) if t < 14000 else 100
            return (None, d, d, d, None)
        robot, rc = self.drive([(0, (5, True))], until=16000, distance=distance)
        self.assertEqual(self.at(robot, 900)[0], rc.SPEED)
        half = next(t for t, l, a in robot.drives if 55 - robot.travelled(t) <= (rc.SLOW_CM + rc.BUMPER_CM) / 2)
        self.assertAlmostEqual(self.at(robot, half)[0], rc.SPEED / 2, delta=0.8)
        stop = next(t for t, l, a in robot.drives if t > 1000 and l == 0)
        self.assertGreaterEqual(self.at(robot, stop - 30)[0], 2, "stops at once, no slowing to a halt")
        self.assertTrue(6.5 < 55 - robot.travelled(stop) <= rc.BUMPER_CM, 55 - robot.travelled(stop))
        slowing = [rgb for t, side, rgb in robot.leds if side == "L" and half - 300 < t < stop]
        self.assertEqual(set(slowing), {RED, WHITE}, "blinks red while slowing down")
        stopped = [(t, rgb) for t, side, rgb in robot.leds if side == "L" and stop + 100 < t < stop + 2100]
        self.assertEqual({rgb for t, rgb in stopped}, {RED, OFF}, "flashes red when stopped")
        self.assertEqual(robot.colour_at(15800)[0], WHITE)
        self.assertGreater(self.at(robot, 15800)[0], 0, "drives on when the way is clear")

    def test_a_new_phone_starts_with_turbo_off(self):
        robot, rc = self.drive([(0, (2, True)), (100, (5, True)), (1500, "lost"), (1600, (5, True))])
        self.assertEqual(self.at(robot, 1400)[0], rc.TURBO_SPEED)
        self.assertEqual(self.at(robot, 3900)[0], rc.SPEED, "turbo is off again after reconnecting")

    # The real robot on an open floor, standing level: the left four zones read 16 to 18 cm (the
    # floor itself) and now and then something far away instead. Read off the robot on 2026-11-20.
    @staticmethod
    def open_floor(t):
        wobble = ((t // 30) * 7 % 23) / 10            # 0 .. 2.2, different every reading
        far = 180 if (t // 30) % 17 == 0 else None
        return (far or 16 + wobble, 18.2 - wobble, far or 16.5 + wobble / 2, 17.3, 180)

    # A shiny kitchen table: the table where the floor would be, plus stray reflections. One zone at a
    # time often reads something close for a while, and now and then all of them dip for one set of
    # readings (the nose dipping as it speeds up or slows down).
    @classmethod
    def kitchen_table(cls, t):
        zones = list(cls.open_floor(t))
        n = t // 60                                   # sets of readings
        if n % 20 < 6:                                # a reflection in one zone, a third of a second long
            zones[1 + (n // 20) % 3] = 6 + (n % 7)
        if n % 27 == 0:                               # everything dips, once
            zones[1:4] = [12.5, 13, 12]
        return tuple(zones)

    def test_open_floor_is_not_something_in_the_way(self):
        for floor in (self.open_floor, self.kitchen_table):
            robot, rc = self.drive([(0, (5, True))], until=6000, distance=floor)
            self.assertEqual(self.at(robot, 1000)[0], rc.SPEED)
            self.assertEqual({l for t, l, a in robot.drives if 1000 <= t < 6000}, {rc.SPEED}, f"{floor.__name__}: never slows down")
            self.assertNotIn(RED, [rgb for t, side, rgb in robot.leds], "and never warns")

    def test_a_wall_is_slowed_for_and_stopped_at_on_a_kitchen_table(self):
        def distance(t):                      # a wall 70 cm ahead that the robot drives up to; it shows once nearer than the table
            table = self.kitchen_table(t)
            wall = 70 - FakeAlvik.current.travelled(t)
            return tuple(min(wall, f) for f in table)
        robot, rc = self.drive([(0, (5, True))], until=30000, distance=distance)
        seen = [(70 - robot.travelled(t), l) for t, l, a in robot.drives if t > 1000]
        self.assertTrue(all(l == rc.SPEED for wall, l in seen if wall > rc.SLOW_CM), "full speed until 14 cm")
        self.assertTrue(all(l < rc.SPEED for wall, l in seen if wall < rc.SLOW_CM - 2), "then always slower")
        self.assertEqual(seen[-1][1], 0, "stopped")
        self.assertTrue(6.5 < seen[-1][0] <= rc.BUMPER_CM, seen[-1][0])

    def test_turning_away_from_a_wall_onto_open_floor_lets_go(self):
        def distance(t):                      # a wall 13 cm ahead; at 2 s the robot has turned away from it
            return (13 - FakeAlvik.current.travelled(t),) * 5 if t < 2000 else self.open_floor(t)
        robot, rc = self.drive([(0, (5, True)), (1500, (5, False)), (1500, (7, True)), (2500, (7, False)), (2500, (5, True))],
                               until=5000, distance=distance)
        self.assertLess(self.at(robot, 1400)[0], rc.SPEED, "slowed for the wall")
        self.assertEqual(self.at(robot, 3500)[0], rc.SPEED, "and free again on the open floor")
        self.assertNotIn(RED, [rgb for t, side, rgb in robot.leds if t > 2600])

    def test_bumper_does_not_stop_reversing(self):
        robot, rc = self.drive([(0, (6, True))], distance=lambda t: (5,) * 5)
        self.assertEqual(self.at(robot, 1000)[0], -rc.SPEED)


def read_telemetry(pkt):
    """The page's side of telemetry_packet (docs/telemetry.js), for checking what the robot sent."""
    assert len(pkt) == 10 and pkt[:2] == b"!T" and (~sum(pkt[:9])) & 0xFF == pkt[9], pkt
    s8 = lambda b: b - 256 if b > 127 else b
    h = pkt[2] | pkt[3] << 8
    bits = lambda v: tuple((v >> i) & 1 for i in range(3))
    return {"heading": (h - 65536 if h > 32767 else h) / 10, "distance": None if pkt[4] == 255 else pkt[4],
            "left": bits(pkt[5]), "right": bits(pkt[5] >> 3), "speed": s8(pkt[6]) / 5, "turn": s8(pkt[7]) * 3,
            "turbo": bool(pkt[8] & 1), "bumper": bool(pkt[8] & 2), "blocked": bool(pkt[8] & 4),
            "dancing": bool(pkt[8] & 8)}


class FloorOrThing(RobotTest):
    """Zone.see: one zone of the distance sensor, with the floor and the blips taken out."""

    def zone(self):
        import remote_control as rc
        return rc.Zone(), rc

    def test_the_floor_and_far_things_are_nothing(self):
        zone, rc = self.zone()
        for i in range(400):
            reading = 16 + (i * 7 % 23) / 10
            self.assertIsNone(zone.see(reading, moved=0.25 if i > 50 else 0), reading)
        self.assertEqual([zone.see(d) for d in (None, 180, 35.5, rc.SLOW_CM)], [None] * 4)

    def test_a_wall_driven_up_to_counts_from_slow_cm_and_stays(self):
        zone, rc = self.zone()
        got, d = [], 40
        while d > 5:
            got.append((d, zone.see(d + (0.4 if int(d * 4) % 2 else -0.4), 0.25)))
            d -= 0.25
        self.assertTrue(all(seen is None for d, seen in got if d > rc.SLOW_CM + 0.5))
        self.assertTrue(all(seen is not None for d, seen in got if d < rc.SLOW_CM - 2), [g for g in got if g[1] is None])

    def test_a_blip_is_not_a_thing(self):
        zone, rc = self.zone()
        self.assertEqual([zone.see(d) for d in (17, 9, 9, 17, 6, 17)], [None] * 6)
        self.assertEqual([zone.see(9) for _ in range(rc.SURE + 1)], [None] * (rc.SURE - 1) + [9, 9], "but it is once it stays")

    def test_standing_still_nothing_is_decided(self):
        zone, rc = self.zone()
        self.assertEqual([zone.see(12) for _ in range(200)][-1], 12, "a thing stays a thing until we drive at it")

    def test_a_thing_that_comes_no_closer_as_we_drive_at_it_is_the_floor(self):
        zone, rc = self.zone()                 # a nose-down robot, or a bump in the table: the floor shows at 12 cm
        seen = [zone.see(12 + (i % 3) * 0.3, 0.2) for i in range(60)]
        self.assertIsNotNone(seen[rc.SURE - 1], "taken for a thing at first")
        gone = seen.index(None, rc.SURE)
        self.assertLessEqual(gone * 0.2, rc.FLOOR_PROOF_CM + 1.5, "let go after driving this far")
        self.assertEqual(set(seen[gone:]), {None}, "and it stays the floor")
        self.assertIsNone(zone.see(11.5), "standing still too")
        self.assertEqual([zone.see(d, 0.2) for d in (9.5, 9.3, 9.1, 8.9, 8.7)][rc.SURE - 2:], [None, 9.1, 8.9, 8.7],
                         "something nearer than that floor is a thing")
        zone.see(17)
        self.assertEqual([zone.see(12) for _ in range(rc.SURE)][-1], 12, "seeing past it forgets it")

    def test_closer_than_the_bumper_distance_is_never_the_floor(self):
        zone, rc = self.zone()
        self.assertEqual([zone.see(7, 0.3) for _ in range(60)][-1], 7)


class WhatIsAhead(RobotTest):
    """Bumper.look: two of the middle three zones have to agree."""

    def settle(self, distances, looks=20):
        import remote_control as rc
        eyes = rc.Bumper()                     # new readings each time, never quite the same
        jitter = lambda i: tuple(None if d is None else d + 0.1 * (i % 2) for d in distances)
        return [eyes.look(jitter(i)) for i in range(looks)][-1], rc

    def test_nothing_or_the_floor_is_nothing(self):
        for distances in ((None,) * 5, (140, 115, 108, 101, 83), (16.5, 16.8, 17.1, 17.4, 180), (5, 200, 200, 200, 5)):
            self.assertIsNone(self.settle(distances)[0], distances)

    def test_one_zone_alone_is_nothing(self):
        for distances in ((None, 6, 17, 17, None), (None, 17, 9, 17, None), (None, 200, 200, 5, None)):
            self.assertIsNone(self.settle(distances)[0], distances)

    def test_two_zones_or_three_count(self):
        self.assertAlmostEqual(self.settle((None, 12, 10, 17, None))[0], 12, delta=0.15, msg="the further of the two")
        self.assertAlmostEqual(self.settle((None, 13, 9, 11, None))[0], 11, delta=0.15, msg="the middle of three")
        ahead, rc = self.settle((None, 7, 7.5, 7, None))
        self.assertEqual(rc.bumper_limit(ahead, rc.SPEED), 0)

    def test_the_kitchen_table_changes_nothing(self):
        import remote_control as rc
        eyes = rc.Bumper()
        self.assertEqual({eyes.look(RemoteDriving.kitchen_table(t // 60 * 60), 0.24) for t in range(0, 20000, 30)}, {None})

    def test_the_same_readings_again_are_not_new(self):
        import remote_control as rc
        eyes = rc.Bumper()                     # one bad set of readings, read ten times round the loop
        self.assertEqual({eyes.look(r) for r in [(None, 9, 9, 9, None)] * 10 + [(None, 17, 17.2, 16.9, None)] * 3}, {None})
        self.assertIsNotNone([eyes.look((None, 9 + i % 2 / 10, 9, 9, None)) for i in range(rc.SURE)][-1], "new ones count")


class SharedSums(RobotTest):
    """The driving sums are copied in JavaScript (docs/bumper.js) for the pretend robot on the web
    page. tests/bumper_vectors.json holds examples with this code's answers, and both sides are
    tested against it (the other side: tests/pretend.test.mjs). After changing ramp, bumper_limit,
    Zone or Bumper: change docs/bumper.js the same way, then write the file again with
        WRITE_VECTORS=1 python3 tests/test_robot.py SharedSums"""
    PATH = os.path.join(REPO, "tests", "bumper_vectors.json")

    def scenes(self):
        wobble = lambda i: (i * 7 % 23) / 10 - 1.1                  # -1.1 .. 1.1, the same every time
        step = 0.24                                                 # cm driven between looks at 8 cm/s
        floor = lambda i: [17 + wobble(i) / 2, 17 - wobble(i), 17 + wobble(i + 3), 17 + wobble(i + 9) / 2, 180]
        wall = [[[min(f, 40 - i * step + w) for f, w in zip(floor(i), (0, wobble(i) / 4, 0, -wobble(i) / 4, 0))], step]
                for i in range(140)]
        table = [[[d if not (i % 40 < 10 and z == 1 + (i // 40) % 3) else 6 + i % 7 for z, d in enumerate(floor(i))], step]
                 for i in range(160)]
        dips = [[floor(i)[:1] + ([12.5, 13, 12] if i % 20 < 2 else floor(i)[1:4]) + [180], step] for i in range(80)]
        leg = [[[None, 17, 30 - i * step, 17, None], step] for i in range(100)]
        nose_down = [[[None, 12 + wobble(i) / 5, 12, 12 - wobble(i) / 5, None], step] for i in range(60)]
        turn = [[[None, 11, 11, 11, None], 0]] * 12 + [[floor(i), 0] for i in range(12)]
        looks = [("driving up to a wall", wall), ("a kitchen table: one zone at a time sees a reflection", table),
                 ("all zones dip for two readings", dips), ("a chair leg dead ahead", leg),
                 ("nose down: it shows closer, and comes no closer", nose_down), ("turning away from a wall onto open floor", turn)]
        zones = [("a wall driven up to", [[30 - i * step, step] for i in range(100)]),
                 ("the floor, standing still then driving", [[17 + wobble(i), step if i > 20 else 0] for i in range(80)]),
                 ("nothing, a blip, nothing", [[None, 0]] * 3 + [[9, 0]] * 3 + [[None, 0]] * 3 + [[9, 0]] * 7),
                 ("the floor shows closer, then normal again", [[12, step]] * 30 + [[17, step]] * 3 + [[12, step]] * 8)]
        ramps = [[0, 8, 0.9, 1.8], [7.5, 8, 0.9, 1.8], [8, 8, 0.9, 1.8], [8, 0, 0.9, 1.8], [1, 0, 0.9, 1.8], [8, -8, 0.9, 1.8],
                 [-8, 8, 0.9, 1.8], [-0.5, 8, 0.9, 1.8], [8, 4, 0.9, 1.8], [-8, -3, 0.9, 1.8], [0, -8, 0.9, 1.8],
                 [0, 90, 16.2, 16.2], [90, -90, 16.2, 16.2], [-10, 0, 16.2, 16.2]]
        limits = [[d, speed] for speed in (8, 13) for d in (None, 0, 5, 7.99, 8, 8.5, 11, 13.9, 14, 100)]
        return looks, zones, ramps, limits

    def test_the_shared_examples_are_this_codes_answers(self):
        import remote_control as rc
        rnd = lambda v: None if v is None else round(v, 6)
        looks, zones, ramps, limits = self.scenes()
        now = {"note": "Examples for docs/bumper.js, with the answers of src/remote_control.py. Written by tests/test_robot.py.",
               "numbers": {k: getattr(rc, k) for k in (
                   "SPEED", "TURBO_SPEED", "TURN", "BUMPER_CM", "SLOW_CM", "FLOOR_SLACK_CM", "FLOOR_PROOF_CM",
                   "CLOSER_CM", "SURE", "ACCEL", "DECEL", "TURN_ACCEL",
                   "STICK_TIMEOUT_MS", "SLOW_FLASH_MS", "STOP_FLASH_MS", "TELEMETRY_MS", "COLORS")},
               "dance": {k: getattr(__import__("dance"), k) for k in ("DISCO", "DANCE_MS", "BEAT_MS", "WIGGLE", "SPIN")},
               "ramp": [r + [rnd(rc.ramp(*r))] for r in ramps],
               "limit": [l + [rnd(rc.bumper_limit(*l))] for l in limits], "looks": [], "zones": []}
        for note, steps in looks:
            eyes = rc.Bumper()
            now["looks"].append({"note": note, "steps": [[[rnd(d) for d in ds], m] for ds, m in steps],
                                 "ahead": [rnd(eyes.look(*s)) for s in steps]})
        for note, steps in zones:
            zone = rc.Zone()
            now["zones"].append({"note": note, "steps": [[rnd(d), m] for d, m in steps],
                                 "seen": [rnd(zone.see(*s)) for s in steps]})
        # the examples must show the interesting things, or they prove little
        by = {scene["note"]: scene["ahead"] for scene in now["looks"]}
        self.assertLess(by["driving up to a wall"][-1], rc.BUMPER_CM)
        self.assertEqual(set(by["a kitchen table: one zone at a time sees a reflection"]), {None})
        self.assertEqual(set(by["all zones dip for two readings"]), {None})
        self.assertEqual(set(by["a chair leg dead ahead"]), {None})
        self.assertIsNone(by["nose down: it shows closer, and comes no closer"][-1])
        self.assertIsNone(by["turning away from a wall onto open floor"][-1])
        if os.environ.get("WRITE_VECTORS"):
            with open(self.PATH, "w") as f:
                json.dump(now, f, separators=(",", ":"))
                f.write("\n")
        with open(self.PATH) as f:
            self.assertEqual(json.load(f), json.loads(json.dumps(now)),
                             "the driving sums changed: see this class's docstring")


class Telemetry(RobotTest):
    ASK = (0, ("T", True))
    drive = RemoteDriving.drive

    def told(self, rc, t):
        """What the robot last said at or before time t."""
        return read_telemetry([p for when, p in rc._link.sent if when <= t and p[1:2] == b"T"][-1])

    def test_packets_match_the_shared_examples(self):
        import remote_control as rc
        with open(os.path.join(REPO, "tests", "telemetry_vectors.json")) as f:
            for case in json.load(f):
                if "sensors" in case:
                    pkt = rc.sensor_packet(**case["sensors"])
                elif "under" in case:
                    pkt = rc.under_packet(**case["under"])
                else:
                    pkt = rc.telemetry_packet(**case["robot"])
                self.assertEqual(pkt.hex(), case["hex"], case["note"])

    def test_request_packet_is_parsed(self):
        import remote_control as rc
        ev = []
        on, off = bytes((0x21, 84, 49, 0)), bytes((0x21, 84, 48, 0))
        data = on + bytes(((~sum(on)) & 0xFF,)) + off + bytes(((~sum(off)) & 0xFF,))
        self.assertEqual(rc.parse_packets(data, ev), b"")
        self.assertEqual(ev, [("T", True), ("T", False)])

    def test_nothing_is_sent_unless_the_page_asks(self):
        robot, rc = self.drive([(0, (5, True))])
        self.assertEqual(rc._link.sent, [])

    def test_about_eight_a_second_with_heading_distance_and_speed(self):
        robot, rc = self.drive([self.ASK, (0, ("J", 0, 100))] + [(t, ("J", 0, 100)) for t in range(150, 3000, 150)],
                               until=3000, heading=lambda t: 400 if t > 2000 else 12.34,
                               distance=lambda t: (3, None, 61.6, 80, 3))
        times = [when for when, p in rc._link.sent if p[1:2] == b"T"]
        self.assertTrue(23 <= len(times) <= 30, len(times))
        self.assertTrue(all(b - a >= rc.TELEMETRY_MS for a, b in zip(times, times[1:])))
        t = self.told(rc, 1500)
        self.assertEqual((t["heading"], t["distance"], t["speed"], t["turn"]), (12.3, None, rc.SPEED, 0))
        self.assertEqual((t["left"], t["right"]), (WHITE, WHITE))
        self.assertEqual((t["turbo"], t["bumper"], t["blocked"], t["dancing"]), (False, True, False, False))
        self.assertEqual(self.told(rc, 2900)["heading"], 40, "heading wraps to -180..180")

    def test_toggles_blocked_and_lights_are_reported(self):
        def distance(t):
            d = 100 if t < 2000 else 5
            return (None, d, d, d, None)
        robot, rc = self.drive([self.ASK, (100, (2, True)), (200, (1, True)), (300, (5, True)), (3000, (4, True))],
                               until=3900, distance=distance)
        t = self.told(rc, 1900)
        self.assertEqual((t["turbo"], t["bumper"], t["blocked"], t["speed"]), (True, True, False, rc.TURBO_SPEED))
        self.assertEqual(t["left"], RED, "button 1: white -> red")
        t = self.told(rc, 2900)
        self.assertEqual((t["blocked"], t["speed"], t["distance"]), (True, 0, 5))
        self.assertIn(t["left"], (RED, OFF), "flashing")
        t = self.told(rc, 3800)
        self.assertEqual((t["bumper"], t["blocked"], t["speed"]), (False, False, rc.TURBO_SPEED))

    def test_dance_reports_both_colours_and_the_spin(self):
        robot, rc = self.drive([self.ASK, (500, (3, True))], until=6000)
        t = self.told(rc, 1000)
        self.assertTrue(t["dancing"])
        self.assertNotEqual(t["left"], t["right"])
        self.assertEqual(robot.colour_at(1000), (t["left"], t["right"]), "says what the LEDs really show")
        self.assertEqual(self.told(rc, 4300)["turn"], 360)
        t = self.told(rc, 5500)
        self.assertEqual((t["dancing"], t["left"], t["turn"]), (False, WHITE, 0))

    def test_sensors_and_under_packets_follow_each_telemetry_packet(self):
        def setup_distance(t):
            return (40, None, 12.4, 300, 7)
        import remote_control
        remote_control._link = TimedLink([self.ASK])
        robot = FakeAlvik()
        robot.distance, robot.tilt, robot.battery = setup_distance, (-12.4, 30.6), 67
        robot.lines, robot.colour, robot.bottom, robot.top = (52, 610, 1023), (0.52, 0.32, 0.22), 7.4, None
        robot.presses = [(1000, 10 ** 9, "cancel")]
        remote_control.run_remote(robot)
        kinds = [p[1:2] for when, p in remote_control._link.sent]
        self.assertEqual(kinds[:6], [b"T", b"S", b"U", b"T", b"S", b"U"])
        s = remote_control._link.sent[1][1]
        self.assertEqual(len(s), 11)
        self.assertEqual((~sum(s[:10])) & 0xFF, s[10])
        self.assertEqual(list(s[2:7]), [40, 255, 12, 254, 7])
        self.assertEqual((s[7] - 256, s[8], s[9]), (-12, 31, 67))
        u = remote_control._link.sent[2][1]
        self.assertEqual(len(u), 11)
        self.assertEqual((~sum(u[:10])) & 0xFF, u[10])
        self.assertEqual(list(u[2:10]), [13, 152, 254, 52, 32, 22, 7, 255])

    def test_a_broken_colour_calibration_does_not_stop_the_driving(self):
        import remote_control
        remote_control._link = TimedLink([self.ASK, (0, (5, True))])
        robot = FakeAlvik()
        robot.colour, robot.lines, robot.bottom = "broken", (52, 52, 52), 7
        robot.presses = [(2000, 10 ** 9, "cancel")]
        self.assertEqual(remote_control.run_remote(robot), -1)
        self.assertEqual([d for d in robot.drives if d[0] <= 1500][-1][1], remote_control.SPEED)
        u = [p for when, p in remote_control._link.sent if p[1:2] == b"U"][-1]
        self.assertEqual(list(u[2:10]), [13, 13, 13, 255, 255, 255, 7, 255])

    def test_under_packet_copes_with_a_robot_that_knows_nothing_yet(self):
        robot, rc = self.drive([self.ASK], until=500)      # the pretend Alvik starts with no readings
        u = [p for when, p in rc._link.sent if p[1:2] == b"U"][0]
        self.assertEqual(list(u[2:10]), [0, 0, 0, 255, 255, 255, 255, 255])

    def test_a_new_phone_has_to_ask_again(self):
        robot, rc = self.drive([self.ASK, (1000, "lost")], until=3000)
        self.assertTrue(rc._link.sent)
        self.assertLessEqual(max(when for when, p in rc._link.sent), 1000)


class WioPackets(RobotTest):
    """The Wio Terminal remote (remotes/wio_remote) speaks the same packets as the web remote: what it
    builds goes through the robot's own parse_packets, and what it reads matches telemetry_vectors.json.
    Needs a C++ compiler (g++ or c++); skipped without one."""

    def setUp(self):
        cxx = shutil.which("g++") or shutil.which("c++")
        if not cxx:
            self.skipTest("no C++ compiler")
        super().setUp()                         # puts the robot's src/ on the path, for parse_packets
        import subprocess
        self.tmp = tempfile.mkdtemp()
        exe = os.path.join(self.tmp, "harness")
        subprocess.run([cxx, "-std=c++11", "-o", exe,
                        os.path.join(REPO, "tests", "wio_packets_harness.cpp")], check=True)
        with open(os.path.join(REPO, "tests", "telemetry_vectors.json")) as f:
            self.vectors = json.load(f)
        run = subprocess.run([exe], input="\n".join(v["hex"] for v in self.vectors) + "\n",
                             capture_output=True, text=True, check=True)
        self.lines = run.stdout.split("\n")

    def tearDown(self):
        shutil.rmtree(getattr(self, "tmp", ""), ignore_errors=True)
        super().tearDown()

    def test_what_it_reads_matches_the_page(self):
        read = [l for l in self.lines if l[:2] in ("T ", "S ", "U ")]
        self.assertEqual(len(read), len(self.vectors), "every example packet is read once, junk and pieces or not")
        none = lambda v: -1 if v is None else v
        for line, v in zip(read, self.vectors):
            p, f = v["page"], line.split()
            if f[0] == "T":
                want = ["%.1f" % p["heading"], str(none(p["distance"])), "".join(map(str, p["left"])),
                        "".join(map(str, p["right"])), "%.1f" % p["speed"], str(p["turn"])] + \
                       [str(int(p[k])) for k in ("turbo", "bumper", "blocked", "dancing")]
            elif f[0] == "S":
                want = [str(none(z)) for z in p["zones"]] + [str(p["roll"]), str(p["pitch"]), str(none(p["battery"]))]
            else:
                floor = p["floor"] or [None] * 3
                want = [str(none(x)) for x in p["lines"]] + \
                       [str(-1 if x is None else int(round(x * 100))) for x in floor] + [str(none(p["bottom"])), str(none(p["top"]))]
            self.assertEqual(f[1:], want, v["note"])

    def test_what_it_sends_the_robot_understands(self):
        import remote_control as rc
        out = b"".join(bytes.fromhex(l[4:]) for l in self.lines if l.startswith("OUT "))
        ev = []
        self.assertEqual(rc.parse_packets(out, ev), b"")
        self.assertEqual(ev, [("J", 0, 100), ("J", -100, 0), ("J", 50, -100), ("J", 100, -100), ("J", 0, 0),
                              (1, True), (1, False), (2, True), (2, False), (3, True), (3, False), (4, True), (4, False),
                              ("T", True)])

if __name__ == "__main__":
    unittest.main(verbosity=2)
