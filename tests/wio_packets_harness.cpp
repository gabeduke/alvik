// Test harness for remotes/wio_remote/alvik_packets.h, built and run by tests/test_robot.py (WioPackets).
//   stdin: one hex packet per line. Each is fed to the Reader in two pieces with junk in front.
//   stdout: one line per packet read ("T ...", "S ...", "U ..."), then "OUT <hex>" for packets it builds.
#include <stdio.h>
#include <string.h>
#include "../remotes/wio_remote/alvik_packets.h"

static void hex(const uint8_t* b, size_t n) { for (size_t i = 0; i < n; i++) printf("%02x", b[i]); }

int main() {
  alvik::Reader r;
  char line[256];
  while (fgets(line, sizeof line, stdin)) {
    uint8_t b[64]; size_t n = 0;
    for (char* p = line; p[0] && p[1] && p[0] != '\n'; p += 2) { unsigned v; sscanf(p, "%2x", &v); b[n++] = (uint8_t)v; }
    const uint8_t junk[] = {'x', '!', '?'};
    r.feed(junk, sizeof junk);
    int got = r.feed(b, n / 2) | r.feed(b + n / 2, n - n / 2);
    if (got & alvik::Reader::GOT_T) {
      const alvik::Telemetry& t = r.t;
      printf("T %.1f %d %d%d%d %d%d%d %.1f %d %d %d %d %d\n", t.heading, t.distance, t.left[0], t.left[1], t.left[2],
             t.right[0], t.right[1], t.right[2], t.speed, t.turn, t.turbo, t.bumper, t.blocked, t.dancing);
    }
    if (got & alvik::Reader::GOT_S) {
      const alvik::Sensors& s = r.s;
      printf("S %d %d %d %d %d %d %d %d\n", s.zones[0], s.zones[1], s.zones[2], s.zones[3], s.zones[4], s.roll, s.pitch, s.battery);
    }
    if (got & alvik::Reader::GOT_U) {
      const alvik::Under& u = r.u;
      printf("U %d %d %d %d %d %d %d %d\n", u.lines[0], u.lines[1], u.lines[2], u.floor[0], u.floor[1], u.floor[2], u.bottom, u.top);
    }
  }
  uint8_t p[5];
  const int sticks[][2] = {{0, 100}, {-100, 0}, {50, -100}, {127, -128}, {0, 0}};
  for (auto& s : sticks) { alvik::joystickPacket(p, s[0], s[1]); printf("OUT "); hex(p, 5); printf("\n"); }
  for (int n = 1; n <= 4; n++) for (int d = 1; d >= 0; d--) { alvik::buttonPacket(p, n, d); printf("OUT "); hex(p, 5); printf("\n"); }
  alvik::telemetryRequest(p, true); printf("OUT "); hex(p, 5); printf("\n");
  return 0;
}
