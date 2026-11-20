# 🙀 Scaredy cat: stands still until something comes close in front, then backs away from it.
#   green = all calm · red = too close, backing away
# ✗ goes back to the menu.
# This is the program written step by step in lesson 8 (docs/learn/8-sketch.html).

from time import sleep_ms

TOO_CLOSE_CM = 15    # closer than this is scary (any more and it would be scared of the floor: lesson 5)
BACK_SPEED = 8       # cm/s

CALM = (0, 1, 0)
SCARED = (1, 0, 0)


def lights(alvik, rgb):
    alvik.left_led.set_color(*rgb)
    alvik.right_led.set_color(*rgb)


def run(alvik):
    middle = alvik.get_distance()[2]          # cm to whatever is straight ahead, or None for nothing
    if middle is not None and middle < TOO_CLOSE_CM:
        lights(alvik, SCARED)
        alvik.drive(-BACK_SPEED, 0)           # backwards, without turning
    else:
        lights(alvik, CALM)
        alvik.brake()
    sleep_ms(50)
