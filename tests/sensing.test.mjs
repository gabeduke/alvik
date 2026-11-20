// What the 3D robot shows for a reading (docs/sensing.js): the heat in front, how high it is held,
// and the shade under a line sensor.
import { test } from "node:test";
import assert from "node:assert/strict";
import { newHeat, easeHeat, heatAt, liftOf, lineShade, newCompass, compassNews, compassStep, wrap, PALE, YELLOW, RED, FLOOR_CM, SEE_CM, SLOW_CM, STOP_CM,
  newCloud, cloudAdd, cloudAlpha, CLOUD_MS, ROW_FRONT } from "../docs/sensing.js";

/** The heat once it has settled on these readings. */
function settled(zones) {
  const heat = newHeat();
  for (let i = 0; i < 400 && easeHeat(heat, zones, 1 / 60); i++);
  return heat;
}
const close = (a, b, eps = 0.02) => a.every((v, i) => Math.abs(v - b[i]) < eps);
const redder = (rgb) => rgb[0] - rgb[1];       // yellow -> orange -> red: green goes down

test("yellow from where the bumper slows, warmer on the way in, red where it stops", () => {
  const at = (cm) => heatAt(settled([cm, cm, cm, cm, cm]), 2);
  assert.equal(SLOW_CM, 14); assert.equal(STOP_CM, 8);
  assert.ok(close(at(20).rgb, PALE), "further than 16 cm: pale");
  assert.ok(close(at(14).rgb, YELLOW), "14 cm: yellow");
  assert.ok(redder(at(11).rgb) > redder(at(14).rgb), "closer is warmer");
  assert.ok(redder(at(9).rgb) > redder(at(11).rgb));
  assert.ok(close(at(8).rgb, RED), "8 cm: red");
  assert.ok(close(at(5).rgb, RED));
  assert.ok(at(39).alpha < at(30).alpha, "fades in from 40 cm");
  assert.equal(at(30).alpha, at(15).alpha, "and is full from 30 cm");
});

test("only the middle three zones go red, like the bumper", () => {
  const heat = settled([5, 5, 5, 5, 5]);
  for (const u of [1, 2, 3]) assert.ok(close(heatAt(heat, u).rgb, RED), `zone ${u}`);
  for (const u of [0, 4]) assert.ok(!close(heatAt(heat, u).rgb, RED, 0.1), `zone ${u} stays orange`);
  assert.ok(heatAt(heat, 0).alpha < heatAt(heat, 1).alpha, "the outer zones are fainter");
});

test("stopped by the bumper: the middle is red however far the wall is", () => {
  const heat = settled([25, 25, 25, 25, 25]);
  assert.ok(!close(heatAt(heat, 2).rgb, RED, 0.1));
  assert.ok(close(heatAt(heat, 2, true).rgb, RED));
  assert.ok(!close(heatAt(heat, 0, true).rgb, RED, 0.1), "not the outer zones");
});

test("distance and colour blend between neighbouring zones: no steps", () => {
  const heat = settled([null, 30, 10, 30, null]);
  assert.equal(heatAt(heat, 1).cm, 30);
  assert.equal(heatAt(heat, 2).cm, 10);
  assert.equal(heatAt(heat, 1.5).cm, 20);
  let last = heatAt(heat, 1);
  for (let u = 1.05; u <= 2.001; u += 0.05) {
    const h = heatAt(heat, u);
    assert.ok(h.cm <= last.cm && last.cm - h.cm < 2.5, `one smooth slope at ${u.toFixed(2)}: ${last.cm} -> ${h.cm}`);
    assert.ok(Math.abs(h.rgb[1] - last.rgb[1]) < 0.2, `colour at ${u.toFixed(2)}`);
    last = h;
  }
});

test("a zone that sees nothing fades away towards its neighbour, and both ends are soft", () => {
  const heat = settled([null, 20, 20, null, null]);
  assert.ok(heatAt(heat, 1).alpha > 0.5);
  assert.equal(heatAt(heat, 0).alpha, 0);
  assert.equal(heatAt(heat, 3).alpha, 0);
  const half = heatAt(heat, 0.5);
  assert.ok(half.alpha > 0 && half.alpha < heatAt(heat, 1).alpha);
  assert.equal(half.cm, 20, "it fades, it does not slide off to somewhere else");
  const all = settled([20, 20, 20, 20, 20]);
  assert.equal(heatAt(all, -0.5).alpha, 0);
  assert.equal(heatAt(all, 4.5).alpha, 0);
  assert.ok(heatAt(all, -0.25).alpha > 0 && heatAt(all, -0.25).alpha < heatAt(all, 0).alpha);
});

test("readings are followed over time, not jumped to", () => {
  const heat = settled([null, 30, 30, 30, null]);
  const zones = [null, 30, 14, 30, null];
  assert.equal(easeHeat(heat, zones, 1 / 60), true);
  assert.ok(heat.cm[2] < 30 && heat.cm[2] > 26, `one frame later: ${heat.cm[2]}`);
  for (let i = 0; i < 12; i++) easeHeat(heat, zones, 1 / 60);            // a fifth of a second
  assert.ok(heat.cm[2] < 18, `mostly there: ${heat.cm[2]}`);
  for (let i = 0; i < 120 && easeHeat(heat, zones, 1 / 60); i++);
  assert.equal(heat.cm[2], 14);
  assert.equal(easeHeat(heat, zones, 1 / 60), false, "settled: nothing left to draw");
});

test("a wall that shows up fades in where it is, and one that goes fades out", () => {
  const heat = settled([null, null, 35, null, null]);
  const zones = [null, null, 35, 15, null];
  easeHeat(heat, zones, 1 / 60);
  assert.equal(heat.cm[3], 15, "no slide in from far away");
  assert.ok(heat.seen[3] > 0 && heat.seen[3] < 0.3);
  easeHeat(heat, [null, null, null, 15, null], 1 / 60);
  assert.ok(heat.seen[2] < 1 && heat.seen[2] > 0.7);
  assert.equal(heat.cm[2], 35);
  const gone = settled([null, null, null, null, null]);
  assert.deepEqual(gone.seen, [0, 0, 0, 0, 0]);
  assert.equal(heatAt(settled([SEE_CM + 1, 50, 200, 60, 41]), 2).alpha, 0, "further than 40 cm is not drawn");
});

test("point cloud: readings become points that fade, and only the newest are kept", () => {
  const cloud = newCloud(6);
  cloudAdd(cloud, 1, ROW_FRONT, 17, 1000);
  cloudAdd(cloud, 2, ROW_FRONT, null, 1000);            // nothing seen: no point
  cloudAdd(cloud, 3, ROW_FRONT, SEE_CM + 60, 1000);     // too far for the picture: no point
  assert.equal(cloud.points.length, 1);
  const [p] = cloud.points;
  assert.equal(cloudAlpha(p, 1000), 1);
  assert.ok(cloudAlpha(p, 1000 + CLOUD_MS / 2) > 0.4 && cloudAlpha(p, 1000 + CLOUD_MS / 2) < 0.6, "half gone half way");
  assert.equal(cloudAlpha(p, 1000 + CLOUD_MS), 0);
  assert.equal(cloudAlpha(p, 900), 0, "a clock that jumped back shows nothing odd");
  for (let i = 0; i < 8; i++) cloudAdd(cloud, i % 5, ROW_FRONT, 20 + i, 2000 + i);
  assert.equal(cloud.points.length, 6);
  assert.deepEqual(cloud.points.map((q) => q.cm).sort(), [22, 23, 24, 25, 26, 27], "the oldest made way");
  const far = newCloud();
  cloudAdd(far, 2, ROW_FRONT, 39, 0);
  cloudAdd(far, 2, ROW_FRONT, 25, 0);
  assert.ok(cloudAlpha(far.points[0], 0) < cloudAlpha(far.points[1], 0), "far points are fainter, like the heat");
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
