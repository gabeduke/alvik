# 3D models

Source files for the 3D Alvik on the web remote (issue #6). Units in the STL/STEP files are millimetres.

| File | What | From | Licence |
|---|---|---|---|
| `reference/alvik_reference_design.stl`, `.step` | Official Alvik chassis: one solid, 96 x 96 x 37 mm, with the LEGO Technic side holes and top mounting slots | Arduino, "STEP Files" on https://docs.arduino.cc/hardware/alvik/ | None stated by Arduino. Published for designing add-ons. |
| `reference/lego_baseplate_12x12.stl` | The printed LEGO-compatible top baseplate (12 x 12 studs, 96 x 96 x 11.4 mm) plus its two pins, laid out as on the print bed | "Arduino Alvik top baseplate (LEGO/DUPLO versions)" by GiulioT, https://makerworld.com/en/models/1298936 | CC BY-NC-SA. Anything built from it keeps that licence and the credit. |
| `alvik_reference.blend` | Blender scene with both imported (collection `AlvikReference`, scaled to metres, plate placed on top) | this repo | as above |
| `build_alvik_guess.py` | Blender script for an earlier guessed model. Not accurate: keep only as a source for the separate wheels (spin axis, marker lug) and LED parts. | this repo | |

The plate may be turned 180 degrees from how it really mounts: its two slots and the board cutout have not been lined up with the chassis yet.
