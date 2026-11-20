// Telemetry: the page's parser (docs/telemetry.js) against the examples the robot code is also tested with.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseTelemetry, parseSensors, parseUnder, telemetryReader, telemetryRequest, TELEMETRY_LEN, SENSORS_LEN, UNDER_LEN } from "../docs/telemetry.js";

const all = JSON.parse(readFileSync(new URL("./telemetry_vectors.json", import.meta.url), "utf8"));
const vectors = all.filter((v) => v.robot), sensorVectors = all.filter((v) => v.sensors), underVectors = all.filter((v) => v.under);
const bytes = (hex) => Uint8Array.from(hex.match(/../g), (h) => parseInt(h, 16));

test("parses the shared example packets", () => {
  assert.ok(vectors.length >= 5);
  for (const v of vectors) {
    assert.equal(bytes(v.hex).length, TELEMETRY_LEN);
    assert.deepEqual(parseTelemetry(bytes(v.hex)), v.page, v.note);
  }
});

test("parses the shared sensors packets", () => {
  assert.ok(sensorVectors.length >= 2);
  for (const v of sensorVectors) {
    assert.equal(bytes(v.hex).length, SENSORS_LEN);
    assert.deepEqual(parseSensors(bytes(v.hex)), v.page, v.note);
    assert.equal(parseTelemetry(bytes(v.hex)), null);
  }
});

test("parses the shared under-the-robot packets", () => {
  assert.ok(underVectors.length >= 3);
  for (const v of underVectors) {
    assert.equal(bytes(v.hex).length, UNDER_LEN);
    assert.deepEqual(parseUnder(bytes(v.hex)), v.page, v.note);
    assert.equal(parseTelemetry(bytes(v.hex)), null);
    assert.equal(parseSensors(bytes(v.hex)), null);
  }
});

test("reader hands out all three kinds, and a reader that isn't told about one skips it", () => {
  const got = [];
  const feed = telemetryReader((t) => got.push(["T", t]), (s) => got.push(["S", s]), (u) => got.push(["U", u]));
  const stream = [...bytes(vectors[0].hex), ...bytes(sensorVectors[0].hex), ...bytes(underVectors[0].hex), ...bytes(vectors[1].hex)];
  feed(stream);
  assert.deepEqual(got, [["T", vectors[0].page], ["S", sensorVectors[0].page], ["U", underVectors[0].page], ["T", vectors[1].page]]);
  const only = [];
  telemetryReader((t) => only.push(t))(stream);
  assert.deepEqual(only, [vectors[0].page, vectors[1].page]);
});

test("a letter from newer robot code is skipped, whatever its bytes look like", () => {
  // 'Q' is not a packet yet. Its body holds a '!' 'T' that is not a real packet, right before a real one.
  const got = [];
  const feed = telemetryReader((t) => got.push(["T", t]), (s) => got.push(["S", s]), (u) => got.push(["U", u]));
  feed([0x21, 0x51, 0x21, 0x54, 7, ...bytes(underVectors[1].hex), ...bytes(vectors[2].hex)]);
  assert.deepEqual(got, [["U", underVectors[1].page], ["T", vectors[2].page]]);
});

test("rejects damaged, short and other packets", () => {
  const good = bytes(vectors[1].hex);
  const bad = good.slice(); bad[4] ^= 1;
  assert.equal(parseTelemetry(bad), null);
  assert.equal(parseTelemetry(good.slice(0, 9)), null);
  const other = good.slice(); other[1] = 0x42;
  assert.equal(parseTelemetry(other), null);
});

test("reader copes with pieces, junk and a damaged packet", () => {
  const got = [];
  const feed = telemetryReader((t) => got.push(t));
  const a = bytes(vectors[1].hex), b = bytes(vectors[2].hex), c = bytes(vectors[3].hex);
  const bad = a.slice(); bad[9] ^= 0xff;
  const all = [0x78, 0x21, ...a, ...bad, 0x21, 0x3f, ...b, ...c];
  feed(all.slice(0, 7));
  feed(all.slice(7, 20));
  feed(all.slice(20));
  assert.deepEqual(got, [vectors[1].page, vectors[2].page, vectors[3].page]);
});

test("the request packet is what the robot expects", () => {
  assert.deepEqual([...telemetryRequest(true)], [0x21, 0x54, 0x31, 0, ~(0x21 + 0x54 + 0x31) & 0xff]);
  assert.deepEqual([...telemetryRequest(false)].slice(0, 4), [0x21, 0x54, 0x30, 0]);
});
