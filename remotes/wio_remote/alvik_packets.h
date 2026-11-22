// The Alvik's Bluetooth packets, for the Wio Terminal remote (wio_remote.ino).
// Plain C++ with no Arduino in it, so tests/test_robot.py (WioPackets) can build it with g++ and
// check it against the robot's own parser and tests/telemetry_vectors.json.
//
// What the remote sends (the robot reads them in parse_packets, src/remote_control.py):
//   '!' 'J' <x int8> <y int8> <checksum>      joystick, -100..100, x right, y forward
//   '!' 'B' <'1'..'8'> <'1' down | '0' up> <checksum>   a button (1 lights, 2 turbo, 3 dance, 4 bumper)
//   '!' 'T' <'1' on | '0' off> <0> <checksum>  "send me telemetry"
// What comes back (layouts at the top of docs/telemetry.js): 'T' (10 bytes), 'S' and 'U' (11 each).
// checksum = ~(sum of the bytes before it) & 0xff
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace alvik {

const int NONE = -1;                    // "nothing seen" / "not known" in the readings below

inline uint8_t checksum(const uint8_t* b, size_t n) {
  unsigned sum = 0;
  for (size_t i = 0; i < n; i++) sum += b[i];
  return (uint8_t)(~sum & 0xFF);
}

inline void close5(uint8_t out[5]) { out[4] = checksum(out, 4); }
inline int clamp100(int v) { return v < -100 ? -100 : v > 100 ? 100 : v; }

/** Joystick packet: x right, y forward, each -100..100. */
inline void joystickPacket(uint8_t out[5], int x, int y) {
  out[0] = '!'; out[1] = 'J';
  out[2] = (uint8_t)(int8_t)clamp100(x);
  out[3] = (uint8_t)(int8_t)clamp100(y);
  close5(out);
}
/** Button packet: n = 1..8, down = pressed (true) or let go (false). */
inline void buttonPacket(uint8_t out[5], int n, bool down) {
  out[0] = '!'; out[1] = 'B'; out[2] = (uint8_t)('0' + n); out[3] = down ? '1' : '0';
  close5(out);
}
/** Ask the robot to start (or stop) sending telemetry. */
inline void telemetryRequest(uint8_t out[5], bool on) {
  out[0] = '!'; out[1] = 'T'; out[2] = on ? '1' : '0'; out[3] = 0;
  close5(out);
}

struct Telemetry {
  float heading = 0;            // degrees, turning left counts up (from the wheels)
  int distance = NONE;          // cm to what the bumper acts on
  uint8_t left[3] = {0, 0, 0};  // LED colours, each 0 or 1: red, green, blue
  uint8_t right[3] = {0, 0, 0};
  float speed = 0;              // cm/s, forward is positive
  int turn = 0;                 // deg/s, left is positive
  bool turbo = false, bumper = true, blocked = false, dancing = false;
};
struct Sensors {
  int zones[5] = {NONE, NONE, NONE, NONE, NONE};   // cm, left to right, raw (floor and blips included)
  int roll = 0, pitch = 0;      // degrees
  int battery = NONE;           // percent
};
struct Under {
  int lines[3] = {NONE, NONE, NONE};   // raw line sensors, left to right: a pale floor reads low
  int floor[3] = {NONE, NONE, NONE};   // floor colour, red/green/blue, each 0..100
  int bottom = NONE, top = NONE;       // cm
};

inline int8_t s8(uint8_t b) { return (int8_t)b; }
inline int cmOrNone(uint8_t b) { return b == 255 ? NONE : b; }

inline bool parseTelemetry(const uint8_t* b, Telemetry& t) {
  if (b[0] != '!' || b[1] != 'T' || checksum(b, 9) != b[9]) return false;
  t.heading = (int16_t)(b[2] | (b[3] << 8)) / 10.0f;
  t.distance = cmOrNone(b[4]);
  for (int i = 0; i < 3; i++) { t.left[i] = (b[5] >> i) & 1; t.right[i] = (b[5] >> (i + 3)) & 1; }
  t.speed = s8(b[6]) / 5.0f;
  t.turn = s8(b[7]) * 3;
  t.turbo = b[8] & 1; t.bumper = b[8] & 2; t.blocked = b[8] & 4; t.dancing = b[8] & 8;
  return true;
}
inline bool parseSensors(const uint8_t* b, Sensors& s) {
  if (b[0] != '!' || b[1] != 'S' || checksum(b, 10) != b[10]) return false;
  for (int i = 0; i < 5; i++) s.zones[i] = cmOrNone(b[2 + i]);
  s.roll = s8(b[7]); s.pitch = s8(b[8]);
  s.battery = cmOrNone(b[9]);
  return true;
}
inline bool parseUnder(const uint8_t* b, Under& u) {
  if (b[0] != '!' || b[1] != 'U' || checksum(b, 10) != b[10]) return false;
  for (int i = 0; i < 3; i++) u.lines[i] = b[2 + i] == 255 ? NONE : b[2 + i] * 4;
  bool known = b[5] != 255 && b[6] != 255 && b[7] != 255;
  for (int i = 0; i < 3; i++) u.floor[i] = known ? b[5 + i] : NONE;
  u.bottom = cmOrNone(b[8]); u.top = cmOrNone(b[9]);
  return true;
}

/** Feed it whatever arrives; packets can come in pieces or with junk between, and letters it
 *  doesn't know are skipped (as in docs/telemetry.js). feed() returns which kinds were updated. */
class Reader {
 public:
  enum { GOT_T = 1, GOT_S = 2, GOT_U = 4 };
  Telemetry t; Sensors s; Under u;

  int feed(const uint8_t* data, size_t n) {
    int got = 0;
    for (size_t i = 0; i < n; i++) {
      if (len == sizeof buf) drop(1);           // never happens with good packets; keeps it safe
      buf[len++] = data[i];
      got |= scan();
    }
    return got;
  }

 private:
  uint8_t buf[32];
  size_t len = 0;

  void drop(size_t k) { memmove(buf, buf + k, len - k); len -= k; }
  static size_t sizeOf(uint8_t kind) { return kind == 'T' ? 10 : (kind == 'S' || kind == 'U') ? 11 : 0; }

  int scan() {
    int got = 0;
    for (;;) {
      size_t i = 0;
      while (i < len && buf[i] != '!') i++;
      if (i) drop(i);
      if (len < 2) return got;
      size_t need = sizeOf(buf[1]);
      if (!need) { drop(1); continue; }         // a letter we don't know
      if (len < need) return got;
      bool ok = buf[1] == 'T' ? parseTelemetry(buf, t) : buf[1] == 'S' ? parseSensors(buf, s) : parseUnder(buf, u);
      if (!ok) { drop(1); continue; }           // damaged: look for the next '!'
      got |= buf[1] == 'T' ? GOT_T : buf[1] == 'S' ? GOT_S : GOT_U;
      drop(need);
    }
  }
};

}  // namespace alvik
