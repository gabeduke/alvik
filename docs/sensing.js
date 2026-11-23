// How the robot's readings become what the 3D robot shows (twin.js draws it). Plain maths with no
// three.js, so the tests can run it: tests/sensing.test.mjs.
//
//   const blocks = newBlocks();                 // the distance sensor's five readings, as five blocks
//   easeBlocks(blocks, zones, dt);              // every frame: zones = five distances in cm, or null
//   blockLook(blocks, i, bumper);               // -> { cm, alpha, rgb } for block i (0 = left .. 4 = right)
//   liftOf(bottom);                             // 0 on the floor .. 1 picked up high
//   const pose = newPose();                     // tipped and picked up, steadied: see poseTilt, poseLift
//   lineShade(raw);                             // 1 pale floor .. 0 black line
//   const head = newCompass();                  // the heading, drawn with less lag
//   compassNews(head, heading, turn);           // on each packet
//   compassStep(head, turn, dt);                // every frame; then draw head.shown

import { SLOW_CM, BUMPER_CM as STOP_CM } from "./bumper.js";   // the robot's: slow from 12 cm, stop at 8
export { SLOW_CM, STOP_CM };
export const VIEW_CM = 30;                      // the picture's scale: this far away is at the edge of the view
export const SEE_CM = 40;                       // a block fades in from here
export const ZONES = 5;                         // the distance sensor's readings, left to right
const MID = [0, 1, 1, 1, 0];                    // the blocks in front of the bumper: its two cells and the reading between them
const BLOCK_RATE = 10, FADE_RATE = 7;           // per second: how fast a block follows its reading, and fades in or out

// a block's colours, [r, g, b] each 0..1: just a reading, the bumper slowing the robot, closer, stopped
export const PALE = [0.87, 0.9, 1], YELLOW = [1, 0.82, 0.25], ORANGE = [1, 0.5, 0.16], RED = [1, 0.23, 0.23];

const clamp01 = (v) => Math.max(0, Math.min(1, v));
const mix3 = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
/** How much of the way to go in dt seconds, for something that closes in at `rate` per second. */
export const ease = (dt, rate) => 1 - Math.exp(-dt * rate);

export const wrap = (deg) => ((deg + 180) % 360 + 360) % 360 - 180;

// Heading with less lag. News from the robot is already a little old when it lands, so it is taken
// to be that much further on at the robot's turn rate. Between packets the heading keeps turning at
// that rate, and what is drawn closes in on it quickly. (When the robot stops turning, the drawing
// runs on for a moment until the next packet says so: a small price.)
const LEAD_S = 0.04, HEADING_RATE = 14;         // seconds ahead; closing in, per second
/** The heading in degrees: where the robot should be by now, and what is drawn. */
export function newCompass() {
  return { target: 0, shown: 0 };
}
/** News from the robot: its heading in degrees and its turn rate in deg/s (left is positive). */
export function compassNews(compass, heading, turn) {
  compass.target = wrap(heading + turn * LEAD_S);
}
/** dt seconds on, the robot turning at `turn` deg/s meanwhile. Returns true while the drawing is still catching up. */
export function compassStep(compass, turn, dt) {
  compass.target = wrap(compass.target + turn * dt);
  compass.shown = wrap(compass.shown + turn * dt);
  compass.shown = wrap(compass.shown + wrap(compass.target - compass.shown) * ease(dt, HEADING_RATE));
  return Math.abs(wrap(compass.target - compass.shown)) >= 0.05;
}

// The distance sensor, as five blocks in front of the robot: one for each reading, standing as far
// away as the reading says, so a thing can be watched coming closer. They show what the sensor
// says, floor and blips and all. The colour is the bumper's own word (the T packet): pale while it
// is doing nothing, yellow to orange while it slows the robot, red once it has stopped it.

/** The blocks as they are drawn now: how far away each one stands (cm) and how much of it shows (0..1). */
export function newBlocks() {
  return { cm: Array(ZONES).fill(SEE_CM), seen: Array(ZONES).fill(0) };
}

/** Move the blocks towards the latest readings (cm, or null = nothing seen), dt seconds on, so they
 *  glide instead of jumping. Returns true while one is still moving. */
export function easeBlocks(blocks, zones, dt) {
  const k = ease(dt, BLOCK_RATE), fade = ease(dt, FADE_RATE);
  let moving = false;
  for (let i = 0; i < ZONES; i++) {
    const z = zones[i], on = z !== null && z !== undefined && z <= SEE_CM;
    if (on) {
      if (blocks.seen[i] < 0.02) blocks.cm[i] = z;              // just showed up: it fades in where it is
      else blocks.cm[i] += (z - blocks.cm[i]) * k;
      if (Math.abs(z - blocks.cm[i]) < 0.05) blocks.cm[i] = z; else moving = true;
    }
    const want = on ? 1 : 0;
    blocks.seen[i] += (want - blocks.seen[i]) * fade;
    if (Math.abs(want - blocks.seen[i]) < 0.01) blocks.seen[i] = want; else moving = true;
  }
  return moving;
}

/** How block i looks (0 = left .. 4 = right). bumper = what the robot says its bumper is doing:
 *  { cm: how far the thing it acts on is (null = nothing), blocked: has it stopped the robot }, or
 *  nothing at all to leave the bumper out. A plain block is pale, faint when far and firmer as it
 *  comes closer. While the bumper acts, the blocks in front of it take its colour: yellow from
 *  SLOW_CM, warmer on the way in, red from STOP_CM or once the robot is stopped.
 *  -> { cm, alpha 0..1, rgb, lit: is it in the bumper's colour } */
export function blockLook(blocks, i, bumper = null) {
  const cm = blocks.cm[i], seen = blocks.seen[i];
  if (seen < 0.001) return { cm, alpha: 0, rgb: PALE, lit: false };
  const acting = !!bumper && MID[i] === 1 && (bumper.blocked || (bumper.cm !== null && bumper.cm !== undefined));
  if (acting) {
    const d = bumper.cm ?? 0;
    const rgb = bumper.blocked || d < STOP_CM ? RED : mix3(YELLOW, ORANGE, clamp01((SLOW_CM - d) / (SLOW_CM - STOP_CM)));
    return { cm, alpha: seen * 0.9, rgb, lit: true };
  }
  const far = clamp01((SEE_CM - cm) / (SEE_CM - VIEW_CM) + 0.15);              // faint at 40 cm, there from 30
  const near = 0.5 + 0.5 * clamp01(1 - cm / VIEW_CM);                         // and firmer the closer it is
  return { cm, alpha: seen * far * near * (MID[i] ? 0.7 : 0.45), rgb: PALE, lit: false };
}

// Picked up. The distance sensor's low zone looks down at the floor just ahead of the robot: 7.4 cm
// on the real robot standing on a desk. Lift the robot and that grows.
export const FLOOR_CM = 7.4;
const LIFT_SLACK_CM = 3;                        // this much more is still "on the floor" (carpet, a ramp, noise)
const LIFT_HALF_CM = 20;                        // this much more again and the 3D robot is half way up
/** How high the robot is held, 0 (on the floor) .. 1 (as high as it is ever drawn), from the
 *  bottom distance in cm (null = not known: then it stays down). */
export function liftOf(bottom) {
  if (bottom === null || bottom === undefined) return 0;
  const up = bottom - FLOOR_CM - LIFT_SLACK_CM;
  return up <= 0 ? 0 : up / (up + LIFT_HALF_CM);
}

// Tipped and picked up, without the wobble. Driving over a floor that is not quite flat (wooden
// boards, a rug's edge) jolts the motion chip and the downward distance for a reading or two at a
// time, so the raw numbers would make the 3D robot jump off the floor and back. So the page goes by
// the middle of the last few readings (one or two jolts never win), and a lean or a lift has to pass
// a higher mark to start than it needs to keep going, so a robot sitting near the mark doesn't flicker.
//
//   const pose = newPose();
//   poseTilt(pose, roll, pitch);                 // on each sensors packet
//   poseLift(pose, bottom);                      // on each under-the-robot packet
//   then draw pose.roll, pose.pitch (degrees) and pose.lift (0..1)
export const STEADY = 5;                        // readings (about 0.6 s): the middle of this many is used
export const TILT_ON = 8, TILT_OFF = 5;         // degrees: a lean starts past this, and ends under that
const TILT_MAX = 60;
export const LIFT_ON_CM = 6, LIFT_OFF_CM = 3;   // cm past FLOOR_CM: a lift starts past this, and ends under that

/** The middle of some numbers. */
export function median(values) {
  const v = [...values].sort((a, b) => a - b), n = v.length;
  if (!n) return 0;
  return n % 2 ? v[(n - 1) / 2] : (v[n / 2 - 1] + v[n / 2]) / 2;
}
const keep = (list, v) => { list.push(v); if (list.length > STEADY) list.shift(); };

/** Nothing seen yet: taken to be flat on the floor, so the first jolt can't win either. */
export function newPose() {
  const flat = (v) => Array(STEADY).fill(v);
  return { rolls: flat(0), pitches: flat(0), bottoms: flat(FLOOR_CM), tipped: false, lifted: false, roll: 0, pitch: 0, lift: 0 };
}
/** A sensors packet: roll and pitch in degrees, as the robot's motion chip gives them. */
export function poseTilt(pose, roll, pitch) {
  keep(pose.rolls, roll || 0);
  keep(pose.pitches, pitch || 0);
  const r = median(pose.rolls), p = median(pose.pitches);
  const most = Math.max(Math.abs(r), Math.abs(p));
  pose.tipped = most >= (pose.tipped ? TILT_OFF : TILT_ON);
  const clamp = (v) => Math.max(-TILT_MAX, Math.min(TILT_MAX, v));
  pose.roll = pose.tipped ? clamp(r) : 0;
  pose.pitch = pose.tipped ? clamp(p) : 0;
  return pose;
}
/** An under-the-robot packet: the bottom distance in cm (null = nothing seen, taken as the floor:
 *  a dark floor can swallow the sensor's light). */
export function poseLift(pose, bottom) {
  keep(pose.bottoms, bottom === null || bottom === undefined ? FLOOR_CM : bottom);
  const b = median(pose.bottoms);
  pose.lifted = b - FLOOR_CM >= (pose.lifted ? LIFT_OFF_CM : LIFT_ON_CM);
  pose.lift = pose.lifted ? liftOf(b) : 0;
  return pose;
}
/** The robot went away, or the page stopped showing these: flat on the floor again. */
export function poseReset(pose) {
  Object.assign(pose, newPose());
  return pose;
}

// Line sensors. About 50 on a pale desk on the real robot; a black line, or no floor at all, reads
// much higher.
const LINE_PALE = 100, LINE_DARK = 500;
/** How bright the floor is under a line sensor: 1 pale .. 0 black, or null if the reading is not known. */
export function lineShade(raw) {
  if (raw === null || raw === undefined) return null;
  return 1 - clamp01((raw - LINE_PALE) / (LINE_DARK - LINE_PALE));
}
