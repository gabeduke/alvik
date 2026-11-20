# 🪩 Disco: the robot dances (the same dance as button 3 on the phone remote, from dance.py).
# ✓ dances again · ✗ goes back to the menu.

from time import sleep_ms

from dance import dance

READY = (1, 1, 1)   # white: ready to dance again


def run(alvik):
    dance(alvik)
    alvik.left_led.set_color(*READY)
    alvik.right_led.set_color(*READY)
    while not alvik.get_touch_cancel():
        if alvik.get_touch_ok():
            return 1        # the menu calls run() again: another dance
        sleep_ms(50)
    return -1               # ✗: back to the menu
