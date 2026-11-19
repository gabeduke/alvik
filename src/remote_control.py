# Phone remote mode for the Alvik demo menu.
# Uses the free Adafruit "Bluefruit Connect" app (iOS / Android):
#   connect to "Alvik"  ->  Controller  ->  Control Pad
#
#   Arrows : drive while held (Up+Left etc. curves)
#   1      : change headlight colour
#   2      : turbo on / off
#   3      : disco dance (flashing lights, wiggle, then a spin)
#   4      : bumper on / off (stops before driving into things — on by default)
#
# Lights while in this mode: yellow = waiting for a phone, then your headlight colour.
# Press the robot's X (cancel) touch button to go back to the menu.

import bluetooth
from time import sleep_ms, ticks_ms, ticks_add, ticks_diff
from micropython import const

# ---------- tweakables ----------
ROBOT_NAME = "Alvik"
SPEED = 8            # cm/s
TURBO_SPEED = 13     # cm/s (about Alvik's top speed)
TURN = 90            # deg/s
BUMPER_CM = 12       # stop when something is closer than this in front
COLORS = [(1, 1, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 0), (0, 0, 0)]
DISCO = COLORS[1:7]  # bright colours only
DANCE_MS = 4000      # whole dance
BEAT_MS = 250        # lights change every beat; direction flips every 2 beats
WIGGLE = 120         # deg/s while wiggling back and forth

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
    """Pull Control Pad packets out of buf, append (button, pressed) to events,
    return leftover bytes. Packet: '!' 'B' <'1'-'8'> <'1' down/'0' up> <checksum>."""
    while True:
        i = buf.find(b"!B")
        if i < 0:
            return buf[-1:]
        if len(buf) - i < 5:
            return buf[i:]
        pkt = buf[i:i + 5]
        buf = buf[i + 5:]
        if (~sum(pkt[:4])) & 0xFF == pkt[4]:
            events.append((pkt[2] - 48, pkt[3] == 49))


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
    dance_until = 0
    dance_start = 0
    last_beat = -1
    was_connected = False
    blocked = False

    _lights(alvik, (1, 1, 0))   # yellow: waiting for a phone

    while not alvik.get_touch_cancel():
        connected = _link.conn is not None
        if connected and not was_connected:
            _lights(alvik, COLORS[color_i])
        was_connected = connected

        if _link.lost:              # phone went away -> stop right away
            _link.lost = False
            held.clear()
            dance_until = 0
            alvik.brake()
            _lights(alvik, (1, 1, 0))

        while _link.events:
            button, pressed = _link.events.pop(0)
            if button in (5, 6, 7, 8):
                if pressed:
                    held.add(button)
                else:
                    held.discard(button)
                if dance_until:
                    dance_until = ticks_ms()   # arrows stop the dance (ends next tick)
            elif pressed and button == 1:
                color_i = (color_i + 1) % len(COLORS)
                _lights(alvik, COLORS[color_i])
            elif pressed and button == 2:
                turbo = not turbo
            elif pressed and button == 3:
                dance_start = ticks_ms()
                dance_until = ticks_add(dance_start, DANCE_MS)
                last_beat = -1
            elif pressed and button == 4:
                bumper = not bumper
                _lights(alvik, (0, 1, 0) if bumper else (1, 0, 0))   # quick green/red flash
                sleep_ms(300)
                _lights(alvik, COLORS[color_i])

        # work out how to move this tick
        now = ticks_ms()
        if dance_until and ticks_diff(dance_until, now) > 0:
            beat = ticks_diff(now, dance_start) // BEAT_MS
            if beat != last_beat:          # disco lights: left and right different colours
                last_beat = beat
                alvik.left_led.set_color(*DISCO[beat % len(DISCO)])
                alvik.right_led.set_color(*DISCO[(beat + 3) % len(DISCO)])
            linear = 0
            if ticks_diff(dance_until, now) < 1000:
                angular = 360              # big finish: one full spin
            else:
                angular = WIGGLE if (beat // 2) % 2 == 0 else -WIGGLE
        else:
            if dance_until:                # dance just ended -> back to normal lights
                dance_until = 0
                _lights(alvik, COLORS[color_i])
            speed = TURBO_SPEED if turbo else SPEED
            linear = (speed if 5 in held else 0) - (speed if 6 in held else 0)
            angular = (TURN if 7 in held else 0) - (TURN if 8 in held else 0)

        # bumper: don't drive forward into something
        now_blocked = False
        if bumper and linear > 0:
            d = alvik.get_distance()           # (left, center-left, center, center-right, right) cm
            front = [x for x in d[1:4] if x is not None]
            if front and min(front) < BUMPER_CM:
                linear = 0
                now_blocked = True
        if now_blocked != blocked:
            _lights(alvik, (1, 0, 0) if now_blocked else COLORS[color_i])
            blocked = now_blocked

        alvik.drive(linear, angular)
        sleep_ms(30)

    alvik.brake()
    _link.stop()
    return -1
