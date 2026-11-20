# 🐕 Follow me: the robot is a puppy that follows your hand (or your feet).
# It looks with the 5 distance sensors on its front (left, centre-left, centre, centre-right, right),
# turns towards the closest thing it sees, and tries to stay NEAR_CM away from it.
#   green = following · yellow = can't see anyone, sitting and waiting
# ✗ goes back to the menu.

from time import sleep_ms

NEAR_CM = 15       # how close the puppy likes to be
SEE_CM = 40        # further than this, it can't see you
MAX_SPEED = 10     # cm/s
TURN = 40          # deg/s for each sensor away from the middle

FOLLOWING = (0, 1, 0)
WAITING = (1, 1, 0)


def lights(alvik, rgb):
    alvik.left_led.set_color(*rgb)
    alvik.right_led.set_color(*rgb)


def run(alvik):
    readings = alvik.get_distance()                  # cm, or None if a sensor has no reading yet
    readings = [SEE_CM + 1 if d is None else d for d in readings]
    closest = min(readings)
    where = readings.index(closest)                  # 0 = far left ... 2 = middle ... 4 = far right

    if closest > SEE_CM:
        lights(alvik, WAITING)
        alvik.brake()
    else:
        lights(alvik, FOLLOWING)
        speed = max(-MAX_SPEED, min(MAX_SPEED, closest - NEAR_CM))   # too far: forward, too close: back up
        turn = (2 - where) * TURN                                    # positive = turn left
        alvik.drive(speed, turn)

    sleep_ms(50)
    return 1
