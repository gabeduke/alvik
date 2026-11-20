// Alvik flasher: copies files onto a MicroPython board through its raw REPL, the way mpremote does
// (mpremote/transport_serial.py: enter_raw_repl, exec_raw, raw_paste_write; transport.py: fs_writefile).
// Plain ES module, no dependencies, so it runs in the browser (Web Serial) and in Node (tests).
//
// A transport is anything with:
//   write(Uint8Array) -> Promise         bytes to the board
//   read() -> Promise<Uint8Array|null>   next chunk from the board, null when closed
//   close() -> Promise                   optional
//
// Typical use (see flash.html):
//   const files = await loadBundle(new URL("robot/", location.href));   // index.json + files, sha-checked
//   const t = await openSerial(port);
//   await flashFiles(t, files, { onEvent: (e) => ... });                // interrupt, write, verify, reset

const enc = new TextEncoder();
const dec = new TextDecoder();
const RAW_BANNER = "raw REPL; CTRL-B to exit\r\n";

export class FlashError extends Error {
  constructor(message, { hint = "", detail = "", fatal = false } = {}) {
    super(message);
    this.name = "FlashError";
    this.hint = hint;       // what a grown-up can do about it
    this.detail = detail;   // raw output from the board, for the log
    this.fatal = fatal;     // the connection is unusable (vs. one command failed)
  }
}

// ---------- Python literals ----------

// Bytes as a Python bytes literal: b'...'. Printable ASCII stays as is, everything else is \xNN.
export function pyBytes(data) {
  let s = "b'";
  for (const c of data) {
    if (c === 0x5c) s += "\\\\";
    else if (c === 0x27) s += "\\'";
    else if (c === 0x0a) s += "\\n";
    else if (c === 0x0d) s += "\\r";
    else if (c === 0x09) s += "\\t";
    else if (c >= 0x20 && c < 0x7f) s += String.fromCharCode(c);
    else s += "\\x" + c.toString(16).padStart(2, "0");
  }
  return s + "'";
}

// A string as a Python str literal (for paths). Non-ASCII is kept as UTF-8, which MicroPython reads.
export function pyStr(text) {
  return "'" + text.replace(/[\\'\x00-\x1f\x7f]/g, (ch) =>
    ch === "\\" ? "\\\\" : ch === "'" ? "\\'" : "\\x" + ch.charCodeAt(0).toString(16).padStart(2, "0")) + "'";
}

// ---------- hashing ----------

export async function sha256Hex(data) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------- byte stream reader ----------

function concat(a, b) {
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

function indexOf(hay, needle, from = 0) {
  outer: for (let i = from; i <= hay.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) if (hay[i + j] !== needle[j]) continue outer;
    return i;
  }
  return -1;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Pumps transport.read() into a buffer so we can wait for prompts with timeouts.
class Stream {
  constructor(transport, log) {
    this.t = transport;
    this.log = log;
    this.buf = new Uint8Array(0);
    this.closed = false;
    this.error = null;
    this.wake = null;
    this.pump = this.run();
  }

  async run() {
    try {
      for (;;) {
        const chunk = await this.t.read();
        if (!chunk) break;
        if (chunk.length) this.buf = concat(this.buf, chunk);
        this.notify();
      }
    } catch (e) {
      this.error = e;
    }
    this.closed = true;
    this.notify();
  }

  notify() {
    const w = this.wake;
    this.wake = null;
    w?.();
  }

  write(data) {
    return this.t.write(typeof data === "string" ? enc.encode(data) : data);
  }

  discard() {
    const old = this.buf;
    this.buf = new Uint8Array(0);
    return old;
  }

  // Waits until the buffer satisfies take(buf) -> n (bytes to consume) or -1. Rejects after timeoutMs.
  async until(take, timeoutMs, what) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const n = take(this.buf);
      if (n >= 0) {
        const out = this.buf.slice(0, n);
        this.buf = this.buf.slice(n);
        return out;
      }
      if (this.closed) {
        throw new FlashError(`The USB connection closed while waiting for ${what}.`, {
          hint: "Is the cable still plugged in? Connect again and retry.",
          detail: this.error ? String(this.error) : dec.decode(this.buf),
          fatal: true,
        });
      }
      const left = deadline - Date.now();
      if (left <= 0) {
        throw new FlashError(`The robot didn't answer in time (waiting for ${what}).`, {
          hint: "Unplug and replug the USB cable, then try again.",
          detail: dec.decode(this.buf),
          fatal: true,
        });
      }
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, left);
        this.wake = () => { clearTimeout(timer); resolve(); };
      });
    }
  }

  readUntil(ending, timeoutMs, what = JSON.stringify(ending)) {
    const needle = typeof ending === "string" ? enc.encode(ending) : ending;
    return this.until((b) => { const i = indexOf(b, needle); return i < 0 ? -1 : i + needle.length; }, timeoutMs, what);
  }

  readExactly(n, timeoutMs, what) {
    return this.until((b) => (b.length >= n ? n : -1), timeoutMs, what);
  }
}

// ---------- the raw REPL ----------

export class RawRepl {
  // options: timeout (ms per exec, default 10000), log(text), rawPaste (true = try it, false = never)
  constructor(transport, { timeout = 10000, log = () => {}, rawPaste = true } = {}) {
    this.s = new Stream(transport, log);
    this.timeout = timeout;
    this.log = log;
    this.rawPaste = rawPaste;   // becomes false if the board says it can't
    this.inRaw = false;
  }

  // Ctrl-C (a few times, the menu catches KeyboardInterrupt) then Ctrl-A, until the raw REPL banner shows.
  async enter({ attempts = 4, wait = 1500 } = {}) {
    for (let i = 1; i <= attempts; i++) {
      await this.s.write("\r\x03\x03");
      await sleep(i === 1 ? 150 : 400);       // let the program stop and print its traceback
      const junk = this.s.discard();
      if (junk.length) this.log(dec.decode(junk));
      await this.s.write("\r\x01");
      try {
        await this.s.readUntil(RAW_BANNER, wait, "the raw REPL");
        this.inRaw = true;
        this.log(`raw REPL (attempt ${i})`);
        return;
      } catch (e) {
        if (this.s.closed || i === attempts) {
          if (this.s.closed) throw e;
          throw new FlashError("Couldn't stop the robot's program to get a Python prompt.", {
            hint: "Turn the robot off and on (or replug USB), then try again. Is it running MicroPython?",
            detail: e.detail,
            fatal: true,
          });
        }
      }
    }
  }

  // Sends code and waits for it to be accepted (raw-paste ack or "OK"). Doesn't wait for the output.
  async send(code) {
    const bytes = typeof code === "string" ? enc.encode(code) : code;
    await this.s.readUntil(">", this.timeout, "the raw REPL prompt");
    if (this.rawPaste) {
      await this.s.write(new Uint8Array([0x05, 0x41, 0x01]));   // Ctrl-E 'A' Ctrl-A: raw-paste request
      const r = await this.s.readExactly(2, this.timeout, "the raw-paste reply");
      if (r[0] === 0x52 && r[1] === 0x01) return this.pasteWrite(bytes);
      if (!(r[0] === 0x52 && r[1] === 0x00)) {
        // Old firmware that doesn't know raw-paste: it echoes a fresh raw REPL banner.
        await this.s.readUntil("w REPL; CTRL-B to exit\r\n>", this.timeout, "the raw REPL prompt");
      }
      this.rawPaste = false;
      this.log("raw-paste not supported, using plain raw REPL");
    }
    // Plain raw REPL: no flow control, so go slowly (256 bytes every 10 ms, like mpremote).
    for (let i = 0; i < bytes.length; i += 256) {
      await this.s.write(bytes.subarray(i, i + 256));
      await sleep(10);
    }
    await this.s.write(new Uint8Array([0x04]));
    const ok = await this.s.readExactly(2, this.timeout, "OK");
    if (ok[0] !== 0x4f || ok[1] !== 0x4b) {
      throw new FlashError("The robot didn't accept the command.", { detail: dec.decode(ok) + dec.decode(this.s.discard()), fatal: true });
    }
  }

  // Raw-paste: the board gives a window size and sends \x01 each time we may send another window.
  async pasteWrite(bytes) {
    const hdr = await this.s.readExactly(2, this.timeout, "the raw-paste window");
    const size = hdr[0] | (hdr[1] << 8);
    let remain = size;
    let i = 0;
    const flowByte = (b) => {
      if (b === 0x01) { remain += size; return; }
      if (b === 0x04) return "end";
      throw new FlashError("Unexpected reply during upload.", { detail: `byte 0x${b.toString(16)}`, fatal: true });
    };
    while (i < bytes.length) {
      while (remain === 0 || this.s.buf.length) {
        const [b] = await this.s.readExactly(1, this.timeout, "flow control");
        if (flowByte(b) === "end") {   // board aborted (e.g. syntax error): acknowledge and stop
          await this.s.write(new Uint8Array([0x04]));
          return;
        }
      }
      const part = bytes.subarray(i, i + remain);
      await this.s.write(part);
      remain -= part.length;
      i += part.length;
    }
    await this.s.write(new Uint8Array([0x04]));
    // Window acks may still arrive before the end-of-data ack.
    for (;;) {
      const [b] = await this.s.readExactly(1, this.timeout, "the end of the upload");
      if (b === 0x04) return;
      if (b !== 0x01) throw new FlashError("Unexpected reply after upload.", { detail: `byte 0x${b.toString(16)}`, fatal: true });
    }
  }

  // Runs code and returns its printed output. A Python exception becomes a FlashError.
  async exec(code, timeout = this.timeout) {
    await this.send(code);
    const out = await this.s.readUntil("\x04", timeout, "the command output");
    const err = await this.s.readUntil("\x04", timeout, "the command output");
    const text = dec.decode(out.subarray(0, -1));
    const errText = dec.decode(err.subarray(0, -1));
    if (errText) throw replError(errText);
    return text;
  }

  // Ctrl-B back to the normal REPL, Ctrl-D soft reset: runs boot.py and main.py again.
  async softReset() {
    await this.s.write("\r\x02");
    this.inRaw = false;
    await sleep(100);
    await this.s.write("\x04");
    try { await this.s.readUntil("soft reboot", 3000, "soft reboot"); } catch { /* fine, it rebooted anyway */ }
  }

  // Hard reset, like `mpremote reset`. The USB port drops and comes back, so don't wait for output.
  async hardReset() {
    await this.send("import time, machine\ntime.sleep_ms(100)\nmachine.reset()");
    this.inRaw = false;
  }

  async close() {
    try { await this.s.t.close?.(); } catch { /* already gone */ }
    await Promise.race([this.s.pump, sleep(500)]);
  }
}

function replError(errText) {
  const last = errText.trim().split(/\r?\n/).pop() || errText;
  let hint = "";
  if (/ENOSPC|Errno 28/.test(last)) hint = "The robot's storage is full. Delete old files with mpremote and try again.";
  else if (/EROFS|Errno 30/.test(last)) hint = "The robot's storage is read-only.";
  else if (/MemoryError/.test(last)) hint = "The robot ran out of memory. Reset it and try again.";
  return new FlashError(`The robot reported an error: ${last}`, { hint, detail: errText });
}

// ---------- file operations ----------

// Writes one file. onProgress(written, total). chunkSize = raw bytes per w(b'...') command.
export async function writeFile(repl, path, data, { chunkSize, onProgress } = {}) {
  chunkSize ??= repl.rawPaste ? 1024 : 256;
  const dirs = path.split("/").slice(0, -1).map((_, i, a) => a.slice(0, i + 1).join("/")).filter(Boolean);
  if (dirs.length) {
    await repl.exec(`import os\nfor d in (${dirs.map(pyStr).join(",")},):\n try:\n  os.mkdir(d)\n except OSError as e:\n  if e.errno!=17:raise`);
  }
  await repl.exec(`f=open(${pyStr(path)},'wb')\nw=f.write`);
  try {
    onProgress?.(0, data.length);
    for (let i = 0; i < data.length; i += chunkSize) {
      const chunk = data.subarray(i, i + chunkSize);
      await repl.exec("w(" + pyBytes(chunk) + ")");
      onProgress?.(i + chunk.length, data.length);
    }
  } catch (e) {
    try { await repl.exec("f.close()"); } catch { /* keep the first error */ }
    throw e;
  }
  await repl.exec("f.close()");
}

// Size and sha256 of a file on the robot. sha256 is "" if the firmware has no hashlib.sha256.
export async function statFile(repl, path) {
  const out = await repl.exec(
    "import os\ntry:\n import hashlib,binascii\nexcept ImportError:\n hashlib=None\n" +
    `p=${pyStr(path)}\nn=os.stat(p)[6]\nh=''\n` +
    "if hashlib and hasattr(hashlib,'sha256'):\n d=hashlib.sha256()\n with open(p,'rb') as f:\n" +
    "  while 1:\n   b=f.read(512)\n   if not b:break\n   d.update(b)\n h=binascii.hexlify(d.digest()).decode()\n" +
    "print('STAT',n,h)\ndel p,n,h"
  );
  const m = /STAT (\d+) ?([0-9a-f]*)/.exec(out);
  if (!m) throw new FlashError("Couldn't read the file back from the robot.", { detail: out });
  return { size: Number(m[1]), sha256: m[2] };
}

// Checks a written file against the bytes we meant to write. method = "sha256" or "size".
export async function verifyFile(repl, path, data) {
  const st = await statFile(repl, path);
  if (st.sha256) return { ok: st.sha256 === (await sha256Hex(data)), method: "sha256", ...st };
  return { ok: st.size === data.length, method: "size", ...st };
}

// boot.py and main.py go last, so a flash cut short doesn't leave main.py importing missing files.
export function flashOrder(files) {
  const late = (p) => (p === "main.py" ? 2 : p === "boot.py" ? 1 : 0);
  return [...files].sort((a, b) => late(a.path) - late(b.path));
}

// The whole job: interrupt, write + verify each file, reset.
//   files: [{ path, data: Uint8Array }]   path is where it goes on the robot, e.g. "demo.py"
//   onEvent({ type, ... }): "stage" {stage: "connect"|"reset"|"done"}, "file" {path, state:
//     "writing"|"verifying"|"ok"|"failed", written, total, method, error}
//   reset: "hard" (default, like `mpremote reset`), "soft", or false
// Returns [{ path, ok, method, error }]. Problems with one file (e.g. storage full) mark it failed
// and carry on; connection problems throw a FlashError.
export async function flashFiles(transport, files, { onEvent = () => {}, log = () => {}, reset = "hard", verify = true, timeout, rawPaste } = {}) {
  const repl = new RawRepl(transport, { log, timeout, rawPaste });
  const results = [];
  onEvent({ type: "stage", stage: "connect" });
  await repl.enter();
  for (const f of flashOrder(files)) {
    const ev = (state, extra = {}) => onEvent({ type: "file", path: f.path, state, ...extra });
    try {
      ev("writing", { written: 0, total: f.data.length });
      await writeFile(repl, f.path, f.data, { onProgress: (written, total) => ev("writing", { written, total }) });
      let method = "none", ok = true;
      if (verify) {
        ev("verifying");
        ({ ok, method } = await verifyFile(repl, f.path, f.data));
      }
      const error = ok ? "" : `${method} doesn't match after writing`;
      ev(ok ? "ok" : "failed", { method, error });
      results.push({ path: f.path, ok, method, error });
    } catch (e) {
      if (!(e instanceof FlashError) || e.fatal) throw e;
      ev("failed", { error: e.message });
      results.push({ path: f.path, ok: false, method: "none", error: e.message });
    }
  }
  if (reset) {
    onEvent({ type: "stage", stage: "reset" });
    if (reset === "soft") await repl.softReset();
    else await repl.hardReset();
  }
  onEvent({ type: "stage", stage: "done" });
  return results;
}

// ---------- the files to flash ----------

// Loads <base>/index.json ({ files: [{ path, size, sha256 }] }, made by scripts/build_site.sh) and the
// files it lists, and checks each against its sha256 so a stale cached copy can't be flashed.
// Returns [{ path, size, sha256, data }]. base is a URL ending in "/".
export async function loadIndex(base, fetchFn = fetch) {
  const res = await fetchFn(new URL("index.json", base), { cache: "no-cache" });
  if (!res.ok) throw new FlashError(`Couldn't load the file list (${res.status}).`);
  return (await res.json()).files;
}

export async function loadFile(base, entry, fetchFn = fetch) {
  const res = await fetchFn(new URL(entry.path, base), { cache: "no-cache" });
  if (!res.ok) throw new FlashError(`Couldn't download ${entry.path} (${res.status}).`);
  const data = new Uint8Array(await res.arrayBuffer());
  if (entry.sha256 && (await sha256Hex(data)) !== entry.sha256) {
    throw new FlashError(`${entry.path} doesn't match the file list.`, { hint: "Reload the page to get the latest version." });
  }
  return { ...entry, data };
}

export async function loadBundle(base, fetchFn = fetch) {
  const entries = await loadIndex(base, fetchFn);
  return Promise.all(entries.map((e) => loadFile(base, e, fetchFn)));
}

// ---------- sketches ----------
// The site has sketches/index.json ({ sketches: [{ name, title, emoji, description, color, hardware,
// entry }] }) and one folder per sketch with its own index.json. On the robot a sketch lives in
// /sketches/<name>/, where the menu (src/sketchbook.py) finds it at boot.

export async function loadSketchList(site, fetchFn = fetch) {
  const res = await fetchFn(new URL("sketches/index.json", site), { cache: "no-cache" });
  if (!res.ok) throw new FlashError(`Couldn't load the sketch list (${res.status}).`);
  return (await res.json()).sketches;
}

// Everything a sketch needs on the robot: the sketch folder, plus all the core robot files (the
// menu that runs sketches), so a robot with old code still gets a menu that can find it.
// Returns [{ path, size, sha256, data }] with robot paths: "demo.py", "sketches/<name>/<file>".
export async function loadSketchFiles(site, name, fetchFn = fetch) {
  if (!/^[a-z][a-z0-9_]*$/.test(name)) throw new FlashError(`Bad sketch name ${JSON.stringify(name)}.`);
  const [core, own] = await Promise.all([
    loadBundle(new URL("robot/", site), fetchFn),
    loadBundle(new URL(`sketches/${name}/`, site), fetchFn),
  ]);
  return [...core, ...own.map((f) => ({ ...f, path: `sketches/${name}/${f.path}` }))];
}

// ---------- Web Serial ----------

// USB vendor ids for the port picker: Arduino (the Alvik's Nano ESP32) and Espressif.
export const USB_FILTERS = [{ usbVendorId: 0x2341 }, { usbVendorId: 0x303a }];

// Opens a Web Serial port as a transport. Throws a FlashError with a hint when the port is busy.
export async function openSerial(port, { baudRate = 115200 } = {}) {
  try {
    await port.open({ baudRate });
  } catch (e) {
    if (e.name === "InvalidStateError") { /* already open by this page */ }
    else throw new FlashError("Couldn't open the USB port. Another program is probably using it.", {
      hint: "Close Arduino Lab for MicroPython, Thonny, any mpremote or serial terminal, and other tabs using it. Then unplug and replug the robot and connect again.",
      detail: String(e),
    });
  }
  // Like pyserial (mpremote): DTR and RTS on. MicroPython's USB only sends output while DTR is set.
  try { await port.setSignals({ dataTerminalReady: true, requestToSend: true }); } catch { /* not supported */ }
  const reader = port.readable.getReader();
  const writer = port.writable.getWriter();
  return {
    async write(data) { await writer.write(data); },
    async read() {
      const { value, done } = await reader.read();
      return done ? null : value;
    },
    async close() {
      try { await reader.cancel(); } catch {}
      try { reader.releaseLock(); } catch {}
      try { await writer.close(); } catch {}
      try { writer.releaseLock(); } catch {}
      try { await port.close(); } catch {}
    },
  };
}
