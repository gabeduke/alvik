# The colour menu. ⬆ / ⬇ pick a program (the lights show which one), ✓ runs it, ✗ comes back.
#
#   red = touch-move · blue = line follower · green = hand follower · purple = phone remote
#   then one entry per installed sketch (/sketches/<name>/, see sketchbook.py), in its own colour.
#
# More than 6 entries? They come in pages of 6. On page 2 the light blinks off once every
# 2 seconds, on page 3 twice, and so on. Page 1 doesn't blink.
#
# A program is run(alvik): the menu calls it over and over until ✗ is pressed. If it returns a
# negative number the menu comes back right away. If it crashes, the lights flash red and the
# menu comes back (the error is printed over USB).

from arduino_alvik import ArduinoAlvik
from time import sleep_ms, ticks_ms

from line_follower import run_line_follower
from touch_move import run_touch_move
from hand_follower import run_hand_follower
from remote_control import run_remote
import sketchbook

RED = (1, 0, 0)
OFF = (0, 0, 0)
PAGE = 6            # entries per page
START = 1           # blue: where the menu starts

MENU = [            # (colour, program)
    (RED, run_touch_move),
    ((0, 0, 1), run_line_follower),
    ((0, 1, 0), run_hand_follower),
    ((1, 0, 1), run_remote),
]
for sketch in sketchbook.find():
    print("sketch", len(MENU), sketch["name"], sketch["color"])
    MENU.append((sketch["color"], sketchbook.runner(sketch)))


alvik = ArduinoAlvik()
alvik.begin()


def lights(rgb):
    alvik.left_led.set_color(*rgb)
    alvik.right_led.set_color(*rgb)


def menu_light(i):
    """The colour entry i shows right now: on page 2+ it blinks off <page - 1> times every 2 s."""
    page = i // PAGE
    t = ticks_ms() % 2000
    if t < page * 400 and t % 400 < 200:
        return OFF
    return MENU[i][0]


def oops():
    """Something went wrong: flash red three times."""
    alvik.brake()
    for _ in range(3):
        lights(RED)
        sleep_ms(200)
        lights(OFF)
        sleep_ms(200)


def run_program(run):
    try:
        while not alvik.get_touch_cancel():
            result = run(alvik)
            if result is not None and result < 0:
                break
    except Exception as e:      # not KeyboardInterrupt: Ctrl-C over USB still stops the menu
        print("program crashed:")
        sketchbook.report(e)
        oops()


def wait_release(button):
    while button():
        sleep_ms(100)


choice = START
shown = None

while True:
    try:
        light = menu_light(choice)
        if light != shown:
            lights(light)
            shown = light

        if alvik.get_touch_ok():
            lights(OFF)
            sleep_ms(500)
            run_program(MENU[choice][1])
            lights(OFF)
            sleep_ms(500)
            alvik.brake()
            shown = None

        if alvik.get_touch_up() and choice < len(MENU) - 1:
            choice += 1
            shown = MENU[choice][0]
            lights(shown)
            wait_release(alvik.get_touch_up)
        if alvik.get_touch_down() and choice > 0:
            choice -= 1
            shown = MENU[choice][0]
            lights(shown)
            wait_release(alvik.get_touch_down)

        sleep_ms(100)

    except KeyboardInterrupt as e:
        print('over')
        alvik.stop()
        break
