// What the 3D robot shows for a reading (docs/sensing.js): the blocks in front, how high it is
// held, and the shade under a line sensor.
import { test } from "node:test";
import assert from "node:assert/strict";
import { newBlocks, easeBlocks, blockLook, liftOf, lineShade, newCompass, compassNews, compassStep, wrap, PALE, YELLOW, RED, FLOOR_CM, SEE_CM, SLOW_CM, STOP_CM,
  newPose, poseTilt, poseLift, poseReset, median, STEADY, TILT_ON } from "../docs/sensing.js";

/** The blocks once they have settled on these readings. */
function settled(zones) {
  const blocks = newBlocks();
  for (let i = 0; i < 400 && easeBlocks(blocks, zones, 1 / 60); i++);
  return blocks;
}
const close = (a, b, eps = 0.02) => a.every((v, i) => Math.abs(v - b[i]) < eps);
const redder = (rgb) => rgb[0] - rgb[1];       // yellow -> orange -> red: green goes down
const clear = { cm: null, blocked: false };    // the bumper has nothing to say

test("a block stands where its reading says, pale, and firmer the closer it comes", () => {
  const blocks = settled([35, 25, 17, 9, null]);
  assert.deepEqual([0, 1, 2, 3].map((i) => blockLook(blocks, i, clear).cm), [35, 25, 17, 9]);
  for (const i of [0, 1, 2, 3]) assert.ok(close(blockLook(blocks, i, clear).rgb, PALE) && !blockLook(blocks, i, clear).lit, `block ${i} is pale`);
  assert.equal(blockLook(blocks, 4, clear).alpha, 0, "nothing seen: no block");
  const at = (cm) => blockLook(settled([cm, cm, cm, cm, cm]), 2, clear).alpha;
  assert.ok(at(39) < at(30) && at(30) < at(20) && at(20) < at(10), "fades in from 40 cm and firms up on the way in");
  assert.equal(blockLook(settled([SEE_CM + 1, 50, 200, 60, 41]), 2, clear).alpha, 0, "further than 40 cm is not drawn");
});

test("the floor's own reading is only a pale block: colour is the bumper's word, not the reading's", () => {
  assert.equal(SLOW_CM, 12); assert.equal(STOP_CM, 8);
  const blocks = settled([17, 16.5, 13.5, 9, 17]);     // readings closer than SLOW_CM, but the bumper says all clear
  for (let i = 0; i < 5; i++) assert.ok(close(blockLook(blocks, i, clear).rgb, PALE), `block ${i}`);
  for (let i = 0; i < 5; i++) assert.ok(close(blockLook(blocks, i).rgb, PALE), `block ${i}, bumper left out`);
});

test("while the bumper acts, the three blocks in front of it take its colour: yellow, warmer, red", () => {
  const blocks = settled([20, 11, 10.5, 10, 20]);
  const at = (cm, blocked = false) => blockLook(blocks, 2, { cm, blocked });
  assert.ok(close(at(SLOW_CM).rgb, YELLOW), "at SLOW_CM: yellow");
  assert.ok(redder(at(10).rgb) > redder(at(SLOW_CM).rgb), "closer is warmer");
  assert.ok(redder(at(8.5).rgb) > redder(at(10).rgb));
  assert.ok(close(at(7.9).rgb, RED), "inside STOP_CM: red");
  assert.ok(close(at(11, true).rgb, RED), "stopped by the bumper: red, whatever the distance");
  assert.ok(at(10).lit && at(10).alpha > blockLook(blocks, 2, clear).alpha, "and they stand out");
  for (const i of [1, 2, 3]) assert.ok(blockLook(blocks, i, { cm: 10, blocked: false }).lit, `block ${i}`);
  for (const i of [0, 4]) assert.ok(close(blockLook(blocks, i, { cm: 5, blocked: true }).rgb, PALE), `the outer block ${i} stays pale`);
  assert.equal(at(10).cm, 10.5, "the block still stands at its own reading");
});

test("readings are followed over time, not jumped to", () => {
  const blocks = settled([null, 30, 30, 30, null]);
  const zones = [null, 30, 14, 30, null];
  assert.equal(easeBlocks(blocks, zones, 1 / 60), true);
  assert.ok(blocks.cm[2] < 30 && blocks.cm[2] > 26, `one frame later: ${blocks.cm[2]}`);
  for (let i = 0; i < 12; i++) easeBlocks(blocks, zones, 1 / 60);        // a fifth of a second
  assert.ok(blocks.cm[2] < 18, `mostly there: ${blocks.cm[2]}`);
  for (let i = 0; i < 120 && easeBlocks(blocks, zones, 1 / 60); i++);
  assert.equal(blocks.cm[2], 14);
  assert.equal(easeBlocks(blocks, zones, 1 / 60), false, "settled: nothing left to draw");
});

test("a block that shows up fades in where it is, and one that goes fades out", () => {
  const blocks = settled([null, null, 35, null, null]);
  const zones = [null, null, 35, 15, null];
  easeBlocks(blocks, zones, 1 / 60);
  assert.equal(blocks.cm[3], 15, "no slide in from far away");
  assert.ok(blocks.seen[3] > 0 && blocks.seen[3] < 0.3);
  easeBlocks(blocks, [null, null, null, 15, null], 1 / 60);
  assert.ok(blocks.seen[2] < 1 && blocks.seen[2] > 0.7);
  assert.equal(blocks.cm[2], 35);
  assert.deepEqual(settled([null, null, null, null, null]).seen, [0, 0, 0, 0, 0]);
});

test("picked up: the further the floor, the higher the robot is drawn", () => {
  assert.equal(liftOf(null), 0);
  assert.equal(liftOf(Math.round(FLOOR_CM)), 0);
  assert.equal(liftOf(Math.round(FLOOR_CM) + 2), 0, "a bump or a carpet is not a lift");
  let last = 0;
  for (const cm of [12, 16, 25, 40, 80, 254]) {
    const up = liftOf(cm);
    assert.ok(up > last && up < 1, `${cm} cm -> ${up}`);
    last = up;
  }
  assert.ok(liftOf(40) > 0.5 && liftOf(254) > 0.9);
});

test("median: the middle reading, so one or two jolts never win", () => {
  assert.equal(median([]), 0);
  assert.equal(median([3, 40, 2]), 3);
  assert.equal(median([1, 2, 3, 100]), 2.5);
});

// A wooden floor that isn't quite flat, while driving: the motion chip and the downward distance
// jolt for one or two packets at a time (made-up numbers, about 8 packets a second for 10 seconds),
// never more than two in any five in a row. Between jolts the readings wobble a little.
function woodFloor(n = 80) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const jolt = i % 6 === 0 || (i % 12 === 1);                    // a board edge; every other one lasts two packets
    out.push({
      roll: (jolt ? (i % 4 ? 14 : -11) : 0) + Math.sin(i) * 3,
      pitch: (jolt ? -12 : 0) + Math.cos(i * 1.3) * 3,
      bottom: jolt ? (i % 4 ? 19 : null) : FLOOR_CM + Math.sin(i * 0.7) * 1.5,
    });
  }
  return out;
}

test("driving over a floor that isn't flat: the 3D robot stays flat on the floor", () => {
  const pose = newPose();
  for (const r of woodFloor()) {
    poseTilt(pose, r.roll, r.pitch);
    poseLift(pose, r.bottom);
    assert.equal(pose.roll, 0, "no lean");
    assert.equal(pose.pitch, 0, "no lean");
    assert.equal(pose.lift, 0, "no lift");
  }
});

test("a robot that rests a little crooked doesn't flicker between leaning and not", () => {
  const pose = newPose();
  const seen = [];
  for (let i = 0; i < 60; i++) { poseTilt(pose, 6.5 + Math.sin(i * 2.1) * 2.5, 0); seen.push(pose.tipped); }
  const flips = seen.filter((v, i) => i && v !== seen[i - 1]).length;
  assert.ok(flips <= 1, `flipped ${flips} times`);
});

test("really tipped or picked up: shows within a few readings, and goes back when it ends", () => {
  const pose = newPose();
  for (let i = 0; i < 10; i++) { poseTilt(pose, 0, 0); poseLift(pose, FLOOR_CM); }
  let n = 0;
  while (!pose.tipped) { poseTilt(pose, 25, -3); n++; assert.ok(n <= Math.ceil(STEADY / 2), "a real lean shows soon"); }
  assert.equal(pose.roll, 25);
  assert.ok(Math.abs(pose.pitch) < TILT_ON);
  for (let i = 0; i < 3; i++) poseTilt(pose, 70, 0);
  assert.equal(pose.roll, 60, "drawn no further than 60 degrees");
  n = 0;
  while (pose.lift === 0) { poseLift(pose, 40); n++; assert.ok(n <= Math.ceil(STEADY / 2), "a real lift shows soon"); }
  assert.ok(pose.lift > 0.4);
  for (let i = 0; i < STEADY; i++) { poseTilt(pose, 1, 1); poseLift(pose, FLOOR_CM); }
  assert.equal(pose.roll, 0);
  assert.equal(pose.lift, 0, "set down again");
  for (let i = 0; i < STEADY; i++) poseTilt(pose, 30, 0);
  poseReset(pose);
  assert.equal(pose.roll, 0);
  poseTilt(pose, 1, 0);
  assert.equal(pose.roll, 0, "after a reset the old lean is gone: one new reading can't bring it back");
});

test("a floor too dark to see (nothing read underneath) is not a lift", () => {
  const pose = newPose();
  for (let i = 0; i < 20; i++) poseLift(pose, i % 3 ? null : 30);
  assert.equal(pose.lift, 0);
});

test("line sensors: pale floor is bright, a black line is dark", () => {
  assert.equal(lineShade(null), null);
  assert.equal(lineShade(52), 1, "the real robot on a pale desk");
  assert.equal(lineShade(1016), 0);
  assert.ok(lineShade(300) > 0 && lineShade(300) < 1);
});

// A pretend robot turns on the spot for two seconds the way the real one does (up to 90 deg/s,
// 540 deg/s per second), telling the page every 120 ms; each packet takes `latency` seconds to land.
// -> how far the drawn heading was from the real one: { mean, ahead (most it ran ahead), end }.
function turnAndWatch(latency) {
  const dt = 1 / 60, head = newCompass(), air = [];
  let heading = 0, rate = 0, turn = 0, nextNews = 0, sum = 0, n = 0, ahead = 0, moving = true;
  for (let t = 0; t < 4; t += dt) {
    const want = t > 0.5 && t < 2.5 ? 90 : 0;
    rate += Math.max(-540 * dt, Math.min(540 * dt, want - rate));
    heading += rate * dt;
    if (t >= nextNews) { air.push([t + latency, heading, rate]); nextNews += 0.12; }
    while (air.length && air[0][0] <= t) {
      const [, h, r] = air.shift();
      turn = r;
      compassNews(head, wrap(h), r);
    }
    moving = compassStep(head, turn, dt);
    const behind = wrap(heading - head.shown);
    sum += Math.abs(behind); n++;
    ahead = Math.max(ahead, -behind);
  }
  return { mean: sum / n, ahead, end: wrap(heading - head.shown), moving };
}

test("heading: the drawing stays close to a turning robot, and ends up where it stopped", () => {
  for (const [latency, mean] of [[0.03, 2], [0.06, 2], [0.1, 4]]) {
    const got = turnAndWatch(latency);
    assert.ok(got.mean < mean, `${latency * 1000} ms: ${got.mean.toFixed(1)} degrees off on average`);
    assert.ok(got.ahead < 8, `${latency * 1000} ms: ran ${got.ahead.toFixed(1)} degrees ahead`);
    assert.ok(Math.abs(got.end) < 0.1, "ends on the robot's heading");
    assert.equal(got.moving, false, "and stops drawing");
  }
});

test("heading: takes the short way round past half a turn", () => {
  const head = newCompass();
  compassNews(head, 170, 0);
  for (let i = 0; i < 120; i++) compassStep(head, 0, 1 / 60);
  compassNews(head, -170, 0);
  compassStep(head, 0, 1 / 60);
  assert.ok(head.shown > 170 || head.shown < -170, `went ${head.shown}`);
});
