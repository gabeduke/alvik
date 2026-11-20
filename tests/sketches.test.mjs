// Sketch library: the build output (scripts/build_site.sh) and flashing a sketch through the fake board.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, mkdirSync, writeFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { loadSketchList, loadSketchFiles, flashFiles } from "../docs/flasher.js";
import { FakeBoard } from "./fake_repl.mjs";

const repo = fileURLToPath(new URL("..", import.meta.url));
const sha = (b) => createHash("sha256").update(b).digest("hex");
const json = (p) => JSON.parse(readFileSync(p, "utf8"));
let out, tmp;

// fetch() over the built site, as if it were served at https://x/alvik/
const site = new URL("https://x/alvik/");
const siteFetch = async (url) => {
  const rel = decodeURIComponent(new URL(url).pathname.replace(/^\/alvik\//, ""));
  try {
    return new Response(readFileSync(join(out, rel)));
  } catch {
    return new Response("not found", { status: 404 });
  }
};

before(() => {
  tmp = mkdtempSync(join(tmpdir(), "alvik-"));
  out = join(tmp, "site");
  execFileSync("sh", ["scripts/build_site.sh"], { cwd: repo, env: { ...process.env, OUT: out, BUILD: "test" }, stdio: "pipe" });
});
after(() => rmSync(tmp, { recursive: true, force: true }));

const sketchNames = () => readdirSync(join(repo, "sketches")).filter((n) => statSync(join(repo, "sketches", n)).isDirectory()).sort();

test("the build publishes every sketch with its meta", () => {
  const { sketches } = json(join(out, "sketches/index.json"));
  assert.deepEqual(sketches.map((s) => s.name), sketchNames());
  assert.ok(sketches.length >= 2);
  for (const s of sketches) {
    const meta = json(join(repo, "sketches", s.name, "sketch.json"));
    assert.equal(s.title, meta.title);
    assert.equal(s.emoji, meta.emoji);
    assert.deepEqual(s.color, meta.color);
    assert.ok(s.description && Array.isArray(s.hardware));
    // per-sketch index: every source file (path, size, sha256), no stray files
    const { files } = json(join(out, "sketches", s.name, "index.json"));
    const src = readdirSync(join(repo, "sketches", s.name)).filter((n) => !n.startsWith(".") && !n.startsWith("__")).sort();
    assert.deepEqual(files.map((f) => f.path), src);
    for (const f of files) {
      const data = readFileSync(join(repo, "sketches", s.name, f.path));
      assert.equal(f.size, data.length);
      assert.equal(f.sha256, sha(data));
    }
    assert.ok(files.some((f) => f.path === `${s.entry}.py`), "entry module published");
  }
  assert.ok(sketches.find((s) => s.name === "disco") && sketches.find((s) => s.name === "follow_me"));
});

test("the core robot bundle has the menu that runs sketches", () => {
  const paths = json(join(out, "robot/index.json")).files.map((f) => f.path);
  for (const p of ["main.py", "demo.py", "sketchbook.py", "dance.py", "remote_control.py"]) assert.ok(paths.includes(p), p);
  assert.equal(readFileSync(join(out, "sw.js"), "utf8").includes('"test"'), true, "build id stamped");
});

test("loadSketchList reads the published list", async () => {
  const list = await loadSketchList(site, siteFetch);
  assert.deepEqual(list.map((s) => s.name), sketchNames());
});

for (const name of ["disco", "follow_me"]) {
  test(`flashing the ${name} sketch puts it in /sketches/${name}/ with the core files`, async () => {
    const files = await loadSketchFiles(site, name, siteFetch);
    const board = new FakeBoard();
    const results = await flashFiles(board.transport(), files);
    assert.ok(results.every((r) => r.ok && r.method === "sha256"), JSON.stringify(results));
    assert.deepEqual(board.resets, ["hard"]);

    const core = json(join(out, "robot/index.json")).files.map((f) => f.path);
    const own = json(join(out, "sketches", name, "index.json")).files.map((f) => `sketches/${name}/${f.path}`);
    assert.deepEqual([...board.files.keys()].sort(), [...core, ...own].sort(), "exactly core + sketch files");
    for (const p of core) assert.equal(sha(board.files.get(p)), sha(readFileSync(join(repo, "src", p))), p);
    for (const p of own) assert.equal(sha(board.files.get(p)), sha(readFileSync(join(repo, p))), p);
    assert.ok(board.dirs.has("sketches") && board.dirs.has(`sketches/${name}`), "folders created");
    assert.equal(results.at(-1).path, "main.py", "main.py still written last");
  });
}

test("loadSketchFiles refuses odd names and missing sketches", async () => {
  await assert.rejects(loadSketchFiles(site, "../robot", siteFetch), /Bad sketch name/);
  await assert.rejects(loadSketchFiles(site, "nope", siteFetch), /Couldn't load the file list \(404\)/);
});

test("sketch_index.py rejects broken sketches", () => {
  const cases = {
    "no entry module": [{ title: "T", emoji: "x", description: "d", color: [1, 0, 0], entry: "gone" }, {}],
    "bad colour": [{ title: "T", emoji: "x", description: "d", color: [2, 0, 0], entry: "m" }, { "m.py": "def run(alvik):\n    return -1\n" }],
    "no run()": [{ title: "T", emoji: "x", description: "d", color: [1, 0, 0], entry: "m" }, { "m.py": "x = 1\n" }],
    "clashes with src/": [{ title: "T", emoji: "x", description: "d", color: [1, 0, 0], entry: "dance" }, { "dance.py": "def run(alvik):\n    pass\n" }],
    "missing title": [{ emoji: "x", description: "d", color: [1, 0, 0], entry: "m" }, { "m.py": "def run(alvik):\n    pass\n" }],
  };
  for (const [why, [meta, files]] of Object.entries(cases)) {
    const dir = join(tmp, "bad-" + why.replace(/\W/g, "_"));
    mkdirSync(join(dir, "s"), { recursive: true });
    writeFileSync(join(dir, "s", "sketch.json"), JSON.stringify(meta));
    for (const [n, body] of Object.entries(files)) writeFileSync(join(dir, "s", n), body);
    const r = spawnSync("python3", [join(repo, "scripts/sketch_index.py"), dir, join(repo, "src")], { encoding: "utf8" });
    assert.notEqual(r.status, 0, why);
    assert.match(r.stderr, /sketches\/s:/, why);
  }
});
