// The 3D robot's files: the model has the parts twin.js looks for and carries its credits, and
// everything the page needs offline is in the service worker's shell (a missing file there would
// stop the app installing).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const docs = fileURLToPath(new URL("../docs/", import.meta.url));

function glbJson(path) {
  const b = readFileSync(path);
  assert.equal(b.toString("latin1", 0, 4), "glTF");
  const len = b.readUInt32LE(12);
  assert.equal(b.toString("latin1", 16, 20), "JSON");
  return JSON.parse(b.toString("utf8", 20, 20 + len));
}

test("alvik.glb has the named parts, in metres, with the credits", () => {
  const gltf = glbJson(join(docs, "models/alvik.glb"));
  const nodes = Object.fromEntries(gltf.nodes.map((n) => [n.name, n]));
  for (const name of ["Body", "Baseplate", "WheelL", "WheelR", "LedL", "LedR", "Tof"]) assert.ok(nodes[name], name);
  assert.match(gltf.asset.copyright, /Arduino/);
  assert.match(gltf.asset.copyright, /GiulioT/);
  assert.match(gltf.asset.copyright, /CC BY-NC-SA/);
  // wheels: origin on the axle, 17 mm up, left wheel on +X; LEDs have their own materials
  assert.deepEqual(nodes.WheelL.translation.map((v) => +v.toFixed(4)), [0.0448, 0.017, 0]);
  assert.deepEqual(nodes.WheelR.translation.map((v) => +v.toFixed(4)), [-0.0448, 0.017, 0]);
  const material = (n) => gltf.materials[gltf.meshes[n.mesh].primitives[0].material].name;
  assert.equal(material(nodes.LedL), "LedL");
  assert.equal(material(nodes.LedR), "LedR");
  // about 96 mm wide: the body's bounding box says the file is in metres
  const pos = gltf.accessors[gltf.meshes[nodes.Body.mesh].primitives[0].attributes.POSITION];
  assert.ok(Math.abs(pos.max[0] - 0.048) < 0.001 && Math.abs(pos.min[1]) < 0.001, JSON.stringify([pos.min, pos.max]));
});

test("the page's files are all in the service worker shell and exist", () => {
  const sw = readFileSync(join(docs, "sw.js"), "utf8");
  const shell = JSON.parse(sw.match(/const SHELL = (\[[\s\S]*?\]);/)[1].replace(/,\s*\]/, "]"));
  for (const f of shell) assert.ok(existsSync(join(docs, f === "./" ? "index.html" : f)), f);
  for (const f of ["telemetry.js", "twin.js", "models/alvik.glb", "vendor/three/three.module.min.js",
    "vendor/three/loaders/GLTFLoader.js", "vendor/three/utils/BufferGeometryUtils.js"]) assert.ok(shell.includes(f), f);
  const page = readFileSync(join(docs, "index.html"), "utf8");
  assert.match(page, /"three": "\.\/vendor\/three\/three\.module\.min\.js"/, "import map for the addons");
});
