"""Builds the printable LEGO-compatible holders for Seeed Grove modules (models/grove/*.stl, mm).

    /Applications/Blender.app/Contents/MacOS/Blender -b --python models/build_grove_holders.py
    ... -- --preview DIR      also renders a PNG of each part into DIR

Each holder is a LEGO brick underneath (it presses onto the studs of the robot's top plate) and a
tray for one Grove board on top. See models/grove/README.md for what to print and how.

Everything is made here from the numbers below; nothing is imported. To change the fit on your
printer, change FIT and build again.
"""
import bpy, bmesh, os, sys
from math import pi, cos, sin
from mathutils import Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "grove")

# ---------- LEGO, mm ----------
P = 8.0                 # stud pitch
STUD_D = 4.9            # our studs (the printed baseplate's are 4.95, real LEGO 4.8)
STUD_H = 1.8
GAP = 0.1               # each side of a brick stops this short of the grid line
FIT = 0.0               # + makes the stud sockets looser, - tighter (try 0.05 steps)
SKIRT = 1.5             # wall of the brick underneath; studs press against its inside
SOCKET = 2.0            # how deep the studs go in
FLOOR = 1.4             # solid layer over the studs = floor of the tray
TUBE_OUT = 6.3          # tube between four studs
TUBE_IN = 3.9           # leaves a 1.2 wall, three passes of a 0.4 nozzle
CHAMFER = 0.3           # bottom edges of the sockets lean back: room for a squashed first layer

# ---------- Grove boards, mm ----------
PCB_T = 1.6
UNIT = 20.0             # a Grove 1x1 board is 20 x 20, 1x2 is 20 x 40, 2x2 is 40 x 40
SLACK = 0.15            # room around the board, each side
EAR_R = 2.0             # the mounting holes sit on the board's edge inside a round ear this big
STANDOFF = 2.6          # room under the board for solder pins
PLUG_HALF = 7.5         # the low part of the end wall, for a sideways Grove plug (11.9 wide)

X = 1.5 * P - GAP                   # every holder is 3 studs wide: half width 11.9
XI = UNIT / 2 + SLACK               # inside face of the side walls
ZF = SOCKET + FLOOR                 # top of the floor
ZS = ZF + STANDOFF                  # the board's underside rests here
ZB = ZS + PCB_T + 0.2               # underside of the clips
ZT = ZB + 1.2                       # top of the walls
ARM_T = 1.0                         # springy bit of wall that carries a clip
BARB = 0.45                         # how far a clip reaches over the board


# ---------- small solid-modelling helpers ----------
def obj_from(bm, name="part"):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def box(x0, x1, y0, y1, z0, z1):
    x0, x1, y0, y1, z0, z1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1), min(z0, z1), max(z0, z1)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x = x0 + (v.co.x + 0.5) * (x1 - x0)
        v.co.y = y0 + (v.co.y + 0.5) * (y1 - y0)
        v.co.z = z0 + (v.co.z + 0.5) * (z1 - z0)
    return obj_from(bm)


def cyl(x, y, r, z0, z1, n=48):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=n, radius1=r, radius2=r, depth=z1 - z0)
    for v in bm.verts:
        v.co.x += x
        v.co.y += y
        v.co.z += (z0 + z1) / 2
    return obj_from(bm)


def turned(x, y, profile, n=48):
    """A solid of revolution about the vertical line at (x, y). profile: (radius, z) going up."""
    bm = bmesh.new()
    rings = [[bm.verts.new((x + r * cos(2 * pi * k / n), y + r * sin(2 * pi * k / n), z)) for k in range(n)]
             for r, z in profile]
    bm.faces.new(rings[0])
    bm.faces.new(rings[-1])
    for lo, hi in zip(rings, rings[1:]):
        for k in range(n):
            j = (k + 1) % n
            bm.faces.new((lo[k], lo[j], hi[j], hi[k]))
    return obj_from(bm)


def flared(hx, hy, z0, z1, grow):
    """A box, half sizes hx, hy at z1, wider by grow each side at z0 (below)."""
    bm = bmesh.new()
    lo = [bm.verts.new((sx * (hx + grow), sy * (hy + grow), z0)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    hi = [bm.verts.new((sx * hx, sy * hy, z1)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    bm.faces.new(lo)
    bm.faces.new(hi)
    for k in range(4):
        j = (k + 1) % 4
        bm.faces.new((lo[k], lo[j], hi[j], hi[k]))
    return obj_from(bm)


def wedge(pz, t0, t1, along='y'):
    """A triangle in the x-z plane pulled out from y = t0 to t1 (or in y-z, pulled out along x)."""
    bm = bmesh.new()
    at = (lambda p, z, t: (p, t, z)) if along == 'y' else (lambda p, z, t: (t, p, z))
    a = [bm.verts.new(at(p, z, t0)) for p, z in pz]
    b = [bm.verts.new(at(p, z, t1)) for p, z in pz]
    bm.faces.new(a)
    bm.faces.new(b)
    for i in range(3):
        j = (i + 1) % 3
        bm.faces.new((a[i], a[j], b[j], b[i]))
    return obj_from(bm)


def combine(a, others, op):
    for o in others:
        m = a.modifiers.new("b", 'BOOLEAN')
        m.operation, m.object, m.solver = op, o, 'EXACT'
        bpy.context.view_layer.objects.active = a
        bpy.ops.object.modifier_apply(modifier=m.name)
        bpy.data.objects.remove(o, do_unlink=True)
    return a


def add(a, others):
    return combine(a, others, 'UNION')


def cut(a, others):
    return combine(a, others, 'DIFFERENCE')


def check(ob):
    """Printable means one closed skin: every edge shared by exactly two faces."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bad = sum(1 for e in bm.edges if not e.is_manifold)
    vol = bm.calc_volume()
    bm.free()
    if bad:
        raise SystemExit("%s: %d open edges" % (ob.name, bad))
    return vol


# ---------- the LEGO brick underneath ----------
def brick_base(nx, ny):
    """Solid slab nx x ny studs, ZF high. Returns (slab, things to cut, things to add after)."""
    hx, hy = nx * P / 2 - GAP, ny * P / 2 - GAP
    sk = SKIRT - FIT
    cuts = [box(-hx + sk, hx - sk, -hy + sk, hy - sk, -1, SOCKET),
            flared(hx - sk, hy - sk, -CHAMFER, CHAMFER, 2 * CHAMFER)]
    adds = []
    r = TUBE_OUT / 2 - FIT
    for i in range(nx - 1):
        for j in range(ny - 1):
            x, y = (i - (nx - 2) / 2) * P, (j - (ny - 2) / 2) * P
            t = turned(x, y, [(r - CHAMFER, 0), (r, CHAMFER), (r, SOCKET + 0.2)])
            adds.append(cut(t, [cyl(x, y, TUBE_IN / 2, -1, SOCKET + 0.1)]))
    return box(-hx, hx, -hy, hy, 0, ZF), cuts, adds


def fit_test():
    """A 2 x 2 brick bottom with two studs on top: print this first to check FIT."""
    body, cuts, adds = brick_base(2, 2)
    body = add(cut(body, cuts), adds)
    return add(body, [cyl(-4, -4, STUD_D / 2, ZF - 0.1, ZF + STUD_H), cyl(4, 4, STUD_D / 2, ZF - 0.1, ZF + STUD_H)])


# ---------- a tray for one board ----------
def cradle(length, ears, arms):
    """length: the board is 20 x length, its Grove socket at the -y end.
    ears: (x, y) of each mounting hole (they sit on the board's edge).
    arms: (side, y_root, y_free): a springy piece of side wall with a clip at its free end."""
    ny = 3 if length <= 20 else 6
    Y = ny * P / 2 - GAP
    yi = length / 2 + SLACK
    body, cuts, adds = brick_base(3, ny)
    walls = [box(s * XI, s * X, -Y, Y, ZF - 0.1, ZT) for s in (-1, 1)]
    walls.append(box(-X, X, yi, Y, ZF - 0.1, ZT))                      # far end
    walls.append(box(-X, X, -Y, -yi, ZF - 0.1, ZS))                    # socket end, low for the plug
    walls += [box(s * PLUG_HALF, s * X, -Y, -yi, ZF - 0.1, ZT) for s in (-1, 1)]
    walls.append(box(-X, X, -yi - 0.1, -yi + 1.0, ZF - 0.1, ZS))       # ledges the board rests on
    walls.append(box(-X, X, yi - 1.0, yi + 0.1, ZF - 0.1, ZS))
    n = EAR_R + SLACK
    for ex, ey in ears:
        if abs(ex) > 1:                                                # in a side wall
            s = 1 if ex > 0 else -1
            cuts.append(box(s * (XI - 0.1), s * (X + 1), ey - n, ey + n, ZS, ZT + 1))
        else:                                                          # in the far end wall
            cuts.append(box(-n, n, yi - 0.1, length / 2 + n, ZS, ZT + 1))
    for s, y_root, y_free in arms:
        d = 1 if y_free > y_root else -1
        end = y_free + d * 0.5
        cuts.append(box(s * (XI - 0.1), s * (X + 1), y_root, end, ZS - 1.0, ZS - 0.4))     # slot under
        cuts.append(box(s * (XI - 0.1), s * (X + 1), y_free, end, ZS - 1.0, ZT + 1))       # slit at the end
        cuts.append(box(s * (XI + ARM_T), s * (X + 1), y_root, end, ZS - 1.0, ZT + 1))     # make it thin
        adds.append(wedge([(s * (XI + 0.2), ZB), (s * (XI - BARB), ZB), (s * (XI + 0.2), ZT)],
                          y_free - d * 0.3, y_free - d * 2.8))
    if length > 20:                         # the end walls are thick enough to hold a lid's tabs
        for sx, sy in TABS:
            xc = sx * TAB_X
            cuts.append(box(xc - 2.2, xc + 2.2, sy * (Y - 1.3), sy * (Y + 1), ZF + 0.4, ZT + 1))
            cuts.append(box(xc - 2.2, xc + 2.2, sy * (Y - 2.0), sy * (Y - 1.2), ZF + 0.4, ZF + 1.7))
    return add(cut(add(body, walls), cuts), adds)


# ---------- a lid for the 20 x 40 tray ----------
TABS = [(sx, sy) for sx in (-1, 1) for sy in (-1, 1)]
TAB_X = 7.0
LID_WALL = 1.2


def lid(clear, holes):
    """A cap that snaps onto the 20 x 40 tray. clear: room above the board.
    holes: ('box', x0, x1, y0, y1) or ('round', x, y, radius), cut through the roof.
    Print it upside down (roof on the bed)."""
    Y = 3 * P - GAP
    inside = ZS + PCB_T + clear
    top = inside + LID_WALL
    body = box(-X, X, -Y, Y, ZT, top)
    cuts = [box(-X + LID_WALL, X - LID_WALL, -Y + LID_WALL, Y - LID_WALL, ZT - 1, inside)]
    for h in holes:
        if h[0] == 'box':
            cuts.append(box(h[1], h[2], h[3], h[4], inside - 1, top + 1))
        else:
            cuts.append(cyl(h[1], h[2], h[3], inside - 1, top + 1))
    adds = []
    for sx, sy in TABS:
        xc, face = sx * TAB_X, sy * (Y - 1.1)
        for side in (-1, 1):                # a slit each side lets the tab bend
            x0 = xc + side * 1.8
            cuts.append(box(x0, x0 + side * 0.6, sy * (Y - LID_WALL - 0.1), sy * (Y + 1), ZT - 1, ZT + 5))
        adds.append(box(xc - 1.8, xc + 1.8, face, sy * Y, ZF + 0.6, ZT + 0.2))
        adds.append(wedge([(face + sy * 0.2, ZF + 0.6), (face - sy * 0.6, ZF + 1.5), (face + sy * 0.2, ZF + 1.5)],
                          xc - 1.8, xc + 1.8, along='x'))
    return add(cut(body, cuts), adds)


E = EAR_R + SLACK + 0.5      # a clip's free end stops this far from an ear
PARTS = {
    # name: (what it is, builder)
    "fit_test_2x2": lambda: fit_test(),
    "grove_1x1_cradle": lambda: cradle(20, [(-10, 0), (10, 0)],
                                       [(s, r, f) for s in (-1, 1) for r, f in ((9.0, E), (-9.0, -E))]),
    "grove_1x2_cradle": lambda: cradle(40, [(-10, -10), (10, -10), (0, 20)],
                                       [(s, r, f) for s in (-1, 1) for r, f in ((-19.5, -10 - E), (19.5, 9.5))]),
    # Grove - Speech Recognizer: socket at the low end. Openings for the plug, the microphone,
    # the two lights and the little speaker socket (positions from Seeed's Eagle board file).
    "lid_speech_recognizer": lambda: lid(8.5, [('box', -6.5, 6.5, -19.8, -12.3), ('round', -3.4, 14.0, 3.2),
                                               ('box', 7.2, 10.4, -7.5, 0.7), ('box', 2.6, 9.6, 13.3, 19.7)]),
    # Grove - Speaker: turned round, socket at the high end (its ears are the other way about).
    # Openings for the plug, the loudness knob, and a grille over the speaker.
    "lid_speaker": lambda: lid(11.0, [('box', -6.5, 6.5, 12.3, 19.8), ('round', -5.7, 1.9, 2.4)] +
                               [('round', 0.5 + 4.4 * cos(k * pi / 3) * r, -11.1 + 4.4 * sin(k * pi / 3) * r, 1.4)
                                for r in (0, 1) for k in range(6 if r else 1)]),
}


def build_all():
    made = {}
    for name, fn in PARTS.items():
        ob = fn()
        ob.name = ob.data.name = name
        made[name] = (ob, check(ob))
    return made


if __name__ == "__main__" and bpy.app.background:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT, exist_ok=True)
    made = build_all()
    for i, (name, (ob, vol)) in enumerate(made.items()):
        if name.startswith("lid_"):         # lids print roof down: turn the file over
            ob.data.transform(Matrix.Rotation(pi, 4, 'Y'))
        ob.data.transform(Matrix.Translation((0, 0, -min(v.co.z for v in ob.data.vertices))))
        bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        bpy.ops.wm.stl_export(filepath=os.path.join(OUT, name + ".stl"), export_selected_objects=True)
        d = ob.dimensions
        print("%-18s %5.1f x %5.1f x %4.1f mm  %5.2f cm3" % (name, d.x, d.y, d.z, vol / 1000))
    if "--preview" in sys.argv:
        out = sys.argv[sys.argv.index("--preview") + 1]
        os.makedirs(out, exist_ok=True)
        scene = bpy.context.scene
        for i, (ob, _) in enumerate(made.values()):
            ob.location.x = (i - 1) * 30
        cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
        scene.collection.objects.link(cam)
        scene.camera = cam
        scene.render.engine = 'BLENDER_WORKBENCH'
        scene.display.shading.light, scene.display.shading.show_cavity = 'STUDIO', True
        scene.render.resolution_x, scene.render.resolution_y = 1600, 1000
        for tag, loc, flip in (("top", (34, -72, 66), False), ("under", (34, -72, 66), True)):
            for ob, _ in made.values():
                turned = flip != ob.name.startswith("lid_")     # lids are stored roof down
                ob.rotation_euler.y = pi if turned else 0
                ob.location.z = 22 if turned else 0
            cam.location = loc
            cam.rotation_euler = (0.85, 0, 0)
            cam.data.type, cam.data.ortho_scale = 'ORTHO', 160
            scene.render.filepath = os.path.join(out, "grove_%s.png" % tag)
            bpy.ops.render.render(write_still=True)
