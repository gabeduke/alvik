// The lessons (docs/learn/) and the other pages: every link inside the site leads somewhere, every
// lesson is kept for offline, and what the lessons say about the robot's code is still true.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join, dirname } from "node:path";

const repo = fileURLToPath(new URL("../", import.meta.url));
const docs = join(repo, "docs");
const read = (...path) => readFileSync(join(repo, ...path), "utf8");
const lessons = readdirSync(join(docs, "learn")).filter((f) => /^\d-.*\.html$/.test(f)).sort();
const pages = ["index.html", "flash.html", "learn/index.html", ...lessons.map((f) => "learn/" + f)];
const plain = (html) => html.replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");

test("there are nine lessons, each linked from the list and to its neighbours", () => {
  assert.equal(lessons.length, 9);
  const list = read("docs", "learn", "index.html");
  lessons.forEach((file, i) => {
    assert.ok(list.includes(`href="${file}"`), `${file} is in the list`);
    const page = read("docs", "learn", file);
    assert.match(page, new RegExp(`Lesson ${i + 1} of 9`), file);
    if (i > 0) assert.ok(page.includes(`href="${lessons[i - 1]}"`), `${file} links back`);
    if (i < 8) assert.ok(page.includes(`href="${lessons[i + 1]}"`), `${file} links on`);
  });
});

test("links and scripts inside the site lead to files that exist", () => {
  // robot/ and sketches/ are made by scripts/build_site.sh, not kept in docs/
  for (const page of pages) {
    const html = read("docs", page);
    const refs = [...html.matchAll(/(?:href|src)="([^"#]+)(?:#[^"]*)?"/g), ...html.matchAll(/from "(\.[^"]+)"/g)].map((m) => m[1]);
    for (const ref of refs) {
      if (/^(https?:|mailto:|data:)/.test(ref)) continue;
      const path = join(docs, dirname(page), ref.split("?")[0]);
      assert.ok(existsSync(path), `${page} -> ${ref}`);
      if (statSync(path).isDirectory()) assert.ok(existsSync(join(path, "index.html")), `${page} -> ${ref}index.html`);
    }
  }
});

test("every lesson is in the service worker's shell, so they open offline", () => {
  const sw = read("docs", "sw.js");
  for (const f of ["learn/", "learn/learn.css", ...lessons.map((f) => "learn/" + f)]) assert.ok(sw.includes(`"${f}"`), f);
});

test("the numbers the lessons quote are still the robot's numbers", () => {
  // Changed one of these in the robot's code? Then say so in the lesson named here too.
  const quoted = {
    "src/remote_control.py": ["SPEED = 8 ", "TURBO_SPEED = 13 ", "ACCEL = 30 ", "DECEL = 60 ", "STICK_TIMEOUT_MS = 600 ", "TELEMETRY_MS = 100 ",
      "BUMPER_CM = 8 ", "SLOW_CM = 14 ", "FLOOR_PROOF_CM = 4 ", "SURE = 3 "],
    "src/demo.py": ["START = 1 ", "PAGE = 6 ", "((1, 0, 1), run_remote)"],
    "src/hand_follower.py": ["reference = 10.0"],
    "docs/index.html": ["const DEAD = 0.18;", "now - sentAt > 150"],
    "docs/sensing.js": ["SEE_CM = 40", "CLOUD_MS = 1200", "FLOOR_CM = 7.4"],
    "docs/twin.js": ["Math.abs(s.roll) < 4"],
  };
  for (const [file, facts] of Object.entries(quoted)) {
    const text = read(...file.split("/"));
    for (const fact of facts) {
      assert.ok(text.includes(fact), `${file} no longer says "${fact.trim()}": check the lessons that quote it`);
    }
  }
});

test("the code the lessons show is the real code", () => {
  const code = (file) => read(...file.split("/")).split("\n")
    .map((line) => line.replace(/\s+#.*$/, "").trimEnd()).filter((line) => line.trim() && !line.trim().startsWith("#"));
  // (the first line of a block sits after the page's own indent, so lines are compared without theirs)
  const has = (lesson, line) => plain(read("docs", "learn", lesson)).split("\n").some((l) => l.replace(/\s+#.*$/, "").trim() === line.trim());
  // lesson 8 types out the whole Scaredy cat sketch and its label
  for (const line of code("sketches/scaredy_cat/scaredy_cat.py")) assert.ok(has("8-sketch.html", line), `lesson 8 is missing: ${line}`);
  for (const line of read("sketches", "scaredy_cat", "sketch.json").trim().split("\n")) assert.ok(has("8-sketch.html", line), `lesson 8 is missing: ${line}`);
  // and quotes Follow me's run(); other lessons quote a few lines each
  const follow = code("sketches/follow_me/follow_me.py");
  for (const line of follow.slice(follow.indexOf("def run(alvik):"))) assert.ok(has("8-sketch.html", line), `lesson 8 is missing: ${line}`);
  const quotes = {
    "2-drive.html": ["src/remote_control.py", ["        pkt = buf[i:i + 5]", "        if (~sum(pkt[:4])) & 0xFF != pkt[4]:"]],
    "3-smooth.html": ["src/remote_control.py", ["            linear = ramp(linear, want_linear, ACCEL * dt, DECEL * dt)", "        if stick != (0, 0) and ticks_diff(now, stick_at) > STICK_TIMEOUT_MS:"]],
    "6-bumper.html": ["src/remote_control.py", ["            seen = [zone.see(d, self.moved) for zone, d in zip(self.zones, distances[1:4])]",
      "            near = sorted(d for d in seen if d is not None)", "            self.ahead = near[1] if len(near) >= 2 else None"]],
  };
  for (const [lesson, [file, lines]] of Object.entries(quotes)) {
    const real = code(file), shown = plain(read("docs", "learn", lesson)).split("\n").map((l) => l.replace(/\s+#.*$/, "").trim());
    for (const line of lines) {
      assert.ok(real.includes(line), `${file} no longer has: ${line.trim()}`);
      assert.ok(shown.includes(line.trim()), `${lesson} should show: ${line.trim()}`);
    }
  }
});
