# ✏️ Doodle: the robot draws with a felt pen.
# It needs the printed pen holder on the robot's right side (models/addons/README.md).
#   ◀ ▶ pick a shape: green = square · yellow = triangle · purple = star · blue = ring
#   ✓ draws it · ✗ stops and goes back to the menu
#
# The trick is at the corners. A robot that spins on the spot swings its pen round in a curve.
# This one drives forward a little while it turns, just fast enough that the PEN stays on its
# spot and the robot swings round the pen. So the corners come out sharp.

from math import pi
from time import sleep_ms, ticks_ms, ticks_diff

PEN_CM = 5.7        # from the middle of the robot sideways to the pen's tip: measure yours
SIDE_CM = 12        # how long each line is
SPEED = 6           # cm/s along a line
TURN = 45           # deg/s at a corner

SHAPES = [          # (light, how many lines, degrees to turn right at each corner)
    ((0, 1, 0), 4, 90),      # square
    ((1, 1, 0), 3, 120),     # triangle
    ((1, 0, 1), 5, 144),     # star
    ((0, 0, 1), 0, 360),     # ring: no lines, one spin on the spot
]

choice = 0
ok_before = True
last_call = None


def lights(alvik, rgb):
    alvik.left_led.set_color(*rgb)
    alvik.right_led.set_color(*rgb)


def line(alvik, cm):
    """Straight ahead for cm. False if ✗ stopped it."""
    alvik.drive(SPEED, 0)
    start = ticks_ms()
    while ticks_diff(ticks_ms(), start) < cm / SPEED * 1000:
        if alvik.get_touch_cancel():
            alvik.brake()
            return False
        sleep_ms(10)
    alvik.brake()
    return True


def turn(alvik, degrees, forward):
    """Turns right by this many degrees while driving forward at `forward` cm/s.
    It asks the robot which way it points and stops when it has turned enough. False if ✗ stopped it."""
    alvik.drive(forward, -TURN)
    start = ticks_ms()
    turned = 0
    before = alvik.get_pose()[2]                   # degrees, counting up to the left
    while turned < degrees and ticks_diff(ticks_ms(), start) < degrees / TURN * 2000:
        if alvik.get_touch_cancel():
            alvik.brake()
            return False
        sleep_ms(10)
        now = alvik.get_pose()[2]
        turned += (before - now + 180) % 360 - 180  # the short way round, so 179 to -179 is 2, not 358
        before = now
    alvik.brake()
    return True


def draw(alvik, lines, corner):
    if lines == 0:
        return turn(alvik, corner, 0)              # on the spot: the pen goes round the robot
    round_the_pen = TURN * pi / 180 * PEN_CM       # cm/s: how fast the robot's middle goes round the pen
    for _ in range(lines):
        if not line(alvik, SIDE_CM):
            return False
        sleep_ms(200)
        if not turn(alvik, corner, round_the_pen):
            return False
        sleep_ms(200)
    return True


def run(alvik):
    global choice, ok_before, last_call
    if last_call is None or ticks_diff(ticks_ms(), last_call) > 500:
        ok_before = True                           # just came in: that ✓ was for the menu, not for us
    light, lines, corner = SHAPES[choice]
    lights(alvik, light)

    ok = alvik.get_touch_ok()
    if alvik.get_touch_right() or alvik.get_touch_left():
        choice = (choice + (1 if alvik.get_touch_right() else -1)) % len(SHAPES)
        lights(alvik, SHAPES[choice][0])
        while alvik.get_touch_right() or alvik.get_touch_left():
            sleep_ms(50)
    elif ok and not ok_before:
        sleep_ms(500)                              # time to take your finger away
        if not draw(alvik, lines, corner):
            return -1                              # ✗: back to the menu
    ok_before = ok

    sleep_ms(50)
    last_call = ticks_ms()
    return 1
