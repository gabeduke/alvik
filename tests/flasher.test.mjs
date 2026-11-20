// Run: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { flashFiles, pyBytes, pyStr, sha256Hex, flashOrder, loadBundle, FlashError, RawRepl } from "../docs/flasher.js";
import { FakeBoard, parsePyLiteral } from "./fake_repl.mjs";

const enc = new TextEncoder();

function awkwardFiles() {
  const big = new Uint8Array(5000);
  for (let i = 0; i < big.length; i++) big[i] = (i * 31 + (i >> 7)) & 0xff;   // every byte value, > several chunks
  return [
    { path: "main.py", data: enc.encode("import demo\n") },
    { path: "quotes.py", data: enc.encode(`s = 'it\\'s' + "say \\"hi\\"" + '''tri'''\npath = "C:\\\\new\\\\table"\n`) },
    { path: "unicode.py", data: enc.encode("print('héllo 🤖 ✓ — ünï')\n# ☃\n") },
    { path: "crlf.py", data: enc.encode("a = 1\r\nb = 2\r\n\r\n\tc = '\\r\\n'\r\n") },
    { path: "empty.py", data: new Uint8Array(0) },
    { path: "big.bin", data: big },
    { path: "lib/sub/dir file's.py", data: enc.encode("x = 1\x00\x7f\xff") },
    { path: "ünï.py", data: enc.encode("pass\n") },
  ];
}

function assertSameFiles(board, files) {
  for (const f of files) {
    const got = board.files.get(f.path);
    assert.ok(got, `missing ${f.path}`);
    assert.equal(Buffer.compare(Buffer.from(got), Buffer.from(f.data)), 0, `${f.path} differs`);
  }
  assert.equal(board.files.size, files.length);
}

test("pyBytes round-trips every byte value", () => {
  const all = Uint8Array.from({ length: 256 }, (_, i) => i);
  const lit = pyBytes(all);
  assert.match(lit, /^b'.*'$/s);
  assert.deepEqual(parsePyLiteral(lit.slice(2, -1)), all);
  assert.ok(!/[\x00-\x1f\x7f-\uffff]/.test(lit), "literal is plain printable ASCII");
});

test("pyStr escapes quotes and backslashes", () => {
  assert.equal(pyStr("a'b\\c"), "'a\\'b\\\\c'");
  assert.equal(new TextDecoder().decode(parsePyLiteral(pyStr("ü'\n").slice(1, -1))), "ü'\n");
});

for (const rawPaste of [true, false]) {
  test(`flashes awkward files byte-for-byte (${rawPaste ? "raw-paste" : "plain raw REPL"})`, async () => {
    const board = new FakeBoard({ rawPaste, window: 64 });
    const files = awkwardFiles();
    const events = [];
    const results = await flashFiles(board.transport(), files, { onEvent: (e) => events.push(e) });
    assertSameFiles(board, files);
    assert.ok(results.every((r) => r.ok && r.method === "sha256"), JSON.stringify(results));
    assert.equal(board.overrun, undefined, "respected raw-paste flow control");
    assert.equal(board.pasteExecs > 0, rawPaste);
    assert.deepEqual(board.resets, ["hard"]);
    assert.equal(results.at(-1).path, "main.py", "main.py written last");
    // progress events reach the full size for the big file
    const big = events.filter((e) => e.path === "big.bin" && e.state === "writing").at(-1);
    assert.deepEqual([big.written, big.total], [5000, 5000]);
    assert.deepEqual(events.filter((e) => e.type === "stage").map((e) => e.stage), ["connect", "reset", "done"]);
  });
}

test("old firmware without raw-paste falls back to plain raw REPL", async () => {
  const board = new FakeBoard({ oldFirmware: true });
  const files = awkwardFiles().slice(0, 3);
  const results = await flashFiles(board.transport(), files);
  assertSameFiles(board, files);
  assert.ok(results.every((r) => r.ok));
  assert.equal(board.pasteExecs, 0);
});

test("falls back to size checks without hashlib", async () => {
  const board = new FakeBoard({ hashlib: false });
  const files = awkwardFiles();
  const results = await flashFiles(board.transport(), files, { reset: "soft" });
  assertSameFiles(board, files);
  assert.ok(results.every((r) => r.ok && r.method === "size"));
  assert.deepEqual(board.resets, ["soft"]);
});

test("a board error marks the file failed and carries on", async () => {
  const board = new FakeBoard({ failOn: /^f=open\('crlf\.py'/ });
  const files = awkwardFiles();
  const results = await flashFiles(board.transport(), files);
  const bad = results.find((r) => r.path === "crlf.py");
  assert.equal(bad.ok, false);
  assert.match(bad.error, /ENOSPC/);
  assert.ok(results.filter((r) => r.path !== "crlf.py").every((r) => r.ok));
});

test("detects a corrupted write", async () => {
  const board = new FakeBoard();
  const orig = board.exec.bind(board);
  board.exec = (code) => {
    const r = orig(code);
    if (code === "f.close()" && board.files.has("quotes.py")) board.files.get("quotes.py")[0] ^= 1;
    return r;
  };
  const results = await flashFiles(board.transport(), awkwardFiles(), { reset: false });
  assert.equal(results.find((r) => r.path === "quotes.py").ok, false);
});

test("times out with a clear message when the board says nothing", async () => {
  const board = new FakeBoard({ silent: true });
  const repl = new RawRepl(board.transport());
  await assert.rejects(repl.enter({ attempts: 2, wait: 50 }), (e) =>
    e instanceof FlashError && e.fatal && /Couldn't stop the robot's program/.test(e.message) && !!e.hint);
});

test("reports a closed connection", async () => {
  const board = new FakeBoard();
  const t = board.transport();
  board.closed = true;
  await assert.rejects(flashFiles(t, awkwardFiles()), (e) => e instanceof FlashError && /USB connection closed/.test(e.message));
});

test("flashOrder puts boot.py and main.py last", () => {
  const order = flashOrder(["main.py", "a.py", "boot.py", "z.py"].map((path) => ({ path }))).map((f) => f.path);
  assert.deepEqual(order, ["a.py", "z.py", "boot.py", "main.py"]);
});

test("loadBundle reads index.json and rejects mismatched files", async () => {
  const files = { "a.py": enc.encode("print(1)\n"), "b.py": enc.encode("") };
  const index = { files: await Promise.all(Object.entries(files).map(async ([path, d]) => ({ path, size: d.length, sha256: await sha256Hex(d) }))) };
  const fakeFetch = async (url) => {
    const name = new URL(url).pathname.split("/").pop();
    if (name === "index.json") return new Response(JSON.stringify(index));
    return files[name] ? new Response(files[name]) : new Response("", { status: 404 });
  };
  const got = await loadBundle(new URL("https://x/alvik/robot/"), fakeFetch);
  assert.deepEqual(got.map((f) => [f.path, f.data.length]), [["a.py", 9], ["b.py", 0]]);
  files["a.py"] = enc.encode("tampered");
  await assert.rejects(loadBundle(new URL("https://x/alvik/robot/"), fakeFetch), /doesn't match/);
});

test("the real src/ files flash correctly", async () => {
  const dir = new URL("../src/", import.meta.url);
  const files = readdirSync(dir).filter((n) => n.endsWith(".py")).map((path) => ({ path, data: new Uint8Array(readFileSync(new URL(path, dir))) }));
  const board = new FakeBoard();
  const results = await flashFiles(board.transport(), files);
  assertSameFiles(board, files);
  assert.ok(results.every((r) => r.ok));
  assert.equal(createHash("sha256").update(board.files.get("demo.py")).digest("hex"), await sha256Hex(files.find((f) => f.path === "demo.py").data));
});
