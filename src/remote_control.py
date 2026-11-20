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
# The web remote also asks for telemetry (see telemetry_packet): where the robot is pointing, its
# lights and speed, about 8 times a second, for the 3D robot on the page. Two more packets follow
# each one: the sensors in front (sensor_packet) and the ones underneath (under_packet).
#
# Lights while in this mode: yellow = waiting for a phone, then your headlight colour.
# With the bumper on they blink red as it slows down for something, and flash fast when it stops.
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
SLOW_FLASH_MS = 300      # lights blink red this slowly while the bumper is slowing the robot down
STOP_FLASH_MS = 120      # and this fast once it has stopped it
TELEMETRY_MS = 100       # how often the web page is told what the robot is doing (when it asked)
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
    Telemetry (web page): '!' 'T' <'1' on/'0' off> <anything> <checksum>   -> ("T", on)
    Checksum = ~(sum of the first 4 bytes) & 0xFF."""
    while True:
        i = buf.find(b"!")
        if i < 0:
            return b""
        if len(buf) - i < 2:
            return buf[i:]
        kind = buf[i + 1]
        if kind != 66 and kind != 74 and kind != 84:   # not 'B', 'J' or 'T'
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
        elif kind == 84:
            events.append(("T", pkt[2] == 49))
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


def front_distance(distances):
    """Closest thing straight ahead in cm (the middle three of the five readings), or None."""
    front = [x for x in distances[1:4] if x is not None]
    return min(front) if front else None


def bumper_limit(distances, speed):
    """Fastest we may go forward given what's in front: full speed beyond SLOW_CM,
    slower as it gets closer, 0 inside BUMPER_CM."""
    d = front_distance(distances)
    if d is None:
        return speed
    if d < BUMPER_CM:
        return 0
    if d >= SLOW_CM:
        return speed
    return max(2, speed * (d - BUMPER_CM) / (SLOW_CM - BUMPER_CM))


def _int8(v, scale):
    v = int(round(v * scale))
    return max(-127, min(127, v)) & 0xFF


def _cm(v):
    """A distance in cm as one byte: 0..254, and 255 for 'nothing seen'."""
    return 255 if v is None else max(0, min(254, int(round(v))))


def telemetry_packet(heading, distance, left, right, linear, angular,
                     turbo=False, bumper=True, blocked=False, dancing=False):
    """What the robot is doing, for the 3D robot on the web remote (docs/telemetry.js reads it).
    10 bytes:  '!' 'T' <heading lo> <heading hi> <distance> <lights> <speed> <turn> <flags> <checksum>
      heading   int16, tenths of a degree, -1800..1799; turning left counts up
      distance  cm to the closest thing in front, 0..254; 255 = nothing seen
      lights    bit 0-2 = left LED red, green, blue; bit 3-5 = right LED
      speed     int8, 0.2 cm/s steps (forward is positive)
      turn      int8, 3 deg/s steps (left is positive)
      flags     bit 0 turbo, 1 bumper, 2 blocked by the bumper, 3 dancing
    Checksum as for the other packets: ~(sum of the bytes before it) & 0xFF."""
    h = int(round((heading or 0) * 10))
    h = ((h + 1800) % 3600 - 1800) & 0xFFFF
    lights = 0
    for i, on in enumerate(tuple(left) + tuple(right)):
        if on:
            lights |= 1 << i
    flags = (1 if turbo else 0) | (2 if bumper else 0) | (4 if blocked else 0) | (8 if dancing else 0)
    body = bytes((0x21, 84, h & 0xFF, h >> 8, _cm(distance), lights, _int8(linear, 5), _int8(angular, 1 / 3), flags))
    return body + bytes(((~sum(body)) & 0xFF,))


def sensor_packet(distances, roll, pitch, battery):
    """The sensors in front, sent right after telemetry_packet (docs/telemetry.js reads it).
    11 bytes:  '!' 'S' <5 distances> <roll> <pitch> <battery> <checksum>
      distances  cm, the five readings from left to right, 0..254; 255 = nothing seen
      roll, pitch  int8, whole degrees, as the IMU reports them
      battery    0..100 percent; 255 = not known"""
    d = [_cm(x) for x in tuple(distances)[:5]]
    d += [255] * (5 - len(d))
    b = 255 if battery is None else max(0, min(100, int(battery)))
    body = bytes([0x21, 83] + d + [_int8(roll or 0, 1), _int8(pitch or 0, 1), b])
    return body + bytes(((~sum(body)) & 0xFF,))


def under_packet(lines, colour, bottom, top):
    """What is under the robot, sent right after sensor_packet (docs/telemetry.js reads it).
    11 bytes:  '!' 'U' <3 line sensors> <red> <green> <blue> <bottom> <top> <checksum>
      line sensors  left, centre, right: the raw reading in steps of 4, 0..254 (so 0..1016; a pale
                    floor reads low, a black line or no floor at all reads high); 255 = not known
      red, green, blue  the floor's colour, 0..100: how far each is from black to white, as the
                    Alvik library works it out (get_color); 255 = not known
      bottom, top   cm to what the distance sensor sees low down and high up in front, 0..254.
                    On the floor, bottom is the floor just ahead (about 7); it grows when the robot
                    is picked up. 255 = nothing seen"""
    body = [0x21, 85]
    for v in (tuple(lines) + (None,) * 3)[:3]:
        body.append(255 if v is None else max(0, min(254, int(v) // 4)))
    for v in (tuple(colour) + (None,) * 3)[:3]:
        body.append(255 if v is None else max(0, min(100, int(round(v * 100)))))
    body = bytes(body + [_cm(bottom), _cm(top)])
    return body + bytes(((~sum(body)) & 0xFF,))


def floor_colour(alvik):
    """The floor's colour as (red, green, blue), each 0..1, or Nones. A colour calibration gone
    wrong (black and white saved over the same floor) makes the library raise: never let that stop
    the driving."""
    try:
        return alvik.get_color()
    except Exception:
        return (None, None, None)


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

    def send(self, data):
        """Notify the phone on the TX characteristic. Quietly does nothing if it just went away."""
        if self.conn is None:
            return
        try:
            self.ble.gatts_notify(self.conn, self._tx, data)
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
    """Both LEDs to one colour. Returns it, so the caller knows what is showing."""
    alvik.left_led.set_color(*rgb)
    alvik.right_led.set_color(*rgb)
    return rgb


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
    warn = 0              # bumper: 0 clear, 1 slowing down, 2 stopped
    warn_at = 0
    stick = (0, 0)        # joystick from the web page: (x right, y forward), each -100..100
    stick_at = 0
    linear = angular = 0  # what the wheels are doing now (ramps towards what's asked for)
    telemetry = False     # the web page asks for it; the Bluefruit app never does
    told_at = 0
    last = ticks_ms()

    lit = _lights(alvik, (1, 1, 0))   # yellow: waiting for a phone (lit = the colour showing)

    while not alvik.get_touch_cancel():
        connected = _link.conn is not None
        if connected and not was_connected:
            lit = _lights(alvik, COLORS[color_i])
        was_connected = connected

        if _link.lost:              # phone went away -> stop right away
            _link.lost = False
            held.clear()
            stick = (0, 0)
            telemetry = False
            turbo = False              # the next phone starts fresh: turbo off, bumper on
            bumper = True              # (the web remote shows them that way when it connects)
            dance.stop()
            dancing = False
            alvik.brake()
            lit = _lights(alvik, (1, 1, 0))

        while _link.events:
            event = _link.events.pop(0)
            button, pressed = event[0], event[1]
            if button == "T":
                telemetry = pressed
            elif button == "J":
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
                lit = _lights(alvik, COLORS[color_i])
            elif pressed and button == 2:
                turbo = not turbo
            elif pressed and button == 3:
                dance.begin()
                dancing = True
            elif pressed and button == 4:
                bumper = not bumper
                lit = _lights(alvik, (0, 1, 0) if bumper else (1, 0, 0))   # quick green/red flash
                sleep_ms(300)
                lit = _lights(alvik, COLORS[color_i])

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
                lit = _lights(alvik, COLORS[color_i])
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
        level = 0
        if bumper and (linear > 0 or want_linear > 0):
            top = TURBO_SPEED if turbo else SPEED
            limit = bumper_limit(alvik.get_distance(), top)
            if linear > limit:
                linear = limit             # right away, no ramp
            level = 2 if limit == 0 else 1 if limit < top else 0
        if level != warn:
            if not level:                  # all clear: headlights back
                lit = _lights(alvik, COLORS[color_i])
            warn = level
            warn_at = now
        blocked = level == 2
        if level:                          # blink red: slowly while slowing, fast when stopped
            red = (ticks_diff(now, warn_at) // (STOP_FLASH_MS if blocked else SLOW_FLASH_MS)) % 2 == 0
            other = (0, 0, 0) if blocked or COLORS[color_i] == (1, 0, 0) else COLORS[color_i]
            show = (1, 0, 0) if red else other
            if show != lit:
                lit = _lights(alvik, show)

        alvik.drive(linear, angular)

        if telemetry and connected and ticks_diff(now, told_at) >= TELEMETRY_MS:
            told_at = now
            left, right = dance.lights if move else (lit, lit)
            _link.send(telemetry_packet(
                alvik.get_pose()[2], front_distance(alvik.get_distance()), left, right,
                linear, angular, turbo, bumper, blocked, bool(move)))
            roll, pitch, _ = alvik.get_orientation()
            _link.send(sensor_packet(alvik.get_distance(), roll, pitch, alvik.get_battery_charge()))
            _link.send(under_packet(alvik.get_line_sensors(), floor_colour(alvik),
                                    alvik.get_distance_bottom(), alvik.get_distance_top()))
        sleep_ms(30)

    alvik.brake()
    _link.stop()
    return -1
