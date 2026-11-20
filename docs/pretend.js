// A pretend Alvik in a pretend room, for trying the remote with no robot (the page's "?demo").
//
// It takes the same packets as the real robot (src/remote_control.py) and answers with the same
// telemetry packets, so the page can't tell the difference: the joystick, the four buttons and
// the 3D robot all work as they do over Bluetooth. Its driving sums are the robot's own
// (bumper.js). What is made up is the room and what the sensors read in it: see ROOM and the
// "readings" numbers below. They copy what the real robot was seen to do (the floor showing at
// 16-18 cm, blips, 7.4 cm to the floor underneath), but they are a guess at a real room.
//
//   const robot = createPretendRobot({ send: (bytes) => feed(bytes) });
//   robot.write(packet);        // what the page would write over Bluetooth
//   robot.step(30);             // 30 ms later (call it often)
//   robot.hold(true);           // picked up; hold(false) puts it down again
//   robot.view()                // where it is, for the little map
//
// No page, no three.js: plain sums, so tests/pretend.test.mjs can drive it.

import { SPEED, TURBO_SPEED, TURN, ACCEL, DECEL, TURN_ACCEL, ramp, bumperLimit, Bumper } from "./bumper.js";

// ---------- the room (cm; x to the right, y away from you; the robot starts facing away) ----------
export const ROOM = {
  w: 140, h: 100,
  start: { x: 70, y: 24 },
  floor: [0.62, 0.55, 0.47],                                    // the colour sensor's reading of plain floor
  boxes: [{ x: 56, y: 76, w: 28, h: 12, name: "box" }],         // tall things with flat sides
  posts: [{ x: 108, y: 46, r: 0.8, name: "chair leg" }],        // tall, thin, round things
  mats: [                                                       // coloured paper on the floor
    { x: 10, y: 60, w: 32, h: 28, rgb: [0.86, 0.18, 0.2], name: "red" },
    { x: 98, y: 62, w: 32, h: 26, rgb: [0.16, 0.36, 0.9], name: "blue" },
    { x: 14, y: 10, w: 30, h: 24, rgb: [0.2, 0.74, 0.36], name: "green" },
  ],
  tape: [{ x: 30, y: 42, w: 62, h: 2.6 }],                      // black tape on the floor
};

const RADIUS = 6;                                // the robot as a circle, for bumping into things
const NOSE = 4.8;                                // the distance sensor, ahead of the robot's middle
export const ZONE_DEG = [22, 11, 0, -11, -22];   // where the five zones look (left is positive): a guess
const RAY_SPREAD = 2;                            // each zone looks a little to both sides too
const EYE_X = 1.3, EYE_Y = 3.6;                  // the line sensors: apart, and ahead of the middle

// ---------- readings (guesses that copy the real robot) ----------
const SEES_CM = 60;                              // a thing further off than this loses to the floor
const FLOOR_SHOWS = [16, 18];                    // cm: where the floor shows with nothing ahead
const BLIP_CHANCE = 0.02;                        // per reading: a zone drops to the floor's reading for a moment
const UNDER_CM = 7.4, HELD_CM = 42;              // the low zone: standing on the floor, and held in the air
const LINE_PALE = 50, LINE_DARK = 720, LINE_AIR = 900;
const BATTERY = 87;

// copies of the robot's own numbers (src/remote_control.py, src/dance.py): the tests compare them
const COLORS = [[1, 1, 1], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 0], [0, 0, 0]];
const DISCO = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 0]];
const DANCE_MS = 4000, BEAT_MS = 250, WIGGLE = 120, SPIN = 360;
const STICK_TIMEOUT_MS = 600, SLOW_FLASH_MS = 300, STOP_FLASH_MS = 120, TELEMETRY_MS = 100;
export const COPIED = { COLORS, DISCO, DANCE_MS, BEAT_MS, WIGGLE, SPIN, STICK_TIMEOUT_MS, SLOW_FLASH_MS, STOP_FLASH_MS, TELEMETRY_MS };
const RED = [1, 0, 0], GREEN = [0, 1, 0], OFF = [0, 0, 0];

const rad = (deg) => deg * Math.PI / 180;
const inside = (r, x, y) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;

// ---------- the robot's side of the packets (the page's side is telemetry.js) ----------
const round = (v) => {                           // halves go to the even number, as Python's round() does
  const f = Math.floor(v), d = v - f;
  return d > 0.5 ? f + 1 : d < 0.5 ? f : f % 2 === 0 ? f : f + 1;
};
const int8 = (v, scale) => Math.max(-127, Math.min(127, round(v * scale))) & 0xff;
const cm = (v) => (v === null || v === undefined ? 255 : Math.max(0, Math.min(254, round(v))));
const closed = (body) => Uint8Array.from([...body, ~body.reduce((a, b) => a + b, 0) & 0xff]);

/** As telemetry_packet() on the robot: heading in degrees, distance in cm (null = nothing), left
 *  and right LED as [r, g, b], linear in cm/s, angular in deg/s. */
export function telemetryPacket({ heading, distance, left, right, linear, angular, turbo = false, bumper = true, blocked = false, dancing = false }) {
  let h = round((heading || 0) * 10);
  h = ((((h + 1800) % 3600) + 3600) % 3600 - 1800) & 0xffff;
  let lights = 0;
  [...left, ...right].forEach((on, i) => { if (on) lights |= 1 << i; });
  const flags = (turbo ? 1 : 0) | (bumper ? 2 : 0) | (blocked ? 4 : 0) | (dancing ? 8 : 0);
  return closed([0x21, 0x54, h & 0xff, h >> 8, cm(distance), lights, int8(linear, 5), int8(angular, 1 / 3), flags]);
}

/** As sensor_packet() on the robot: five distances in cm, roll and pitch in degrees, battery percent. */
export function sensorPacket({ distances, roll, pitch, battery }) {
  const d = [0, 1, 2, 3, 4].map((i) => cm(distances[i]));
  const b = battery === null || battery === undefined ? 255 : Math.max(0, Math.min(100, Math.trunc(battery)));
  return closed([0x21, 0x53, ...d, int8(roll || 0, 1), int8(pitch || 0, 1), b]);
}

/** As under_packet() on the robot: three line sensors (raw), the floor's colour (each 0..1), and
 *  the distance sensor's low and high zones in cm. */
export function underPacket({ lines, colour, bottom, top }) {
  const known = (v) => v !== null && v !== undefined;
  const l = [0, 1, 2].map((i) => (known(lines[i]) ? Math.max(0, Math.min(254, Math.floor(lines[i] / 4))) : 255));
  const c = [0, 1, 2].map((i) => (known(colour[i]) ? Math.max(0, Math.min(100, round(colour[i] * 100))) : 255));
  return closed([0x21, 0x55, ...l, ...c, cm(bottom), cm(top)]);
}

// ---------- looking around the room ----------
/** How far a ray from (ox, oy) going (dx, dy) gets before it meets a wall, a box or a post, in cm. */
export function rayLength(ox, oy, dx, dy, room = ROOM) {
  let best = Infinity;
  const slab = (x0, y0, x1, y1, fromInside) => {                // a rectangle's sides
    let near = -Infinity, far = Infinity;
    for (const [o, d, lo, hi] of [[ox, dx, x0, x1], [oy, dy, y0, y1]]) {
      if (Math.abs(d) < 1e-9) { if (o < lo || o > hi) return; continue; }
      const a = (lo - o) / d, b = (hi - o) / d;
      near = Math.max(near, Math.min(a, b));
      far = Math.min(far, Math.max(a, b));
    }
    if (near > far || far < 0) return;
    const t = fromInside ? far : near;
    if (t >= 0 && t < best) best = t;
  };
  slab(0, 0, room.w, room.h, true);
  for (const b of room.boxes) slab(b.x, b.y, b.x + b.w, b.y + b.h, false);
  for (const p of room.posts) {
    const fx = ox - p.x, fy = oy - p.y;
    const along = -(fx * dx + fy * dy), off2 = fx * fx + fy * fy - along * along;
    if (along > 0 && off2 <= p.r * p.r) best = Math.min(best, along - Math.sqrt(p.r * p.r - off2));
  }
  return best;
}

function free(x, y, room) {                      // may the robot's middle be here?
  if (x < RADIUS || y < RADIUS || x > room.w - RADIUS || y > room.h - RADIUS) return false;
  for (const b of room.boxes) {
    const nx = Math.max(b.x, Math.min(x, b.x + b.w)), ny = Math.max(b.y, Math.min(y, b.y + b.h));
    if (Math.hypot(x - nx, y - ny) < RADIUS) return false;
  }
  return room.posts.every((p) => Math.hypot(x - p.x, y - p.y) >= RADIUS + p.r);
}

export function createPretendRobot({ send = () => {}, random = Math.random, room = ROOM } = {}) {
  // where it is: x, y in cm, heading in degrees (0 = away from you, turning left counts up)
  let x = room.start.x, y = room.start.y, heading = 0;
  let held = false;                              // picked up
  // as run_remote() on the robot
  let now = 0, stick = [0, 0], stickAt = 0, turbo = false, bumper = true, colorI = 0;
  let linear = 0, angular = 0, telemetry = false, toldAt = -TELEMETRY_MS;
  let warn = 0, warnAt = 0, blocked = false, flashUntil = -1;
  let danceAt = null, lit = [COLORS[0], COLORS[0]];
  let eyes = new Bumper(), buf = [], seen = [null, null, null, null, null], ahead = null;
  const blips = [0, 0, 0, 0, 0];                 // readings left in each zone's blip
  const noise = (size) => (random() - 0.5) * 2 * size;

  // the directions it faces: forward and to its left
  const forward = () => [-Math.sin(rad(heading)), Math.cos(rad(heading))];

  function distances() {
    if (held) return [null, null, null, null, null];
    const [fx, fy] = forward(), ox = x + fx * NOSE, oy = y + fy * NOSE;
    return ZONE_DEG.map((deg, i) => {
      let d = Infinity;
      for (const off of [-RAY_SPREAD, 0, RAY_SPREAD]) {
        const a = rad(heading + deg + off);
        d = Math.min(d, rayLength(ox, oy, -Math.sin(a), Math.cos(a), room));
      }
      const floor = FLOOR_SHOWS[0] + random() * (FLOOR_SHOWS[1] - FLOOR_SHOWS[0]);
      if (d > SEES_CM) return floor;                                    // nothing ahead: the floor shows
      if (blips[i] > 0) { blips[i] -= 1; return d > floor ? floor : d; }
      if (d > 34 && random() < BLIP_CHANCE) blips[i] = 1 + Math.floor(random() * 2);
      return Math.max(0, d + noise(0.5));
    });
  }

  function under() {
    if (held) {
      return { lines: [0, 1, 2].map(() => LINE_AIR + noise(20)), colour: [0.04, 0.04, 0.05], bottom: HELD_CM + noise(2), top: null };
    }
    const [fx, fy] = forward(), lx = -fy, ly = fx;                      // its left
    const lines = [1, 0, -1].map((side) => {
      const ex = x + fx * EYE_Y + lx * EYE_X * side, ey = y + fy * EYE_Y + ly * EYE_X * side;
      return (room.tape.some((t) => inside(t, ex, ey)) ? LINE_DARK : LINE_PALE) + noise(8);
    });
    const mat = room.mats.find((m) => inside(m, x, y));
    const top = rayLength(x + fx * NOSE, y + fy * NOSE, fx, fy, room);
    return { lines, colour: mat ? mat.rgb : room.floor, bottom: UNDER_CM + noise(0.3), top: top > SEES_CM ? null : top };
  }

  function dance() {                             // as Dance.step(): sets the lights, returns [linear, angular] or null
    if (danceAt === null) return null;
    const t = now - danceAt;
    if (t >= DANCE_MS) { danceAt = null; return null; }
    const beat = Math.floor(t / BEAT_MS);
    lit = [DISCO[beat % DISCO.length], DISCO[(beat + 3) % DISCO.length]];
    if (DANCE_MS - t < 1000) return [0, SPIN];
    return [0, Math.floor(beat / 2) % 2 === 0 ? WIGGLE : -WIGGLE];
  }

  function event(kind, a, b) {
    if (kind === 0x54) { telemetry = a === 0x31; return; }              // 'T'
    if (kind === 0x4a) {                                                // 'J'
      const s = (v) => Math.max(-100, Math.min(100, v > 127 ? v - 256 : v));
      stick = [s(a), s(b)]; stickAt = now;
      if (stick[0] || stick[1]) danceAt = null;                         // the joystick stops the dance
      return;
    }
    const button = a - 48, pressed = b === 0x31;                        // 'B'
    if (!pressed) return;
    if (button === 1) colorI = (colorI + 1) % COLORS.length;
    else if (button === 2) turbo = !turbo;
    else if (button === 3) danceAt = now;
    else if (button === 4) { bumper = !bumper; flashUntil = now + 300; }   // a quick green or red flash
  }

  return {
    room,

    /** What the page would write to the robot over Bluetooth: '!' <letter> <a> <b> <checksum>. */
    write(bytes) {
      buf.push(...bytes);
      for (;;) {
        const i = buf.indexOf(0x21);
        if (i < 0) { buf = []; return; }
        if (i) buf = buf.slice(i);
        if (buf.length < 2) return;
        if (![0x42, 0x4a, 0x54].includes(buf[1])) { buf.shift(); continue; }
        if (buf.length < 5) return;
        const sum = ~(buf[0] + buf[1] + buf[2] + buf[3]) & 0xff;
        if (sum !== buf[4]) { buf.shift(); continue; }                  // damaged: look for the next '!'
        event(buf[1], buf[2], buf[3]);
        buf = buf.slice(5);
      }
    },

    /** ms more have gone by: look, drive, light up, and tell the page if it asked. */
    step(ms) {
      const dt = Math.min(ms, 200) / 1000;
      now += ms;
      if ((stick[0] || stick[1]) && now - stickAt > STICK_TIMEOUT_MS) stick = [0, 0];   // the page went quiet

      seen = distances();
      ahead = eyes.look(seen, linear * dt, angular * dt);

      const base = COLORS[colorI];
      const move = dance();
      let wantLinear;
      if (move) {
        [linear, angular] = move;                                       // the dance is meant to be jerky: no ramp
        wantLinear = linear;
      } else {
        const speed = turbo ? TURBO_SPEED : SPEED;
        wantLinear = Math.max(-speed, Math.min(speed, speed * stick[1] / 100));
        const wantAngular = Math.max(-TURN, Math.min(TURN, -TURN * stick[0] / 100));
        linear = ramp(linear, wantLinear, ACCEL * dt, DECEL * dt);
        angular = ramp(angular, wantAngular, TURN_ACCEL * dt, TURN_ACCEL * dt);
      }

      // bumper: slow down near things, and don't drive forward into them
      let level = 0;
      if (bumper && (linear > 0 || wantLinear > 0)) {
        const top = turbo ? TURBO_SPEED : SPEED, limit = bumperLimit(ahead, top);
        if (linear > limit) linear = limit;
        level = limit === 0 ? 2 : limit < top ? 1 : 0;
      }
      if (level !== warn) { warn = level; warnAt = now; }
      blocked = level === 2;
      if (!move) {
        let show = base;
        if (now < flashUntil) show = bumper ? GREEN : RED;
        else if (level) {                                               // blink red: slowly while slowing, fast when stopped
          const red = Math.floor((now - warnAt) / (blocked ? STOP_FLASH_MS : SLOW_FLASH_MS)) % 2 === 0;
          show = red ? RED : blocked || base.join() === RED.join() ? OFF : base;
        }
        lit = [show, show];
      }

      // the wheels turn it and carry it along, unless it is in the air or up against something
      heading = ((heading + angular * dt + 180) % 360 + 360) % 360 - 180;
      if (!held && linear) {
        const [fx, fy] = forward(), nx = x + fx * linear * dt, ny = y + fy * linear * dt;
        if (free(nx, ny, room)) { x = nx; y = ny; }
        else if (free(nx, y, room)) x = nx;                             // slide along it
        else if (free(x, ny, room)) y = ny;
      }

      if (telemetry && now - toldAt >= TELEMETRY_MS) {
        toldAt = now;
        send(telemetryPacket({ heading, distance: ahead, left: lit[0], right: lit[1], linear, angular, turbo, bumper, blocked, dancing: !!move }));
        send(sensorPacket({
          distances: seen, battery: BATTERY,
          roll: held ? 9 * Math.sin(now / 420) : noise(1), pitch: held ? -13 + 5 * Math.sin(now / 530) : noise(1),
        }));
        send(underPacket(under()));
      }
    },

    /** Pick it up (true) or put it back down (false). In the air the wheels still turn, so the
     *  heading it reports still changes, but it goes nowhere. */
    hold(on) {
      held = !!on;
      if (!held) eyes = new Bumper();
    },

    /** Where it is and what it sees, for drawing the map. */
    view() {
      return { x, y, heading, held, seen, ahead, linear, angular, lit, turbo, bumper, blocked };
    },
  };
}
