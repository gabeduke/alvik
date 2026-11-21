"""Builds the printable add-ons that go with the Grove holders (models/addons/*.stl, mm).

    /Applications/Blender.app/Contents/MacOS/Blender -b --python models/build_addons.py
    ... -- --preview DIR      also renders PNGs into DIR (each part, and all of them on the robot)

  pen_holder        presses onto the plate's side studs and holds a felt pen beside a wheel
  corner_3x3        a brick with studs on an upright wall, so a Grove tray can face forward
  cable_clip_2x2    keeps Grove and Qwiic wires out of the wheels
  test_stand        the robot sits on it with its wheels in the air
  modulino_tray     a tray for one Arduino Modulino board, LEGO underneath like the Grove ones

The LEGO underside, the fit numbers and the helpers come from build_grove_holders.py: change FIT
there and build both scripts again. See models/addons/README.md for what to print and how.
"""
import bpy, bmesh, os, sys
from math import pi
from mathutils import Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_grove_holders as G
from build_grove_holders import (P, GAP, STUD_H, ZF, ZS, ZB, ZT, PCB_T, SLACK, ARM_T, BARB,
                                 box, cyl, turned, add, cut, check, brick_base, obj_from)

OUT = os.path.join(HERE, "addons")

# ---------- the robot, mm (measured on the files in reference/, see models/README.md) ----------
PLATE_TOP = 36.7        # the plate's top face between the studs, in the chassis file's z
HALF = 48.0             # the plate and the body are 96 x 96
BELLY = 10.1            # the flat underside is this far above the table


def prism(pts, t0, t1, axis='z'):
    """A flat outline pulled out into a solid. axis 'z': pts are (x, y), pulled from z = t0 to t1.
    'y': pts are (x, z). 'x': pts are (y, z)."""
    at = {'z': lambda a, b, t: (a, b, t), 'y': lambda a, b, t: (a, t, b), 'x': lambda a, b, t: (t, a, b)}[axis]
    bm = bmesh.new()
    lo = [bm.verts.new(at(a, b, t0)) for a, b in pts]
    hi = [bm.verts.new(at(a, b, t1)) for a, b in pts]
    bm.faces.new(lo)
    bm.faces.new(hi)
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((lo[i], lo[j], hi[j], hi[i]))
    return obj_from(bm)


def brick(nx, ny, on_top=(), carve=(), after=()):
    """A LEGO brick bottom nx x ny studs with things on top. on_top is joined before the stud
    sockets are cut, so anything that reaches down to z = 0 over the sockets is hollowed too."""
    body, cuts, adds, holes = brick_base(nx, ny)
    return add(cut(add(cut(add(body, list(on_top)), cuts + list(carve)), adds), holes), list(after))


# ---------- pen holder ----------
PEN_APEX = 9.5          # the corner of the V, measured from the middle of the two stud rows
PEN_V = 8.0             # how deep the V is; pens from about 8 to 19 mm across sit in it
PEN_TOP = 28.0          # the pen is held over this height
PEN_BACK = 4.0
PEN_HALF = 10.5
BAND_Z = (10.0, 22.0)   # a rubber band goes round the pen and the tower at each of these heights


def pen_centre(pen_d):
    """How far the middle of a pen this wide sits from the middle of the robot, mm."""
    return HALF - P + PEN_APEX + pen_d / 2 * 2 ** 0.5


def pen_holder():
    """2 x 4 studs on the plate's outer two stud rows, centred on the wheels. A tower stands on the
    outer row and hangs over the plate's edge; the pen sits in the V on its outside face."""
    x1 = PEN_APEX + PEN_V
    tower = box(PEN_BACK, x1, -PEN_HALF, PEN_HALF, 0, PEN_TOP)
    carve = [prism([(PEN_APEX, 0), (x1 + 1, -PEN_V - 1), (x1 + 1, PEN_V + 1)], -1, PEN_TOP + 1)]
    for z in BAND_Z:        # grooves so the bands stay at their height; sloped, so they print
        carve.append(prism([(PEN_BACK - 0.1, z - 1.5), (PEN_BACK + 1.2, z), (PEN_BACK - 0.1, z + 1.5)],
                           -PEN_HALF - 1, PEN_HALF + 1, 'y'))
        for s in (-1, 1):
            carve.append(prism([(s * (PEN_HALF + 0.1), z - 1.5), (s * (PEN_HALF - 1.0), z),
                                (s * (PEN_HALF + 0.1), z + 1.5)], PEN_BACK - 1, x1 + 1, 'x'))
    return brick(2, 4, on_top=[tower], carve=carve)


# ---------- corner: studs on an upright wall ----------
SIDE_STUD_D = 4.8       # studs printed sideways sag a little underneath, so they start smaller
WALL_FACE = 4.0         # y of the wall's front face
WALL_T = 3.6
ROW_Z = 16.0            # height of the middle row of wall studs: a 3 x 3 tray then clears the foot


def side_stud(x, z):
    """A stud lying on its side, sticking out of the wall's front face towards -y."""
    r = SIDE_STUD_D / 2 - G.FIT / 2
    s = turned(0, 0, [(r, -0.3), (r, STUD_H - 0.3), (r - 0.3, STUD_H)])
    s.data.transform(Matrix.Translation((x, WALL_FACE, z)) @ Matrix.Rotation(pi / 2, 4, 'X'))
    return s


def corner():
    """3 x 3 studs underneath, a wall standing across it with 3 x 3 studs on its front."""
    hx = 1.5 * P - GAP
    top = ROW_Z + 1.5 * P - GAP
    wall = box(-hx, hx, WALL_FACE, WALL_FACE + WALL_T, ZF - 0.1, top)
    back = WALL_FACE + WALL_T - 0.1
    braces = [prism([(back, ZF - 0.1), (hx, ZF - 0.1), (back, 20.0)], x0, x0 + 2.0, 'x')
              for x0 in (-hx, -1.0, hx - 2.0)]
    studs = [side_stud(i * P, ROW_Z + k * P) for i in (-1, 0, 1) for k in (-1, 0, 1)]
    return brick(3, 3, on_top=[wall] + braces, after=studs)


# ---------- cable clip ----------
def cable_clip():
    """2 x 2 studs underneath, a channel on top with a narrow mouth: wires go in one at a time."""
    hy = P - GAP
    inner, outer, mouth = 4.0, 5.6, 0.9
    z0, z1, z2 = ZF + 3.0, ZF + 6.2, ZF + 6.8
    sides = [box(s * inner, s * outer, -hy, hy, ZF - 0.1, z2) for s in (-1, 1)]
    lips = [prism([(s * (inner + 0.1), z0), (s * mouth, z1), (s * mouth, z2), (s * (inner + 0.1), z2)],
                  -hy, hy, 'y') for s in (-1, 1)]
    return brick(2, 2, on_top=sides, after=lips)


# ---------- test stand ----------
STAND_X, STAND_Y, STAND_H = 32.0, 24.0, 17.0    # half sizes; high enough to lift the wheels 7 mm


def test_stand():
    """A little table that fits between the wheels, under the flat part of the robot's belly."""
    w, roof = 2.4, 2.0
    body = box(-STAND_X, STAND_X, -STAND_Y, STAND_Y, 0, STAND_H)
    hollow = box(-STAND_X + w, STAND_X - w, -STAND_Y + w, STAND_Y - w, -1, STAND_H - roof)
    rib = box(-w / 2, w / 2, -STAND_Y + 1, STAND_Y - 1, 0, STAND_H - roof + 0.1)
    return add(cut(body, [hollow]), [rib])


# ---------- a tray for an Arduino Modulino ----------
# From Arduino's datasheets (the same for every Modulino): board 41 x 25.36 x 1.6 mm, four 3.2 mm
# holes 32 mm apart along it and 16 mm across it, a Qwiic socket in the middle of each short end.
MOD_L, MOD_W = 41.0, 25.36
MOD_HOLES = [(sx * 8.0, sy * 16.0) for sx in (-1, 1) for sy in (-1, 1)]
MOD_PEG = 2.8           # goes through a 3.2 mm hole
MOD_PLUG = 5.5          # half width of the low part of each end wall, for the Qwiic plug


def modulino_tray():
    """4 x 6 studs. The board sits on four posts, a peg through each hole, and four clips on
    springy pieces of the side walls hold it down, as on the Grove trays."""
    hx, hy = 2 * P - GAP, 3 * P - GAP
    xi, yi = MOD_W / 2 + SLACK, MOD_L / 2 + SLACK
    walls = [box(s * xi, s * hx, -hy, hy, ZF - 0.1, ZT) for s in (-1, 1)]
    for e in (-1, 1):
        walls.append(box(-hx, hx, e * yi, e * hy, ZF - 0.1, ZS))
        walls += [box(s * MOD_PLUG, s * hx, e * yi, e * hy, ZF - 0.1, ZT) for s in (-1, 1)]
    carve, after = [], []
    for x, y in MOD_HOLES:
        walls.append(cyl(x, y, 2.9, ZF - 0.1, ZS))
        r = MOD_PEG / 2
        after.append(turned(x, y, [(r, ZS - 0.1), (r, ZS + PCB_T), (r - 0.4, ZS + PCB_T + 0.8)]))
    for s in (-1, 1):
        for y_root, y_free in ((19.5, 8.0), (-19.5, -8.0)):
            d = 1 if y_free > y_root else -1
            end = y_free + d * 0.5
            carve.append(box(s * (xi - 0.1), s * (hx + 1), y_root, end, ZS - 1.0, ZS - 0.4))   # slot under
            carve.append(box(s * (xi - 0.1), s * (hx + 1), y_free, end, ZS - 1.0, ZT + 1))     # slit at the end
            carve.append(box(s * (xi + ARM_T), s * (hx + 1), y_root, end, ZS - 1.0, ZT + 1))   # make it thin
            after.append(prism([(s * (xi + 0.2), ZB), (s * (xi - BARB), ZB), (s * (xi + 0.2), ZT)],
                               y_free - d * 0.3, y_free - d * 2.8, 'y'))
    return brick(4, 6, on_top=walls, carve=carve, after=after)


PARTS = {
    "pen_holder": pen_holder,
    "corner_3x3": corner,
    "cable_clip_2x2": cable_clip,
    "test_stand": test_stand,
    "modulino_tray": modulino_tray,
}
ROOF_DOWN = {"test_stand"}      # printed upside down: the flat top goes on the bed


def build_all():
    made = {}
    for name, fn in PARTS.items():
        ob = fn()
        ob.name = ob.data.name = name
        made[name] = (ob, check(ob))
    return made


# ---------- pictures ----------
def render(scene, cam, path, loc, rot, scale):
    cam.location, cam.rotation_euler = loc, rot
    cam.data.type, cam.data.ortho_scale = 'ORTHO', scale
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def load_reference():
    """The chassis and the plate as they sit on the robot (chassis file's axes: front = +y)."""
    ref = os.path.join(HERE, "reference")

    def load(f):
        before = set(bpy.data.objects)
        bpy.ops.wm.stl_import(filepath=os.path.join(ref, f))
        return (set(bpy.data.objects) - before).pop()
    body = load("alvik_reference_design.stl")
    plate = load("lego_baseplate_12x12.stl")
    bm = bmesh.new()
    bm.from_mesh(plate.data)
    far = [v for v in bm.verts if v.co.x > 45]          # the two loose pins beside it on the bed
    bmesh.ops.delete(bm, geom=far, context='VERTS')
    xs, ys, zs = ([v.co[k] for v in bm.verts] for k in range(3))
    bmesh.ops.translate(bm, verts=bm.verts, vec=(-(min(xs) + max(xs)) / 2, -(min(ys) + max(ys)) / 2,
                                                  27.1 - min(zs)))
    bm.to_mesh(plate.data)
    bm.free()
    return body, plate


def pictures(made, out):
    os.makedirs(out, exist_ok=True)
    scene = bpy.context.scene
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.world = bpy.data.worlds.new("Paper")
    scene.world.color = (0.82, 0.84, 0.87)
    scene.render.engine = 'BLENDER_WORKBENCH'
    sh = scene.display.shading
    sh.light, sh.show_cavity, sh.color_type = 'STUDIO', True, 'OBJECT'
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1100
    colours = {"pen_holder": (1.0, 0.45, 0.05, 1), "corner_3x3": (0.1, 0.45, 0.9, 1),
               "cable_clip_2x2": (0.9, 0.75, 0.05, 1), "test_stand": (0.55, 0.3, 0.8, 1),
               "modulino_tray": (0.9, 0.2, 0.35, 1)}
    obs = {name: ob for name, (ob, _) in made.items()}
    for name, ob in obs.items():
        ob.color = colours[name]
    # 1. the parts in a row, from above and from below
    xs = {"pen_holder": -95, "corner_3x3": -55, "cable_clip_2x2": -22, "modulino_tray": 15, "test_stand": 80}
    for name, ob in obs.items():
        ob.location = (xs[name], 0, 0)
    render(scene, cam, os.path.join(out, "addons_top.png"), (0, -150, 135), (0.85, 0, 0), 240)
    for ob in obs.values():
        ob.rotation_euler.y, ob.location.z = pi, 30
    render(scene, cam, os.path.join(out, "addons_under.png"), (0, -150, 135), (0.85, 0, 0), 240)
    # 2. on the robot (chassis file's axes: front = +y, the robot's right = +x)
    body, plate = load_reference()
    body.color, plate.color = (0.12, 0.13, 0.15, 1), (0.0, 0.5, 0.2, 1)
    pen_d = 10.0
    place = {"pen_holder": ((HALF - P, 0, PLATE_TOP), 0), "corner_3x3": ((4, 36, PLATE_TOP), pi),
             "cable_clip_2x2": ((-24, -40, PLATE_TOP), 0), "modulino_tray": ((-16, -8, PLATE_TOP), 0),
             "test_stand": ((0, 0, -STAND_H), 0)}
    for name, (loc, turn) in place.items():
        obs[name].location, obs[name].rotation_euler = loc, (0, 0, turn)
    pen = [cyl(pen_centre(pen_d), 0, pen_d / 2, -BELLY + 3, 95),
           turned(pen_centre(pen_d), 0, [(0.6, -BELLY), (pen_d / 2, -BELLY + 3.1)])]
    for ob in pen:
        ob.color = (0.85, 0.1, 0.15, 1)
    tray = G.PARTS["grove_1x1_cradle"]()               # a Grove tray pressed onto the corner's wall
    tray.color = (0.95, 0.9, 0.2, 1)
    tray.data.transform(Matrix.Translation((4, 36 - WALL_FACE, PLATE_TOP + ROW_Z))
                        @ Matrix.Rotation(-pi / 2, 4, 'X'))
    obs["test_stand"].hide_render = True
    render(scene, cam, os.path.join(out, "addons_on_robot.png"), (150, 150, 190), (0.9, 0, 2.36), 190)
    render(scene, cam, os.path.join(out, "addons_on_robot_front.png"), (0, 240, 40), (pi / 2, 0, pi), 190)
    obs["test_stand"].hide_render = False              # on the stand, wheels in the air, no pen
    for ob in pen:
        ob.hide_render = True
    render(scene, cam, os.path.join(out, "addons_on_stand.png"), (240, 0, 25), (pi / 2, 0, pi / 2), 190)


if __name__ == "__main__" and bpy.app.background:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT, exist_ok=True)
    made = build_all()
    for name, (ob, vol) in made.items():
        if name in ROOF_DOWN:
            ob.data.transform(Matrix.Rotation(pi, 4, 'Y'))
        ob.data.transform(Matrix.Translation((0, 0, -min(v.co.z for v in ob.data.vertices))))
        bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        bpy.ops.wm.stl_export(filepath=os.path.join(OUT, name + ".stl"), export_selected_objects=True)
        d = ob.dimensions
        print("%-16s %5.1f x %5.1f x %4.1f mm  %5.2f cm3" % (name, d.x, d.y, d.z, vol / 1000))
    if "--preview" in sys.argv:
        for name in ROOF_DOWN:                          # back the right way up for the pictures
            ob = made[name][0]
            ob.data.transform(Matrix.Rotation(pi, 4, 'Y'))
            ob.data.transform(Matrix.Translation((0, 0, -min(v.co.z for v in ob.data.vertices))))
        pictures(made, sys.argv[sys.argv.index("--preview") + 1])
