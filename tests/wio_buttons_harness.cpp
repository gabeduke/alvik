// Test harness for remotes/wio_remote/wio_buttons.h, built and run by tests/test_robot.py (WioButtons).
//   stdin: one line per moment, "<ms> <stick pressed in 0|1> <left> <middle> <right>" (buttons 0|1).
//          The left and right buttons have a grown-up switch behind them, as on the remote.
//   stdout: one line per thing a button did, "<ms> <button 0..2> <DOWN|UP|TAP|HELD>", and
//           "<ms> <button> WAIT <percent>" while a button is part way through its hold.
#include <stdio.h>
#include "../remotes/wio_remote/wio_buttons.h"

int main() {
  alvik::TopButtons tops;
  tops.grownUp[0] = tops.grownUp[2] = true;
  const char* names[] = {"", "DOWN", "UP", "TAP", "HELD"};
  unsigned ms; int shift, b[3];
  while (scanf("%u %d %d %d %d", &ms, &shift, &b[0], &b[1], &b[2]) == 5) {
    bool raw[3] = {b[0] != 0, b[1] != 0, b[2] != 0};
    alvik::TopButtons::What out[3];
    tops.step(shift != 0, raw, ms, out);
    for (int i = 0; i < 3; i++) {
      if (out[i]) printf("%u %d %s\n", ms, i, names[out[i]]);
      else if (tops.progress(i, ms) >= 0) printf("%u %d WAIT %d\n", ms, i, (int)(tops.progress(i, ms) * 100));
    }
  }
  return 0;
}
