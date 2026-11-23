# Wio Terminal remote

A handheld remote for the Alvik, no phone needed: drive with the Wio Terminal's 5-way stick, use the
three buttons on top for lights, turbo and dance, and watch a little radar of what the robot senses.
It talks to the robot's purple "phone remote" mode over Bluetooth LE with the same packets as the web
remote (`alvik_packets.h`), so the robot needs no new code.

**It has driven a real Alvik** (Wio wireless firmware 2.1.3, Seeeduino:samd 1.8.5, rpcBLE 1.0.0).
The packets are tested too (`python3 tests/test_robot.py WioPackets` checks them against the robot's
own parser and `tests/telemetry_vectors.json`). Not checked yet: the rest of "First run" below.

## Controls

| | |
|---|---|
| 5-way up / down | forward / back, while held |
| 5-way left / right | spin left / right |
| 5-way press | tilt steering on or off: hold up and tip the Wio like a steering wheel to curve |
| 5-way press, held 1 s | bumper on / off |
| top buttons, left to right | lights · turbo · dance |

The screen: battery, speed, what is ahead, a compass, turbo and bumper (as the robot reports them),
and a radar seen from above. The radar shows the robot with its light colours, the floor's colour under
it, the line sensors at its nose, the distance sensor's raw readings as dots, and the bumper's view as
an arc. The arc turns yellow from 12 cm and red from 8 cm, where the robot stops.

## Setup (once)

Flashing this **replaces whatever is on the Wio now** (the grow monitor). Put that back later from
its own repo.

1. **Bluetooth firmware.** The Wio's wireless chip needs Seeed's "rpc" firmware before Bluetooth works
   from Arduino. If the Wio already does Wi-Fi from Arduino (the grow monitor), it probably has it.
   If not, follow Seeed's wiki page "Update the Wireless Core Firmware" (the `ambd_flash_tool`).
2. **Board package and libraries** (Arduino IDE, or `arduino-cli` as here):
   ```sh
   arduino-cli config add board_manager.additional_urls https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
   arduino-cli core update-index && arduino-cli core install Seeeduino:samd
   arduino-cli lib install "Seeed Arduino rpcBLE" "Seeed Arduino rpcUnified" "Grove-3-Axis-Digital-Accelerometer-2g-to-16g-LIS3DHTR"
   ```
   If a name isn't found, search the Library Manager for "rpcBLE", "rpcUnified" and "LIS3DHTR".
3. **Build and flash** (Wio plugged in over USB-C; slide the power switch down twice quickly if the
   port doesn't show up):
   ```sh
   arduino-cli compile --fqbn Seeeduino:samd:seeed_wio_terminal remotes/wio_remote
   arduino-cli upload  --fqbn Seeeduino:samd:seeed_wio_terminal -p /dev/cu.usbmodemXXXX remotes/wio_remote
   ```

## Driving

1. Robot on, then tap the up arrow until the lights are **purple** and tap ✓. The lights go **yellow**.
2. Disconnect any phone or web remote first. The robot takes one connection at a time.
3. Switch the Wio on. It finds "Alvik" by itself, and the robot's lights go back to its headlight colour.

If the robot goes away, the Wio looks for it again. If Bluetooth gets stuck, it restarts itself.

## First run: what to check

- **It connects.** While it looks, numbered steps show at the bottom of the screen (and on USB serial
  at 115200). The last one says where it got stuck. A good start ends "subscribed".
- **The top buttons are in the right order.** If they aren't, swap the pins in `TOP_PINS`.
- **The tilt bar leans the way you tip the Wio.** If not, flip `TILT_SIGN` or change `TILT_AXIS` to
  `getAccelerationX`.
- **Letting go stops the robot.** The Wio sends "stop" when you let go, and the robot also stops
  by itself 600 ms after the Wio goes quiet.
- **Reconnecting** after the robot is switched off and on again: this is the least certain part.
  If it never comes back, press the Wio's reset.

## Seeed's Bluetooth library: what to know

rpcBLE 1.0.0 has bugs the sketch works around (each one found on the real Wio). Keep these in mind
before changing `hookUp()`:

- Discovered 128-bit UUIDs print as `<NULL>`, so looking a service or characteristic up by UUID never
  finds it. The sketch matches the raw bytes (`nusPart()`) and lists characteristics by handle.
- Asking for the service list a second time, or rebuilding characteristics, frees memory twice and
  freezes the Wio (`ASSERT: vPortFree`, and USB stops answering). Read them once per connection.
- `registerForNotify()` waits for the first notification with no time limit, so ask the robot for
  telemetry first.
- `writeValue()` always waits for a reply. Packets go out as write commands via `client_attr_write`.
- Include `rpcBLEDevice.h` before `TFT_eSPI.h`, or it doesn't compile (`min`/`max` macros).

Flashing over USB can stop working while the Wio is frozen: slide the power switch down twice quickly
for the bootloader, then upload.

## Files

- `wio_remote.ino`: the sketch (Bluetooth, buttons, screen).
- `alvik_packets.h`: the packets, as plain C++ so the tests can build it on a computer. The layouts
  are the robot's (`src/remote_control.py`) and the web page's (`docs/telemetry.js`): change them all
  together.
