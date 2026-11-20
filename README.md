# Alvik

The boys' Arduino Alvik: the stock demo menu plus a **phone remote** mode.

## Layout
- `docs/` – the web remote (`index.html`), its live 3D robot (`twin.js`, `telemetry.js`, `models/alvik.glb`, `vendor/three/`) and the 🔧 flash page (`flash.html`, `flasher.js`)
- `models/` – where the 3D robot comes from: reference files, credits and the Blender script that builds `docs/models/alvik.glb`
- `scripts/build_site.sh` – builds the Pages site into `_site/`; `tests/` – flasher, build and robot-menu tests
- `src/` – the robot's own code (the "core")
  - `main.py`, `demo.py` – the colour menu (stock modes, the purple phone remote, then installed sketches)
  - `sketchbook.py` – finds the sketches installed on the robot
  - `remote_control.py` – the phone remote (Bluetooth, Bluefruit Connect app)
  - `dance.py` – the disco dance (remote button 3 and the Disco sketch)
  - `line_follower.py`, `hand_follower.py`, `touch_move.py` – stock Arduino demos
- `sketches/<name>/` – extra programs for the menu (see [Sketches](#sketches))
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

## Flash from the browser (no terminal)
**https://gabeduke.github.io/alvik/flash.html** (or the faint 🔧 in the corner of the remote).
Chrome or Edge on a computer, robot plugged in by USB-C, Arduino Lab for MicroPython closed.
Three steps: 🔌 Connect USB → tap **＋ Add** on any sketches (extras) you want → **⚡ Update the robot**.
Each file is written, checked (sha256 on the robot), then the robot restarts into the menu.
It flashes the files from the last push to `main`. Every flash writes all the core `src/` files (with or
without sketches), so the menu that runs sketches is always up to date.
It also rescues a stuck robot: Ctrl-C stops whatever is running first. iPad/Android can't do it.

## Handy commands
```sh
mpr fs cp src/*.py : + reset    # deploy after changes
mpr fs mkdir :sketches; mpr fs cp -r sketches/disco :sketches/ + reset   # install a sketch by hand
mpr fs rm -r :sketches/disco    # uninstall a sketch
mpr repl                        # Python prompt on the robot (Ctrl-] to quit)
mpr fs ls                       # list files on the robot
mpr mip install github:arduino/arduino-alvik-mpy   # reinstall the Alvik library if import fails
```
If several boards are plugged in: `mpr connect /dev/cu.usbmodemXXXX ...`

## Driving
1. Robot on → tap the up arrow until the lights are **purple** → tap ✓ (lights go yellow).
2. Phone/tablet: **Bluefruit Connect** → connect to **Alvik** → Controller → Control Pad.
3. Arrows drive · 1 lights · 2 turbo · 3 disco dance · 4 bumper on/off. ✗ on the robot returns to the menu.

The robot speeds up gently and slows down as it gets close to things (bumper on), then stops 12 cm away with red lights. Tune it at the top of `src/remote_control.py` (`ACCEL`, `DECEL`, `SLOW_CM`, `BUMPER_CM`).

## Web remote (`docs/index.html`)
**Live: https://gabeduke.github.io/alvik/** (GitHub Pages via `.github/workflows/pages.yml`, redeploys on every push to `main`)
Installable app: Chrome → Install (or Android "Add to Home screen"). It works offline. Installed copies update themselves: the build stamps the commit into `sw.js`, and the page reloads on its own (`docs/pwa.js`), but never while the robot is connected or a flash is running.
A joystick (push a little = slow, push a lot = fast) and big labelled buttons. The buttons are the same Bluetooth messages as Bluefruit; the joystick is its own message, so the robot needs the current `remote_control.py` (flash it with 🔧).
Works in Chrome/Edge (Android, laptop). iPad Safari can't do Bluetooth: open it in the free **Bluefy** app.
The 🕹️ / 🙌 switch in the header changes how you drive, and the choice is remembered on that device: **One hand** (joystick) or **Two hands** (left thumb speed, right thumb steering: good on a tablet).
Laptop keys: arrows or WASD drive, 1-4 for the buttons, Esc stops.

**Live 3D robot.** The page shows a 3D Alvik that copies the real one: it turns when the robot turns, its wheels spin, its light strips take the LED colours (red when the bumper stops it), and a wall appears in front when the distance sensor sees something closer than 40 cm (yellow from 30 cm, red from 12 cm; drawn closer than it really is so it fits). It starts facing away from you; tap 🧭 when the real robot points away from you to line them up again. On a phone held upright in One hand mode it is a small picture in the corner: tap it to make it big, tap again to shrink it. The robot sends this about 5 times a second, only when the page asks (the Bluefruit app gets nothing new), so the robot needs the current `remote_control.py` (flash it with 🔧); with older robot code the remote still drives and the 3D robot stands still. The Turbo and Bumper labels follow what the robot reports. Packet layout: top of `docs/telemetry.js`. Heading comes from the wheels (`get_pose`), so it does not notice the robot being picked up and turned.
The model is Arduino's Alvik chassis with the LEGO baseplate by GiulioT (CC BY-NC-SA); see `models/README.md`. three.js is copied into `docs/vendor/` (see `docs/vendor/README.md`); there is still no bundler or install step.
```sh
scripts/build_site.sh && python3 -m http.server -d _site 8000   # then open http://localhost:8000
node --test tests/*.test.mjs                                     # flasher, sketch build, telemetry and 3D model tests (Node 20+, no installs)
python3 tests/test_robot.py                                      # menu, sketches, remote and telemetry on a pretend Alvik (no installs)
```
`scripts/build_site.sh` builds `_site/` = `docs/` + `robot/*.py` (from `src/`) + `robot/index.json`
(path, size, sha256 of each) + `sketches/<name>/` (each with its own `index.json`) + `sketches/index.json`
(every sketch's `sketch.json`, checked by `scripts/sketch_index.py`), and stamps the build id into `sw.js`.
The Pages workflow runs the tests and this script, then deploys `_site/`.

The flasher (`docs/flasher.js`) is a dependency-free ES module that talks to MicroPython's raw REPL like
mpremote does, over any `{ write, read }` transport. `tests/fake_repl.mjs` is a pretend board for the tests.

## Menu colors
⬆ / ⬇ on the robot pick a program, ✓ runs it, ✗ comes back to the menu.
Order: red = touch-move · **blue = line follower (start)** · green = hand follower · purple = phone remote ·
then each installed sketch in its own colour (sorted by folder name): white = 🪩 Disco · yellow = 🐕 Follow me.

More than 6 entries? They come in pages of 6. Page 1 is steady; on page 2 the light blinks off once every
2 seconds, on page 3 twice, and so on. If a program crashes the lights flash red 3 times and the menu comes back
(the error is printed over USB: `mpr repl`, or the flash page's Log).

## Sketches
A sketch is a small program that shows up as an extra colour in the robot's menu. Pick one on the
[flash page](https://gabeduke.github.io/alvik/flash.html) (**＋ Add**) and press **⚡ Update the robot**.

| | Sketch | Uses |
|---|---|---|
| 🪩 | [`disco`](sketches/disco/) – party lights, wiggle, big spin. ✓ dances again | wheels, lights |
| 🐕 | [`follow_me`](sketches/follow_me/) – follows your hand like a puppy | distance sensors, wheels, lights |

On the robot, a sketch lives in `/sketches/<name>/` (the same files as in this repo). At boot the menu
(`src/sketchbook.py`) lists `/sketches/`, reads each `sketch.json`, and adds a menu entry. The first time you
pick it, it adds `/sketches/<name>` to the end of `sys.path` and imports the entry module. No `__init__.py`,
no index file on the robot: delete the folder to uninstall.

### How to add a sketch
1. Make `sketches/<name>/` (`<name>` = lowercase letters, digits, `_`) with:
   - **`<name>.py`** with a `run(alvik)` function. The menu calls it over and over until ✗ is pressed;
     return a negative number to go back to the menu straight away (do this if your code waits for ✗ itself).
     Don't block for long without checking `alvik.get_touch_cancel()`.
   - **`sketch.json`**:
     ```json
     {
       "title": "Follow me",
       "emoji": "🐕",
       "description": "One line for the card on the flash page.",
       "color": [1, 1, 0],
       "hardware": ["distance sensors", "wheels", "lights"],
       "entry": "follow_me"
     }
     ```
     `color` is the menu light, each of red, green, blue 0 or 1 (free ones: cyan `[0,1,1]`; reuse is fine
     on another page). `entry` is the module to import; its name must not match a file in `src/` or another
     sketch's entry (the build checks this).
   - **`README.md`**: what it does, its lights and buttons, which sensors it uses.
2. More files? Put them in the same folder and `import` them by name (keep the names unique). Shared code can
   go in `src/` (like `dance.py`); flashing a sketch always flashes `src/` too.
3. Test: `python3 tests/test_robot.py` and `node --test tests/*.test.mjs`, or copy it onto the robot with
   mpremote (see Handy commands). Push to `main` and it appears on the flash page about a minute later.

## Ideas / next
Sketch ideas waiting for hardware (#3): 🦾 claw + catapult (servos), 👀 eyes (OLED).
- Servos (Geekservo 9g 270°) on servo A/B → claw + catapult buttons (`alvik.set_servo_positions(a, b)`)
- Xbox Wireless Controller (model 1914) via Bluepad32 (needs Arduino C++, not MicroPython)
- Eyes on the Qwiic port (uses `alvik.i2c`): Adafruit 1.3" 128x64 OLED STEMMA QT (#938) showing moods — happy driving, scared at the bumper, dizzy after a spin, sleepy when idle, angry when picked up
