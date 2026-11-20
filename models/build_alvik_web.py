"""Builds docs/models/alvik.glb, the 3D Alvik shown on the web remote (issue #6).

    /Applications/Blender.app/Contents/MacOS/Blender -b --python models/build_alvik_web.py
    ... -- --preview DIR      also renders a few PNGs of the result into DIR

What goes in (see models/README.md for sources and licences):
  reference/alvik_reference_design.stl   Arduino's chassis, one solid, mm, front = +Y, floor at z = -10.1
  reference/lego_baseplate_12x12.stl     the printed LEGO baseplate, mm, as laid out on the print bed

What comes out, in metres, origin on the floor between the wheels. In Blender the robot faces -Y with
+Z up, so in the GLB (Y up) it faces +Z and its left is +X:
  Body        the chassis (caster ball included), dark
  Baseplate   the LEGO plate, sitting on the chassis
  WheelL/R    made here; origin on the axle, spin about X. They are a little bigger than the wheel
              discs moulded into the chassis solid, which stay hidden inside them.
  LedL/R      made here; a light strip along each side under the plate, wrapping both corners.
              The real LEDs sit under the plate at (+-31.8, 0) mm and glow through the see-through
              body; the strips stand in for that glow. Each has its own material (LedL, LedR).
  Tof         made here; the distance sensor on the front face

The viewer (docs/twin.js) finds the parts by these names.
"""
import bpy, bmesh, os, sys
from math import pi, cos, sin, radians
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, "reference")
GLB = os.path.join(HERE, "..", "docs", "models", "alvik.glb")
COPYRIGHT = ("Chassis: Arduino Alvik reference design (docs.arduino.cc/hardware/alvik). "
             "Baseplate: 'Arduino Alvik top baseplate (LEGO/DUPLO versions)' by GiulioT, "
             "makerworld.com/en/models/1298936, CC BY-NC-SA. This model: CC BY-NC-SA.")
MM = 0.001

# ---------- measured on the chassis STL (mm, STL axes) ----------
FLOOR_Z = -10.1          # lowest point of the wheel discs and the caster
TOP_Z = 27.1             # top face; the plate sits on it
HALF = 48.0              # the body is 96 x 96
WHEEL_X, WHEEL_Z, WHEEL_R = 44.75, 6.9, 17.0     # disc: x 41.5..48, centre height, radius
# the plate's board cutout (x -24..24, y 9.5..35.5) and two slots (x +-40.5..45.5, y -21.7..-13.7)
# line up with the same shapes on the chassis top when the plate's outline is centred on the body

# our axes: robot faces -Y, floor at z = 0  (STL turned half a turn about Z, lifted)
TO_OURS = Matrix.Translation((0, 0, -FLOOR_Z)) @ Matrix.Rotation(pi, 4, 'Z')
AXLE_Z = WHEEL_Z - FLOOR_Z
TOP = TOP_Z - FLOOR_Z

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
col = bpy.data.collections.new("Alvik")
scene.collection.children.link(col)


def mat(name, rgb, rough=0.5, metal=0.0, emission=None, strength=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emission:
        b.inputs["Emission Color"].default_value = (*emission, 1.0)
        b.inputs["Emission Strength"].default_value = strength
    m.diffuse_color = (*rgb, 1.0)
    return m


M = {
    "Body": mat("Body", (0.022, 0.026, 0.032), 0.45),
    "Baseplate": mat("Baseplate", (0.0, 0.45, 0.16), 0.5),
    "Tyre": mat("Tyre", (0.012, 0.012, 0.014), 0.9),
    "Hub": mat("Hub", (0.0, 0.42, 0.47), 0.4),
    "HubDark": mat("HubDark", (0.01, 0.05, 0.06), 0.6),
    "White": mat("White", (0.9, 0.9, 0.88), 0.4),
    "LedL": mat("LedL", (0.85, 0.85, 0.85), 0.3, emission=(1.0, 0.8, 0.0)),
    "LedR": mat("LedR", (0.85, 0.85, 0.85), 0.3, emission=(1.0, 0.8, 0.0)),
    "TofBlack": mat("TofBlack", (0.01, 0.01, 0.012), 0.15),
    "TofLens": mat("TofLens", (0.28, 0.05, 0.45), 0.1),
    "Metal": mat("Metal", (0.72, 0.74, 0.77), 0.3, 0.35),
}


def finish(bm, name, mats, origin=(0, 0, 0), smooth_angle=30):
    """bm is in mm, our axes. Makes the object, in metres, with its origin at `origin` (mm)."""
    origin = Vector(origin)
    bmesh.ops.translate(bm, verts=bm.verts, vec=-origin)
    bmesh.ops.scale(bm, verts=bm.verts, vec=(MM, MM, MM))
    lim = radians(smooth_angle)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        e.smooth = len(e.link_faces) == 2 and e.calc_face_angle(0.0) <= lim
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(M[m])
    ob = bpy.data.objects.new(name, me)
    ob.location = origin * MM
    col.objects.link(ob)
    return ob


def load_stl(filename, keep=None):
    """An STL as a bmesh in mm (welded). keep(island_bbox_lo, island_bbox_hi) picks loose parts."""
    before = set(bpy.data.objects)
    bpy.ops.wm.stl_import(filepath=os.path.join(REF, filename))
    ob = (set(bpy.data.objects) - before).pop()
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bpy.data.objects.remove(ob)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
    if keep:
        seen = set()
        for start in list(bm.verts):
            if start in seen:
                continue
            island, stack = [], [start]
            seen.add(start)
            while stack:
                v = stack.pop()
                island.append(v)
                for e in v.link_edges:
                    o = e.other_vert(v)
                    if o not in seen:
                        seen.add(o)
                        stack.append(o)
            lo = Vector([min(v.co[k] for v in island) for k in range(3)])
            hi = Vector([max(v.co[k] for v in island) for k in range(3)])
            if not keep(lo, hi):
                bmesh.ops.delete(bm, geom=island, context='VERTS')
    return bm


def lighten(bm, name):
    """CAD exports cut flat faces into far more triangles than they need: merge what is flat, then
    triangulate again. The shape stays the same."""
    n0 = len(bm.faces)
    bmesh.ops.dissolve_limit(bm, angle_limit=radians(0.5), verts=bm.verts, edges=bm.edges,
                             delimit={'NORMAL'})
    bmesh.ops.triangulate(bm, faces=bm.faces)
    print(f"{name}: {n0} -> {len(bm.faces)} triangles")


# ---------- Body ----------
bm = load_stl("alvik_reference_design.stl")
bmesh.ops.transform(bm, matrix=TO_OURS, verts=bm.verts)
lighten(bm, "Body")
body = finish(bm, "Body", ["Body"])

# ---------- Baseplate (the big part only; the two loose pins on the print bed are left out) ----------
bm = load_stl("lego_baseplate_12x12.stl", keep=lambda lo, hi: hi.x - lo.x > 50)
lo = Vector([min(v.co[k] for v in bm.verts) for k in range(3)])
hi = Vector([max(v.co[k] for v in bm.verts) for k in range(3)])
bmesh.ops.translate(bm, verts=bm.verts, vec=(-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, TOP_Z - lo.z))
bmesh.ops.transform(bm, matrix=TO_OURS, verts=bm.verts)
lighten(bm, "Baseplate")
plate = finish(bm, "Baseplate", ["Baseplate"])


# ---------- small helpers for the made-up parts (mm, our axes) ----------
def add(bm, tmp, mat_index, matrix=None):
    for f in tmp.faces:
        f.material_index = mat_index
    if matrix is not None:
        bmesh.ops.transform(tmp, matrix=matrix, verts=tmp.verts)
    bmesh.ops.recalc_face_normals(tmp, faces=tmp.faces)
    me = bpy.data.meshes.new("tmp")
    tmp.to_mesh(me)
    tmp.free()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)


def bevel(tmp, offset, segments, min_angle=30):
    edges = [e for e in tmp.edges if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > radians(min_angle)]
    if offset > 0 and edges:
        bmesh.ops.bevel(tmp, geom=edges, offset=offset, segments=segments, affect='EDGES',
                        profile=0.5, clamp_overlap=True)


def box(bm, mi, center, size, bev=0.0, segs=2):
    tmp = bmesh.new()
    bmesh.ops.create_cube(tmp, size=1.0)
    bmesh.ops.scale(tmp, verts=tmp.verts, vec=size)
    bevel(tmp, bev, segs)
    add(bm, tmp, mi, Matrix.Translation(center))


def cyl(bm, mi, center, r, depth, axis='Z', segs=24, bev=0.0, bsegs=2):
    tmp = bmesh.new()
    bmesh.ops.create_cone(tmp, cap_ends=True, cap_tris=False, segments=segs, radius1=r, radius2=r, depth=depth)
    bevel(tmp, bev, bsegs, 60)
    rot = {'X': Matrix.Rotation(pi / 2, 4, 'Y'), 'Y': Matrix.Rotation(pi / 2, 4, 'X'), 'Z': Matrix.Identity(4)}[axis]
    add(bm, tmp, mi, Matrix.Translation(center) @ rot)


# ---------- Wheels: tyre with tread, hub with dark holes, one white lug so a turn is easy to see ----------
def wheel(name, sx):
    R, W = WHEEL_R + 0.3, 7.4                     # just bigger than the moulded disc (x 41.5..48)
    c = (sx * (WHEEL_X - 0.1), 0, AXLE_Z)
    bm = bmesh.new()
    mats = ["Tyre", "Hub", "HubDark", "White"]
    cyl(bm, 0, c, R - 0.6, W, axis='X', segs=32, bev=1.6, bsegs=2)
    n = 18
    for i in range(n):                             # tread blocks, outer surface at R
        tmp = bmesh.new()
        bmesh.ops.create_cube(tmp, size=1.0)
        bmesh.ops.scale(tmp, verts=tmp.verts, vec=(W - 2.4, 2.6, 1.4))
        add(bm, tmp, 0, Matrix.Translation(c) @ Matrix.Rotation(2 * pi * i / n, 4, 'X')
            @ Matrix.Translation((0, 0, R - 0.7)))
    cyl(bm, 1, c, 11.0, W + 0.8, axis='X', segs=24, bev=0.8, bsegs=1)
    for i in range(5):
        a = 2 * pi * i / 5
        cyl(bm, 2, (c[0], 6.6 * cos(a), c[2] + 6.6 * sin(a)), 2.3, W + 1.2, axis='X', segs=10)
    cyl(bm, 3, c, 3.0, W + 1.8, axis='X', segs=12, bev=0.5, bsegs=1)
    box(bm, 3, (c[0], 0, c[2] + 9.3), (W + 1.2, 2.2, 2.2))
    return finish(bm, name, mats, origin=(sx * WHEEL_X, 0, AXLE_Z), smooth_angle=35)


wheel_l = wheel("WheelL", +1)      # the robot faces -Y, so its left is +X
wheel_r = wheel("WheelR", -1)


# ---------- LEDs: a strip along the side, under the plate, round both corners ----------
def led(name, sx):
    out, thick, rad, reach = HALF + 0.7, 2.0, 5.5, 12.0     # how far it sticks out; corner radius; how far it wraps
    z0, z1 = TOP - 2.9, TOP - 0.15                           # above the wheel, below the plate
    path = [(out - reach - rad, -out)]
    for k, (cy, a0) in enumerate(((-(out - rad), -pi / 2), (out - rad, 0.0))):
        for i in range(7):
            a = a0 + (pi / 2) * i / 6
            path.append((out - rad + rad * cos(a), cy + rad * sin(a)))
    path.append((out - reach - rad, out))
    inner = []
    for i, (x, y) in enumerate(path):                        # the same line, moved in by `thick`
        px, py = path[max(i - 1, 0)]
        nx, ny = path[min(i + 1, len(path) - 1)]
        t = Vector((nx - px, ny - py)).normalized()
        inner.append((x - t.y * thick, y + t.x * thick))
    bm = bmesh.new()
    ring = [(sx * x, y) for x, y in path + inner[::-1]]
    f = bm.faces.new([bm.verts.new((x, y, z0)) for x, y in ring])
    ext = bmesh.ops.extrude_face_region(bm, geom=[f])
    bmesh.ops.translate(bm, verts=[g for g in ext["geom"] if isinstance(g, bmesh.types.BMVert)], vec=(0, 0, z1 - z0))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    return finish(bm, name, [name], origin=(sx * HALF, 0, (z0 + z1) / 2), smooth_angle=40)


led_l = led("LedL", +1)
led_r = led("LedR", -1)

# ---------- ToF distance sensor: front face, in the middle ----------
bm = bmesh.new()
front, tz = -(HALF + 0.2), TOP - 9.0
box(bm, 0, (0, front, tz), (26, 2.4, 7.5), bev=1.0, segs=2)
for sx in (-1, 1):
    cyl(bm, 2, (sx * 6.5, front - 1.1, tz), 2.9, 0.5, axis='Y', segs=14)
    cyl(bm, 1, (sx * 6.5, front - 1.3, tz), 2.2, 0.5, axis='Y', segs=14)
tof = finish(bm, "Tof", ["TofBlack", "TofLens", "Metal"], origin=(0, front, tz))

# ---------- check and export ----------
bpy.context.view_layer.update()
total = 0
for ob in col.objects:
    ob.data.calc_loop_triangles()
    n = len(ob.data.loop_triangles)
    total += n
    ws = [ob.matrix_world @ v.co for v in ob.data.vertices]
    print(f"{ob.name:10s} {n:6d} tris  origin mm {[round(c * 1000, 2) for c in ob.location]}  "
          f"z {min(w.z for w in ws) * 1000:.1f}..{max(w.z for w in ws) * 1000:.1f}")
print("total", total, "tris")

os.makedirs(os.path.dirname(GLB), exist_ok=True)
for ob in col.objects:
    ob.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.export_scene.gltf(filepath=os.path.abspath(GLB), export_format='GLB', use_selection=True,
                          export_apply=True, export_yup=True, export_cameras=False, export_lights=False,
                          export_animations=False, export_texcoords=False, export_copyright=COPYRIGHT)
print("wrote", os.path.abspath(GLB), os.path.getsize(GLB), "bytes")

# ---------- optional preview renders ----------
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if "--preview" in argv:
    out = argv[argv.index("--preview") + 1]
    scene.render.engine = 'BLENDER_WORKBENCH'
    sh = scene.display.shading
    sh.light, sh.color_type, sh.show_cavity, sh.show_shadows = 'STUDIO', 'MATERIAL', True, False
    scene.render.resolution_x, scene.render.resolution_y = 900, 700
    cd = bpy.data.cameras.new("Preview")
    cd.type, cd.ortho_scale, cd.clip_start, cd.clip_end = 'ORTHO', 0.15, 0.001, 5
    cam = bpy.data.objects.new("Preview", cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    world = bpy.data.worlds.new("w")
    scene.world = world
    world.color = (0.5, 0.52, 0.55)
    target = Vector((0, 0, 0.025))
    for name, d in {"behind": (0.5, 1.2, 0.8), "front": (-0.6, -1.2, 0.6), "side": (1, 0, 0.05),
                    "under": (0.6, -1, -0.8)}.items():
        cam.location = target + Vector(d).normalized() * 0.5
        cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = os.path.join(out, f"alvik_{name}.png")
        bpy.ops.render.render(write_still=True)
