// The pretend robot (docs/pretend.js, "try it without a robot") and the JavaScript copy of the
// robot's driving sums (docs/bumper.js). The packets it sends are checked against the same examples
// as the real robot's, and the sums against examples worked out by the robot's own Python code
// (tests/bumper_vectors.json, written by tests/test_robot.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createPretendRobot, telemetryPacket, sensorPacket, underPacket, rayLength, ROOM, COPIED } from "../docs/pretend.js";
import * as sums from "../docs/bumper.js";
import { ramp, bumperLimit, Bumper, Zone, SLOW_CM, BUMPER_CM } from "../docs/bumper.js";
import { telemetryReader, telemetryRequest } from "../docs/telemetry.js";

const load = (name) => JSON.parse(readFileSync(new URL(name, import.meta.url), "utf8"));
const hex = (bytes) => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
const same = (a, b) => (a === null || b === null ? a === b : Math.abs(a - b) < 1e-6);

function packet(kind, a, b) {
  const bytes = [0x21, kind.charCodeAt(0), a & 0xff, b & 0xff];
  bytes.push(~bytes.reduce((x, y) => x + y, 0) & 0xff);
  return Uint8Array.from(bytes);
}

/** A pretend robot the test can drive: seeded, with everything it sends parsed into `got`. */
function robot(room) {
  let seed = 42;
  const random = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;
  const got = { T: [], S: [], U: [] };
  const feed = telemetryReader((t) => got.T.push(t), (s) => got.S.push(s), (u) => got.U.push(u));
  const r = createPretendRobot({ send: feed, random, room });
  r.write(telemetryRequest(true));
  r.got = got;
  r.run = (ms, each = () => {}) => { for (let t = 0; t < ms; t += 30) { each(t); r.step(30); } };
  r.stick = (x, y) => r.write(packet("J", x, y));
  r.press = (b) => { r.write(packet("B", 48 + b, 0x31)); r.write(packet("B", 48 + b, 0x30)); };
  r.driving = (x, y, ms) => r.run(ms, (t) => { if (t % 150 === 0) r.stick(x, y); });
  return r;
}

test("its packets are the real robot's packets (the shared examples)", () => {
  const all = load("./telemetry_vectors.json");
  for (const v of all.filter((v) => v.robot)) assert.equal(hex(telemetryPacket(v.robot)), v.hex, v.note);
  for (const v of all.filter((v) => v.sensors)) assert.equal(hex(sensorPacket(v.sensors)), v.hex, v.note);
  for (const v of all.filter((v) => v.under)) assert.equal(hex(underPacket(v.under)), v.hex, v.note);
});

test("the driving sums give what the robot's Python gives", () => {
  const v = load("./bumper_vectors.json");
  assert.ok(v.ramp.length >= 8 && v.limit.length >= 5 && v.looks.length >= 4);
  // every number of the robot's that is copied into the page's code is still the robot's
  for (const [name, value] of Object.entries({ ...v.numbers, ...v.dance })) {
    const copy = name in COPIED ? COPIED[name] : sums[name];
    assert.deepEqual(copy, value, `${name} is ${JSON.stringify(value)} on the robot`);
  }
  for (const [now, want, up, down, out] of v.ramp) assert.ok(same(ramp(now, want, up, down), out), `ramp ${now} -> ${want}`);
  for (const [d, speed, out] of v.limit) assert.ok(same(bumperLimit(d, speed), out), `limit at ${d}`);
  for (const scene of v.looks) {
    const eyes = new Bumper();
    scene.steps.forEach(([distances, moved, turned], i) =>
      assert.ok(same(eyes.look(distances, moved, turned), scene.ahead[i]), `${scene.note}, look ${i}`));
  }
  for (const scene of v.zones) {
    const zone = new Zone();
    scene.steps.forEach(([d, moved, turned], i) =>
      assert.ok(same(zone.see(d, moved, turned), scene.seen[i]), `${scene.note}, reading ${i}`));
  }
});

test("says nothing until the page asks, then three packets about eight times a second", () => {
  const quiet = createPretendRobot({ send: () => assert.fail("not asked") });
  for (let i = 0; i < 30; i++) quiet.step(30);
  const r = robot();
  r.run(3000);
  for (const k of ["T", "S", "U"]) assert.ok(r.got[k].length >= 22 && r.got[k].length <= 30, `${k}: ${r.got[k].length}`);
  const t = r.got.T.at(-1);
  assert.deepEqual([t.heading, t.speed, t.turn, t.turbo, t.bumper, t.blocked], [0, 0, 0, false, true, false]);
  assert.deepEqual(t.left, [1, 1, 1]);
  assert.equal(r.got.S.at(-1).battery, 87);
  assert.ok([7, 8].includes(r.got.U.at(-1).bottom), "about 7.4 cm to the floor");
});

test("the joystick drives it, gently, and it stops when the page goes quiet", () => {
  const r = robot();
  r.driving(0, 100, 150);
  assert.ok(r.view().linear > 0 && r.view().linear < 8, "still speeding up");
  r.driving(0, 100, 600);
  assert.equal(r.view().linear, 8);
  assert.ok(r.view().y > ROOM.start.y + 3);
  r.run(1500);                                   // no more joystick packets
  assert.equal(r.view().linear, 0);
  r.driving(-100, 0, 1000);                      // stick left: turns left, heading counts up
  assert.ok(r.got.T.at(-1).heading > 40 && r.view().angular === 90);
});

test("drives up to the box, slows, stops BUMPER_CM short and flashes red; reversing is still allowed", () => {
  const r = robot();
  r.driving(0, 100, 12000);
  const v = r.view(), gap = ROOM.boxes[0].y - (v.y + 4.8);
  assert.ok(v.blocked && v.linear === 0, "stopped by the bumper");
  assert.ok(gap > BUMPER_CM - 2 && gap < BUMPER_CM + 1.5, `stopped ${gap.toFixed(1)} cm from the box`);
  const t = r.got.T.at(-1);
  assert.ok(t.blocked && t.distance < BUMPER_CM + 1);
  assert.ok(r.got.T.some((p) => !p.blocked && p.distance !== null && p.distance < SLOW_CM && p.speed > 0 && p.speed < 8), "slowed on the way in");
  assert.ok(r.got.T.slice(-12).some((p) => p.left.join() === "1,0,0"), "red flashes");
  r.driving(0, -100, 600);
  assert.ok(r.view().linear < 0);
});

test("on open floor the floor's reading shows in what the sensor sends but does not slow it", () => {
  const empty = { ...ROOM, w: 400, h: 400, start: { x: 200, y: 200 }, boxes: [], posts: [], mats: [], tape: [] };
  const r = robot(empty);
  r.driving(0, 100, 6000);
  assert.equal(r.view().linear, 8);
  assert.ok(r.got.T.every((t) => t.distance === null && !t.blocked));
  assert.ok(r.got.S.every((s) => s.zones.every((d) => d >= 16 && d <= 18)), "the floor, 16 to 18 cm");
});

test("bumper off: it drives into the box and stays outside it", () => {
  const r = robot();
  r.press(4);
  r.driving(0, 100, 12000);
  const v = r.view();
  assert.equal(v.bumper, false);
  assert.ok(Math.abs(ROOM.boxes[0].y - v.y - 6) < 0.3, `up against the box at y = ${v.y.toFixed(1)}`);
  assert.equal(r.got.T.at(-1).bumper, false);
});

test("a chair leg to one side fills one cell only: the bumper does nothing and the robot bumps into it", () => {
  const post = ROOM.posts[0];
  const r = robot({ ...ROOM, start: { x: post.x + 2.5, y: post.y - 36 }, tape: [], mats: [] });
  const gap = () => Math.hypot(post.x - r.view().x, post.y - r.view().y) - post.r - 4.8;
  r.driving(0, 100, 8000);
  assert.ok(r.got.T.every((t) => t.distance === null && !t.blocked), "one cell alone is nothing");
  assert.ok(r.got.S.some((s) => s.zones.some((d) => d < 10)), "though the sensor saw it");
  assert.ok(gap() < 2, `up against the leg: ${gap().toFixed(1)} cm from its nose`);
});

test("a chair leg dead ahead is in both middle cells: it stops for it like a wall", () => {
  const post = ROOM.posts[0];
  const r = robot({ ...ROOM, start: { x: post.x, y: post.y - 36 }, tape: [], mats: [] });
  r.driving(0, 100, 8000);
  const gap = post.y - post.r - (r.view().y + 4.8);
  assert.ok(r.view().blocked && gap > BUMPER_CM - 2 && gap < BUMPER_CM + 1.5, `stopped ${gap.toFixed(1)} cm from the leg`);
});

test("line sensors read dark over the tape, and the floor's colour changes on a mat", () => {
  const r = robot();
  assert.ok(r.got.U.length === 0);
  r.run(200);
  assert.ok(r.got.U.at(-1).lines.every((v) => v < 100));
  assert.deepEqual(r.got.U.at(-1).floor, ROOM.floor);
  r.driving(0, 100, 3600);
  assert.ok(r.got.U.some((u) => u.lines.every((v) => v > 500)), "crossed the tape");
  const mat = ROOM.mats[0];
  const onMat = robot({ ...ROOM, start: { x: mat.x + mat.w / 2, y: mat.y + mat.h / 2 } });
  onMat.run(200);
  assert.deepEqual(onMat.got.U.at(-1).floor, mat.rgb);
});

test("lights, turbo and the dance", () => {
  const r = robot();
  r.press(1);
  r.run(200);
  assert.deepEqual(r.got.T.at(-1).left, [1, 0, 0]);
  r.press(2);
  r.driving(0, -100, 1500);
  assert.equal(r.got.T.at(-1).speed, -13);
  assert.ok(r.got.T.at(-1).turbo);
  r.run(1500);
  r.press(3);
  r.run(3500);
  const d = r.got.T.at(-1);
  assert.ok(d.dancing && d.turn === 360 && d.left.join() !== d.right.join(), "the big spin, two colours");
  r.run(1500);                                   // the dance ends, and the spin winds down
  assert.ok(!r.got.T.at(-1).dancing && r.got.T.at(-1).turn === 0);
  r.press(3);
  r.run(300);
  r.stick(0, 50);                                // the joystick stops the dance
  r.run(200);
  assert.ok(!r.got.T.at(-1).dancing);
});

test("picked up: the floor falls away, it tips, the wheels turn it but it goes nowhere", () => {
  const r = robot();
  r.hold(true);
  const before = r.view();
  r.driving(-100, 100, 1500);
  const v = r.view(), u = r.got.U.at(-1), s = r.got.S.at(-1);
  assert.deepEqual([v.x, v.y], [before.x, before.y]);
  assert.ok(v.heading > 60, "the wheels still turn the heading");
  assert.ok(u.bottom > 35 && u.lines.every((l) => l > 800));
  assert.ok(Math.abs(s.pitch) >= 8 && s.zones.every((z) => z === null));
  r.hold(false);
  r.run(300);
  assert.ok([7, 8].includes(r.got.U.at(-1).bottom), "about 7.4 cm to the floor");
});

test("rays stop at walls, boxes and posts", () => {
  const room = { w: 100, h: 100, boxes: [{ x: 40, y: 60, w: 20, h: 10 }], posts: [{ x: 80, y: 50, r: 2 }] };
  assert.ok(same(rayLength(50, 10, 0, 1, room), 50));           // the box
  assert.ok(same(rayLength(10, 10, 0, 1, room), 90));           // the far wall
  assert.ok(same(rayLength(10, 10, -1, 0, room), 10));          // the wall beside it
  assert.ok(same(rayLength(50, 50, 1, 0, room), 28));           // the post
  assert.ok(same(rayLength(50, 53, 1, 0, room), 50));           // just past the post
});

test("the service worker keeps the pretend robot for offline", () => {
  const sw = readFileSync(new URL("../docs/sw.js", import.meta.url), "utf8");
  for (const f of ["pretend.js", "bumper.js", "playroom.js"]) assert.ok(sw.includes(`"${f}"`), f);
});
