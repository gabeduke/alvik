"""Build a stylised low-poly Arduino Alvik. Units: metres. Front = -Y, up = +Z.
Origin = midpoint between the wheels, on the floor."""
import bpy, bmesh, json, os, sys
from math import pi, cos, sin, radians, sqrt
from mathutils import Matrix, Vector

SCRATCH = "/private/tmp/claude-501/-Users-gabeduke-repos-alvik/8922ef54-d559-4a21-9371-559bdd912a35/scratchpad"
GLB = "/Users/gabeduke/repos/alvik/docs/models/alvik.glb"
BLEND = "/Users/gabeduke/repos/alvik/models/alvik.blend"
MM = 0.001

# ---------- start from an empty file (this is our own headless Blender) ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1.0
col = bpy.data.collections.new("Alvik")
scene.collection.children.link(col)


# ---------- materials ----------
def mat(name, rgb, rough=0.5, metal=0.0, alpha=1.0, emission=None, strength=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Alpha"].default_value = alpha
    if emission:
        b.inputs["Emission Color"].default_value = (*emission, 1.0)
        b.inputs["Emission Strength"].default_value = strength
    m.diffuse_color = (*rgb, alpha)
    if alpha < 1.0:
        if hasattr(m, "surface_render_method"):
            m.surface_render_method = 'BLENDED'
        m.use_backface_culling = True
    return m


M = {
    "Body": mat("Body", (0.012, 0.075, 0.085), 0.55),
    "Shell": mat("Shell", (0.35, 0.75, 0.78), 0.15, alpha=0.38),
    "Tyre": mat("Tyre", (0.015, 0.015, 0.018), 0.85),
    "Hub": mat("Hub", (0.0, 0.42, 0.47), 0.4),
    "HubDark": mat("HubDark", (0.01, 0.05, 0.06), 0.6),
    "White": mat("White", (0.9, 0.9, 0.88), 0.4),
    "LedL": mat("LedL", (0.9, 0.9, 0.9), 0.3, emission=(1.0, 0.75, 0.0), strength=2.0),
    "LedR": mat("LedR", (0.9, 0.9, 0.9), 0.3, emission=(1.0, 0.75, 0.0), strength=2.0),
    "Baseplate": mat("Baseplate", (1.0, 0.33, 0.03), 0.45),
    "Standoff": mat("Standoff", (0.55, 0.57, 0.6), 0.4, metal=0.3),
    "Metal": mat("Metal", (0.72, 0.74, 0.77), 0.3, metal=0.35),
    "Pcb": mat("Pcb", (0.0, 0.22, 0.28), 0.5),
    "Button": mat("Button", (0.95, 0.72, 0.15), 0.35, metal=0.2),
    "TofBlack": mat("TofBlack", (0.01, 0.01, 0.012), 0.15),
    "TofLens": mat("TofLens", (0.28, 0.05, 0.45), 0.1),
}


# ---------- geometry helpers (all sizes in mm) ----------
class Part:
    """Accumulates primitives into one mesh with several material slots."""

    def __init__(self, name, origin=(0, 0, 0)):
        self.name = name
        self.origin = Vector(origin)  # mm, world
        self.bm = bmesh.new()
        self.mats = []

    def slot(self, mname):
        if mname not in self.mats:
            self.mats.append(mname)
        return self.mats.index(mname)

    def absorb(self, tmp, mname, matrix=None):
        idx = self.slot(mname)
        for f in tmp.faces:
            f.material_index = idx
        if matrix is not None:
            bmesh.ops.transform(tmp, matrix=matrix, verts=tmp.verts)
        bmesh.ops.translate(tmp, verts=tmp.verts, vec=-self.origin)
        bmesh.ops.scale(tmp, verts=tmp.verts, vec=(MM, MM, MM))
        bmesh.ops.recalc_face_normals(tmp, faces=tmp.faces)
        me = bpy.data.meshes.new("tmp")
        tmp.to_mesh(me)
        tmp.free()
        self.bm.from_mesh(me)
        bpy.data.meshes.remove(me)

    def finish(self, smooth_angle=35):
        bm = self.bm
        for f in bm.faces:
            f.smooth = True
        lim = radians(smooth_angle)
        for e in bm.edges:
            if len(e.link_faces) == 2:
                e.smooth = e.calc_face_angle(0.0) <= lim
        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        bm.free()
        for mname in self.mats:
            me.materials.append(M[mname])
        ob = bpy.data.objects.new(self.name, me)
        ob.location = self.origin * MM
        col.objects.link(ob)
        return ob


def bevel_sharp(bm, offset, segments, min_angle=30):
    edges = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > radians(min_angle)]
    if offset > 0 and edges:
        bmesh.ops.bevel(bm, geom=edges, offset=offset, segments=segments, affect='EDGES',
                        profile=0.5, clamp_overlap=True)


def box(part, mname, center, size, bevel=0.0, segs=2):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, verts=bm.verts, vec=size)
    bevel_sharp(bm, bevel, segs)
    part.absorb(bm, mname, Matrix.Translation(center))


def cyl(part, mname, center, r, depth, axis='Z', segs=24, bevel=0.0, bsegs=2, r2=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs,
                          radius1=r, radius2=r if r2 is None else r2, depth=depth)
    bevel_sharp(bm, bevel, bsegs, 60)
    rot = Matrix.Identity(4)
    if axis == 'X':
        rot = Matrix.Rotation(pi / 2, 4, 'Y')
    elif axis == 'Y':
        rot = Matrix.Rotation(pi / 2, 4, 'X')
    part.absorb(bm, mname, Matrix.Translation(center) @ rot)


def sphere(part, mname, center, r, u=16, v=10, scale=(1, 1, 1)):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r)
    part.absorb(bm, mname, Matrix.Translation(center) @ Matrix.Diagonal((*scale, 1)))


def chassis_outline(hw, hl, r, notch_x, notch_y, arc=8):
    """Rounded rectangle (half-width hw, half-length hl) with wheel notches. CCW from above."""
    right = []
    cx, cy = hw - r, -(hl - r)
    for i in range(arc + 1):
        a = -pi / 2 + (pi / 2) * i / arc
        right.append((cx + r * cos(a), cy + r * sin(a)))
    right += [(hw, -notch_y), (notch_x, -notch_y), (notch_x, notch_y), (hw, notch_y)]
    cy = hl - r
    for i in range(arc + 1):
        a = (pi / 2) * i / arc
        right.append((cx + r * cos(a), cy + r * sin(a)))
    left = [(-x, y) for (x, y) in reversed(right)]
    pts, out = right + left, []
    for p in pts:  # drop duplicates
        if not out or (Vector(p) - Vector(out[-1])).length > 1e-4:
            out.append(p)
    return out


def prism(part, mname, outline, z0, z1, bevel=0.0, segs=2):
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, z0)) for x, y in outline]
    f = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[f])
    bmesh.ops.translate(bm, verts=[g for g in ext["geom"] if isinstance(g, bmesh.types.BMVert)],
                        vec=(0, 0, z1 - z0))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bevel_sharp(bm, bevel, segs, 30)
    part.absorb(bm, mname)


# ---------- dimensions (mm) ----------
WHEEL_R = 17.0
WHEEL_W = 8.0
AXLE_X = 43.5          # wheel centre; outer faces at +-47.5 -> 95 mm overall
BODY_Z0, BODY_Z1 = 5.0, 21.0
SHELL_Z1 = 33.0
PLATE_Z0, PLATE_T = 39.0, 2.0

# ---------- Body (chassis + Nano ESP32 + touch buttons) ----------
body = Part("Body")
prism(body, "Body", chassis_outline(47.0, 48.0, 14.0, 38.5, 20.0), BODY_Z0, BODY_Z1, bevel=2.0, segs=3)
# axle stubs so the wheels look attached
for sx in (-1, 1):
    cyl(body, "Body", (sx * 38.5, 0, WHEEL_R), 4.0, 3.0, axis='X', segs=12)
# Nano ESP32 on top of the shell (long side left-right, a little forward of centre)
box(body, "Pcb", (0, -6, SHELL_Z1 + 0.8), (45, 18, 1.6))
box(body, "Metal", (-9, -6, SHELL_Z1 + 2.6), (16, 13, 2.2), bevel=0.4, segs=1)      # radio module can
box(body, "Metal", (20, -6, SHELL_Z1 + 2.9), (7.5, 9, 3.0), bevel=0.8, segs=2)      # USB-C
box(body, "TofBlack", (8, -6, SHELL_Z1 + 2.0), (5, 5, 1.0))                          # chip
for sy in (-1, 1):                                                                    # header rows
    box(body, "TofBlack", (0, -6 + sy * 7.6, SHELL_Z1 + 0.2), (40, 2.2, 2.6))
# touch buttons on the top, at the back: d-pad + centre + ok / cancel
for bx, by in ((0, 0), (-8, 0), (8, 0), (0, -8), (0, 8)):
    cyl(body, "Button", (bx, 30 + by, SHELL_Z1 + 0.3), 3.0, 0.8, segs=12)
cyl(body, "Button", (-24, 34, SHELL_Z1 + 0.3), 3.4, 0.8, segs=12)
cyl(body, "Button", (24, 34, SHELL_Z1 + 0.3), 3.4, 0.8, segs=12)
body_ob = body.finish()

# ---------- Shell (translucent top cover) ----------
shell = Part("Shell")
prism(shell, "Shell", chassis_outline(45.5, 46.5, 12.5, 37.0, 21.5), BODY_Z1, SHELL_Z1, bevel=3.0, segs=3)
shell_ob = shell.finish()


# ---------- Wheels (origin on the axle; spin about local X) ----------
def wheel(name, sx):
    w = Part(name, origin=(sx * AXLE_X, 0, WHEEL_R))
    c = (sx * AXLE_X, 0, WHEEL_R)
    cyl(w, "Tyre", c, WHEEL_R - 0.6, WHEEL_W, axis='X', segs=32, bevel=1.8, bsegs=2)
    n = 18  # tread blocks, outer surface at exactly WHEEL_R
    for i in range(n):
        a = 2 * pi * i / n
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, verts=bm.verts, vec=(WHEEL_W - 2.4, 2.6, 1.4))
        mtx = (Matrix.Translation(c) @ Matrix.Rotation(a, 4, 'X')
               @ Matrix.Translation((0, 0, WHEEL_R - 0.7)))
        w.absorb(bm, "Tyre", mtx)
    cyl(w, "Hub", c, 11.0, WHEEL_W + 1.0, axis='X', segs=24, bevel=0.8, bsegs=1)
    for i in range(5):  # dark "holes" so you can see the wheel turn
        a = 2 * pi * i / 5
        cyl(w, "HubDark", (c[0], 6.6 * cos(a), WHEEL_R + 6.6 * sin(a)), 2.3, WHEEL_W + 1.5, axis='X', segs=10)
    cyl(w, "White", c, 3.0, WHEEL_W + 2.2, axis='X', segs=12, bevel=0.5, bsegs=1)
    # one white marker lug: makes rotation obvious even at a glance
    box(w, "White", (c[0], 0, WHEEL_R + 9.3), (WHEEL_W + 1.4, 2.2, 2.2))
    return w.finish()


wheel_l = wheel("WheelL", +1)   # robot faces -Y, so its left is +X
wheel_r = wheel("WheelR", -1)

# ---------- Caster (rear ball) ----------
caster = Part("Caster")
sphere(caster, "Metal", (0, 37, 5.0), 5.0, u=16, v=10)
cyl(caster, "Body", (0, 37, 5.5), 7.0, 3.0, segs=16)
caster_ob = caster.finish()

# ---------- ToF sensor bar (front) ----------
tof = Part("Tof")
box(tof, "TofBlack", (0, -47.6, 23.5), (36, 3.6, 8), bevel=1.2, segs=2)
for sx in (-1, 1):
    cyl(tof, "TofLens", (sx * 9, -49.3, 23.5), 2.6, 0.8, axis='Y', segs=14)
    cyl(tof, "Metal", (sx * 9, -49.2, 23.5), 3.3, 0.5, axis='Y', segs=14)
tof_ob = tof.finish()


# ---------- RGB LEDs (front-top corners) ----------
def led(name, sx):
    c = (sx * 31, -45.0, 31.5)
    p = Part(name, origin=c)
    box(p, name, c, (13, 6.5, 6.5), bevel=2.2, segs=3)
    return p.finish()


led_l = led("LedL", +1)
led_r = led("LedR", -1)

# ---------- LEGO-compatible baseplate (10 x 10 studs, 8 mm pitch) ----------
plate = Part("Baseplate")
box(plate, "Baseplate", (0, 0, PLATE_Z0 + PLATE_T / 2), (80, 80, PLATE_T), bevel=0.5, segs=1)
zs = PLATE_Z0 + PLATE_T
for i in range(10):
    for j in range(10):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=12,
                              radius1=2.4, radius2=2.4, depth=1.7)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z < -0.5], context='FACES')
        plate.absorb(bm, "Baseplate", Matrix.Translation((-36 + 8 * i, -36 + 8 * j, zs + 0.85)))
for sx in (-1, 1):
    for sy in (-1, 1):
        cyl(plate, "Standoff", (sx * 30, sy * 30 + (0 if sy < 0 else 0), (SHELL_Z1 + PLATE_Z0) / 2 - 0.5),
            2.5, PLATE_Z0 - SHELL_Z1 + 1.0, segs=10)
plate_ob = plate.finish()

# ---------- stats ----------
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
stats, total = {}, 0
lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
for ob in col.objects:
    me = ob.evaluated_get(dg).to_mesh()
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    for v in me.vertices:
        w = ob.matrix_world @ v.co
        for k in range(3):
            lo[k] = min(lo[k], w[k]); hi[k] = max(hi[k], w[k])
    stats[ob.name] = {"tris": n, "origin_m": [round(c, 5) for c in ob.location],
                      "materials": [m.name for m in ob.data.materials]}
    total += n
    ob.evaluated_get(dg).to_mesh_clear()

# ---------- export GLB (Alvik collection only) ----------
os.makedirs(os.path.dirname(GLB), exist_ok=True)
os.makedirs(os.path.dirname(BLEND), exist_ok=True)
bpy.ops.object.select_all(action='DESELECT')
for ob in col.objects:
    ob.select_set(True)
bpy.context.view_layer.objects.active = body_ob
bpy.ops.export_scene.gltf(filepath=GLB, export_format='GLB', use_selection=True,
                          export_apply=True, export_yup=True, export_cameras=False,
                          export_lights=False, export_animations=False)
bpy.ops.object.select_all(action='DESELECT')

# ---------- preview rig (separate collection, not exported) ----------
pcol = bpy.data.collections.new("AlvikPreview")
scene.collection.children.link(pcol)
world = bpy.data.worlds.new("PreviewWorld")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.82, 0.86, 0.9, 1)
bg.inputs[1].default_value = 0.45
scene.world = world
fm = bpy.data.meshes.new("PreviewFloor")
fb = bmesh.new()
bmesh.ops.create_grid(fb, x_segments=1, y_segments=1, size=1.0)
fb.to_mesh(fm); fb.free()
fmat = mat("PreviewFloor", (0.75, 0.78, 0.8), 0.8)
fm.materials.append(fmat)
floor = bpy.data.objects.new("PreviewFloor", fm)
pcol.objects.link(floor)


def add_light(name, loc, energy, size):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.size = size
    lo_ = bpy.data.objects.new(name, ld)
    lo_.location = loc
    lo_.rotation_euler = (Vector((0, 0, 0.02)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    pcol.objects.link(lo_)


add_light("PreviewKey", (0.15, -0.25, 0.3), 1.2, 0.25)
add_light("PreviewFill", (-0.3, -0.05, 0.2), 0.4, 0.3)
add_light("PreviewRim", (0.0, 0.3, 0.25), 0.6, 0.3)

cam_d = bpy.data.cameras.new("PreviewCamera")
cam_d.lens = 70
cam_d.clip_start = 0.005
cam_d.clip_end = 10
cam = bpy.data.objects.new("PreviewCamera", cam_d)
pcol.objects.link(cam)
scene.camera = cam

scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = 1200, 900
scene.render.image_settings.file_format = 'PNG'
try:
    scene.view_settings.view_transform = 'Standard'
except Exception:
    pass


def shot(path, loc, target=(0, 0, 0.02)):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


views = {
    "alvik_view_rear.png": (-0.24, 0.26, 0.17),
    "alvik_view_side.png": (0.38, 0.0, 0.03),
    "alvik_view_top.png": (0.0, -0.001, 0.42),
    "alvik_view_under.png": (0.2, -0.22, -0.12),
    "alvik_preview.png": (0.22, -0.30, 0.17),
}
only = os.environ.get("ALVIK_VIEWS")
for fn, loc in views.items():
    if only and fn not in only.split(","):
        continue
    floor.hide_render = "under" in fn
    # shell + plate off for one extra look at the top deck
    shot(os.path.join(SCRATCH, fn), loc)
floor.hide_render = False
cam.location = views["alvik_preview.png"]
cam.rotation_euler = (Vector((0, 0, 0.02)) - Vector(cam.location)).to_track_quat('-Z', 'Y').to_euler()
scene.render.filepath = "//alvik_preview.png"

bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)

out = {"total_tris": total, "objects": stats,
       "bbox_min_m": [round(c, 5) for c in lo], "bbox_max_m": [round(c, 5) for c in hi],
       "size_m": [round(hi[k] - lo[k], 5) for k in range(3)]}
with open(os.path.join(SCRATCH, "alvik_stats.json"), "w") as fh:
    json.dump(out, fh, indent=1)
print("ALVIK_STATS " + json.dumps(out))
