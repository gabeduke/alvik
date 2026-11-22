// The 3D Alvik on the remote: a live copy of the real robot, fed by telemetry (telemetry.js).
// It turns with the robot's heading, its wheels spin, its light strips take the LED colours. What
// the distance sensor reads hovers in front of it as a cloud of points, and what the bumper makes
// of that glows as heat. It leans and rises when the real one is tipped or picked up, the floor under it takes the colour the robot sees there, and
// three dots at its nose show what the line sensors see. (How a reading becomes a colour or a
// height is in sensing.js.)
//
//   const twin = await createTwin(canvas);      // loads three.js and models/alvik.glb
//   twin.update(t);                             // t = a parsed telemetry packet
//   twin.sensors(s);                            // s = a parsed sensors packet (five raw distances, tilt)
//   twin.under(u);                              // u = a parsed under-the-robot packet (lines, floor colour, height)
//   twin.reset();                               // robot went away: stand still, lights off
//   twin.recentre();                            // "the robot is pointing away from me right now"
//   twin.show({ cloud: false, heat: false });   // leave some sensors out (the lessons add them one at a time)
//
// The model (models/build_alvik_web.py) is in metres, faces +Z, left = +X, with parts named
// Body, Baseplate, WheelL, WheelR, LedL, LedR, Tof. The camera sits behind and above it, so a robot
// at heading 0 drives away from you, like the real one when you stand behind it.
// Draws only when something changes, so an idle page costs nothing.
import * as THREE from "three";
import { GLTFLoader } from "./vendor/three/loaders/GLTFLoader.js";
import { VIEW_CM, ZONES, ease, wrap, newHeat, easeHeat, heatAt, lineShade, newPose, poseTilt, poseLift, poseReset, newCompass, compassNews, compassStep,
  newCloud, cloudAdd, cloudAlpha, ROW_BOTTOM, ROW_FRONT, ROW_TOP } from "./sensing.js";

const WHEEL_R = 0.017, TRACK = 0.0895;          // metres: wheel radius, distance between the wheels
const NOSE = 0.048;                             // front face, from the middle
const ZONE_DEG = 18;                            // the five distance zones are drawn this far apart
const ROLL_SIGN = 1, PITCH_SIGN = 1;            // flip if the 3D robot tips the wrong way (checked on the real one)
const FLASH_MS = 120;                           // blink of the strips while the bumper holds the robot
const STALE_MS = 500;                           // no news for this long: stop the wheels
const TILT_RATE = 12, LIFT_RATE = 7, FLOOR_RATE = 6;   // per second: leaning, rising, the floor's colour
const LIFT_M = 0.06;                            // metres in the picture for a robot held high up
// the heat in front: columns across, and rows from the floor at the robot's nose up to the top edge
const HEAT_COLS = ZONES * 8 + 1;
const HEAT_ROWS = [{ y: 0.0012, foot: false, a: 0 }, { y: 0.0012, foot: true, a: 0.85 }, { y: 0.026, foot: true, a: 0.7 }, { y: 0.058, foot: true, a: 0 }];
const EYE_X = 0.013, EYE_Z = 0.036;             // metres: the line sensors, apart and ahead of the middle
const CLOUD_Y = { [ROW_BOTTOM]: 0.004, [ROW_FRONT]: 0.024, [ROW_TOP]: 0.047 };   // metres up: where each row's points hover
const CLOUD_DOT = 0.014;                        // metres across
const BG = 0x1b1630, FLOOR = 0x2a2347, GRID = 0x4a3f7c, CELL = 0.05;
const AZIMUTH = 0.42, ELEVATION = 0.6;          // camera: radians round to the robot's right, and up

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

  // What the bumper makes of the distance sensor (the robot's averaged "something is this far
  // ahead"): one soft sheet of heat across the middle zones. It lies on the floor from the robot's
  // nose out to where the thing is, and stands up there, fading out at the top (sensing.js).
  const heatGeo = new THREE.BufferGeometry();
  const heatPos = new THREE.BufferAttribute(new Float32Array(HEAT_COLS * HEAT_ROWS.length * 3), 3);
  const heatCol = new THREE.BufferAttribute(new Float32Array(HEAT_COLS * HEAT_ROWS.length * 4), 4);
  heatGeo.setAttribute("position", heatPos);
  heatGeo.setAttribute("color", heatCol);
  const quads = [];
  for (let c = 0; c < HEAT_COLS - 1; c++) for (let j = 0; j < HEAT_ROWS.length - 1; j++) {
    const a = c * HEAT_ROWS.length + j, b = a + HEAT_ROWS.length;
    quads.push(a, b, a + 1, a + 1, b, b + 1);
  }
  heatGeo.setIndex(quads);
  const heatMesh = new THREE.Mesh(heatGeo, new THREE.MeshBasicMaterial(
    { vertexColors: true, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
  heatMesh.frustumCulled = false;               // its shape changes all the time
  heatMesh.renderOrder = 3;                     // over the patch of floor and the shadow
  robot.add(heatMesh);

  // What the distance sensor really reads: a cloud of points, one for every reading, that fade
  // after a moment. Floor bounce and blips are all there; the robot's bumper sorts them out.
  const cloud = newCloud();
  const cloudPos = new THREE.BufferAttribute(new Float32Array(cloud.size * 3), 3);
  const cloudCol = new THREE.BufferAttribute(new Float32Array(cloud.size * 4), 4);
  const cloudGeo = new THREE.BufferGeometry();
  cloudGeo.setAttribute("position", cloudPos);
  cloudGeo.setAttribute("color", cloudCol);
  const dot = document.createElement("canvas");
  dot.width = dot.height = 64;
  const pen = dot.getContext("2d"), glow = pen.createRadialGradient(32, 32, 0, 32, 32, 32);
  glow.addColorStop(0, "rgba(255,255,255,1)");
  glow.addColorStop(0.35, "rgba(255,255,255,.75)");
  glow.addColorStop(1, "rgba(255,255,255,0)");
  pen.fillStyle = glow;
  pen.fillRect(0, 0, 64, 64);
  const cloudMesh = new THREE.Points(cloudGeo, new THREE.PointsMaterial({
    size: CLOUD_DOT, map: new THREE.CanvasTexture(dot), vertexColors: true, transparent: true,
    depthWrite: false, blending: THREE.AdditiveBlending }));
  cloudMesh.frustumCulled = false;
  cloudMesh.renderOrder = 4;
  robot.add(cloudMesh);

  // Under the robot. A round patch of floor in the colour the robot sees there (with a clear edge,
  // so it is not taken for heat), and its shadow, which stays on the floor when the robot is picked up.
  function softDisc(full, edge, color) {        // a disc that is solid out to `full` and fades to nothing at `edge`
    const n = 48, pos = [0, 0, 0], col = [1, 1, 1, 1], idx = [];
    for (let i = 0; i < n; i++) {
      const a = i / n * Math.PI * 2, x = Math.sin(a), z = Math.cos(a);
      pos.push(x * full, 0, z * full, x * edge, 0, z * edge);
      col.push(1, 1, 1, 1, 1, 1, 1, 0);
      const p = 1 + i * 2, q = 1 + ((i + 1) % n) * 2;
      idx.push(0, p, q, p, p + 1, q, q, p + 1, q + 1);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.Float32BufferAttribute(col, 4));
    geo.setIndex(idx);
    return new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, vertexColors: true, transparent: true, opacity: 0, depthWrite: false }));
  }
  const patch = softDisc(0.084, 0.092, 0xffffff);
  patch.position.y = 0.0002;                    // under the grid lines
  patch.visible = false;
  patch.renderOrder = 1;
  scene.add(patch);
  const shadow = softDisc(0.03, 0.062, 0x05040c);
  shadow.position.y = 0.0008;
  shadow.renderOrder = 2;                       // on top of the patch
  scene.add(shadow);

  // The three line sensors under the nose, drawn through the body so you can always see them:
  // a ring, filled as bright as the floor each one sees (dark over a black line).
  const eyes = [0, 1, 2].map((i) => {
    const eye = new THREE.Group();
    const seen = { depthTest: false, depthWrite: false, transparent: true };
    const fill = new THREE.Mesh(new THREE.CircleGeometry(0.0042, 20), new THREE.MeshBasicMaterial(seen));
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.0042, 0.0058, 24), new THREE.MeshBasicMaterial({ ...seen, color: 0x8fd0ff }));
    fill.renderOrder = ring.renderOrder = 5;
    eye.add(fill, ring);
    eye.rotation.x = -Math.PI / 2;              // flat, facing up
    eye.position.set((1 - i) * EYE_X, 0.004, EYE_Z);       // the robot's left is +X
    eye.visible = false;
    gltf.scene.add(eye);                        // so they lean and rise with the body
    return { eye, fill: fill.material };
  });

  // ---------- state ----------
  const head = newCompass();                    // heading in degrees, as drawn (sensing.js keeps the lag down)
  let latest = 0, zero = null;                  // the robot's own heading from the last packet, and what counts as 0
  let speed = 0, turn = 0;                      // cm/s, deg/s
  let zones = [null, null, null, null, null], blocked = false;   // cm, left to right: what the bumper reacts to
  const heat = newHeat();                       // the heat as drawn: it follows zones
  let lights = [[0, 0, 0], [0, 0, 0]];
  let roll = 0, pitch = 0, rollNow = 0, pitchNow = 0;      // degrees: latest from the robot, and drawn
  let lift = 0, liftNow = 0;                    // 0 on the floor .. 1 held high: latest, and drawn
  const pose = newPose();                       // the readings behind roll, pitch and lift, steadied (sensing.js)
  let ground = null, patchNow = 0;              // the floor's colour [r, g, b] (null = not known), and how much of the patch shows
  const groundNow = [0, 0, 0];
  let lines = [null, null, null];               // line sensors, left to right: raw readings
  let newsAt = 0, lastFrame = 0, frame = 0, small = false;
  // which sensors are drawn: the cloud of raw readings, the bumper's heat, and everything that
  // looks down or feels the robot move (floor colour, line sensors, picked up, tipped)
  const on = { cloud: true, heat: true, under: true };
  const pos = new THREE.Vector2();              // how far the floor has slid (x, z), metres
  const tint = new THREE.Color();

  const gapMax = () => (small ? 0.05 : 0.11);   // metres in the picture for a wall 30 cm away

  function place() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    small = Math.min(w, h) < 130;
    // camera: behind the robot, a little to its right and above. It must fit the circle the heat
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

  // The heat, as it is right now. It is drawn closer than real, so it fits in the picture: 30 cm
  // away is at the edge of the view.
  function showHeat() {
    const gap = gapMax(), rows = HEAT_ROWS.length;
    for (let c = 0; c < HEAT_COLS; c++) {
      const u = -0.5 + c * ZONES / (HEAT_COLS - 1);
      const h = heatAt(heat, u, blocked);
      const r = NOSE + 0.006 + gap * Math.min(h.cm, VIEW_CM) / VIEW_CM;
      const a = THREE.MathUtils.degToRad(((ZONES - 1) / 2 - u) * ZONE_DEG);   // the robot's left is +X
      tint.setRGB(h.rgb[0], h.rgb[1], h.rgb[2], THREE.SRGBColorSpace);
      HEAT_ROWS.forEach((row, j) => {
        const at = row.foot ? r : NOSE;
        heatPos.setXYZ(c * rows + j, Math.sin(a) * at, row.y, Math.cos(a) * at);
        heatCol.setXYZW(c * rows + j, tint.r, tint.g, tint.b, h.alpha * row.a);
      });
    }
    heatPos.needsUpdate = heatCol.needsUpdate = true;
  }

  // The point cloud, at the same scale as the heat. Each point fades with age.
  function showCloud(now) {
    const gap = gapMax();
    tint.setRGB(0.56, 0.84, 1, THREE.SRGBColorSpace);
    for (let i = 0; i < cloud.size; i++) {
      const p = cloud.points[i], alpha = p ? cloudAlpha(p, now) : 0;
      if (alpha) {
        const r = NOSE + 0.006 + gap * Math.min(p.cm, VIEW_CM) / VIEW_CM;
        const a = THREE.MathUtils.degToRad(((ZONES - 1) / 2 - p.u) * ZONE_DEG);
        cloudPos.setXYZ(i, Math.sin(a) * r, CLOUD_Y[p.row] + p.up, Math.cos(a) * r);
      }
      cloudCol.setXYZW(i, tint.r, tint.g, tint.b, alpha);
    }
    cloudPos.needsUpdate = cloudCol.needsUpdate = true;
  }

  // Under the robot: the patch of floor in the colour it sees, the shadow, and the line sensors.
  function showUnder(dt) {
    const want = ground ? 1 : 0;
    if (ground) for (let i = 0; i < 3; i++) groundNow[i] = patchNow < 0.02 ? ground[i] : groundNow[i] + (ground[i] - groundNow[i]) * ease(dt, FLOOR_RATE);
    patchNow += (want - patchNow) * ease(dt, FLOOR_RATE);
    if (Math.abs(want - patchNow) < 0.01) patchNow = want;
    patch.visible = patchNow > 0;
    patch.material.opacity = 0.85 * patchNow;
    patch.material.color.setRGB(groundNow[0], groundNow[1], groundNow[2], THREE.SRGBColorSpace);
    shadow.scale.setScalar(1 + 0.35 * liftNow);                // higher up: a wider, fainter shadow
    shadow.material.opacity = 0.65 - 0.15 * liftNow;
    eyes.forEach(({ eye, fill }, i) => {
      const shade = lineShade(lines[i]);
      eye.visible = shade !== null;
      if (shade !== null) fill.color.setRGB(0.05 + 0.95 * shade, 0.05 + 0.95 * shade, 0.08 + 0.92 * shade, THREE.SRGBColorSpace);
    });
    return patchNow !== want || (ground !== null && ground.some((v, i) => Math.abs(v - groundNow[i]) > 0.01));
  }

  function draw() { renderer.render(scene, camera); }

  function tick(now) {
    frame = 0;
    const dt = Math.min((now - lastFrame) / 1000, 0.1);
    lastFrame = now;
    if (now - newsAt > STALE_MS) { speed = 0; turn = 0; }
    const turning = compassStep(head, turn, dt);
    const rad = THREE.MathUtils.degToRad(head.shown);
    robot.rotation.y = rad;
    const v = speed / 100, w = THREE.MathUtils.degToRad(turn);
    wheels[0].rotation.x += (v - w * TRACK / 2) / WHEEL_R * dt;       // left wheel
    wheels[1].rotation.x += (v + w * TRACK / 2) / WHEEL_R * dt;
    pos.x = (pos.x + Math.sin(rad) * v * dt) % CELL;
    pos.y = (pos.y + Math.cos(rad) * v * dt) % CELL;
    grid.position.x = -pos.x;
    grid.position.z = -pos.y;
    // tilt and height: lean the way the real robot leans, and rise when it is picked up
    rollNow += (roll - rollNow) * ease(dt, TILT_RATE);
    pitchNow += (pitch - pitchNow) * ease(dt, TILT_RATE);
    liftNow += (lift - liftNow) * ease(dt, LIFT_RATE);
    if (Math.abs(lift - liftNow) < 0.002) liftNow = lift;
    gltf.scene.rotation.set(THREE.MathUtils.degToRad(pitchNow * PITCH_SIGN), 0, THREE.MathUtils.degToRad(rollNow * ROLL_SIGN));
    gltf.scene.position.y = LIFT_M * liftNow
      + 0.02 * Math.min(1, (Math.abs(rollNow) + Math.abs(pitchNow)) / 30);     // and clear of the floor as it tips
    const heating = easeHeat(heat, zones, dt);
    showHeat();
    showCloud(now);                             // (it fades in steps, as packets come in: no need to keep drawing for it)
    const colouring = showUnder(dt);
    // stopped by the bumper: the strips flash red, like the real lights
    const dark = blocked && Math.floor(now / FLASH_MS) % 2;
    [0, 1].forEach((i) => setLed(i, blocked ? (dark ? [0, 0, 0] : [1, 0, 0]) : lights[i]));
    draw();
    const settled = !speed && !turn && !blocked && !turning && !heating && !colouring && liftNow === lift
      && Math.abs(roll - rollNow) + Math.abs(pitch - pitchNow) < 0.2;
    if (!settled) run();
  }
  function run() {
    if (!frame) frame = requestAnimationFrame(tick);
  }
  function wake() {                             // news came in: start drawing again, from now
    if (!frame) lastFrame = performance.now();
    run();
  }

  new ResizeObserver(place).observe(canvas);
  [0, 1].forEach((i) => setLed(i, [0, 0, 0]));
  showHeat();
  showCloud(0);
  showUnder(0);
  place();

  return {
    /** t = parsed telemetry (telemetry.js). */
    update(t) {
      if (zero === null) { zero = t.heading; head.shown = 0; }
      latest = t.heading;
      compassNews(head, wrap(t.heading - zero), t.turn);
      speed = t.speed; turn = t.turn;
      blocked = t.blocked;
      lights = [t.left, t.right];
      zones = [null, t.distance, t.distance, t.distance, null];   // what the bumper sees ahead: the middle three zones
      newsAt = performance.now();
      wake();
    },
    /** The robot went away. The next one starts facing away from you again. */
    reset() {
      zero = null; head.target = head.shown = 0; speed = turn = 0; blocked = false;
      zones = [null, null, null, null, null];
      cloud.points.length = 0; cloud.next = 0;
      lights = [[0, 0, 0], [0, 0, 0]];
      roll = pitch = 0; poseReset(pose);
      lift = 0; ground = null; lines = [null, null, null];
      wake();
    },
    /** s = parsed sensors packet (telemetry.js): five raw distances, tilt. */
    sensors(s) {
      const now = performance.now();
      if (on.cloud) s.zones.forEach((cm, i) => cloudAdd(cloud, i + (Math.random() - 0.5) * 0.7, ROW_FRONT, cm, now, (Math.random() - 0.5) * 0.01));
      // small leans, and jolts from a floor that isn't quite flat, are left out (poseTilt)
      if (on.under) { poseTilt(pose, s.roll, s.pitch); roll = pose.roll; pitch = pose.pitch; }
      wake();
    },
    /** u = parsed under-the-robot packet (telemetry.js): line sensors, the floor's colour, how far down the floor is. */
    under(u) {
      if (on.under) { lines = u.lines; ground = u.floor; poseLift(pose, u.bottom); lift = pose.lift; }
      // the sensor's low and high rows, each one reading for the whole width
      const now = performance.now();
      if (on.cloud) {
        cloudAdd(cloud, 2 + (Math.random() - 0.5) * 1.6, ROW_BOTTOM, u.bottom, now);
        cloudAdd(cloud, 2 + (Math.random() - 0.5) * 2.4, ROW_TOP, u.top, now, (Math.random() - 0.5) * 0.008);
      }
      wake();
    },
    /** Call the way the robot points right now "away from me". */
    recentre() {
      if (zero === null) return;
      zero = latest;
      head.target = head.shown = 0;
      wake();
    },
    /** Draw only some of the sensors: { cloud, heat, under }, each true or false (left out = as it was). */
    show(layers) {
      for (const k of Object.keys(on)) if (k in layers) on[k] = !!layers[k];
      heatMesh.visible = on.heat;
      cloudMesh.visible = on.cloud;
      if (!on.cloud) { cloud.points.length = 0; cloud.next = 0; }
      if (!on.under) { lines = [null, null, null]; ground = null; lift = 0; roll = pitch = 0; poseReset(pose); }
      wake();
    },
    resize: place,
  };
}
