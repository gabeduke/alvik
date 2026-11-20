# 🙀 Scaredy cat

The robot sits still. Bring your hand (or a toy) close to its nose and it backs away until it
feels safe again.

- **Menu light:** cyan
- **Lights while running:** green = calm · red = too close, backing away
- **Buttons:** ✗ back to the menu
- **Uses:** the middle distance sensor (`alvik.get_distance()[2]`), wheels, lights

This is the program written step by step in [lesson 8](https://gabeduke.github.io/alvik/learn/8-sketch.html).

Things to try: change `TOO_CLOSE_CM` (what happens at 20, on an empty floor?), or make it turn
away instead of backing up (`alvik.drive(0, 90)`).
