"""DMX box – krabička pre 3D tlač (Blender / bpy).

Raspberry Pi 3B+ (predvolené) alebo Pi 4 (--pi4: iné porty), MAX485 modul vnútri na GPIO,
displej 2,2" TFT ILI9341 a rotačný enkóder s tlačidlom vo veku,
panelová XLR samica (D-typ, napr. Neutrik NC3FD-L-1) na ľavej stene, porty Pi vyvedené.

Spustenie:  python3 dmxbox_enclosure.py [--pi4] [--no-render]   (pip install bpy)   → STL + náhľady do ./out
Súradnice: vnútorné dno = z 0, vnútro x 0..L, y 0..W. Jednotky mm.
"""

import math
import os
import sys

import bpy
from mathutils import Vector

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)

# --- rozmery --------------------------------------------------------------------------------
T = 2.4              # stena / dno / veko
L, W, H = 128.0, 60.0, 40.0     # vnútro (40: pod displejom sa zmestí telo XLR)
LID = 2.4
CLR = 0.3            # vôľa veka
PI_X0, PI_Y0 = 42.0, 2.0        # ľavý-predný roh dosky Pi vo vnútri krabičky
STANDOFF_H = 5.0
BOARD = 1.6
BT = STANDOFF_H + BOARD          # horná strana dosky Pi (z)
PI4 = "--pi4" in sys.argv
# porty podľa mechanických výkresov Raspberry Pi: (stred, šírka, výška otvoru)
FRONT = ([(11.2, 10.5, 4.5), (26.0, 8.5, 4.5), (39.5, 8.5, 4.5)] if PI4      # USB-C, 2× micro HDMI
         else [(10.6, 10.5, 5.0), (32.0, 17.0, 8.0)])                        # micro USB, HDMI
RIGHT = ([(9.0, 16.0, 17.0), (27.0, 16.0, 17.0), (45.75, 17.0, 14.5)] if PI4  # USB2, USB3, Ethernet
         else [(10.25, 17.0, 14.5), (29.0, 16.0, 17.0), (47.0, 16.0, 17.0)])  # Ethernet, USB, USB
SUFFIX = "_pi4" if PI4 else "_pi3"

# displej 2,2" 240×320 ILI9341 SPI (MSP2202): doska 67,2 × 40,1 mm, aktívna plocha 45,12 × 33,84 mm.
# Otvory dosky nie sú v dokumentácii – DISP_HOLE je typická vzdialenosť od rohu, over na module.
DISP_PCB = (67.2, 40.1)
DISP_ACTIVE = (45.12, 33.84)
DISP_X0, DISP_YC = 8.0, 30.0          # ľavý okraj dosky a stred v y (vo vnútri krabice)
DISP_GLASS = 2.6                       # sklo + rám displeja nad doskou (výška stĺpikov)
DISP_HOLE = 2.6
ENC_XY = (116.0, 30.0)                 # rotačný enkóder (závit ~7 mm)


def pi(x, y):
    """Súradnice z výkresu Pi (ľavá krátka hrana = microSD, predná dlhá = HDMI) → krabička."""
    return PI_X0 + x, PI_Y0 + y


# --- pomocné --------------------------------------------------------------------------------
def clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m)


def box(name, x0, y0, z0, x1, y1, z1):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    o = bpy.context.active_object
    o.scale = (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))
    bpy.ops.object.transform_apply(scale=True)
    o.name = name
    return o


def cyl(name, x, y, z0, z1, r, axis="Z", verts=64, r2=None):
    depth = z1 - z0
    if r2 is None:
        bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth)
    else:
        bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, radius2=r2, depth=depth)
    o = bpy.context.active_object
    o.name = name
    if axis == "Z":
        o.location = (x, y, (z0 + z1) / 2)
    elif axis == "X":                     # x,y = (y, z) stredu, z0..z1 = rozsah v x
        o.rotation_euler = (0, math.radians(90), 0)
        o.location = ((z0 + z1) / 2, x, y)
    elif axis == "Y":                     # x,y = (x, z) stredu, z0..z1 = rozsah v y
        o.rotation_euler = (math.radians(90), 0, 0)
        o.location = (x, (z0 + z1) / 2, y)
    bpy.ops.object.transform_apply(rotation=True, location=False)
    return o


def boolean(target, tools, op):
    for t in tools:
        m = target.modifiers.new(name=f"b_{t.name}", type="BOOLEAN")
        m.operation = op
        m.object = t
        m.solver = "EXACT"
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.modifier_apply(modifier=m.name)
        bpy.data.objects.remove(t, do_unlink=True)
    return target


def frustum(name, cx, cy, z0, z1, hx, hy, grow):
    """Zrezaný ihlan (skosenie okna): spodok hx × hy, vrch o `grow` väčší na každú stranu."""
    vs = []
    for z, g in ((z0, 0.0), (z1, grow)):
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            vs.append((cx + sx * (hx + g), cy + sy * (hy + g), z))
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(vs, [], faces)
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


def text(name, body, size, x, y, z, depth, rot=(0, 0, 0), align="CENTER"):
    bpy.ops.object.text_add(location=(x, y, z), rotation=rot)
    o = bpy.context.active_object
    o.data.body = body
    o.data.size = size
    o.data.extrude = depth / 2
    o.data.align_x = align
    o.data.align_y = "CENTER"
    bpy.ops.object.convert(target="MESH")
    o.name = name
    return o


# --- krabica --------------------------------------------------------------------------------
def build_case():
    outer = box("case", -T, -T, -T, L + T, W + T, H)
    cuts = [box("inner", 0, 0, 0, L, W, H + 1)]

    # predná stena (y = 0): napájanie micro-USB, HDMI, jack 3,5 mm (Pi 3B+)
    for px, wdt, hgt in FRONT:
        x, _ = pi(px, 0)
        cuts.append(box(f"front_{px}", x - wdt / 2, -T - 1, BT - 0.8, x + wdt / 2, 1, BT - 0.8 + hgt))
    jx, _ = pi(53.5, 0)
    cuts.append(cyl("jack", jx, BT + 3.0, -T - 1, 1, 3.8, axis="Y"))

    # pravá stena (x = L): Ethernet + 2× dvojité USB
    for py, wdt, hgt in RIGHT:
        _, y = pi(0, py)
        cuts.append(box(f"right_{py}", L - 1, y - wdt / 2, BT - 0.8, L + T + 1, y + wdt / 2, BT - 0.8 + hgt))

    # ľavá stena (x = 0): XLR samica D-typ – otvor Ø24, skrutky M3 na uhlopriečke 19 × 24 mm
    yc, zc = W / 2, H / 2
    cuts.append(cyl("xlr", yc, zc, -T - 1, 1, 12.2, axis="X"))
    for dy, dz in ((-9.5, 12.0), (9.5, -12.0)):
        cuts.append(cyl(f"xlr_m3_{dy}", yc + dy, zc + dz, -T - 1, 1, 1.65, axis="X", verts=32))

    # zadná stena (y = W): vetracie štrbiny nad Pi
    for i in range(12):
        x = 52 + i * 6.0
        cuts.append(box(f"vent_{i}", x, W - 1, 9, x + 2.4, W + T + 1, 27))

    # popis na ľavej stene pod XLR (vrytý 0,6 mm)
    lab = text("lbl_dmx", "DMX OUT", 4.2, -T - 0.01, yc, 3.0, 1.2, rot=(math.radians(90), 0, math.radians(-90)))
    lab.location.x = -T + 0.3
    cuts.append(lab)

    boolean(outer, cuts, "DIFFERENCE")

    # podpery dosky Pi (M2.5 – samorezná skrutka do Ø2,2)
    adds = []
    for hx, hy in ((3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)):
        x, y = pi(hx, hy)
        adds.append(cyl(f"so_{hx}_{hy}", x, y, -0.5, STANDOFF_H, 3.0))
    # lôžko pre MAX485 (modul ~44 × 14 mm, pozdĺž osi y): dve lišty, konce voľné pre káble
    adds.append(box("rail_a", 22.4, 14, -0.5, 24.0, 46, 4.0))
    adds.append(box("rail_b", 38.6, 14, -0.5, 40.2, 46, 4.0))
    # rohové stĺpiky pre veko (M3 samorezná), zospodu kužeľ 45° – tlač bez podpier
    for cx, cy in ((3.5, 3.5), (L - 3.5, 3.5), (3.5, W - 3.5), (L - 3.5, W - 3.5)):
        adds.append(cyl(f"boss_{cx}_{cy}", cx, cy, H - 7.0, H, 3.6))
        adds.append(cyl(f"cone_{cx}_{cy}", cx, cy, H - 10.6, H - 7.0, 0.01, r2=3.6))
        # spojka do rohu steny, nech stĺpik nevisí len na kúsku
        sx0, sx1 = (-0.5, cx) if cx < L / 2 else (cx, L + 0.5)
        sy0, sy1 = (-0.5, cy) if cy < W / 2 else (cy, W + 0.5)
        adds.append(box(f"web_{cx}_{cy}", sx0, sy0, H - 7.0, sx1, sy1, H))
    boolean(outer, adds, "UNION")

    holes = []
    for hx, hy in ((3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)):
        x, y = pi(hx, hy)
        holes.append(cyl(f"soh_{hx}", x, y, 0.0, STANDOFF_H + 1, 1.1, verts=24))
    for cx, cy in ((3.5, 3.5), (L - 3.5, 3.5), (3.5, W - 3.5), (L - 3.5, W - 3.5)):
        holes.append(cyl(f"bh_{cx}_{cy}", cx, cy, H - 8.0, H + 1, 1.25, verts=24))
    boolean(outer, holes, "DIFFERENCE")
    return outer


# --- veko -----------------------------------------------------------------------------------
def build_lid():
    lid = box("lid", -T, -T, H, L + T, W + T, H + LID)
    adds = []
    # lem do krabice (nezasahuje do rohových stĺpikov)
    lip_h, lip_t = 3.0, 1.6
    x0, y0, x1, y1 = CLR, CLR, L - CLR, W - CLR
    adds.append(box("lip_f", 10, y0, H - lip_h, L - 10, y0 + lip_t, H + 0.1))
    adds.append(box("lip_b", 10, y1 - lip_t, H - lip_h, L - 10, y1, H + 0.1))
    adds.append(box("lip_l", x0, 10, H - lip_h, x0 + lip_t, W - 10, H + 0.1))
    adds.append(box("lip_r", x1 - lip_t, 10, H - lip_h, x1, W - 10, H + 0.1))
    boolean(lid, adds, "UNION")
    cuts = []
    for cx, cy in ((3.5, 3.5), (L - 3.5, 3.5), (3.5, W - 3.5), (L - 3.5, W - 3.5)):
        cuts.append(cyl(f"lh_{cx}", cx, cy, H - 1, H + LID + 1, 1.7, verts=32))
        cuts.append(cyl(f"lcs_{cx}", cx, cy, H + LID - 1.6, H + LID + 0.01, 1.7, r2=3.2, verts=32))
    # vetranie nad Pi (medzi displejom a gombíkom)
    for i in range(4):
        x = 83 + i * 6.0
        cuts.append(box(f"lv_{i}", x, 14, H - 1, x + 2.6, 46, H + LID + 1))
    # okno displeja: aktívna plocha + 0,8 mm, zhora skosené 45°
    pw, ph = DISP_PCB
    aw, ah = DISP_ACTIVE
    dcx = DISP_X0 + pw / 2
    wx, wy = aw / 2 + 0.8, ah / 2 + 0.8
    cuts.append(box("disp_win", dcx - wx, DISP_YC - wy, H - 5, dcx + wx, DISP_YC + wy, H + LID + 1))
    bev = frustum("disp_bevel", dcx, DISP_YC, H + LID - 1.2, H + LID + 0.01, wx, wy, 1.2)
    cuts.append(bev)
    # gombík
    cuts.append(cyl("enc_hole", ENC_XY[0], ENC_XY[1], H - 1, H + LID + 1, 3.7, verts=48))
    # nápisy
    cuts.append(text("logo", "fajny DMX box", 4.2, 108.0, 8.0, H + LID - 0.3, 1.2))
    cuts.append(text("enc_lbl", "PUSH", 2.8, ENC_XY[0], ENC_XY[1] + 9.5, H + LID - 0.3, 1.2))
    boolean(lid, cuts, "DIFFERENCE")

    # pod vekom: rámik okolo dosky displeja + 4 stĺpiky na skrutky M2 (doska visí zo skla)
    adds = []
    x0, x1 = DISP_X0 - 0.3, DISP_X0 + pw + 0.3
    y0, y1 = DISP_YC - ph / 2 - 0.3, DISP_YC + ph / 2 + 0.3
    fh = DISP_GLASS + 1.6 + 1.0
    for nm, a, b, c, d in (("fr_f", x0 - 1.2, y0 - 1.2, x1 + 1.2, y0),
                           ("fr_b", x0 - 1.2, y1, x1 + 1.2, y1 + 1.2),
                           ("fr_l", x0 - 1.2, y0, x0, y1)):          # pravá strana voľná: pin header
        adds.append(box(nm, a, b, H - fh, c, d, H + 0.1))
    for hx in (DISP_X0 + DISP_HOLE, DISP_X0 + pw - DISP_HOLE):
        for hy in (DISP_YC - ph / 2 + DISP_HOLE, DISP_YC + ph / 2 - DISP_HOLE):
            adds.append(cyl(f"dpost_{hx}_{hy}", hx, hy, H - DISP_GLASS, H + 0.1, 2.3, verts=32))
    boolean(lid, adds, "UNION")
    holes = []
    for hx in (DISP_X0 + DISP_HOLE, DISP_X0 + pw - DISP_HOLE):
        for hy in (DISP_YC - ph / 2 + DISP_HOLE, DISP_YC + ph / 2 - DISP_HOLE):
            holes.append(cyl(f"dph_{hx}_{hy}", hx, hy, H - DISP_GLASS - 1, H - 0.4, 0.8, verts=20))
    boolean(lid, holes, "DIFFERENCE")
    return lid


# --- export a náhľad ------------------------------------------------------------------------
def export(obj, fname, flip=False):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if flip:                                   # veko tlačiť hornou stranou na podložke
        obj.rotation_euler = (math.radians(180), 0, 0)
        bpy.ops.object.transform_apply(rotation=True)
    bpy.ops.wm.stl_export(filepath=os.path.join(OUT, fname), export_selected_objects=True)
    if flip:
        obj.rotation_euler = (math.radians(180), 0, 0)
        bpy.ops.object.transform_apply(rotation=True)


def material(obj, rgb):
    m = bpy.data.materials.new(obj.name + "_mat")
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = 0.55
    obj.data.materials.clear()
    obj.data.materials.append(m)
    obj.active_material = m


def render(path, cam_loc, target, size=(1200, 800)):
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = 32
    scn.render.resolution_x, scn.render.resolution_y = size
    scn.render.film_transparent = False
    if "Camera" not in bpy.data.objects:
        bpy.ops.object.camera_add()
        bpy.context.active_object.name = "Camera"
    cam = bpy.data.objects["Camera"]
    cam.location = cam_loc
    d = Vector(target) - Vector(cam_loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 40
    scn.camera = cam
    if "Sun" not in bpy.data.objects:
        bpy.ops.object.light_add(type="SUN", location=(0, 0, 200))
        sun = bpy.context.active_object
        sun.name = "Sun"
        sun.data.energy = 3.5
        sun.rotation_euler = (math.radians(40), math.radians(15), math.radians(30))
    w = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    scn.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.06, 0.06, 0.08, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    clear()
    case = build_case()
    lid = build_lid()
    export(case, f"dmxbox_case{SUFFIX}.stl")
    export(lid, "dmxbox_lid.stl", flip=True)
    material(case, (0.08, 0.08, 0.1))
    material(lid, (0.85, 0.12, 0.38))
    if "--no-render" in sys.argv:
        return
    # len do náhľadu: displej a gombík vo veku
    pw, ph = DISP_PCB
    dcx = DISP_X0 + pw / 2
    glass = box("glass", dcx - DISP_ACTIVE[0] / 2 - 1, DISP_YC - DISP_ACTIVE[1] / 2 - 1, H - DISP_GLASS,
                dcx + DISP_ACTIVE[0] / 2 + 1, DISP_YC + DISP_ACTIVE[1] / 2 + 1, H + 0.6)
    material(glass, (0.02, 0.15, 0.35))
    knob = cyl("knob", ENC_XY[0], ENC_XY[1], H + LID, H + LID + 14, 7.5, verts=48)
    material(knob, (0.12, 0.12, 0.14))
    for o in (glass, knob):
        o.parent = lid
    lid.location.z += 40                      # rozložený pohľad
    c = (L / 2, W / 2, 20)
    render(os.path.join(OUT, f"preview_front{SUFFIX}.png"), (-90, -150, 140), c)
    render(os.path.join(OUT, f"preview_back{SUFFIX}.png"), (230, 210, 120), c)
    render(os.path.join(OUT, f"preview_top{SUFFIX}.png"), (L / 2, W / 2 - 60, 230), (L / 2, W / 2, 40))
    for o in (lid, glass, knob):
        o.hide_render = True
    render(os.path.join(OUT, f"preview_inside{SUFFIX}.png"), (L / 2, -40, 190), (L / 2, W / 2, 0))
    # spodok veka: rámik a stĺpiky displeja
    for o in (lid, glass, knob):
        o.hide_render = o is not lid
    case.hide_render = True
    lid.location.z -= 40
    lid.rotation_euler = (math.radians(180), 0, 0)
    lid.location = (0, W, 2 * H + LID)
    render(os.path.join(OUT, f"preview_lid_under{SUFFIX}.png"), (L / 2, -60, H + 150), (L / 2, W / 2, H))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, f"dmxbox_enclosure{SUFFIX}.blend"))


if __name__ == "__main__":
    main()
