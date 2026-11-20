// Telemetry from the robot (src/remote_control.py, telemetry_packet), for the 3D robot on the remote.
// It comes as notifications on the Nordic UART TX characteristic, about 8 times a second, but only
// after the page asks for it with telemetryRequest(true).
//
//   '!' 'T' <heading lo> <heading hi> <distance> <lights> <speed> <turn> <flags> <checksum>
//     heading   int16, tenths of a degree, -1800..1799; turning left counts up
//     distance  cm to what the robot's bumper sees in front (an average, without the floor),
//               0..254; 255 = nothing
//     lights    bit 0-2 = left LED red, green, blue; bit 3-5 = right LED
//     speed     int8, 0.2 cm/s steps (forward is positive)
//     turn      int8, 3 deg/s steps (left is positive)
//     flags     bit 0 turbo, 1 bumper, 2 blocked by the bumper, 3 dancing
//   checksum = ~(sum of the bytes before it) & 0xff
//
// Right after it comes a second packet with the other sensors (robot code from before it existed
// just doesn't send it):
//
//   '!' 'S' <left> <half left> <middle> <half right> <right> <roll> <pitch> <battery> <checksum>
//     five distances in cm, just as the sensor reads them from left to right (floor and blips
//     included: the page shows them as a point cloud); 255 = nothing seen
//     roll, pitch   int8, whole degrees, as the robot's IMU reports them
//     battery       0..100 percent; 255 = not known
//
// and a third with what is under the robot (again, older robot code doesn't send it):
//
//   '!' 'U' <line left> <line centre> <line right> <red> <green> <blue> <bottom> <top> <checksum>
//     line sensors  the raw reading in steps of 4 (0..254, so 0..1016): a pale floor reads low, a
//                   black line or no floor at all reads high; 255 = not known
//     red, green, blue   the floor's colour, 0..100: how far each is from black to white, as the
//                   Alvik library works it out; 255 = not known
//     bottom, top   cm to what the distance sensor sees low down and high up in front. On the floor,
//                   bottom is the floor just ahead (about 7); it grows when the robot is picked up.
//                   255 = nothing seen
//
// A new kind of reading gets a new letter: these layouts never change, and a reader skips letters
// it doesn't know.
//
// tests/telemetry_vectors.json holds example packets that both this file and the robot code are
// tested against.

export const NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";   // robot talks here
export const TELEMETRY_LEN = 10;
export const SENSORS_LEN = 11;
export const UNDER_LEN = 11;

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

/** One whole sensors packet (11 bytes) -> the readings, or null if it is not a good packet. */
export function parseSensors(bytes) {
  if (bytes.length !== SENSORS_LEN || bytes[0] !== 0x21 || bytes[1] !== 0x53) return null;
  if (checksum(bytes, SENSORS_LEN - 1) !== bytes[SENSORS_LEN - 1]) return null;
  return {
    zones: [...bytes.slice(2, 7)].map((d) => (d === 255 ? null : d)),   // cm, left to right
    roll: int8(bytes[7]), pitch: int8(bytes[8]),                        // degrees
    battery: bytes[9] === 255 ? null : bytes[9],                        // percent
  };
}

/** One whole under-the-robot packet (11 bytes) -> the readings, or null if it is not a good packet. */
export function parseUnder(bytes) {
  if (bytes.length !== UNDER_LEN || bytes[0] !== 0x21 || bytes[1] !== 0x55) return null;
  if (checksum(bytes, UNDER_LEN - 1) !== bytes[UNDER_LEN - 1]) return null;
  const colour = [...bytes.slice(5, 8)];
  return {
    lines: [...bytes.slice(2, 5)].map((v) => (v === 255 ? null : v * 4)),   // raw, left to right: dark reads high
    floor: colour.includes(255) ? null : colour.map((v) => v / 100),       // [r, g, b], each 0..1
    bottom: bytes[8] === 255 ? null : bytes[8],                             // cm
    top: bytes[9] === 255 ? null : bytes[9],                                // cm
  };
}

/** Feed it whatever arrives (packets can come in pieces, or with junk between): calls onPacket for
 *  each good telemetry packet, onSensors for each good sensors packet and onUnder for each good
 *  under-the-robot packet. Returns the function to feed. */
export function telemetryReader(onPacket, onSensors = () => {}, onUnder = () => {}) {
  const kinds = {
    0x54: [TELEMETRY_LEN, parseTelemetry, onPacket],
    0x53: [SENSORS_LEN, parseSensors, onSensors],
    0x55: [UNDER_LEN, parseUnder, onUnder],
  };
  let buf = [];
  return (chunk) => {
    buf.push(...chunk);
    for (;;) {
      const i = buf.indexOf(0x21);
      if (i < 0) { buf = []; return; }
      if (i) buf = buf.slice(i);
      if (buf.length < 2) return;
      const kind = kinds[buf[1]];
      if (!kind) { buf.shift(); continue; }                              // a letter we don't know: skip it
      const [len, parse, hand] = kind;
      if (buf.length < len) return;
      const t = parse(buf.slice(0, len));
      if (!t) { buf.shift(); continue; }                                 // damaged: find the next '!'
      buf = buf.slice(len);
      hand(t);
    }
  };
}
