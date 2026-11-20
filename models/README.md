# 3D models

Source files for the 3D Alvik on the web remote (issue #6). Units in the STL/STEP files are millimetres.

| File | What | From | Licence |
|---|---|---|---|
| `reference/alvik_reference_design.stl`, `.step` | Official Alvik chassis: one solid, 96 x 96 x 37 mm, with the LEGO Technic side holes and top mounting slots | Arduino, "STEP Files" on https://docs.arduino.cc/hardware/alvik/ | None stated by Arduino. Published for designing add-ons. |
| `reference/lego_baseplate_12x12.stl` | The printed LEGO-compatible top baseplate (12 x 12 studs, 96 x 96 x 11.4 mm) plus its two pins, laid out as on the print bed | "Arduino Alvik top baseplate (LEGO/DUPLO versions)" by GiulioT, https://makerworld.com/en/models/1298936 | CC BY-NC-SA. Anything built from it keeps that licence and the credit. |
| `alvik_reference.blend` | Blender scene with both imported (collection `AlvikReference`, scaled to metres, plate placed on top), for looking at them | this repo | as above |
| `build_alvik_web.py` | Blender script that builds `docs/models/alvik.glb` from the two STLs | this repo | |
| `../docs/models/alvik.glb` | The model the web remote shows. Built, not edited by hand. | `build_alvik_web.py` | CC BY-NC-SA (it contains the baseplate); the credit is in the file's `asset.copyright` and on the page |

## Building the web model

```sh
/Applications/Blender.app/Contents/MacOS/Blender -b --python models/build_alvik_web.py
/Applications/Blender.app/Contents/MacOS/Blender -b --python models/build_alvik_web.py -- --preview /tmp/alvik   # also renders PNGs
```

Made with Blender 5.2. The script reads the STLs directly (not the `.blend`). About 47,000 triangles, 1.2 MB.

## What was measured on the chassis (mm, STL axes)

- Front is +Y: the rear face (-Y) has the connector slots, the caster ball is at the rear, the touch buttons are on the rear half of the top and the board cutout (x -24..24, y 9.5..35.5) on the front half.
- Floor at z = -10.1 (wheel discs and caster), top face at z = 27.1.
- Wheel discs: centre y = 0, z = 6.9, radius 17, x from 41.5 to 48 on each side.
- LED windows in the top face: two 1.8 mm holes at x = +-31.8, y = 0. The baseplate covers them.
- The baseplate is **not** turned round: with its outline centred on the body, its board cutout and its two slots (x +-40.5..45.5, y -21.7..-13.7) sit exactly over the same shapes on the chassis.

## What the script makes up

- `WheelL` / `WheelR`: tyre with tread, hub and one white lug so a turn is easy to see. Slightly bigger than the moulded discs, which stay hidden inside them.
- `LedL` / `LedR`: a light strip along each side under the plate, wrapping both corners. The real LEDs are under the plate and glow through the see-through body; the strips stand in for that so the colour can be seen from any side.
- `Tof`: the distance sensor on the front face (the STL front is plain).
- Colours: body near-black, plate green. Kids' own skins are issue #10.
