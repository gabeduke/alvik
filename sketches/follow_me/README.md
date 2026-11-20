# 🐕 Follow me

The robot is a puppy. Hold your hand in front of it (about a ruler away) and it walks after you,
turning to keep your hand in the middle. Move closer and it backs up. Take your hand away and it
sits and waits.

- **Menu light:** yellow
- **Lights while running:** green = following you · yellow = can't see you, waiting
- **Buttons:** ✗ back to the menu
- **Uses:** the 5 distance sensors on the front (`alvik.get_distance()`), wheels, lights

Things to try: change `NEAR_CM` (how close it likes to be), `SEE_CM` (how far it can see you)
or `MAX_SPEED` in `follow_me.py`.
