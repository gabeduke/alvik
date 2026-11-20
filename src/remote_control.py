# Phone remote mode for the Alvik demo menu.
# Uses the free Adafruit "Bluefruit Connect" app (iOS / Android):
#   connect to "Alvik"  ->  Controller  ->  Control Pad
#
#   Arrows : drive while held (Up+Left etc. curves)
#   Joystick (web remote only): push a little = slow, push a lot = fast
#   1      : change headlight colour
#   2      : turbo on / off
#   3      : disco dance (flashing lights, wiggle, then a spin)
#   4      : bumper on / off (stops before driving into things — on by default)
#
# Lights while in this mode: yellow = waiting for a phone, then your headlight colour.
# Press the robot's X (cancel) touch button to go back to the menu.

import bluetooth
from time import sleep_ms, ticks_ms, ticks_diff
from micropython import const

from dance import Dance

# ---------- tweakables ----------
ROBOT_NAME = "Alvik"
SPEED = 8            # cm/s
TURBO_SPEED = 13     # cm/s (about Alvik's top speed)
TURN = 90            # deg/s
BUMPER_CM = 12       # stop when something is closer than this in front
SLOW_CM = 30         # start slowing down when something is closer than this
ACCEL = 30           # cm/s per second: how gently it speeds up
DECEL = 60           # cm/s per second: how quickly it slows down
TURN_ACCEL = 540     # deg/s per second, for turning
STICK_TIMEOUT_MS = 600   # joystick goes quiet for this long -> stop (the page froze or went away)
COLORS = [(1, 1, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 0), (0, 0, 0)]
# the dance itself (lights, wiggle, spin) is in dance.py

# ---------- Bluetooth: Nordic UART Service (what Bluefruit Connect talks to) ----------
_IRQ_CONNECT = const(1)
_IRQ_DISCONNECT = const(2)
_IRQ_WRITE = const(3)
_UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_NOTIFY)
_UART_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"),
            bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE)


def _field(t, v):
    return bytes((len(v) + 1, t)) + v


def parse_packets(buf, events):
    """Pull packets out of buf, append them to events, return leftover bytes.
    Control Pad button:  '!' 'B' <'1'-'8'> <'1' down/'0' up> <checksum>  -> (button, pressed)
    Joystick (web page): '!' 'J' <x> <y> <checksum>                       -> ("J", x, y)
    x and y are signed bytes, -100..100: x right, y forward.
    Checksum = ~(sum of the first 4 bytes) & 0xFF."""
    while True:
        i = buf.find(b"!")
        if i < 0:
            return b""
        if len(buf) - i < 2:
            return buf[i:]
        kind = buf[i + 1]
        if kind != 66 and kind != 74:          # not 'B' or 'J'
            buf = buf[i + 1:]
            continue
        if len(buf) - i < 5:
            return buf[i:]
        pkt = buf[i:i + 5]
        if (~sum(pkt[:4])) & 0xFF != pkt[4]:
            buf = buf[i + 1:]                  # damaged: look for the next '!'
            continue
        buf = buf[i + 5:]
        if kind == 66:
            events.append((pkt[2] - 48, pkt[3] == 49))
        else:
            events.append(("J", _stick(pkt[2]), _stick(pkt[3])))


def _stick(byte):
    v = byte - 256 if byte > 127 else byte
    return max(-100, min(100, v))


def ramp(now, want, step_up, step_down):
    """Move 'now' towards 'want': by at most step_up when speeding up, step_down when slowing.
    Changing direction slows to zero first."""
    if want == now:
        return now
    if now != 0 and (want == 0 or (want > 0) != (now > 0) or abs(want) < abs(now)):
        target = want if (want > 0) == (now > 0) else 0      # slowing down
        if abs(now - target) <= step_down:
            return target
        return now - step_down if now > target else now + step_down
    if abs(want - now) <= step_up:
        return want
    return now + step_up if want > now else now - step_up


def bumper_limit(distances, speed):
    """Fastest we may go forward given what's in front: full speed beyond SLOW_CM,
    slower as it gets closer, 0 inside BUMPER_CM."""
    front = [x for x in distances[1:4] if x is not None]
    if not front:
        return speed
    d = min(front)
    if d < BUMPER_CM:
        return 0
    if d >= SLOW_CM:
        return speed
    return max(2, speed * (d - BUMPER_CM) / (SLOW_CM - BUMPER_CM))


class PhoneLink:
    def __init__(self, name):
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        ((self._tx, self._rx),) = self.ble.gatts_register_services(
            ((_UART_UUID, (_UART_TX, _UART_RX)),))
        self.ble.gatts_set_buffer(self._rx, 64, True)
        self._adv = _field(0x01, b"\x06") + _field(0x09, name.encode()) + \
            _field(0x07, bytes(_UART_UUID))
        self.conn = None
        self.lost = False
        self.buf = b""
        self.events = []
        self.listening = False

    def start(self):
        self.listening = True
        self.events.clear()
        if self.conn is None:
            self.ble.gap_advertise(100_000, adv_data=self._adv)

    def stop(self):
        self.listening = False
        self.ble.gap_advertise(None)
        if self.conn is not None:
            try:
                self.ble.gap_disconnect(self.conn)
            except OSError:
                pass

    def _irq(self, event, data):
        # Keep this short; the main loop does the robot work.
        if event == _IRQ_CONNECT:
            self.conn = data[0]
        elif event == _IRQ_DISCONNECT:
            self.conn = None
            self.lost = True
            if self.listening:
                self.ble.gap_advertise(100_000, adv_data=self._adv)
        elif event == _IRQ_WRITE:
            self.buf = parse_packets(self.buf + self.ble.gatts_read(self._rx), self.events)


_link = None  # created once, reused each time the mode is picked


def _lights(alvik, rgb):
    alvik.left_led.set_color(*rgb)
    alvik.right_led.set_color(*rgb)


def run_remote(alvik):
    """Runs until the robot's cancel (X) button is pressed. Returns -1 so the menu
    loop exits back to the menu."""
    global _link
    if _link is None:
        _link = PhoneLink(ROBOT_NAME)
    _link.start()

    held = set()          # arrows held: 5 up, 6 down, 7 left, 8 right
    turbo = False
    bumper = True
    color_i = 0
    dance = Dance(alvik)
    dancing = False
    was_connected = False
    blocked = False
    stick = (0, 0)        # joystick from the web page: (x right, y forward), each -100..100
    stick_at = 0
    linear = angular = 0  # what the wheels are doing now (ramps towards what's asked for)
    last = ticks_ms()

    _lights(alvik, (1, 1, 0))   # yellow: waiting for a phone

    while not alvik.get_touch_cancel():
        connected = _link.conn is not None
        if connected and not was_connected:
            _lights(alvik, COLORS[color_i])
        was_connected = connected

        if _link.lost:              # phone went away -> stop right away
            _link.lost = False
            held.clear()
            stick = (0, 0)
            dance.stop()
            dancing = False
            alvik.brake()
            _lights(alvik, (1, 1, 0))

        while _link.events:
            event = _link.events.pop(0)
            button, pressed = event[0], event[1]
            if button == "J":
                stick = (event[1], event[2])
                stick_at = ticks_ms()
                if stick != (0, 0):
                    dance.stop()           # the joystick stops the dance too
            elif button in (5, 6, 7, 8):
                if pressed:
                    held.add(button)
                else:
                    held.discard(button)
                dance.stop()               # arrows stop the dance (lights come back next tick)
            elif pressed and button == 1:
                color_i = (color_i + 1) % len(COLORS)
                _lights(alvik, COLORS[color_i])
            elif pressed and button == 2:
                turbo = not turbo
            elif pressed and button == 3:
                dance.begin()
                dancing = True
            elif pressed and button == 4:
                bumper = not bumper
                _lights(alvik, (0, 1, 0) if bumper else (1, 0, 0))   # quick green/red flash
                sleep_ms(300)
                _lights(alvik, COLORS[color_i])

        now = ticks_ms()
        dt = min(ticks_diff(now, last), 200) / 1000
        last = now
        if stick != (0, 0) and ticks_diff(now, stick_at) > STICK_TIMEOUT_MS:
            stick = (0, 0)                 # the page stopped talking: don't keep driving

        # work out what's being asked for this tick
        move = dance.step() if dancing else None
        if move:
            linear, angular = move         # the dance is meant to be jerky: no ramp
            want_linear = linear
        else:
            if dancing:                    # dance just ended -> back to normal lights
                dancing = False
                _lights(alvik, COLORS[color_i])
            speed = TURBO_SPEED if turbo else SPEED
            want_linear = (speed if 5 in held else 0) - (speed if 6 in held else 0) \
                + speed * stick[1] / 100
            want_angular = (TURN if 7 in held else 0) - (TURN if 8 in held else 0) \
                - TURN * stick[0] / 100
            want_linear = max(-speed, min(speed, want_linear))
            want_angular = max(-TURN, min(TURN, want_angular))
            linear = ramp(linear, want_linear, ACCEL * dt, DECEL * dt)
            angular = ramp(angular, want_angular, TURN_ACCEL * dt, TURN_ACCEL * dt)

        # bumper: slow down near things, and don't drive forward into them
        now_blocked = False
        if bumper and (linear > 0 or want_linear > 0):
            limit = bumper_limit(alvik.get_distance(), TURBO_SPEED if turbo else SPEED)
            if linear > limit:
                linear = limit             # right away, no ramp
            now_blocked = limit == 0
        if now_blocked != blocked:
            _lights(alvik, (1, 0, 0) if now_blocked else COLORS[color_i])
            blocked = now_blocked

        alvik.drive(linear, angular)
        sleep_ms(30)

    alvik.brake()
    _link.stop()
    return -1
