# The disco dance: flashing lights, wiggle back and forth, then a big spin.
# Used by the phone remote (button 3) and by the Disco sketch (sketches/disco).
#
#   d = Dance(alvik)
#   d.begin()
#   move = d.step()          # call often: sets the lights, returns (linear, angular) or None when done
#
# or just dance(alvik) to do one whole dance (✗ stops it early).

from time import sleep_ms, ticks_ms, ticks_diff

DISCO = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 0)]  # bright colours
DANCE_MS = 4000      # whole dance
BEAT_MS = 250        # lights change every beat; direction flips every 2 beats
WIGGLE = 120         # deg/s while wiggling back and forth
SPIN = 360           # deg/s for the big finish (the last second)


class Dance:
    def __init__(self, alvik):
        self.alvik = alvik
        self.start = None     # None = not dancing
        self.beat = -1
        self.lights = ((0, 0, 0), (0, 0, 0))   # (left, right) colours of the current beat

    def begin(self):
        self.start = ticks_ms()
        self.beat = -1

    def stop(self):
        self.start = None

    def step(self):
        """Sets the disco lights for now and returns (linear cm/s, angular deg/s),
        or None when the dance is over (or was never started)."""
        if self.start is None:
            return None
        t = ticks_diff(ticks_ms(), self.start)
        if t >= DANCE_MS:
            self.start = None
            return None
        beat = t // BEAT_MS
        if beat != self.beat:          # left and right get different colours
            self.beat = beat
            self.lights = (DISCO[beat % len(DISCO)], DISCO[(beat + 3) % len(DISCO)])
            self.alvik.left_led.set_color(*self.lights[0])
            self.alvik.right_led.set_color(*self.lights[1])
        if DANCE_MS - t < 1000:
            return 0, SPIN
        return 0, WIGGLE if (beat // 2) % 2 == 0 else -WIGGLE


def dance(alvik):
    """One whole dance. Returns early if ✗ is pressed."""
    d = Dance(alvik)
    d.begin()
    while not alvik.get_touch_cancel():
        move = d.step()
        if move is None:
            break
        alvik.drive(*move)
        sleep_ms(30)
    alvik.brake()
