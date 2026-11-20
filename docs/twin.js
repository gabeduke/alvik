// The 3D Alvik on the remote: a live copy of the real robot, fed by telemetry (telemetry.js).
// It turns with the robot's heading, its wheels spin, its light strips take the LED colours and a
// wall shows up in front when the distance sensor sees something.
//
//   const twin = await createTwin(canvas);      // loads three.js and models/alvik.glb
//   twin.update(t);                             // t = a parsed telemetry packet
//   twin.sensors(s);                            // s = a parsed sensors packet (five distances, tilt)
//   twin.reset();                               // robot went away: stand still, lights off
//   twin.recentre();                            // "the robot is pointing away from me right now"
//
// The model (models/build_alvik_web.py) is in metres, faces +Z, left = +X, with parts named
// Body, Baseplate, WheelL, WheelR, LedL, LedR, Tof. The camera sits behind and above it, so a robot
// at heading 0 drives away from you, like the real one when you stand behind it.
// Draws only when something changes, so an idle page costs nothing.
import * as THREE from "three";
import { GLTFLoader } from "./vendor/three/loaders/GLTFLoader.js";

const WHEEL_R = 0.017, TRACK = 0.0895;          // metres: wheel radius, distance between the wheels
const NOSE = 0.048;                             // front face, from the middle
const SLOW_CM = 30, STOP_CM = 12;               // as on the robot: bumper slows from 30 cm, stops at 12
const SEE_CM = 40;                              // the wall fades in from here
const ZONE_DEG = 18;                            // the five distance zones are drawn this far apart
const ROLL_SIGN = 1, PITCH_SIGN = 1;            // flip if the 3D robot tips the wrong way
const FLASH_MS = 120;                           // blink of the strips while the bumper holds the robot
const STALE_MS = 1000;                          // no news for this long: stop the wheels
const BG = 0x1b1630, FLOOR = 0x2a2347, GRID = 0x4a3f7c, CELL = 0.05;
const AZIMUTH = 0.42, ELEVATION = 0.6;          // camera: radians round to the robot's right, and up
const wrap = (deg) => ((deg + 180) % 360 + 360) % 360 - 180;

export async function createTwin(canvas, { modelUrl = "models/alvik.glb" } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BG);
  scene.fog = new THREE.Fog(BG, 1, 2);          // set for real in place()
  const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 5);

  scene.add(new THREE.HemisphereLight(0xdfe6ff, 0x30284f, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 2.2);
  sun.position.set(-0.3, 0.6, -0.4);
  scene.add(sun);
  const rim = new THREE.DirectionalLight(0x9fc4ff, 1.4);       // from the front, so the dark body has an edge
  rim.position.set(0.4, 0.3, 0.6);
  scene.add(rim);

  // the floor: a grid that slides under the robot as it drives
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(4, 4),
    new THREE.MeshStandardMaterial({ color: FLOOR, roughness: 0.9 }));
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);
  const grid = new THREE.GridHelper(4, 4 / CELL, GRID, GRID);
  grid.position.y = 0.0005;
  scene.add(grid);

  const robot = new THREE.Group();
  scene.add(robot);
  const gltf = await new GLTFLoader().loadAsync(modelUrl);
  robot.add(gltf.scene);
  const part = (name) => {
    const p = gltf.scene.getObjectByName(name);
    if (!p) throw new Error(`alvik.glb has no part called ${name}`);
    return p;
  };
  const wheels = [part("WheelL"), part("WheelR")];
  part("Body").material.color.set(0x1c2026);                   // near-black, but not lost on the dark page

  // light strips: the material glows in the LED's colour, and a small lamp colours the floor beside it
  const leds = [part("LedL"), part("LedR")].map((mesh, i) => {
    const lamp = new THREE.PointLight(0x000000, 0, 0.3, 2);
    lamp.position.set(i ? -0.062 : 0.062, 0.03, 0);
    robot.add(lamp);
    return { mat: mesh.material, lamp };
  });
  function setLed(i, [r, g, b]) {
    const { mat, lamp } = leds[i], on = r || g || b;
    mat.color.setRGB(on ? r * 0.8 + 0.2 : 0.12, on ? g * 0.8 + 0.2 : 0.12, on ? b * 0.8 + 0.2 : 0.14);
    mat.emissive.setRGB(r, g, b);
    mat.emissiveIntensity = on ? 1.6 : 0;
    lamp.color.setRGB(r, g, b);
    lamp.intensity = on ? 0.06 : 0;
  }

  // what the distance sensor sees: five see-through wall pieces, one for each zone from left to
  // right. Each comes closer on its own; yellow where the robot slows, red where it stops.
  const walls = [0, 1, 2, 3, 4].map((i) => {
    const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0, roughness: 0.6, depthWrite: false });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 0.055, 0.006), mat);
    mesh.visible = false;
    mesh.rotation.y = THREE.MathUtils.degToRad((2 - i) * ZONE_DEG);     // the robot's left is +X
    robot.add(mesh);
    return mesh;
  });

  // ---------- state ----------
  let target = 0, shown = 0, zero = null;       // heading in degrees: latest from the robot, drawn, and what counts as 0
  let speed = 0, turn = 0;                      // cm/s, deg/s
  let zones = [null, null, null, null, null], zoned = false, blocked = false;   // cm, left to right
  let lights = [[0, 0, 0], [0, 0, 0]];
  let roll = 0, pitch = 0, rollNow = 0, pitchNow = 0;      // degrees: latest from the robot, and drawn
  let newsAt = 0, lastFrame = 0, frame = 0, small = false;
  const pos = new THREE.Vector2();              // how far the floor has slid (x, z), metres

  const gapMax = () => (small ? 0.05 : 0.11);   // metres in the picture for a wall 30 cm away

  function place() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    small = Math.min(w, h) < 130;
    // camera: behind the robot, a little to its right and above. It must fit the circle the wall
    // can sweep as the robot turns on the spot.
    const round = NOSE + gapMax() + 0.014;
    const centre = new THREE.Vector3(0, 0.02, 0);
    const across = round, upDown = round * Math.sin(ELEVATION) + 0.03;
    camera.aspect = w / h;
    const half = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const dist = Math.max(upDown / half, across / (half * camera.aspect));
    camera.position.set(-Math.sin(AZIMUTH) * Math.cos(ELEVATION), Math.sin(ELEVATION), -Math.cos(AZIMUTH) * Math.cos(ELEVATION))
      .multiplyScalar(dist).add(centre);
    camera.lookAt(centre);
    scene.fog.near = dist + 0.25;               // the floor fades into the page a little behind the robot
    scene.fog.far = dist + 1.0;
    camera.updateProjectionMatrix();
    draw();
  }

  function showWalls() {
    const step = Math.tan(THREE.MathUtils.degToRad(ZONE_DEG / 2)) * 2;
    walls.forEach((wall, i) => {
      const cm = zones[i];
      if (cm === null || cm > SEE_CM) { wall.visible = false; return; }
      wall.visible = true;
      // closer than real, so it fits in the picture: 30 cm away is drawn at the edge of the view
      const r = NOSE + 0.006 + gapMax() * Math.min(cm, SLOW_CM) / SLOW_CM;
      const a = wall.rotation.y;
      wall.position.set(Math.sin(a) * r, 0.03, Math.cos(a) * r);
      wall.scale.x = r * step * 0.94;
      const mat = wall.material, mid = i > 0 && i < 4;        // the bumper only looks at the middle three
      mat.opacity = (mid ? 0.75 : 0.45) * Math.min(1, (SEE_CM - cm) / (SEE_CM - SLOW_CM) + 0.15);
      mat.color.set(mid && (blocked || cm < STOP_CM) ? 0xff3b3b : cm < SLOW_CM ? 0xffd23f : 0xdfe6ff);
      mat.emissive.copy(mat.color).multiplyScalar(0.35);
    });
  }

  function draw() { renderer.render(scene, camera); }

  function tick(now) {
    frame = 0;
    const dt = Math.min((now - lastFrame) / 1000, 0.1);
    lastFrame = now;
    if (now - newsAt > STALE_MS) { speed = 0; turn = 0; }
    // heading: keep turning at the robot's turn rate between packets, and close in on what it last said
    shown = wrap(shown + turn * dt);
    shown = wrap(shown + wrap(target - shown) * Math.min(1, dt * 8));
    const rad = THREE.MathUtils.degToRad(shown);
    robot.rotation.y = rad;
    const v = speed / 100, w = THREE.MathUtils.degToRad(turn);
    wheels[0].rotation.x += (v - w * TRACK / 2) / WHEEL_R * dt;       // left wheel
    wheels[1].rotation.x += (v + w * TRACK / 2) / WHEEL_R * dt;
    pos.x = (pos.x + Math.sin(rad) * v * dt) % CELL;
    pos.y = (pos.y + Math.cos(rad) * v * dt) % CELL;
    grid.position.x = -pos.x;
    grid.position.z = -pos.y;
    draw();
    // tilt: lean the way the real robot leans (picked up, on a ramp)
    rollNow += (roll - rollNow) * Math.min(1, dt * 8);
    pitchNow += (pitch - pitchNow) * Math.min(1, dt * 8);
    gltf.scene.rotation.set(THREE.MathUtils.degToRad(pitchNow * PITCH_SIGN), 0, THREE.MathUtils.degToRad(rollNow * ROLL_SIGN));
    gltf.scene.position.y = 0.02 * Math.min(1, (Math.abs(rollNow) + Math.abs(pitchNow)) / 30);   // lifts off the floor as it tips
    // stopped by the bumper: the strips flash red, like the real lights
    const dark = blocked && Math.floor(now / FLASH_MS) % 2;
    [0, 1].forEach((i) => setLed(i, blocked ? (dark ? [0, 0, 0] : [1, 0, 0]) : lights[i]));
    const settled = !speed && !turn && !blocked && Math.abs(wrap(target - shown)) < 0.05
      && Math.abs(roll - rollNow) + Math.abs(pitch - pitchNow) < 0.2;
    if (!settled) run();
  }
  function run() {
    if (!frame) frame = requestAnimationFrame(tick);
  }

  new ResizeObserver(place).observe(canvas);
  [0, 1].forEach((i) => setLed(i, [0, 0, 0]));
  place();

  return {
    /** t = parsed telemetry (telemetry.js). */
    update(t) {
      if (zero === null) { zero = t.heading; shown = 0; }
      target = wrap(t.heading - zero);
      speed = t.speed; turn = t.turn;
      blocked = t.blocked;
      lights = [t.left, t.right];
      if (!zoned) zones = [null, t.distance, t.distance, t.distance, null];   // older robot code: one distance
      showWalls();
      newsAt = performance.now();
      if (!frame) lastFrame = newsAt;
      run();
    },
    /** The robot went away. The next one starts facing away from you again. */
    reset() {
      zero = null; target = shown = 0; speed = turn = 0; blocked = false;
      zones = [null, null, null, null, null]; zoned = false;
      lights = [[0, 0, 0], [0, 0, 0]];
      roll = pitch = 0;
      showWalls();
      run();
    },
    /** s = parsed sensors packet (telemetry.js): five distances, tilt. */
    sensors(s) {
      zones = s.zones; zoned = true;
      // small leans are just the floor and the sensor's noise
      roll = Math.abs(s.roll) < 4 ? 0 : Math.max(-60, Math.min(60, s.roll));
      pitch = Math.abs(s.pitch) < 4 ? 0 : Math.max(-60, Math.min(60, s.pitch));
      showWalls();
      run();
    },
    /** Call the way the robot points right now "away from me". */
    recentre() {
      if (zero === null) return;
      zero = wrap(zero + target);
      target = 0; shown = 0;
      run();
    },
    resize: place,
  };
}
