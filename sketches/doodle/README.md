# ✏️ Doodle

The robot draws with a felt pen: a square, a triangle, a star or a ring.

**Not run on a real robot yet.** It passes on the pretend robot in `tests/test_robot.py`. On the real
one the corners may come out a little under or over: see "Things to try".

You need the printed [pen holder](../../models/addons/) on the robot's right side, a felt pen, two
rubber bands and a big sheet of paper **on the floor** (not on a table: the robot drives off on its own).

- **Menu light:** yellow
- **Lights while running:** the shape. green = square · yellow = triangle · purple = star · blue = ring
- **Buttons:** ◀ ▶ pick a shape · ✓ draws it · ✗ stops, also in the middle of a drawing, and goes back to the menu
- **Uses:** wheels, lights, and which way the robot points (`alvik.get_pose()`)

## The trick at the corners

Spin a robot on the spot and a pen on its side swings round in a curve. So at each corner this
robot drives forward a little while it turns, just fast enough that the pen stays on its spot and
the robot swings round the pen. The speed is `TURN` (as a part of a circle each second) times
`PEN_CM`, how far the pen is from the robot's middle.

The ring is the other way about: the robot spins on the spot and lets the pen swing all the way round.

## Things to try

- Set `PEN_CM` for your pen: 5.5 for a thin one (8 mm), 5.7 for 10 mm, 6.0 for 15 mm, 6.2 for a fat
  one (18 mm). Wrong number: the corners get a little hook or a little gap.
- Change `SIDE_CM` for bigger shapes.
- Add a shape to `SHAPES`. A shape with `n` lines turns `360 / n` at each corner; a star with five
  points turns 144.
- A shape that does not close up? Make `TURN` smaller, so the robot has an easier time stopping on
  the right spot.
