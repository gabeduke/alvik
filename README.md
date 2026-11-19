# Alvik

The boys' Arduino Alvik: the stock demo menu plus a **phone remote** mode.

## Layout
- `src/` – everything that goes on the robot
  - `main.py`, `demo.py` – stock menu (demo.py adds a 4th, purple, "phone remote" mode)
  - `remote_control.py` – the phone remote (Bluetooth, Bluefruit Connect app)
  - `line_follower.py`, `hand_follower.py`, `touch_move.py` – stock Arduino demos
- `stock-backup/` – a copy of whatever was on the robot before we changed it

## First time
Close Arduino Lab for MicroPython first; only one program can hold the USB port.
```sh
cd ~/repos/alvik
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
alias mpr=.venv/bin/mpremote

# save the robot's original files (once) — copies every top-level file on the robot
for f in $(mpr fs ls | awk 'NR>1 && $2 !~ /\/$/ {print $2}'); do mpr fs cp :$f stock-backup/; done
mpr fs cp src/*.py : + reset                               # deploy src/ and restart the robot
```

## Handy commands
```sh
mpr fs cp src/*.py : + reset    # deploy after changes
mpr repl                        # Python prompt on the robot (Ctrl-] to quit)
mpr fs ls                       # list files on the robot
mpr mip install github:arduino/arduino-alvik-mpy   # reinstall the Alvik library if import fails
```
If several boards are plugged in: `mpr connect /dev/cu.usbmodemXXXX ...`

## Driving
1. Robot on → tap the up arrow until the lights are **purple** → tap ✓ (lights go yellow).
2. Phone/tablet: **Bluefruit Connect** → connect to **Alvik** → Controller → Control Pad.
3. Arrows drive · 1 lights · 2 turbo · 3 disco dance · 4 bumper on/off. ✗ on the robot returns to the menu.

## Web remote (`docs/index.html`)
Big labelled buttons in the browser, same Bluetooth messages as Bluefruit, so nothing changes on the robot.
Works in Chrome/Edge (Android, laptop). iPad Safari can't do Bluetooth: open it in the free **Bluefy** app.
Laptop keys: arrows drive, 1-4 for the buttons.
```sh
python3 -m http.server -d docs 8000   # then open http://localhost:8000 in Chrome
```

## Menu colors
blue = line follower · green = hand follower · red = touch-move · purple = phone remote

## Ideas / next
- Servos (Geekservo 9g 270°) on servo A/B → claw + catapult buttons
- Xbox Wireless Controller (model 1914) via Bluepad32 (needs Arduino C++, not MicroPython)
- Eyes on the Qwiic port (uses `alvik.i2c`): Adafruit 1.3" 128x64 OLED STEMMA QT (#938) showing moods — happy driving, scared at the bumper, dizzy after a spin, sleepy when idle, angry when picked up
