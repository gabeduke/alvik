# Grove holders that press onto LEGO

Printable trays for Seeed Grove boards. Underneath, each one is a LEGO brick, so it presses onto the
studs of the robot's top plate like a backpack. Units are millimetres.

**Not printed yet.** The shapes are checked in Blender (closed solids, on the stud grid). The fit on
studs and the clips are still guesses until someone prints them: start with the fit test.

| File | For | Size | Studs |
|---|---|---|---|
| `fit_test_2x2.stl` | Checking the fit on your printer before anything else | 15.8 x 15.8 x 5.2 | 2 x 2 |
| `grove_1x1_cradle.stl` | Any 20 x 20 Grove board | 23.8 x 23.8 x 9 | 3 x 3 |
| `grove_1x2_cradle.stl` | Any 20 x 40 Grove board | 23.8 x 47.8 x 9 | 3 x 6 |
| `lid_speech_recognizer.stl` | Snaps onto the 20 x 40 tray over a [Grove - Speech Recognizer](https://wiki.seeedstudio.com/Grove-Speech_Recognizer/) | 23.8 x 47.8, 17.3 tall on the tray | |
| `lid_speaker.stl` | Snaps onto the 20 x 40 tray over a [Grove - Speaker](https://wiki.seeedstudio.com/Grove-Speaker/) | 23.8 x 47.8, 19.8 tall on the tray | |

They are built by `../build_grove_holders.py`, not edited by hand:

```sh
/Applications/Blender.app/Contents/MacOS/Blender -b --python models/build_grove_holders.py
```

## How a board sits

- The board's Grove socket goes at the low end of the tray, so a sideways plug can reach it. A socket
  that points up works too.
- The round ears with the mounting holes drop into notches in the walls. That stops the board sliding.
- Four small clips on springy pieces of wall hold it down. Push the board straight down until it clicks.
  To take it out, pull one side's clips outward with a fingernail and tip the board up.
- There is 2.6 mm of room under the board for solder pins.

## The two lids

Both fit the 20 x 40 tray: four tabs slide down slots in the tray's end walls and click into a groove.
To take the lid off, pull one end's two tabs outward and lift that end.

- **Speech Recognizer**: the board's socket goes at the tray's low end. The lid has openings for the
  Grove plug, the microphone, the red and blue lights, and the small socket for an extra speaker.
- **Speaker**: this board's ears are the other way about, so it goes in turned round, speaker over the
  tray's low end and socket at the high end. The lid has openings for the plug and the loudness knob,
  and seven holes over the speaker.

Where the openings are comes from Seeed's Eagle board files (linked on the two wiki pages) and, for the
speaker itself, from the product photo, so it is a few tenths of a millimetre to a millimetre sure.
The room under the roof (8.5 mm and 11 mm above the board) is from usual part heights, not measured:
hold the lid over the board before snapping it on.

## Printing

- Print every file the way up it comes: it already lies flat on the bed (the lids roof down). Don't
  let the slicer turn it (in Bambu Studio, skip "Auto orient"; "Arrange" is fine). No supports. 0.2 mm layers or finer, 3 walls.
- The hollow underside prints without supports: the gaps the roof has to bridge are about 3 mm. The
  socket edges lean back 0.3 mm at the bed so a squashed first layer does not pinch the studs.
- The trays touch the bed only along their rim, tubes and ribs. Wash the plate first, and add a 5 mm brim
  (Bambu Studio: Others, Brim type "Outer brim only", so none ends up in the stud sockets). A first print
  without ribs or brim came loose and failed.
- PETG is kinder to the clips than PLA; PLA should do if the board is not taken out often.
- Print `fit_test_2x2.stl` first and press it onto the plate, and a LEGO brick onto its two studs.
  Too tight or too loose: change `FIT` at the top of the script by 0.05 (+ is looser), build, print again.
- Board loose or tight in the tray: `SLACK`. Clips too stiff or too weak: `ARM_T` and `BARB`.

## Where the numbers come from

- LEGO: measured on the printed plate in `../reference/lego_baseplate_12x12.stl` (8 mm between studs,
  studs 4.95 mm wide and 1.8 mm tall).
- Grove boards: Seeed's own drawings, "Grove Mechanical Drawing" linked from
  https://wiki.seeedstudio.com/Grove_System/ . Boards are 1.6 mm thick; the 2.2 mm mounting holes sit on
  the board's edge inside a round ear, so a 20 mm board is 24 mm across the ears. 20 x 20: one ear in the
  middle of each side. 20 x 40: one on each long side 10 mm from the socket end, one in the middle of the
  far end. The Speech Recognizer's board file agrees. The Speaker's has them reversed (the single ear at
  the socket end), which is why it goes in turned round.
- No 40 x 40 holder: Seeed's drawings don't cover that board, so its ears are not known here.

## Before buying a module

The Alvik's two Grove ports are I2C only and give 3.3 V (Arduino's datasheet, AKX00066). A module that
talks serial (UART) or needs a PWM pin or 5 V fits a holder but will not work from that port as it is.
Pick modules that say I2C and 3.3 V. Of the two with lids here: the Speech Recognizer runs at 3.3 V but
talks serial at 9600 baud, and the Speaker wants 4 to 5.5 V and a plain output pin. Neither has been
tried on the robot.

## Others' holders

Not used here, and their licences were not checked: Seeed's own
[Grove Wrapper](https://wiki.seeedstudio.com/Grove-Wrapper/) (a bought plastic case, drawings only),
[PELA Blocks](https://pelablocks.org/) (LEGO-compatible board mounts in OpenSCAD),
Thingiverse [2679675](https://www.thingiverse.com/thing:2679675) and
[751361](https://www.thingiverse.com/thing:751361).

## Licence

Made in this repo from the numbers above; MIT like the rest of the code.
