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
    def get_distance(self): return self.distance(CLOCK.now)
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
        def distance(t):                      # a wall coming closer, then gone
            d = 100 if t < 1000 else 21 if t < 2000 else 5 if t < 3000 else 100
            return (None, d, d, d, None)
        robot, rc = self.drive([(0, (5, True))], until=3900, distance=distance)
        self.assertEqual(self.at(robot, 900)[0], rc.SPEED)
        self.assertAlmostEqual(self.at(robot, 1500)[0], rc.SPEED / 2)
        self.assertEqual(self.at(robot, 2040)[0], 0, "stops at once")
        slowing = [rgb for t, side, rgb in robot.leds if side == "L" and 1000 < t < 2000]
        self.assertEqual(set(slowing), {RED, WHITE}, "blinks red while slowing down")
        stopped = [(t, rgb) for t, side, rgb in robot.leds if side == "L" and 2040 < t < 3000]
        self.assertEqual({rgb for t, rgb in stopped}, {RED, OFF}, "flashes red when stopped")
        self.assertGreater(len(stopped), 1.5 * len(slowing), "and faster")
        self.assertEqual(robot.colour_at(3800)[0], WHITE)
        self.assertGreater(self.at(robot, 3800)[0], 0, "drives on when the way is clear")

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

    def test_open_floor_is_not_something_in_the_way(self):
        robot, rc = self.drive([(0, (5, True))], until=6000, distance=self.open_floor)
        self.assertEqual(self.at(robot, 1000)[0], rc.SPEED)
        self.assertEqual({l for t, l, a in robot.drives if 1000 <= t < 6000}, {rc.SPEED}, "never slows down")
        self.assertNotIn(RED, [rgb for t, side, rgb in robot.leds], "and never warns")

    def test_a_wall_is_still_slowed_for_and_stopped_at_past_where_the_floor_shows(self):
        robot = None

        def distance(t):                      # open floor, with a wall 70 cm ahead that the robot drives up to
            floor = self.open_floor(t)
            wall = 70 - FakeAlvik.current.travelled(t)
            return tuple(wall if wall < 45 else f for f in floor)
        robot, rc = self.drive([(0, (5, True))], until=30000, distance=distance)
        seen = [(70 - robot.travelled(t), l) for t, l, a in robot.drives if t > 1000]
        self.assertTrue(all(l == rc.SPEED for wall, l in seen if wall > rc.SLOW_CM + 1), "full speed until 30 cm")
        self.assertTrue(all(l < rc.SPEED for wall, l in seen if wall < rc.SLOW_CM - 1), "then always slower")
        for cm in (25, 21, 19, 17, 15, 13):   # no letting go where the floor shows (14 to 20 cm)
            wall, l = min(seen, key=lambda x: abs(x[0] - cm))
            self.assertAlmostEqual(l, max(2, rc.SPEED * (wall - rc.BUMPER_CM) / (rc.SLOW_CM - rc.BUMPER_CM)), delta=0.2, msg=cm)
        self.assertEqual(seen[-1][1], 0, "stopped")
        self.assertTrue(rc.BUMPER_CM - 0.5 < seen[-1][0] <= rc.BUMPER_CM, seen[-1][0])

    def test_turning_away_from_a_wall_onto_open_floor_lets_go(self):
        def distance(t):                      # a wall 26 cm ahead; at 2 s the robot has turned away from it
            return (26 - FakeAlvik.current.travelled(t),) * 5 if t < 2000 else self.open_floor(t)
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
    """Zone.see: one zone of the distance sensor, with the floor taken out."""

    def zone(self):
        import remote_control as rc
        return rc.Zone(), rc

    def test_the_floor_is_nothing_standing_or_driving(self):
        zone, rc = self.zone()
        for i in range(400):
            reading = 16 + (i * 7 % 23) / 10
            self.assertIsNone(zone.see(reading, moved=0.25 if i > 50 else 0), reading)

    def test_far_readings_and_nothing_pass_straight_through(self):
        zone, rc = self.zone()
        self.assertEqual([zone.see(d) for d in (None, 180, 35.5, 30, None)], [None, 180, 35.5, 30, None])

    def test_a_wall_driven_up_to_stays_a_wall_through_where_the_floor_shows(self):
        zone, rc = self.zone()
        for d in (17, 17.4, 16.8):
            self.assertIsNone(zone.see(d, 0.25))
        got = []
        d = 45
        while d > 9:
            got.append((d, zone.see(d + (0.4 if int(d * 4) % 2 else -0.4), 0.25)))
            d -= 0.25
        self.assertTrue(all(seen is not None for d, seen in got if d < rc.SLOW_CM - 1), [g for g in got if g[1] is None])

    def test_closer_than_the_bumper_distance_counts_at_once(self):
        zone, rc = self.zone()
        self.assertEqual(zone.see(11), 11)
        self.assertEqual(zone.see(12.5), 12.5, "and backing off a little it is still that thing")

    def test_one_odd_reading_is_not_a_thing_but_two_are(self):
        zone, rc = self.zone()
        self.assertEqual([zone.see(d) for d in (17, 25, 17, 17)], [None] * 4)
        self.assertEqual([zone.see(d) for d in (25, 25, 24.8)], [None, 25, 24.8])

    def test_a_thing_that_comes_no_closer_as_we_drive_at_it_is_the_floor(self):
        zone, rc = self.zone()                 # a thick carpet, or a nose-up robot: the floor shows at 23 cm
        seen = [zone.see(23 + (i % 3) * 0.3, 0.2) for i in range(60)]
        self.assertEqual(seen[1], 23.3, "taken for a thing at first")
        gone = seen.index(None, 1)
        self.assertLessEqual(gone * 0.2, rc.FLOOR_PROOF_CM + 0.5, "let go after driving this far")
        self.assertEqual(set(seen[gone:]), {None}, "and it stays the floor")
        self.assertIsNone(zone.see(22.5), "standing still too")
        self.assertEqual([zone.see(d, 0.2) for d in (19.5, 19, 18.5)], [None, 19, 18.5], "something nearer than that floor is a thing")

    def test_a_wobble_in_the_floor_reading_does_not_stick(self):
        zone, rc = self.zone()                 # the real robot's left zone: 15 to 20.6 cm on a still floor
        self.assertEqual([zone.see(d) for d in (17, 20.4, 20.6, 19.8, 17.2, 16)], [None, None, 20.6, None, None, None])

    def test_standing_still_nothing_is_decided(self):
        zone, rc = self.zone()
        self.assertEqual([zone.see(24) for _ in range(200)][-1], 24, "a thing stays a thing until we drive at it")

    def test_a_wall_met_at_an_angle_keeps_coming_closer_slowly_and_stays_a_wall(self):
        zone, rc = self.zone()
        d, seen = 29.0, []
        while d > 13:
            seen.append(zone.see(d, 0.25))
            d -= 0.12                          # half as fast as we drive
        self.assertNotIn(None, seen[1:])

    def test_looking_somewhere_else_it_is_the_floor_again(self):
        zone, rc = self.zone()
        for d in (25, 24.5, 24):               # a wall
            zone.see(d, 0.25)
        self.assertIsNone(zone.see(17.2, 0.25), "the wall slid out of view: a jump down to the floor")
        zone, rc = self.zone()
        d = 26
        while d >= 20:                         # a wall driven up to, close to where the floor shows: no jump when it goes
            zone.see(d, 0.25)
            d -= 0.25
        seen = [zone.see(18.5, 0, turned=3) for _ in range(4)]
        self.assertEqual(seen[:2], [18.5, 18.5], "not yet")
        self.assertIsNone(seen[-1], "but after turning away it is")
        self.assertEqual([zone.see(d, 0, turned=3) for d in (26, 26, 26, 26, 26)], [None, 26, 26, 26, 26],
                         "turning with a real thing in view: it stays")


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
        self.assertEqual((t["heading"], t["distance"], t["speed"], t["turn"]), (12.3, 62, rc.SPEED, 0))
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
