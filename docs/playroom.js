// "Try it without a robot": runs the pretend Alvik (pretend.js) in the page and draws the little
// map of its pretend room. To the rest of the page it looks like a robot on Bluetooth: write()
// takes the same packets, and onData gets the same telemetry bytes back.
//
//   const room = openPlayroom({ canvas, onData: (bytes) => feed(bytes) });
//   room.write(packet);          // as you would write to the robot
//   room.hold(true);             // pick the pretend robot up; hold(false) puts it down
//   room.close();                // stop
import { createPretendRobot, ZONE_DEG } from "./pretend.js";

const STEP_MS = 30;                              // the real robot's loop takes about this long
const WALL = "#b8b0d8", FLOOR = "#3a3163", RAY = "rgba(143,208,255,.55)";
const css = ([r, g, b]) => `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;

export function openPlayroom({ canvas, onData }) {
  const robot = createPretendRobot({ send: onData });
  const room = robot.room, pen = canvas.getContext("2d");
  let last = performance.now();

  function draw() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(w * ratio)) { canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio); }
    const s = Math.min(canvas.width / room.w, canvas.height / room.h);
    pen.setTransform(s, 0, 0, -s, 0, room.h * s);                // cm, with y going up the map
    pen.fillStyle = FLOOR;
    pen.fillRect(0, 0, room.w, room.h);
    for (const m of room.mats) { pen.fillStyle = css(m.rgb); pen.fillRect(m.x, m.y, m.w, m.h); }
    pen.fillStyle = "#000";
    for (const t of room.tape) pen.fillRect(t.x, t.y, t.w, t.h);
    pen.fillStyle = WALL;
    for (const b of room.boxes) pen.fillRect(b.x, b.y, b.w, b.h);
    for (const p of room.posts) { pen.beginPath(); pen.arc(p.x, p.y, Math.max(p.r, 2.2), 0, 7); pen.fill(); }
    pen.strokeStyle = WALL; pen.lineWidth = 3;
    pen.strokeRect(0, 0, room.w, room.h);

    const v = robot.view(), a = v.heading * Math.PI / 180;
    pen.translate(v.x, v.y);
    pen.rotate(a);                                               // now +y is the way the robot faces
    if (!v.held) {                                               // what the five zones see, out to their readings
      pen.strokeStyle = RAY; pen.lineWidth = 1;
      ZONE_DEG.forEach((deg, i) => {
        const d = v.seen[i];
        if (d === null) return;
        const r = deg * Math.PI / 180;
        pen.beginPath(); pen.moveTo(0, 4.8); pen.lineTo(-Math.sin(r) * d, 4.8 + Math.cos(r) * d); pen.stroke();
      });
    }
    const size = v.held ? 9 : 7;                                 // picked up: nearer to you, so bigger
    pen.fillStyle = v.blocked ? "#ff3b3b" : v.lit[0].some(Boolean) ? css(v.lit[0]) : "#777";
    pen.strokeStyle = "#1b1630"; pen.lineWidth = 1.5;
    pen.beginPath(); pen.moveTo(0, size + 3); pen.lineTo(size, -size); pen.lineTo(-size, -size); pen.closePath();
    pen.fill(); pen.stroke();
  }

  const timer = setInterval(() => {
    const now = performance.now();
    robot.step(Math.min(now - last, 200));       // a tab in the background ticks slowly: the robot just waits
    last = now;
    draw();
  }, STEP_MS);
  draw();

  return {
    write: (bytes) => robot.write(bytes),
    hold: (on) => robot.hold(on),
    close: () => clearInterval(timer),
  };
}
