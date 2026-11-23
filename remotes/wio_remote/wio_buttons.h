// The Wio remote's three top buttons, and the grown-up switches hidden behind two of them
// (wio_remote.ino). Plain C++ with no Arduino in it, like alvik_packets.h, so tests/test_robot.py
// (WioButtons) can build it with g++ and press the buttons there.
//
// A child drives with a thumb on the stick, and the stick clicks in when it is pushed hard. So
// pressing the stick in does nothing by itself, however long. It only works as a "shift" key:
//   stick pressed in first, then a grown-up button held for holdMs  ->  HELD (the switch), once
//   the same, but let go early                                      ->  TAP  (the button's own job)
//   any button without the stick pressed in                         ->  DOWN, then UP when let go
// A button that was already down when the stick went in stays an ordinary press.
#pragma once
#include <stdint.h>

namespace alvik {

class TopButtons {
 public:
  static const int N = 3;
  enum What { NOTHING = 0, DOWN, UP, TAP, HELD };

  uint32_t holdMs;          // hold a grown-up button this long, with the stick pressed in
  uint32_t bounceMs;        // a button can't change again sooner than this (its contacts chatter)
  bool grownUp[N];          // which buttons have a switch behind them

  TopButtons(uint32_t hold = 1500, uint32_t bounce = 20) : holdMs(hold), bounceMs(bounce) {
    for (int i = 0; i < N; i++) { grownUp[i] = false; down[i] = false; state[i] = IDLE; changedAt[i] = 0; since[i] = 0; }
  }

  /** Call often. shift = the stick is pressed in (and not pushed any way); raw = each button as it
   *  reads now; now = milliseconds. out says what each button just did. */
  void step(bool shift, const bool raw[N], uint32_t now, What out[N]) {
    for (int i = 0; i < N; i++) {
      out[i] = NOTHING;
      if (raw[i] != down[i] && now - changedAt[i] >= bounceMs) { down[i] = raw[i]; changedAt[i] = now; }
      switch (state[i]) {
        case IDLE:
          if (!down[i]) break;
          if (shift && grownUp[i]) { state[i] = WAIT; since[i] = now; }
          else { state[i] = SENT; out[i] = DOWN; }
          break;
        case SENT:
          if (!down[i]) { state[i] = IDLE; out[i] = UP; }
          break;
        case WAIT:
          if (!down[i]) { state[i] = IDLE; out[i] = TAP; }                    // let go early: just a tap
          else if (!shift) { state[i] = SENT; out[i] = DOWN; }                // the stick came out: an ordinary press
          else if (now - since[i] >= holdMs) { state[i] = DONE; out[i] = HELD; }
          break;
        case DONE:
          if (!down[i]) state[i] = IDLE;
          break;
      }
    }
  }

  /** Is button i down (after the chatter is taken out)? */
  bool isDown(int i) const { return down[i]; }
  /** How far button i is through its hold, 0..1, or -1 if it isn't being held for a switch. */
  float progress(int i, uint32_t now) const {
    if (state[i] != WAIT) return -1;
    float p = (float)(now - since[i]) / (float)holdMs;
    return p > 1 ? 1 : p;
  }
  /** Is any button part way through a hold? (The screen shows how far.) */
  bool waiting() const {
    for (int i = 0; i < N; i++) if (state[i] == WAIT) return true;
    return false;
  }

 private:
  enum State { IDLE, SENT, WAIT, DONE };
  bool down[N];
  State state[N];
  uint32_t changedAt[N], since[N];
};

}  // namespace alvik
