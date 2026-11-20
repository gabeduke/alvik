// A pretend MicroPython board for testing docs/flasher.js without hardware.
// It speaks the raw REPL protocol (and optionally raw-paste), "runs" only the few kinds of Python
// the flasher sends (open/w/close, stat+sha256, mkdir, reset), and keeps the files in memory.
// Also loads in a browser (no node:crypto there: pass hashlib: false to verify by size).
const nodeCrypto = globalThis.process?.versions?.node ? await import("node:crypto") : null;
const later = globalThis.setImmediate ?? ((f) => setTimeout(f, 0));

const enc = new TextEncoder();
const BANNER = "raw REPL; CTRL-B to exit\r\n>";

// Parses a Python bytes/str literal body, independently of the flasher's encoder.
export function parsePyLiteral(src) {
  const out = [];
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (ch !== "\\") { out.push(...enc.encode(ch)); continue; }
    const n = src[++i];
    const simple = { "\\": 0x5c, "'": 0x27, '"': 0x22, n: 0x0a, r: 0x0d, t: 0x09, 0: 0x00, a: 7, b: 8, f: 12, v: 11 };
    if (n === "x") { out.push(parseInt(src.slice(i + 1, i + 3), 16)); i += 2; }
    else if (n in simple) out.push(simple[n]);
    else throw new Error("unknown escape \\" + n);
  }
  return Uint8Array.from(out);
}

function lit(code, re) {
  const m = re.exec(code);
  return m ? m : null;
}

export class FakeBoard {
  // opts: rawPaste (bool), window (raw-paste window size), hashlib (bool), running (a program is
  // running and ignores Ctrl-A until Ctrl-C), chunkOut (max bytes per read, to split replies),
  // failOn (regex: code matching it raises fail), fail (error text), silent (never answers)
  constructor(opts = {}) {
    this.o = { rawPaste: true, window: 128, hashlib: true, running: true, chunkOut: 7, fail: "OSError: [Errno 28] ENOSPC", ...opts };
    this.files = new Map();
    this.dirs = new Set();
    this.mode = "friendly";
    this.running = this.o.running;
    this.code = [];
    this.out = [];        // pending output bytes
    this.waiters = [];
    this.closed = false;
    this.execs = 0;
    this.pasteExecs = 0;
    this.resets = [];
    this.open = null;     // { path, data[] }
    this.log = [];
  }

  // ----- transport side -----
  transport() {
    return {
      write: async (data) => { for (const b of data) this.byte(b); },
      read: () => this.readChunk(),
      close: async () => { this.closed = true; this.flush(); },
    };
  }

  readChunk() {
    return new Promise((resolve) => { this.waiters.push(resolve); this.flush(); });
  }

  flush() {
    while (this.waiters.length && (this.out.length || this.closed)) {
      const w = this.waiters.shift();
      if (!this.out.length) { w(null); continue; }
      const n = Math.min(this.out.length, this.o.chunkOut);
      w(Uint8Array.from(this.out.splice(0, n)));
    }
  }

  emit(s) {
    if (this.o.silent) return;
    const bytes = typeof s === "string" ? enc.encode(s) : s;
    this.out.push(...bytes);
    later(() => this.flush());   // async, like a real port
  }

  // ----- device side -----
  byte(b) {
    if (this.mode === "paste") return this.pasteByte(b);
    if (b === 0x03) {   // Ctrl-C
      if (this.running) { this.running = false; this.emit("Traceback (most recent call last):\r\nKeyboardInterrupt: \r\nover\r\n"); }
      if (this.mode === "friendly") this.emit("\r\n>>> ");
      this.code = [];
      return;
    }
    if (this.running) return;   // the menu ignores everything else
    if (this.mode === "friendly") {
      if (b === 0x01) { this.mode = "raw"; this.code = []; this.emit("\r\n" + BANNER); }
      else if (b === 0x04) { this.resets.push("soft"); this.emit("MPY: soft reboot\r\n"); this.running = true; }
      return;
    }
    // raw mode
    if (b === 0x02) { this.mode = "friendly"; this.emit("\r\n>>> "); return; }
    if (b === 0x05 && this.code.length === 0 && !this.o.oldFirmware) { this.pendingE = 1; return; }
    if (this.pendingE === 1 && b === 0x41) { this.pendingE = 2; return; }
    if (this.pendingE === 2 && b === 0x01) {
      this.pendingE = 0;
      if (!this.o.rawPaste) { this.emit("R\x00"); return; }
      this.mode = "paste";
      this.pasteCount = 0;
      this.granted = this.o.window;
      this.emit(Uint8Array.from([0x52, 0x01, this.o.window & 0xff, this.o.window >> 8]));
      return;
    }
    this.pendingE = 0;
    if (b === 0x01) { this.code = []; this.emit("\r\n" + BANNER); return; }   // Ctrl-A resets the raw REPL
    if (b === 0x04) {
      if (this.code.length === 0) { this.resets.push("soft-raw"); this.emit("OK\r\nMPY: soft reboot\r\n" + BANNER); return; }
      this.emit("OK");
      this.run();
      return;
    }
    this.code.push(b);
  }

  pasteByte(b) {
    if (b === 0x04) {
      this.mode = "raw";
      this.emit("\x04");
      this.pasteExecs++;
      this.run();
      return;
    }
    this.code.push(b);
    if (++this.pasteCount > this.granted) this.overrun = true;      // host ignored flow control
    if (this.pasteCount % this.o.window === 0) {                     // room for another window
      this.granted += this.o.window;
      this.emit("\x01");
    }
  }

  run() {
    const code = new TextDecoder().decode(Uint8Array.from(this.code));
    this.code = [];
    this.execs++;
    this.log.push(code);
    let out = "", err = "";
    try {
      out = this.exec(code);
    } catch (e) {
      err = `Traceback (most recent call last):\r\n  File "<stdin>", line 1, in <module>\r\n${e.message}\r\n`;
    }
    if (this.hardResetPending) {
      this.hardResetPending = false;
      this.resets.push("hard");
      this.closed = true;   // the USB port drops on machine.reset()
      this.flush();
      return;
    }
    this.emit(out + "\x04" + err + "\x04>");
  }

  exec(code) {
    if (this.o.failOn && this.o.failOn.test(code)) throw new Error(this.o.fail);
    let m;
    if ((m = lit(code, /^f=open\('((?:[^'\\]|\\.)*)','wb'\)\nw=f\.write$/))) {
      const path = new TextDecoder().decode(parsePyLiteral(m[1]));
      const dir = path.split("/").slice(0, -1).join("/");
      if (dir && !this.dirs.has(dir)) throw new Error("OSError: [Errno 2] ENOENT");
      this.open = { path, data: [] };
      return "";
    }
    if ((m = lit(code, /^w\(b'((?:[^'\\]|\\.)*)'\)$/s))) {
      if (!this.open) throw new Error("NameError: name 'w' isn't defined");
      this.open.data.push(...parsePyLiteral(m[1]));
      return "";
    }
    if (code === "f.close()") {
      if (this.open) this.files.set(this.open.path, Uint8Array.from(this.open.data));
      this.open = null;
      return "";
    }
    if ((m = lit(code, /^import os\nfor d in \((.*),\):\n/))) {
      for (const [, p] of m[1].matchAll(/'((?:[^'\\]|\\.)*)'/g)) this.dirs.add(new TextDecoder().decode(parsePyLiteral(p)));
      return "";
    }
    if ((m = lit(code, /\np='((?:[^'\\]|\\.)*)'\n/)) && code.includes("print('STAT'")) {
      const path = new TextDecoder().decode(parsePyLiteral(m[1]));
      const data = this.files.get(path);
      if (!data) throw new Error("OSError: [Errno 2] ENOENT");
      const h = this.o.hashlib ? nodeCrypto.createHash("sha256").update(data).digest("hex") : "";
      return `STAT ${data.length} ${h}\r\n`;
    }
    if (code.includes("machine.reset()")) { this.hardResetPending = true; return ""; }
    throw new Error("SyntaxError: fake board doesn't understand: " + JSON.stringify(code.slice(0, 80)));
  }
}
