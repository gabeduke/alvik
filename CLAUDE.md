# Alvik

Arduino Alvik robot (MicroPython, ESP32) for the kids, plus a web remote. Backlog = GitHub issues on `gabeduke/alvik`. Setup and commands: README.md.

## Layout
- `src/` – core robot files (`main.py` → `demo.py` colour menu; `remote_control.py` = purple "phone remote"; `dance.py` = shared disco dance; `sketchbook.py` = finds sketches).
- `sketches/<name>/` – extra menu programs: `<entry>.py` with `run(alvik)` (called until ✗; negative return = back to menu), `sketch.json` (title, emoji, description, color [r,g,b] 0/1, hardware, entry), `README.md`. On the robot: `/sketches/<name>/`, found at boot by listing the folder (no index on the robot). Menu = 4 built-ins then sketches sorted by name; pages of 6, page N blinks N-1 times per 2 s; crashes flash red and return. How to add one: README "Sketches".
- `docs/` – the web remote (installable PWA: `manifest.webmanifest`, `sw.js`, `pwa.js` = SW registration + update toast with a busy hook), deployed by `.github/workflows/pages.yml` (Pages source = GitHub Actions) at https://gabeduke.github.io/alvik/. Push to `main` = deploy (~1 min). Pages sends `cache-control: max-age=600`. Served under `/alvik/`: use relative URLs. New pages go in `SHELL` in `sw.js`.
- `scripts/build_site.sh` builds `_site/` = `docs/` + `robot/` (`src/*.py` + `index.json` with path/size/sha256) + `sketches/<name>/` (+ per-sketch `index.json`) + `sketches/index.json` (validated by `scripts/sketch_index.py`), and stamps the commit into `sw.js`. `OUT=dir` builds elsewhere.
- `docs/flash.html` + `docs/flasher.js`: Web Serial flasher (raw REPL like mpremote). Reuse `loadBundle(url)`, `loadSketchFiles(site, name)` (core + sketch, robot paths) + `flashFiles(transport, files, {onEvent})`. A sketch flash always includes all core files.
- Tests: `node --test tests/*.test.mjs` (fake board: `tests/fake_repl.mjs`) and `python3 tests/test_robot.py` (menu + sketches on a fake Alvik with a virtual clock). Both run in the Pages workflow. Keep robot code MicroPython-safe (no `os.path`/`pathlib`; `except Exception` must not swallow KeyboardInterrupt, the flasher's Ctrl-C).

## Robot over USB
- `.venv/bin/mpremote` (venv from README). Port is usually `/dev/cu.usbmodem1234561`; it disappears when the robot is unplugged.
- Only one program can hold the port: close Arduino Lab for MicroPython first.
- Deploy: `.venv/bin/mpremote fs cp src/*.py : + reset`, or the 🔧 flash page in Chrome (flashes what's on `main`). Smoke test: `mpremote exec "import remote_control" + reset`. Install a sketch by hand: `mpremote fs mkdir :sketches` (once), then `mpremote fs cp -r sketches/disco :sketches/ + reset`.
- Any mpremote command interrupts the running menu; finish with `+ reset`.
- Alvik library is in `:lib/arduino_alvik` (reinstall: `mpremote mip install github:arduino/arduino-alvik-mpy`).

## Bluetooth protocol (remote mode)
- Nordic UART service `6E400001-…`, robot advertises as `Alvik`. Phone writes to RX `6E400002-…`.
- Bluefruit Connect Control Pad packets: `'!' 'B' <'1'..'8'> <'1' down | '0' up> <checksum = ~sum(first 4) & 0xFF>`.
- Buttons: 1 lights, 2 turbo (toggle), 3 disco dance, 4 bumper (toggle, on by default), 5 up, 6 down, 7 left, 8 right. Arrows are hold-to-drive (Bluefruit app only; the web remote drives with the joystick).
- Web remote drive layouts (`body[data-layout]`, saved in localStorage `alvik-layout`): `stick`, `two` (throttle + steer sliders). Both feed one (x, y) and the same packet.
- Web remote joystick packet: `'!' 'J' <x int8> <y int8> <checksum>`, -100..100, x right, y forward. The page repeats it every 150 ms while held; the robot stops after 600 ms of silence. Speeds ramp (`ramp()`), and the bumper slows from 30 cm and stops at 12 cm (`bumper_limit()`).
- **One connection at a time.** While anything is connected the robot stops advertising, so the web page can't see it until the Bluefruit app disconnects (lights go yellow = advertising).
- Web Bluetooth: Chrome/Edge on Android, macOS, Windows. Not iPad/iOS Safari (use the Bluefy app). macOS needs Chrome allowed under Privacy & Security → Bluetooth.

## Conventions
- Kid-facing: big buttons, emoji labels, robot lights as feedback (yellow = waiting, red flash = bumper/blocked).
- Keep the web remote dependency-free static files (no bundler; the build script only copies and indexes) unless an issue says otherwise.
