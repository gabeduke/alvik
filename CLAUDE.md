# Alvik

Arduino Alvik robot (MicroPython, ESP32) for the kids, plus a web remote. Backlog = GitHub issues on `gabeduke/alvik`. Setup and commands: README.md.

## Layout
- `src/` – files that go on the robot (`main.py` → `demo.py` menu; `remote_control.py` = purple "phone remote" mode).
- `docs/` – the web remote, served by GitHub Pages (branch `main`, folder `/docs`) at https://gabeduke.github.io/alvik/. Push to `main` = deploy (~1 min). Pages sends `cache-control: max-age=600`.

## Robot over USB
- `.venv/bin/mpremote` (venv from README). Port is usually `/dev/cu.usbmodem1234561`; it disappears when the robot is unplugged.
- Only one program can hold the port: close Arduino Lab for MicroPython first.
- Deploy: `.venv/bin/mpremote fs cp src/*.py : + reset`. Smoke test: `mpremote exec "import remote_control" + reset`.
- Any mpremote command interrupts the running menu; finish with `+ reset`.
- Alvik library is in `:lib/arduino_alvik` (reinstall: `mpremote mip install github:arduino/arduino-alvik-mpy`).

## Bluetooth protocol (remote mode)
- Nordic UART service `6E400001-…`, robot advertises as `Alvik`. Phone writes to RX `6E400002-…`.
- Bluefruit Connect Control Pad packets: `'!' 'B' <'1'..'8'> <'1' down | '0' up> <checksum = ~sum(first 4) & 0xFF>`.
- Buttons: 1 lights, 2 turbo (toggle), 3 disco dance, 4 bumper (toggle, on by default), 5 up, 6 down, 7 left, 8 right. Arrows are hold-to-drive.
- **One connection at a time.** While anything is connected the robot stops advertising, so the web page can't see it until the Bluefruit app disconnects (lights go yellow = advertising).
- Web Bluetooth: Chrome/Edge on Android, macOS, Windows. Not iPad/iOS Safari (use the Bluefy app). macOS needs Chrome allowed under Privacy & Security → Bluetooth.

## Conventions
- Kid-facing: big buttons, emoji labels, robot lights as feedback (yellow = waiting, red flash = bumper/blocked).
- Keep the web remote dependency-free static files (no build step) unless an issue says otherwise.
