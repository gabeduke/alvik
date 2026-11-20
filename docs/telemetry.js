// Telemetry from the robot (src/remote_control.py, telemetry_packet), for the 3D robot on the remote.
// It comes as notifications on the Nordic UART TX characteristic, about 5 times a second, but only
// after the page asks for it with telemetryRequest(true).
//
//   '!' 'T' <heading lo> <heading hi> <distance> <lights> <speed> <turn> <flags> <checksum>
//     heading   int16, tenths of a degree, -1800..1799; turning left counts up
//     distance  cm to the closest thing in front, 0..254; 255 = nothing seen
//     lights    bit 0-2 = left LED red, green, blue; bit 3-5 = right LED
//     speed     int8, 0.2 cm/s steps (forward is positive)
//     turn      int8, 3 deg/s steps (left is positive)
//     flags     bit 0 turbo, 1 bumper, 2 blocked by the bumper, 3 dancing
//   checksum = ~(sum of the bytes before it) & 0xff
//
// tests/telemetry_vectors.json holds example packets that both this file and the robot code are
// tested against.

export const NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";   // robot talks here
export const TELEMETRY_LEN = 10;

const checksum = (bytes, n) => {
  let sum = 0;
  for (let i = 0; i < n; i++) sum += bytes[i];
  return ~sum & 0xff;
};
const int8 = (b) => (b > 127 ? b - 256 : b);
const rgb = (bits) => [bits & 1, (bits >> 1) & 1, (bits >> 2) & 1];

/** The packet that turns telemetry on or off: '!' 'T' <'1' | '0'> <0> <checksum>. */
export function telemetryRequest(on) {
  const bytes = [0x21, 0x54, on ? 0x31 : 0x30, 0];
  bytes.push(checksum(bytes, 4));
  return new Uint8Array(bytes);
}

/** One whole packet (10 bytes) -> what the robot is doing, or null if it is not a good packet. */
export function parseTelemetry(bytes) {
  if (bytes.length !== TELEMETRY_LEN || bytes[0] !== 0x21 || bytes[1] !== 0x54) return null;
  if (checksum(bytes, TELEMETRY_LEN - 1) !== bytes[TELEMETRY_LEN - 1]) return null;
  const h = bytes[2] | (bytes[3] << 8);
  return {
    heading: (h > 32767 ? h - 65536 : h) / 10,          // degrees, left is positive
    distance: bytes[4] === 255 ? null : bytes[4],       // cm, null = nothing seen
    left: rgb(bytes[5]), right: rgb(bytes[5] >> 3),     // [r, g, b], each 0 or 1
    speed: int8(bytes[6]) / 5,                          // cm/s
    turn: int8(bytes[7]) * 3,                           // deg/s, left is positive
    turbo: !!(bytes[8] & 1), bumper: !!(bytes[8] & 2), blocked: !!(bytes[8] & 4), dancing: !!(bytes[8] & 8),
  };
}

/** Feed it whatever arrives (packets can come in pieces, or with junk between): calls onPacket for
 *  each good one. Returns the function to feed. */
export function telemetryReader(onPacket) {
  let buf = [];
  return (chunk) => {
    buf.push(...chunk);
    for (;;) {
      const i = buf.indexOf(0x21);
      if (i < 0) { buf = []; return; }
      if (i) buf = buf.slice(i);
      if (buf.length < 2) return;
      if (buf[1] !== 0x54) { buf.shift(); continue; }
      if (buf.length < TELEMETRY_LEN) return;
      const t = parseTelemetry(buf.slice(0, TELEMETRY_LEN));
      if (t) { buf = buf.slice(TELEMETRY_LEN); onPacket(t); } else buf.shift();   // damaged: find the next '!'
    }
  };
}
