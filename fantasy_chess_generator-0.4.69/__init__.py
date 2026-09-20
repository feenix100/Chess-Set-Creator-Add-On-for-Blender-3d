# SPDX-FileCopyrightText: 2026 Fantasy Chess Generator contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fantasy Chess Set Generator Blender Extension.

Extension metadata lives in blender_manifest.toml as required by Blender 4.2+.
The add-on remains self-contained and uses Blender's extension namespace.
"""


import bpy
import os
from math import sin, cos, pi, radians
from mathutils import Vector
from bpy.props import FloatProperty, IntProperty, EnumProperty

ROOT_NAME = "CHESS_SET"
BOARD_NAME = "CHESS_BOARD"
PIECES_NAME = "PIECE_SETS"
WHITE_NAME = "WHITE"
BLACK_NAME = "BLACK"
RENDER_SCENE_NAME = "Render Scene"
RENDER_SEQUENCE_NAME = "Render Sequence"
INDIVIDUAL_SHOWCASE_NAME = "Individual Piece Showcase"


# -----------------------------------------------------------------------------
# Collection helpers
# -----------------------------------------------------------------------------

def _find_child(parent, name):
    for child in parent.children:
        if child.name == name:
            return child
    return None


def _get_or_create_collection(parent, name):
    found = _find_child(parent, name)
    if found:
        return found
    coll = bpy.data.collections.new(name)
    parent.children.link(coll)
    return coll


def _remove_collection_tree(coll):
    for child in list(coll.children):
        _remove_collection_tree(child)
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(coll)


def _remove_named_child(parent, name):
    coll = _find_child(parent, name)
    if coll:
        _remove_collection_tree(coll)
        return True
    return False


def _root_collection(scene):
    return _get_or_create_collection(scene.collection, ROOT_NAME)


def _iter_collection_objects_recursive(coll):
    for obj in coll.objects:
        yield obj
    for child in coll.children:
        yield from _iter_collection_objects_recursive(child)


def _focus_generated_chess_view(scene):
    """Frame the generated board and piece sets in the active 3D viewport."""
    root = _find_child(scene.collection, ROOT_NAME)
    if not root:
        return False

    targets = [obj for obj in _iter_collection_objects_recursive(root) if obj and obj.type in {'MESH', 'EMPTY'}]
    mesh_targets = [obj for obj in targets if obj.type == 'MESH']
    if not mesh_targets:
        return False

    window = bpy.context.window
    if window is None:
        return False
    screen = window.screen
    if screen is None:
        return False

    area = next((a for a in screen.areas if a.type == 'VIEW_3D'), None)
    if area is None:
        return False
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return False
    space = next((s for s in area.spaces if s.type == 'VIEW_3D'), None)
    if space is None:
        return False

    view_layer = bpy.context.view_layer
    active_prev = view_layer.objects.active
    selected_prev = list(bpy.context.selected_objects)

    try:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in mesh_targets:
            obj.select_set(True)
        view_layer.objects.active = mesh_targets[0]
        with bpy.context.temp_override(window=window, screen=screen, area=area, region=region, space_data=space, scene=scene, view_layer=view_layer):
            bpy.ops.view3d.view_selected(use_all_regions=False)
        return True
    except Exception:
        return False
    finally:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected_prev:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if active_prev and active_prev.name in bpy.data.objects:
            view_layer.objects.active = active_prev


def _join_objects_as_single(collection, objects, final_name):
    """Join objects into one selectable mesh object while preserving material slots."""
    mesh_objects = [obj for obj in objects if obj and obj.type == 'MESH']
    if not mesh_objects:
        return None
    if len(mesh_objects) == 1:
        mesh_objects[0].name = final_name
        return mesh_objects[0]

    view_layer = bpy.context.view_layer
    active_prev = view_layer.objects.active
    selected_prev = list(bpy.context.selected_objects)

    try:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in mesh_objects:
            obj.select_set(True)
        view_layer.objects.active = mesh_objects[0]
        bpy.ops.object.join()
        merged = view_layer.objects.active
        if merged is not None:
            merged.name = final_name
            merged.data.name = final_name + '_Mesh'
        return merged
    finally:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected_prev:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if active_prev and active_prev.name in bpy.data.objects:
            view_layer.objects.active = active_prev


# -----------------------------------------------------------------------------
# Mesh construction helpers
# -----------------------------------------------------------------------------

def _new_mesh_object(name, verts, faces, collection, parent=None, smooth=False):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if parent:
        obj.parent = parent

    if smooth:
        for poly in mesh.polygons:
            poly.use_smooth = True
    return obj


def _box(name, size, location, collection, parent=None, rotation=(0, 0, 0)):
    sx, sy, sz = size
    x = sx * 0.5
    y = sy * 0.5
    z = sz * 0.5
    verts = [
        (-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
        (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z),
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    obj = _new_mesh_object(name, verts, faces, collection, parent)
    obj.location = location
    obj.rotation_euler = rotation
    return obj


def _lathe(name, profile, segments, collection, parent=None,
           location=(0, 0, 0), rotation=(0, 0, 0), smooth=True):
    """Spin an (radius, z) profile around Z. Handles pole vertices at radius=0."""
    verts = []
    rings = []
    eps = 1e-6

    for radius, z in profile:
        if abs(radius) <= eps:
            rings.append([len(verts)])
            verts.append((0.0, 0.0, z))
        else:
            ring = []
            for i in range(segments):
                a = 2.0 * pi * i / segments
                ring.append(len(verts))
                verts.append((radius * cos(a), radius * sin(a), z))
            rings.append(ring)

    faces = []
    for a, b in zip(rings[:-1], rings[1:]):
        if len(a) == 1 and len(b) > 1:
            pole = a[0]
            for i in range(segments):
                j = (i + 1) % segments
                faces.append((pole, b[j], b[i]))
        elif len(a) > 1 and len(b) == 1:
            pole = b[0]
            for i in range(segments):
                j = (i + 1) % segments
                faces.append((a[i], a[j], pole))
        else:
            for i in range(segments):
                j = (i + 1) % segments
                faces.append((a[i], a[j], b[j], b[i]))

    if len(rings[0]) > 1:
        c = len(verts)
        verts.append((0.0, 0.0, profile[0][1]))
        ring = rings[0]
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((c, ring[i], ring[j]))

    if len(rings[-1]) > 1:
        c = len(verts)
        verts.append((0.0, 0.0, profile[-1][1]))
        ring = rings[-1]
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((c, ring[j], ring[i]))

    obj = _new_mesh_object(name, verts, faces, collection, parent, smooth=smooth)
    obj.location = location
    obj.rotation_euler = rotation
    return obj


def _sphere(name, radius, collection, parent=None, location=(0, 0, 0),
            scale=(1, 1, 1), segments=32, rings=12, rotation=(0, 0, 0)):
    profile = []
    for j in range(rings + 1):
        t = -0.5 * pi + pi * j / rings
        profile.append((radius * cos(t), radius * sin(t)))
    obj = _lathe(name, profile, max(12, segments), collection, parent,
                 location, rotation=rotation, smooth=True)
    obj.scale = scale
    return obj


def _leaf(name, width, height, thickness, collection, parent=None,
          location=(0, 0, 0), rotation=(0, 0, 0)):
    """Faceted pointed vesica/leaf prism aligned vertically along local +Z."""
    outline = [
        (0.0, 0.0),
        (-0.48 * width, 0.30 * height),
        (-0.34 * width, 0.68 * height),
        (0.0, height),
        (0.34 * width, 0.68 * height),
        (0.48 * width, 0.30 * height),
    ]
    y0 = -thickness * 0.5
    y1 = thickness * 0.5
    verts = [(x, y0, z) for x, z in outline] + [(x, y1, z) for x, z in outline]
    n = len(outline)
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))

    obj = _new_mesh_object(name, verts, faces, collection, parent, smooth=False)
    obj.location = location
    obj.rotation_euler = rotation
    return obj


def _tube(name, points, radius, collection, parent=None, resolution=2,
          location=(0, 0, 0), rotation=(0, 0, 0)):
    curve = bpy.data.curves.new(name + "_Curve", type='CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = 1
    curve.bevel_depth = radius
    curve.bevel_resolution = resolution
    try:
        curve.use_fill_caps = True
    except AttributeError:
        pass

    spline = curve.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for p, co in zip(spline.points, points):
        p.co = (co[0], co[1], co[2], 1.0)

    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    if parent:
        obj.parent = parent
    obj.location = location
    obj.rotation_euler = rotation
    return obj


def _empty(name, collection, location=(0, 0, 0), rotation_z=0.0):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = 'PLAIN_AXES'
    obj.empty_display_size = 0.18
    collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler[2] = rotation_z
    return obj


def _bipyramid(name, radius, height, collection, parent=None,
               location=(0, 0, 0), rotation=(0, 0, 0), sides=6):
    verts = []
    half = height * 0.5
    for i in range(sides):
        a = 2.0 * pi * i / sides
        verts.append((radius * cos(a), radius * sin(a), 0.0))
    bottom = len(verts)
    verts.append((0.0, 0.0, -half))
    top = len(verts)
    verts.append((0.0, 0.0, half))

    faces = []
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((bottom, j, i))
        faces.append((top, i, j))

    obj = _new_mesh_object(name, verts, faces, collection, parent, smooth=False)
    obj.location = location
    obj.rotation_euler = rotation
    return obj


def _cone(name, radius, height, collection, parent=None, location=(0, 0, 0),
          rotation=(0, 0, 0), segments=24):
    profile = [(radius, 0.0), (radius * 0.82, height * 0.18), (0.0, height)]
    return _lathe(name, profile, segments, collection, parent, location, rotation, smooth=True)


def _leaf_with_vein(name, width, height, thickness, collection, parent=None,
                    location=(0, 0, 0), rotation=(0, 0, 0), vein=True):
    leaf = _leaf(name, width, height, thickness, collection, parent, location, rotation)
    if vein:
        vein_y = thickness * 0.58
        _tube(name + "_Vein", [
            (0.0, vein_y, 0.08 * height),
            (0.0, vein_y, 0.52 * height),
            (0.0, vein_y, 0.88 * height),
        ], max(thickness * 0.12, width * 0.025), collection, parent, resolution=1,
              location=location, rotation=rotation)
    return leaf


def _radial_leaf_ring(prefix, count, radius, z, width, height, thickness,
                      collection, parent, tilt=0.0, veins=False, phase=0.0):
    for i in range(count):
        a = phase + 2.0 * pi * i / count
        x = radius * cos(a)
        y = radius * sin(a)
        # Local Y is the leaf thickness axis. Rotate it approximately radial.
        rz = a - 0.5 * pi
        maker = _leaf_with_vein if veins else _leaf
        maker(
            f"{prefix}_{i+1}", width, height, thickness,
            collection, parent,
            location=(x, y, z),
            rotation=(0.0, tilt, rz),
        )


def _body_ribs(prefix, count, lower_z, upper_z, lower_r, upper_r, radius,
               collection, parent, phase=0.0, bow=0.04):
    for i in range(count):
        a = phase + 2.0 * pi * i / count
        c, s = cos(a), sin(a)
        mid_r = max(lower_r, upper_r) + bow
        pts = [
            (lower_r * c, lower_r * s, lower_z),
            (mid_r * c, mid_r * s, (lower_z + upper_z) * 0.5),
            (upper_r * c, upper_r * s, upper_z),
        ]
        _tube(f"{prefix}_Rib_{i+1}", pts, radius, collection, parent, resolution=1)


# -----------------------------------------------------------------------------
# Board render materials
# -----------------------------------------------------------------------------

def _ensure_board_material(kind, role):
    """Create/reuse board materials while keeping Solid viewport neutral gray."""
    name = f"FantasyChess_Board_{kind.title()}_{role.title()}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (0.58, 0.58, 0.58, 1.0)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (520, 0)

    if kind == 'GLASS':
        # Clearer translucent glass with a very subtle micro-texture. The material
        # keeps enough tint to preserve the checker pattern without reading as
        # smoky opaque glass or a dark mirror.
        glass = nodes.new("ShaderNodeBsdfGlass")
        glass.location = (190, 100)
        diffuse = nodes.new("ShaderNodeBsdfDiffuse")
        diffuse.location = (190, -25)
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        transparent.location = (190, -185)
        mix_surface = nodes.new("ShaderNodeMixShader")
        mix_surface.location = (410, 45)
        mix_final = nodes.new("ShaderNodeMixShader")
        mix_final.location = (610, 0)

        # Fine, low-strength surface variation keeps the glass from looking
        # perfectly CG-smooth while remaining polished and transparent.
        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-600, 175)
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-390, 175)
        bump = nodes.new("ShaderNodeBump")
        bump.location = (-80, 175)
        links.new(texcoord.outputs.get("Generated"), noise.inputs.get("Vector"))
        links.new(noise.outputs.get("Fac"), bump.inputs.get("Height"))
        links.new(bump.outputs.get("Normal"), glass.inputs.get("Normal"))
        noise.inputs.get("Scale").default_value = 38.0
        noise.inputs.get("Detail").default_value = 2.0
        noise.inputs.get("Roughness").default_value = 0.36
        _set_node_input(bump, "Strength", 0.035)
        _set_node_input(bump, "Distance", 0.035)

        if role == 'LIGHT':
            glass_color = (0.985, 0.992, 1.0, 1.0)
            diffuse_color = (0.82, 0.88, 0.96, 1.0)
            roughness = 0.032
            surface_mix = 0.050
            transparent_mix = 0.22
        elif role == 'DARK':
            glass_color = (0.34, 0.43, 0.56, 1.0)
            diffuse_color = (0.16, 0.22, 0.32, 1.0)
            roughness = 0.042
            surface_mix = 0.070
            transparent_mix = 0.26
        else:
            glass_color = (0.46, 0.42, 0.40, 1.0)
            diffuse_color = (0.20, 0.18, 0.17, 1.0)
            roughness = 0.038
            surface_mix = 0.060
            transparent_mix = 0.20

        _set_node_input(glass, "Color", glass_color)
        _set_node_input(glass, "Roughness", roughness)
        _set_node_input(glass, "IOR", 1.45)
        _set_node_input(diffuse, "Color", diffuse_color)
        _set_node_input(diffuse, "Roughness", 0.42)
        _set_node_input(transparent, "Color", (1.0, 1.0, 1.0, 1.0))

        # A small diffuse contribution gives the squares definition; the larger
        # transparent contribution makes the board noticeably more translucent.
        mix_surface.inputs[0].default_value = surface_mix
        mix_final.inputs[0].default_value = transparent_mix
        links.new(glass.outputs.get("BSDF"), mix_surface.inputs[1])
        links.new(diffuse.outputs.get("BSDF"), mix_surface.inputs[2])
        links.new(mix_surface.outputs.get("Shader"), mix_final.inputs[1])
        links.new(transparent.outputs.get("BSDF"), mix_final.inputs[2])
        links.new(mix_final.outputs.get("Shader"), output.inputs.get("Surface"))
        return mat

    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (220, 0)
    links.new(principled.outputs.get("BSDF"), output.inputs.get("Surface"))

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-760, 20)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-580, 20)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-350, 20)
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-90, 40)
    links.new(texcoord.outputs.get("Generated"), mapping.inputs.get("Vector"))
    links.new(mapping.outputs.get("Vector"), noise.inputs.get("Vector"))
    links.new(noise.outputs.get("Fac"), ramp.inputs.get("Fac"))
    links.new(ramp.outputs.get("Color"), principled.inputs.get("Base Color"))

    cr = ramp.color_ramp
    e0, e1 = cr.elements[0], cr.elements[1]
    e0.position = 0.22
    e1.position = 0.78

    if kind == 'STONE':
        mapping.inputs.get("Scale").default_value = (2.2, 2.2, 2.2)
        noise.inputs.get("Scale").default_value = 4.5
        noise.inputs.get("Detail").default_value = 5.0
        noise.inputs.get("Roughness").default_value = 0.72
        if role == 'LIGHT':
            e0.color = (0.34, 0.32, 0.28, 1.0)
            e1.color = (0.88, 0.85, 0.76, 1.0)
        elif role == 'DARK':
            e0.color = (0.018, 0.020, 0.022, 1.0)
            e1.color = (0.16, 0.18, 0.20, 1.0)
        else:
            e0.color = (0.055, 0.050, 0.045, 1.0)
            e1.color = (0.30, 0.28, 0.25, 1.0)
        # Slightly polished stone so piece reflections are visible while the board
        # still reads as stone rather than glossy plastic.
        _set_node_input(principled, "Roughness", 0.18 if role != 'FRAME' else 0.24)
        _set_node_input(principled, ("Coat Weight", "Clearcoat"), 0.22)
        _set_node_input(principled, ("Coat Roughness", "Clearcoat Roughness"), 0.10)
    elif kind == 'METAL':
        mapping.inputs.get("Scale").default_value = (8.0, 8.0, 8.0)
        noise.inputs.get("Scale").default_value = 7.0
        noise.inputs.get("Detail").default_value = 8.0
        noise.inputs.get("Roughness").default_value = 0.40
        if noise.inputs.get("Distortion") is not None:
            noise.inputs.get("Distortion").default_value = 0.04
        if role == 'LIGHT':
            e0.color = (0.56, 0.58, 0.62, 1.0)
            e1.color = (0.92, 0.94, 0.98, 1.0)
        elif role == 'DARK':
            e0.color = (0.06, 0.07, 0.08, 1.0)
            e1.color = (0.24, 0.26, 0.30, 1.0)
        else:
            e0.color = (0.25, 0.16, 0.06, 1.0)
            e1.color = (0.78, 0.58, 0.22, 1.0)
        _set_node_input(principled, "Metallic", 1.0)
        _set_node_input(principled, "Roughness", 0.12 if role != 'FRAME' else 0.18)
        _set_node_input(principled, ("Coat Weight", "Clearcoat"), 0.08)
        _set_node_input(principled, ("Coat Roughness", "Clearcoat Roughness"), 0.08)
    else:
        # Broad directional grain gives the board a readable wood surface in renders.
        mapping.inputs.get("Scale").default_value = (5.5, 1.4, 0.8)
        noise.inputs.get("Scale").default_value = 3.0
        noise.inputs.get("Detail").default_value = 4.0
        noise.inputs.get("Roughness").default_value = 0.62
        if noise.inputs.get("Distortion") is not None:
            noise.inputs.get("Distortion").default_value = 0.22
        if role == 'LIGHT':
            e0.color = (0.20, 0.075, 0.022, 1.0)
            e1.color = (0.82, 0.46, 0.16, 1.0)
        elif role == 'DARK':
            e0.color = (0.010, 0.004, 0.002, 1.0)
            e1.color = (0.16, 0.035, 0.010, 1.0)
        else:
            e0.color = (0.025, 0.007, 0.003, 1.0)
            e1.color = (0.30, 0.075, 0.018, 1.0)
        # A lacquered wood finish gives visible reflections without losing the wood grain.
        _set_node_input(principled, "Roughness", 0.20 if role != 'FRAME' else 0.24)
        _set_node_input(principled, ("Coat Weight", "Clearcoat"), 0.28)
        _set_node_input(principled, ("Coat Roughness", "Clearcoat Roughness"), 0.10)

    return mat


def _assign_render_material(obj, material):
    if obj is None or obj.type != 'MESH' or material is None:
        return
    obj.data.materials.clear()
    obj.data.materials.append(material)
    obj.color = (0.58, 0.58, 0.58, 1.0)


def _board_role_from_object(obj):
    name = obj.name
    if name.startswith("Tile_") and len(name) >= 7:
        square = name.split("_", 1)[1]
        try:
            file_index = ord(square[0].upper()) - ord('A')
            rank_index = int(square[1:]) - 1
            return 'DARK' if (file_index + rank_index) % 2 == 0 else 'LIGHT'
        except (ValueError, IndexError):
            return 'LIGHT'
    return 'FRAME'


def _board_role_from_material_name(name):
    lname = (name or '').lower()
    if '_light' in lname:
        return 'LIGHT'
    if '_dark' in lname:
        return 'DARK'
    return 'FRAME'


def apply_board_material(scene):
    root = _find_child(scene.collection, ROOT_NAME)
    if not root:
        return 0
    board = _find_child(root, BOARD_NAME)
    if not board:
        return 0

    kind = scene.elf_chess_board_material
    mats = {
        'LIGHT': _ensure_board_material(kind, 'LIGHT'),
        'DARK': _ensure_board_material(kind, 'DARK'),
        'FRAME': _ensure_board_material(kind, 'FRAME'),
    }
    count = 0
    for obj in board.objects:
        if obj.type != 'MESH':
            continue
        # If the board has been joined into one object, update its material slots
        # rather than replacing the whole object with a single material.
        if len(obj.material_slots) > 1:
            for slot in obj.material_slots:
                role = _board_role_from_material_name(slot.material.name if slot.material else '')
                slot.material = mats[role]
            obj.color = (0.58, 0.58, 0.58, 1.0)
        else:
            _assign_render_material(obj, mats[_board_role_from_object(obj)])
        count += 1
    return count


# -----------------------------------------------------------------------------
# Board
# -----------------------------------------------------------------------------

def build_board(scene):
    root = _root_collection(scene)
    _remove_named_child(root, BOARD_NAME)
    coll = _get_or_create_collection(root, BOARD_NAME)

    s = scene.elf_chess_square_size
    base_h = scene.elf_chess_board_base_height
    tile_h = scene.elf_chess_tile_height
    border = scene.elf_chess_border_width
    gap = min(scene.elf_chess_tile_gap, s * 0.18)
    geometry_mode = getattr(scene, "elf_chess_board_geometry", 'JOINED')

    board = 8.0 * s
    outer = board + 2.0 * border

    _box("Board_Base", (outer, outer, base_h), (0.0, 0.0, base_h * 0.5), coll)

    tile_size = max(0.05, s - gap)
    tile_z = base_h + tile_h * 0.5
    for rank in range(8):
        for file in range(8):
            x = (file - 3.5) * s
            y = (rank - 3.5) * s
            _box(
                f"Tile_{chr(65 + file)}{rank + 1}",
                (tile_size, tile_size, tile_h),
                (x, y, tile_z),
                coll,
            )

    rail_h = tile_h * 1.45
    rail_z = base_h + rail_h * 0.5
    rail_t = border * 0.62
    _box("Border_N", (outer, rail_t, rail_h), (0, board * 0.5 + border * 0.5, rail_z), coll)
    _box("Border_S", (outer, rail_t, rail_h), (0, -board * 0.5 - border * 0.5, rail_z), coll)
    _box("Border_E", (rail_t, board, rail_h), (board * 0.5 + border * 0.5, 0, rail_z), coll)
    _box("Border_W", (rail_t, board, rail_h), (-board * 0.5 - border * 0.5, 0, rail_z), coll)

    # Broad lozenge corner inlays keep the board decorative without leaf motifs
    # or thin protrusions. Leaves are reserved for pawns in v0.3.
    corner = board * 0.5 + border * 0.52
    corner_size = min(border * 0.72, s * 0.34)
    corner_z = base_h + rail_h * 0.78
    for i, (x, y) in enumerate([
        (corner, corner), (-corner, corner),
        (-corner, -corner), (corner, -corner),
    ]):
        _box(
            f"Board_Lozenge_{i+1}",
            (corner_size, corner_size, max(tile_h * 0.32, 0.025)),
            (x, y, corner_z), coll,
            rotation=(0, 0, radians(45)),
        )

    apply_board_material(scene)

    if geometry_mode == 'SEPARATE':
        base_objects = []
        tile_objects = []
        for obj in list(coll.objects):
            if obj.name.startswith("Tile_"):
                tile_objects.append(obj)
            else:
                base_objects.append(obj)

        base = _join_objects_as_single(coll, base_objects, "Chess_Board_Base")
        if base is not None:
            base["elf_chess_board"] = True
            base["elf_chess_board_base"] = True
            base["elf_chess_generator"] = True
            base.color = (0.58, 0.58, 0.58, 1.0)

        for tile in tile_objects:
            tile["elf_chess_board"] = True
            tile["elf_chess_board_tile"] = True
            tile["elf_chess_generator"] = True
            tile.color = (0.58, 0.58, 0.58, 1.0)
    else:
        merged = _join_objects_as_single(coll, list(coll.objects), "Chess_Board")
        if merged is not None:
            merged["elf_chess_board"] = True
            merged["elf_chess_generator"] = True
            merged.color = (0.58, 0.58, 0.58, 1.0)

    _focus_generated_chess_view(scene)
    return coll


def remove_board(scene):
    root = _find_child(scene.collection, ROOT_NAME)
    if not root:
        return False
    return _remove_named_child(root, BOARD_NAME)


# -----------------------------------------------------------------------------
# Piece design helpers
# -----------------------------------------------------------------------------

# v0.3 design rule: all non-pawn ornament is broad, compact, and substantially
# attached to the main mass. No antlers, wire-like ribs, tall spikes, or thin
# leaf crowns. Leaf geometry is deliberately reserved for pawns.


def _scaled_profile(points, scale):
    return [(r * scale, z * scale) for r, z in points]


def _standard_body(name, scale, segments, collection, parent, profile=None):
    if profile is None:
        profile = [
            (0.34, 0.00), (0.42, 0.05), (0.43, 0.10), (0.39, 0.15),
            (0.31, 0.22), (0.27, 0.31), (0.22, 0.41), (0.18, 0.64),
            (0.22, 0.73), (0.22, 0.78), (0.19, 0.82),
        ]
    return _lathe(name, _scaled_profile(profile, scale), segments, collection, parent)


def _outline_prism(name, outline, depth, collection, parent=None,
                   location=(0, 0, 0), rotation=(0, 0, 0)):
    """Extrude an X/Z polygon through local Y. Used for thick armor plates."""
    y0 = -depth * 0.5
    y1 = depth * 0.5
    verts = [(x, y0, z) for x, z in outline] + [(x, y1, z) for x, z in outline]
    n = len(outline)
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    obj = _new_mesh_object(name, verts, faces, collection, parent, smooth=False)
    obj.location = location
    obj.rotation_euler = rotation
    return obj


def _detail_band(name, scale, segments, collection, parent, z, radius,
                 height=0.07, projection=0.035):
    """A substantial raised ring; dimensions are normalized to piece scale."""
    r0 = max(0.02, radius - 0.025)
    r1 = radius + projection
    h = height * 0.5
    profile = [
        (r0 * scale, (z - h) * scale),
        (r1 * scale, (z - h * 0.62) * scale),
        (r1 * scale, (z + h * 0.62) * scale),
        (r0 * scale, (z + h) * scale),
    ]
    return _lathe(name, profile, segments, collection, parent)


def _bead_ring(prefix, count, ring_radius, z, bead_radius, scale,
               segments, collection, parent, squash=1.0, phase=0.0):
    """Half-embedded rounded studs for durable surface detail."""
    for i in range(count):
        a = phase + 2.0 * pi * i / count
        r = ring_radius * scale
        _sphere(
            f"{prefix}_{i+1}", 1.0, collection, parent,
            location=(r * cos(a), r * sin(a), z * scale),
            scale=(bead_radius * scale, bead_radius * scale,
                   bead_radius * squash * scale),
            segments=max(12, segments // 3), rings=8,
        )


def _boss_ring(prefix, count, ring_radius, z, boss_radius, boss_depth, scale,
               collection, parent, sides=6, phase=0.0):
    """Faceted gems/shields embedded radially in the piece body."""
    for i in range(count):
        a = phase + 2.0 * pi * i / count
        r = ring_radius * scale
        _bipyramid(
            f"{prefix}_{i+1}", boss_radius * scale, boss_depth * scale,
            collection, parent,
            location=(r * cos(a), r * sin(a), z * scale),
            rotation=(0, radians(90), a), sides=sides,
        )


def _flute_ring(prefix, count, ring_radius, z, width, depth, height, scale,
                segments, collection, parent, phase=0.0):
    """Broad vertical flutes made from overlapping ellipsoids, not thin rods."""
    for i in range(count):
        a = phase + 2.0 * pi * i / count
        r = ring_radius * scale
        _sphere(
            f"{prefix}_{i+1}", 1.0, collection, parent,
            location=(r * cos(a), r * sin(a), z * scale),
            scale=(width * scale, depth * scale, height * scale),
            segments=max(12, segments // 3), rings=8,
            rotation=(0, 0, a),
        )


def _crenellation_ring(prefix, count, ring_radius, z, tangential, radial,
                       height, scale, collection, parent, phase=0.0):
    """Chunky rook/architectural crown blocks."""
    for i in range(count):
        a = phase + 2.0 * pi * i / count
        r = ring_radius * scale
        _box(
            f"{prefix}_{i+1}",
            (tangential * scale, radial * scale, height * scale),
            (r * cos(a), r * sin(a), z * scale), collection, parent,
            rotation=(0, 0, a),
        )


def _pawn(name, scale, segments, collection, parent):
    profile = [
        (0.31, 0.00), (0.39, 0.05), (0.40, 0.10), (0.36, 0.15),
        (0.28, 0.22), (0.24, 0.30), (0.20, 0.39), (0.155, 0.56),
        (0.145, 0.70), (0.19, 0.76), (0.19, 0.81), (0.15, 0.85),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.17, 0.31, 0.055, 0.022)
    _detail_band(name + "_BudCollar", scale, segments, collection, parent, 0.79, 0.17, 0.06, 0.025)

    # Pawn-specific leaf relief: broad, thick, and close to the body.
    for i in range(4):
        a = pi / 4 + 2.0 * pi * i / 4
        r = 0.17 * scale
        _leaf(
            f"{name}_BodyLeaf_{i+1}", 0.17 * scale, 0.29 * scale, 0.075 * scale,
            collection, parent,
            location=(r * cos(a), r * sin(a), 0.38 * scale),
            rotation=(0, radians(12), a - pi * 0.5),
        )

    _sphere(name + "_Bud", 1.0, collection, parent,
            location=(0, 0, 0.96 * scale),
            scale=(0.16 * scale, 0.16 * scale, 0.18 * scale),
            segments=max(16, segments // 2), rings=10)

    # Four sturdy sepals overlap the bud; these are the only free-standing leaf
    # forms in the set and intentionally stay thick enough to avoid twiggy detail.
    for i in range(4):
        a = 2.0 * pi * i / 4
        r = 0.075 * scale
        _leaf(
            f"{name}_Sepal_{i+1}", 0.15 * scale, 0.27 * scale, 0.070 * scale,
            collection, parent,
            location=(r * cos(a), r * sin(a), 0.86 * scale),
            rotation=(0, radians(18), a - pi * 0.5),
        )


def _rook(name, scale, segments, collection, parent):
    profile = [
        (0.36, 0.00), (0.44, 0.05), (0.45, 0.11), (0.40, 0.16),
        (0.32, 0.23), (0.29, 0.31), (0.255, 0.41), (0.245, 0.72),
        (0.28, 0.80), (0.32, 0.85), (0.33, 0.95), (0.32, 1.02),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_LowerBand", scale, segments, collection, parent, 0.24, 0.31, 0.075, 0.030)
    _detail_band(name + "_UpperBand", scale, segments, collection, parent, 0.79, 0.28, 0.075, 0.030)
    _detail_band(name + "_CrownBand", scale, segments, collection, parent, 0.96, 0.32, 0.065, 0.025)

    # Thick tower buttresses and inset faceted window bosses.
    _flute_ring(name + "_Buttress", 8, 0.255, 0.53, 0.055, 0.085, 0.23,
                scale, segments, collection, parent, phase=pi / 8)
    _boss_ring(name + "_Window", 8, 0.255, 0.58, 0.055, 0.075,
               scale, collection, parent, sides=6, phase=pi / 8)

    # Replace the boxy roofline with rounded battlements so the crown still reads
    # as a rook but no longer feels too square on top.
    _detail_band(name + "_ParapetBase", scale, segments, collection, parent, 1.03, 0.29, 0.070, 0.030)
    for i in range(8):
        a = pi / 8 + 2.0 * pi * i / 8
        r = 0.245 * scale
        _sphere(
            f"{name}_Merlon_{i+1}", 1.0, collection, parent,
            location=(r * cos(a), r * sin(a), 1.095 * scale),
            scale=(0.085 * scale, 0.085 * scale, 0.115 * scale),
            segments=max(12, segments // 3), rings=8,
        )
    _detail_band(name + "_RoofCollar", scale, segments, collection, parent, 1.08, 0.19, 0.060, 0.018)
    _sphere(name + "_RoofBoss", 1.0, collection, parent,
            location=(0, 0, 1.075 * scale),
            scale=(0.16 * scale, 0.16 * scale, 0.095 * scale),
            segments=max(16, segments // 2), rings=8)


def _knight(name, scale, segments, collection, parent):
    profile = [
        (0.35, 0.00), (0.43, 0.05), (0.44, 0.10), (0.39, 0.15),
        (0.31, 0.22), (0.27, 0.30), (0.22, 0.39), (0.19, 0.57),
        (0.18, 0.66), (0.23, 0.72), (0.21, 0.78),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.23, 0.31, 0.070, 0.028)
    _detail_band(name + "_Collar", scale, segments, collection, parent, 0.68, 0.21, 0.085, 0.035)
    _boss_ring(name + "_HarnessBoss", 4, 0.215, 0.52, 0.065, 0.080,
               scale, collection, parent, sides=6, phase=pi / 4)

    # The neck is made from overlapping solid masses rather than a narrow curve.
    neck_parts = [
        ((0, 0.00, 0.79), (0.17, 0.17, 0.20), radians(-4)),
        ((0, 0.05, 0.94), (0.17, 0.18, 0.21), radians(-10)),
        ((0, 0.11, 1.08), (0.17, 0.19, 0.20), radians(-16)),
        ((0, 0.18, 1.19), (0.17, 0.20, 0.17), radians(-20)),
    ]
    for idx, (loc, scl, rx) in enumerate(neck_parts, 1):
        _sphere(
            f"{name}_NeckMass_{idx}", 1.0, collection, parent,
            location=tuple(v * scale for v in loc),
            scale=tuple(v * scale for v in scl),
            segments=max(16, segments // 2), rings=10,
            rotation=(rx, 0, 0),
        )

    _sphere(name + "_Head", 1.0, collection, parent,
            location=(0, 0.24 * scale, 1.26 * scale),
            scale=(0.18 * scale, 0.26 * scale, 0.21 * scale),
            segments=max(18, segments // 2), rings=10)
    _sphere(name + "_Muzzle", 1.0, collection, parent,
            location=(0, 0.44 * scale, 1.20 * scale),
            scale=(0.14 * scale, 0.19 * scale, 0.11 * scale),
            segments=max(18, segments // 2), rings=10)

    # Thick triangular ears, cheek guards, brow plate, and stacked mane plates.
    ear = [(-0.065 * scale, 0), (0.065 * scale, 0), (0, 0.19 * scale)]
    _outline_prism(name + "_Ear_L", ear, 0.11 * scale, collection, parent,
                   location=(-0.095 * scale, 0.17 * scale, 1.31 * scale),
                   rotation=(radians(-7), radians(-8), radians(-5)))
    _outline_prism(name + "_Ear_R", ear, 0.11 * scale, collection, parent,
                   location=(0.095 * scale, 0.17 * scale, 1.31 * scale),
                   rotation=(radians(-7), radians(8), radians(5)))

    _sphere(name + "_BrowGuard", 1.0, collection, parent,
            location=(0, 0.385 * scale, 1.29 * scale),
            scale=(0.135 * scale, 0.055 * scale, 0.085 * scale),
            segments=max(14, segments // 3), rings=8)
    for side, sx in (("L", -1), ("R", 1)):
        _sphere(name + f"_CheekGuard_{side}", 1.0, collection, parent,
                location=(sx * 0.13 * scale, 0.25 * scale, 1.22 * scale),
                scale=(0.065 * scale, 0.075 * scale, 0.105 * scale),
                segments=max(12, segments // 3), rings=8)

    mane_outline = [
        (-0.085 * scale, -0.075 * scale),
        (0.085 * scale, -0.075 * scale),
        (0.075 * scale, 0.075 * scale),
        (-0.075 * scale, 0.075 * scale),
    ]
    for i, z in enumerate((0.86, 0.98, 1.10, 1.22), 1):
        _outline_prism(
            f"{name}_ManePlate_{i}", mane_outline, 0.15 * scale,
            collection, parent,
            location=(0, -0.115 * scale, z * scale),
            rotation=(radians(4), 0, 0),
        )


def _bishop(name, scale, segments, collection, parent):
    profile = [
        (0.34, 0.00), (0.42, 0.05), (0.43, 0.10), (0.38, 0.15),
        (0.30, 0.22), (0.26, 0.31), (0.21, 0.41), (0.16, 0.69),
        (0.19, 0.84), (0.24, 0.92), (0.22, 1.00), (0.18, 1.06),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.23, 0.30, 0.070, 0.027)
    _detail_band(name + "_WaistBand", scale, segments, collection, parent, 0.48, 0.205, 0.060, 0.025)
    _detail_band(name + "_Collar", scale, segments, collection, parent, 0.91, 0.23, 0.075, 0.030)
    _flute_ring(name + "_RobeFlute", 6, 0.19, 0.62, 0.045, 0.070, 0.18,
                scale, segments, collection, parent, phase=pi / 6)
    _boss_ring(name + "_CollarGem", 6, 0.205, 0.88, 0.052, 0.072,
               scale, collection, parent, sides=6, phase=pi / 6)

    # A single substantial mitre mass with an embedded broad diagonal sash.
    _sphere(name + "_Mitre", 1.0, collection, parent,
            location=(0, 0, 1.23 * scale),
            scale=(0.21 * scale, 0.21 * scale, 0.30 * scale),
            segments=max(18, segments // 2), rings=10)
    _bipyramid(name + "_MitreCap", 0.13 * scale, 0.18 * scale,
               collection, parent, location=(0, 0, 1.50 * scale), sides=6)

    sash = [
        (-0.11 * scale, -0.18 * scale),
        (-0.03 * scale, -0.18 * scale),
        (0.11 * scale, 0.18 * scale),
        (0.03 * scale, 0.18 * scale),
    ]
    _outline_prism(name + "_MitreSlash", sash, 0.080 * scale,
                   collection, parent,
                   location=(0, 0.175 * scale, 1.23 * scale))
    _bipyramid(name + "_FrontGem", 0.075 * scale, 0.085 * scale,
               collection, parent, location=(0, 0.205 * scale, 1.08 * scale),
               rotation=(radians(90), 0, 0), sides=8)


def _queen(name, scale, segments, collection, parent):
    profile = [
        (0.37, 0.00), (0.45, 0.05), (0.46, 0.10), (0.41, 0.15),
        (0.32, 0.23), (0.28, 0.32), (0.22, 0.42), (0.17, 0.76),
        (0.22, 0.93), (0.28, 1.00), (0.26, 1.08), (0.20, 1.14),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.23, 0.32, 0.075, 0.030)
    _detail_band(name + "_WaistBand", scale, segments, collection, parent, 0.50, 0.205, 0.060, 0.024)
    _detail_band(name + "_ShoulderBand", scale, segments, collection, parent, 0.91, 0.23, 0.075, 0.030)
    _flute_ring(name + "_RobeFlute", 8, 0.19, 0.65, 0.040, 0.065, 0.19,
                scale, segments, collection, parent, phase=pi / 8)
    _boss_ring(name + "_BeltGem", 8, 0.205, 0.49, 0.045, 0.065,
               scale, collection, parent, sides=8, phase=pi / 8)
    _bead_ring(name + "_Necklace", 8, 0.205, 0.92, 0.050, scale,
               segments, collection, parent, squash=0.85, phase=pi / 8)

    # Give the queen a clear coronet silhouette: lower and broader than the king,
    # with many rounded jewel-tipped points and a small central orb.
    _detail_band(name + "_CrownBand", scale, segments, collection, parent, 1.17, 0.25, 0.090, 0.035)
    _detail_band(name + "_CrownSkirt", scale, segments, collection, parent, 1.23, 0.235, 0.070, 0.020)
    for i in range(8):
        a = pi / 8 + 2.0 * pi * i / 8
        r = 0.205 * scale
        _bipyramid(
            f"{name}_CrownPoint_{i+1}", 0.060 * scale, 0.18 * scale,
            collection, parent,
            location=(r * cos(a), r * sin(a), 1.34 * scale),
            rotation=(0, radians(90), a), sides=6,
        )
        _sphere(
            f"{name}_CrownPearl_{i+1}", 1.0, collection, parent,
            location=(r * cos(a), r * sin(a), 1.46 * scale),
            scale=(0.045 * scale, 0.045 * scale, 0.045 * scale),
            segments=max(12, segments // 3), rings=8,
        )
    _sphere(name + "_CrownOrb", 1.0, collection, parent,
            location=(0, 0, 1.54 * scale),
            scale=(0.085 * scale, 0.085 * scale, 0.085 * scale),
            segments=max(14, segments // 2), rings=8)


def _king(name, scale, segments, collection, parent):
    profile = [
        (0.38, 0.00), (0.46, 0.05), (0.47, 0.10), (0.42, 0.15),
        (0.33, 0.23), (0.29, 0.32), (0.23, 0.43), (0.18, 0.81),
        (0.23, 0.99), (0.29, 1.06), (0.27, 1.14), (0.20, 1.20),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.23, 0.33, 0.080, 0.032)
    _detail_band(name + "_WaistBand", scale, segments, collection, parent, 0.51, 0.215, 0.065, 0.027)
    _detail_band(name + "_ShoulderBand", scale, segments, collection, parent, 0.96, 0.24, 0.080, 0.032)
    _flute_ring(name + "_RobeFlute", 8, 0.20, 0.68, 0.043, 0.070, 0.20,
                scale, segments, collection, parent)
    _boss_ring(name + "_RoyalShield", 8, 0.215, 0.52, 0.052, 0.075,
               scale, collection, parent, sides=8, phase=pi / 8)
    _boss_ring(name + "_ShoulderGem", 4, 0.225, 0.96, 0.065, 0.085,
               scale, collection, parent, sides=8, phase=pi / 4)

    # Make the king unmistakable with a heavier crown and a chunky cross finial.
    _detail_band(name + "_CrownBand", scale, segments, collection, parent, 1.22, 0.26, 0.105, 0.040)
    for i in range(4):
        a = pi / 4 + 2.0 * pi * i / 4
        r = 0.18 * scale
        merlon = [
            (-0.065 * scale, -0.11 * scale),
            ( 0.065 * scale, -0.11 * scale),
            ( 0.090 * scale,  0.02 * scale),
            ( 0.000 * scale,  0.16 * scale),
            (-0.090 * scale,  0.02 * scale),
        ]
        _outline_prism(
            f"{name}_CrownMerlon_{i+1}", merlon, 0.12 * scale,
            collection, parent,
            location=(r * cos(a), r * sin(a), 1.36 * scale),
            rotation=(0, radians(90), a),
        )
    _sphere(name + "_CrownCore", 1.0, collection, parent,
            location=(0, 0, 1.47 * scale),
            scale=(0.12 * scale, 0.12 * scale, 0.10 * scale),
            segments=max(16, segments // 2), rings=8)

    cross_stem = [
        (-0.050 * scale, -0.23 * scale),
        ( 0.050 * scale, -0.23 * scale),
        ( 0.050 * scale,  0.23 * scale),
        (-0.050 * scale,  0.23 * scale),
    ]
    cross_arm = [
        (-0.17 * scale, -0.05 * scale),
        ( 0.17 * scale, -0.05 * scale),
        ( 0.17 * scale,  0.05 * scale),
        (-0.17 * scale,  0.05 * scale),
    ]
    _outline_prism(name + "_CrossStem", cross_stem, 0.12 * scale,
                   collection, parent, location=(0, 0, 1.74 * scale))
    _outline_prism(name + "_CrossArm", cross_arm, 0.12 * scale,
                   collection, parent, location=(0, 0, 1.83 * scale))


PIECE_BUILDERS = {
    "Pawn": _pawn,
    "Rook": _rook,
    "Knight": _knight,
    "Bishop": _bishop,
    "Queen": _queen,
    "King": _king,
}


# -----------------------------------------------------------------------------
# Samurai piece style
# -----------------------------------------------------------------------------

def _samurai_pawn(name, scale, segments, collection, parent):
    # Ashigaru-inspired pawn: compact lamellar skirt, armored torso, head, and
    # a low kabuto. Everything stays thick and close to the body.
    profile = [
        (0.31, 0.00), (0.39, 0.05), (0.40, 0.10), (0.36, 0.15),
        (0.29, 0.23), (0.25, 0.32), (0.22, 0.44), (0.18, 0.62),
        (0.18, 0.70), (0.20, 0.75),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.19, 0.31, 0.065, 0.026)
    _detail_band(name + "_LamellarBelt", scale, segments, collection, parent, 0.48, 0.22, 0.075, 0.030)
    _flute_ring(name + "_SkirtPlate", 6, 0.20, 0.39, 0.055, 0.075, 0.16,
                scale, segments, collection, parent, phase=pi / 6)
    _sphere(name + "_Head", 1.0, collection, parent,
            location=(0, 0, 0.84 * scale),
            scale=(0.15 * scale, 0.15 * scale, 0.15 * scale),
            segments=max(16, segments // 2), rings=9)
    # Low kabuto dome and broad brim.
    _sphere(name + "_KabutoDome", 1.0, collection, parent,
            location=(0, 0, 0.95 * scale),
            scale=(0.19 * scale, 0.19 * scale, 0.12 * scale),
            segments=max(16, segments // 2), rings=8)
    _detail_band(name + "_KabutoBrim", scale, segments, collection, parent,
                 0.91, 0.20, 0.060, 0.030)
    # One broad frontal crest, intentionally short and stout.
    crest = [
        (-0.075 * scale, -0.06 * scale),
        ( 0.075 * scale, -0.06 * scale),
        ( 0.055 * scale,  0.08 * scale),
        ( 0.000 * scale,  0.15 * scale),
        (-0.055 * scale,  0.08 * scale),
    ]
    _outline_prism(name + "_KabutoCrest", crest, 0.075 * scale,
                   collection, parent, location=(0, 0.17 * scale, 1.00 * scale))


def _samurai_rook(name, scale, segments, collection, parent):
    # Castle-tower rook with heavy corner posts and layered pagoda eaves.
    profile = [
        (0.36, 0.00), (0.44, 0.05), (0.45, 0.11), (0.40, 0.16),
        (0.32, 0.23), (0.29, 0.31), (0.255, 0.42), (0.255, 0.76),
        (0.29, 0.82), (0.30, 0.87),
    ]
    _standard_body(name + "_Tower", scale, segments, collection, parent, profile)
    _detail_band(name + "_FoundationBand", scale, segments, collection, parent, 0.24, 0.31, 0.075, 0.030)
    _detail_band(name + "_UpperBand", scale, segments, collection, parent, 0.76, 0.28, 0.070, 0.030)
    _boss_ring(name + "_WallBoss", 4, 0.255, 0.55, 0.060, 0.080,
               scale, collection, parent, sides=4, phase=pi / 4)
    for ix in (-1, 1):
        for iy in (-1, 1):
            _box(name + f"_CornerPost_{ix}_{iy}",
                 (0.10 * scale, 0.10 * scale, 0.50 * scale),
                 (ix * 0.20 * scale, iy * 0.20 * scale, 0.56 * scale),
                 collection, parent)

    # Curved pagoda tiers soften the top silhouette while keeping the samurai
    # rook distinct from the elf rook.
    lower_eave_profile = [
        (0.17 * scale, 0.87 * scale),
        (0.24 * scale, 0.88 * scale),
        (0.34 * scale, 0.90 * scale),
        (0.37 * scale, 0.93 * scale),
        (0.30 * scale, 0.97 * scale),
        (0.18 * scale, 0.98 * scale),
    ]
    upper_eave_profile = [
        (0.14 * scale, 0.98 * scale),
        (0.20 * scale, 0.99 * scale),
        (0.28 * scale, 1.01 * scale),
        (0.31 * scale, 1.04 * scale),
        (0.25 * scale, 1.07 * scale),
        (0.15 * scale, 1.08 * scale),
    ]
    _lathe(name + "_LowerEave", lower_eave_profile, segments, collection, parent, smooth=True)
    _lathe(name + "_UpperEave", upper_eave_profile, segments, collection, parent, smooth=True)
    _detail_band(name + "_RoofCollar", scale, segments, collection, parent, 1.08, 0.18, 0.060, 0.020)
    _sphere(name + "_RoofCore", 1.0, collection, parent,
            location=(0, 0, 1.13 * scale),
            scale=(0.14 * scale, 0.14 * scale, 0.09 * scale),
            segments=max(14, segments // 3), rings=8)
    for i in range(4):
        a = pi / 4 + 2.0 * pi * i / 4
        r = 0.18 * scale
        _sphere(
            f"{name}_RoofGuard_{i+1}", 1.0, collection, parent,
            location=(r * cos(a), r * sin(a), 1.165 * scale),
            scale=(0.085 * scale, 0.085 * scale, 0.095 * scale),
            segments=max(12, segments // 3), rings=8,
        )


def _samurai_knight(name, scale, segments, collection, parent):
    # Armored horse-head knight with kabuto plates rather than exposed thin horns.
    profile = [
        (0.35, 0.00), (0.43, 0.05), (0.44, 0.10), (0.39, 0.15),
        (0.31, 0.22), (0.27, 0.30), (0.22, 0.39), (0.19, 0.58),
        (0.18, 0.68), (0.22, 0.74),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.23, 0.31, 0.070, 0.028)
    _detail_band(name + "_ArmorCollar", scale, segments, collection, parent, 0.67, 0.22, 0.090, 0.038)
    _flute_ring(name + "_LamellarSkirt", 6, 0.205, 0.48, 0.050, 0.073, 0.15,
                scale, segments, collection, parent, phase=pi / 6)

    # Solid S-curve neck using overlapping volumes.
    for idx, (loc, scl, rx) in enumerate([
        ((0, 0.00, 0.79), (0.17, 0.17, 0.19), radians(-5)),
        ((0, 0.06, 0.94), (0.17, 0.18, 0.20), radians(-11)),
        ((0, 0.13, 1.08), (0.17, 0.19, 0.19), radians(-17)),
    ], 1):
        _sphere(f"{name}_Neck_{idx}", 1.0, collection, parent,
                location=tuple(v * scale for v in loc),
                scale=tuple(v * scale for v in scl),
                segments=max(16, segments // 2), rings=9,
                rotation=(rx, 0, 0))
    _sphere(name + "_HorseHead", 1.0, collection, parent,
            location=(0, 0.23 * scale, 1.21 * scale),
            scale=(0.18 * scale, 0.25 * scale, 0.20 * scale),
            segments=max(18, segments // 2), rings=10)
    _sphere(name + "_Muzzle", 1.0, collection, parent,
            location=(0, 0.43 * scale, 1.15 * scale),
            scale=(0.14 * scale, 0.18 * scale, 0.11 * scale),
            segments=max(16, segments // 2), rings=9)

    # Broad cheek armor and helmet dome.
    for side, sx in (("L", -1), ("R", 1)):
        _sphere(name + f"_CheekPlate_{side}", 1.0, collection, parent,
                location=(sx * 0.13 * scale, 0.23 * scale, 1.20 * scale),
                scale=(0.070 * scale, 0.080 * scale, 0.12 * scale),
                segments=max(12, segments // 3), rings=8)
    _sphere(name + "_Kabuto", 1.0, collection, parent,
            location=(0, 0.16 * scale, 1.34 * scale),
            scale=(0.19 * scale, 0.19 * scale, 0.13 * scale),
            segments=max(16, segments // 2), rings=8)
    brim = [
        (-0.18 * scale, -0.045 * scale), (0.18 * scale, -0.045 * scale),
        (0.15 * scale,  0.045 * scale), (-0.15 * scale, 0.045 * scale),
    ]
    _outline_prism(name + "_KabutoBrim", brim, 0.22 * scale,
                   collection, parent, location=(0, 0.12 * scale, 1.30 * scale))
    # Thick twin crest plates form a bold V, not narrow antlers.
    crest_l = [
        (-0.055 * scale, -0.03 * scale), (0.055 * scale, -0.03 * scale),
        (0.13 * scale, 0.18 * scale), (0.02 * scale, 0.15 * scale),
    ]
    crest_r = [(-x, z) for x, z in crest_l]
    _outline_prism(name + "_CrestL", crest_l, 0.075 * scale, collection, parent,
                   location=(-0.04 * scale, 0.12 * scale, 1.41 * scale))
    _outline_prism(name + "_CrestR", crest_r, 0.075 * scale, collection, parent,
                   location=(0.04 * scale, 0.12 * scale, 1.41 * scale))
    for i, z in enumerate((0.90, 1.02, 1.14), 1):
        _box(name + f"_NeckGuard_{i}", (0.22 * scale, 0.09 * scale, 0.10 * scale),
             (0, -0.13 * scale, z * scale), collection, parent)


def _samurai_bishop(name, scale, segments, collection, parent):
    # Warrior-monk / court-priest bishop: tall eboshi-like cap and a broad sash.
    profile = [
        (0.34, 0.00), (0.42, 0.05), (0.43, 0.10), (0.38, 0.15),
        (0.30, 0.22), (0.26, 0.31), (0.21, 0.41), (0.17, 0.70),
        (0.20, 0.83), (0.23, 0.90), (0.21, 0.98),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.23, 0.30, 0.070, 0.027)
    _detail_band(name + "_Obi", scale, segments, collection, parent, 0.50, 0.21, 0.075, 0.030)
    _flute_ring(name + "_RobePanel", 6, 0.19, 0.63, 0.050, 0.070, 0.18,
                scale, segments, collection, parent, phase=pi / 6)
    _sphere(name + "_Head", 1.0, collection, parent,
            location=(0, 0, 1.02 * scale),
            scale=(0.16 * scale, 0.16 * scale, 0.16 * scale),
            segments=max(16, segments // 2), rings=9)
    # Tall folded court cap, wider than it is thin, so it remains durable.
    cap = [
        (-0.15 * scale, -0.13 * scale), (0.15 * scale, -0.13 * scale),
        (0.13 * scale,  0.15 * scale), (0.07 * scale, 0.32 * scale),
        (-0.05 * scale, 0.35 * scale), (-0.14 * scale, 0.16 * scale),
    ]
    _outline_prism(name + "_Eboshi", cap, 0.22 * scale, collection, parent,
                   location=(0, 0, 1.12 * scale), rotation=(radians(-5), 0, 0))
    # Broad diagonal sash is the bishop's slash cue.
    sash = [
        (-0.11 * scale, -0.25 * scale), (-0.015 * scale, -0.25 * scale),
        (0.13 * scale, 0.25 * scale), (0.035 * scale, 0.25 * scale),
    ]
    _outline_prism(name + "_DiagonalSash", sash, 0.085 * scale,
                   collection, parent, location=(0, 0.18 * scale, 0.77 * scale))
    _bipyramid(name + "_SashClasp", 0.070 * scale, 0.080 * scale,
               collection, parent, location=(0.03 * scale, 0.205 * scale, 0.77 * scale),
               rotation=(radians(90), 0, 0), sides=6)


def _samurai_queen(name, scale, segments, collection, parent):
    # Formal warrior-lady silhouette: broad layered armor and a fan crest.
    profile = [
        (0.37, 0.00), (0.45, 0.05), (0.46, 0.10), (0.41, 0.15),
        (0.32, 0.23), (0.28, 0.32), (0.22, 0.42), (0.18, 0.77),
        (0.22, 0.92), (0.28, 1.00), (0.25, 1.08),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.23, 0.32, 0.075, 0.030)
    _detail_band(name + "_Obi", scale, segments, collection, parent, 0.52, 0.22, 0.085, 0.035)
    _detail_band(name + "_ShoulderBand", scale, segments, collection, parent, 0.91, 0.24, 0.080, 0.032)
    _flute_ring(name + "_FormalSkirt", 8, 0.195, 0.67, 0.045, 0.068, 0.19,
                scale, segments, collection, parent, phase=pi / 8)
    _boss_ring(name + "_ObiClasp", 4, 0.22, 0.52, 0.060, 0.080,
               scale, collection, parent, sides=6, phase=pi / 4)
    _sphere(name + "_Head", 1.0, collection, parent,
            location=(0, 0, 1.15 * scale),
            scale=(0.16 * scale, 0.16 * scale, 0.16 * scale),
            segments=max(16, segments // 2), rings=9)
    _sphere(name + "_KabutoDome", 1.0, collection, parent,
            location=(0, 0, 1.28 * scale),
            scale=(0.21 * scale, 0.21 * scale, 0.14 * scale),
            segments=max(18, segments // 2), rings=8)
    _detail_band(name + "_KabutoBrim", scale, segments, collection, parent,
                 1.23, 0.23, 0.070, 0.035)
    # Five stout fan plates create a queen-like crown silhouette.
    fan_specs = [
        (-0.22, 1.36, -18), (-0.11, 1.42, -9), (0.00, 1.45, 0),
        (0.11, 1.42, 9), (0.22, 1.36, 18),
    ]
    fan = [
        (-0.075 * scale, -0.06 * scale), (0.075 * scale, -0.06 * scale),
        (0.095 * scale, 0.15 * scale), (0.00, 0.23 * scale),
        (-0.095 * scale, 0.15 * scale),
    ]
    for i, (x, z, ang) in enumerate(fan_specs, 1):
        _outline_prism(name + f"_FanCrest_{i}", fan, 0.075 * scale,
                       collection, parent,
                       location=(x * scale, 0.08 * scale, z * scale),
                       rotation=(0, radians(ang), 0))
    _sphere(name + "_CrestJewel", 1.0, collection, parent,
            location=(0, 0.10 * scale, 1.57 * scale),
            scale=(0.075 * scale, 0.075 * scale, 0.075 * scale),
            segments=max(14, segments // 2), rings=8)


def _samurai_king(name, scale, segments, collection, parent):
    # Shogun king: heavier armor, broad helmet flare, and an unmistakable
    # three-part maedate crest. No swords, spears, or narrow protrusions.
    profile = [
        (0.38, 0.00), (0.46, 0.05), (0.47, 0.10), (0.42, 0.15),
        (0.33, 0.23), (0.29, 0.32), (0.23, 0.43), (0.19, 0.82),
        (0.23, 0.99), (0.29, 1.06), (0.27, 1.14),
    ]
    _standard_body(name + "_Body", scale, segments, collection, parent, profile)
    _detail_band(name + "_BaseBand", scale, segments, collection, parent, 0.23, 0.33, 0.080, 0.032)
    _detail_band(name + "_ArmorBelt", scale, segments, collection, parent, 0.52, 0.225, 0.090, 0.038)
    _detail_band(name + "_ShoulderBand", scale, segments, collection, parent, 0.97, 0.25, 0.085, 0.035)
    _flute_ring(name + "_LamellarSkirt", 8, 0.20, 0.69, 0.048, 0.072, 0.20,
                scale, segments, collection, parent)
    _boss_ring(name + "_RoyalMon", 4, 0.225, 0.54, 0.065, 0.085,
               scale, collection, parent, sides=8, phase=pi / 4)
    _sphere(name + "_Head", 1.0, collection, parent,
            location=(0, 0, 1.19 * scale),
            scale=(0.17 * scale, 0.17 * scale, 0.17 * scale),
            segments=max(16, segments // 2), rings=9)
    _sphere(name + "_KabutoDome", 1.0, collection, parent,
            location=(0, 0, 1.34 * scale),
            scale=(0.23 * scale, 0.23 * scale, 0.16 * scale),
            segments=max(18, segments // 2), rings=8)
    _detail_band(name + "_KabutoBrim", scale, segments, collection, parent,
                 1.28, 0.25, 0.080, 0.040)
    # Thick side neck guards add the broad shogun silhouette.
    for side, sx in (("L", -1), ("R", 1)):
        guard = [
            (-0.10 * scale, -0.13 * scale), (0.10 * scale, -0.13 * scale),
            (0.13 * scale, 0.13 * scale), (-0.13 * scale, 0.13 * scale),
        ]
        _outline_prism(name + f"_Shikoro_{side}", guard, 0.15 * scale,
                       collection, parent,
                       location=(sx * 0.22 * scale, 0, 1.19 * scale),
                       rotation=(0, radians(sx * 14), 0))
    # Three broad crest masses: a tall center tablet and two swept side plates.
    center = [
        (-0.085 * scale, -0.08 * scale), (0.085 * scale, -0.08 * scale),
        (0.10 * scale, 0.22 * scale), (0.00, 0.32 * scale),
        (-0.10 * scale, 0.22 * scale),
    ]
    sidecrest = [
        (-0.06 * scale, -0.05 * scale), (0.06 * scale, -0.05 * scale),
        (0.18 * scale, 0.17 * scale), (0.06 * scale, 0.15 * scale),
    ]
    _outline_prism(name + "_MaedateCenter", center, 0.10 * scale,
                   collection, parent, location=(0, 0.08 * scale, 1.48 * scale))
    _outline_prism(name + "_MaedateLeft", sidecrest, 0.085 * scale,
                   collection, parent,
                   location=(-0.08 * scale, 0.08 * scale, 1.48 * scale),
                   rotation=(0, radians(-10), 0))
    _outline_prism(name + "_MaedateRight", [(-x, z) for x, z in sidecrest], 0.085 * scale,
                   collection, parent,
                   location=(0.08 * scale, 0.08 * scale, 1.48 * scale),
                   rotation=(0, radians(10), 0))
    _bipyramid(name + "_CrestMon", 0.105 * scale, 0.11 * scale,
               collection, parent, location=(0, 0.13 * scale, 1.57 * scale),
               rotation=(radians(90), 0, 0), sides=8)


SAMURAI_PIECE_BUILDERS = {
    "Pawn": _samurai_pawn,
    "Rook": _samurai_rook,
    "Knight": _samurai_knight,
    "Bishop": _samurai_bishop,
    "Queen": _samurai_queen,
    "King": _samurai_king,
}


# -----------------------------------------------------------------------------
# Dog & cat piece style
# -----------------------------------------------------------------------------

def _cat_ear_pair(prefix, scale, collection, parent, z, spread=0.12, width=0.08, height=0.14, depth=0.08):
    ear = [
        (-width * scale, 0.0),
        (0.0, height * scale),
        (width * scale, 0.0),
    ]
    _outline_prism(prefix + '_EarL', ear, depth * scale, collection, parent,
                   location=(-spread * scale, 0.0, z * scale),
                   rotation=(0, radians(-8), radians(8)))
    _outline_prism(prefix + '_EarR', ear, depth * scale, collection, parent,
                   location=(spread * scale, 0.0, z * scale),
                   rotation=(0, radians(8), radians(-8)))


def _dog_ear_pair(prefix, scale, segments, collection, parent, z, spread=0.16):
    _sphere(prefix + '_EarL', 1.0, collection, parent,
            location=(-spread * scale, 0.03 * scale, z * scale),
            scale=(0.08 * scale, 0.045 * scale, 0.17 * scale),
            rotation=(radians(-18), 0, radians(14)),
            segments=max(12, segments // 3), rings=8)
    _sphere(prefix + '_EarR', 1.0, collection, parent,
            location=(spread * scale, 0.03 * scale, z * scale),
            scale=(0.08 * scale, 0.045 * scale, 0.17 * scale),
            rotation=(radians(-18), 0, radians(-14)),
            segments=max(12, segments // 3), rings=8)


def _muzzle(prefix, scale, segments, collection, parent, y, z, sx=0.11, sy=0.10, sz=0.08):
    _sphere(prefix + '_Muzzle', 1.0, collection, parent,
            location=(0, y * scale, z * scale),
            scale=(sx * scale, sy * scale, sz * scale),
            segments=max(12, segments // 3), rings=8)
    _sphere(prefix + '_Nose', 1.0, collection, parent,
            location=(0, (y + sy * 0.78) * scale, (z + sz * 0.10) * scale),
            scale=(0.030 * scale, 0.040 * scale, 0.024 * scale),
            segments=max(10, segments // 4), rings=6)


def _paw_medallion(prefix, scale, segments, collection, parent, y, z, pad=0.055):
    _sphere(prefix + '_Pad', 1.0, collection, parent,
            location=(0, y * scale, z * scale),
            scale=(pad * scale, 0.028 * scale, pad * 0.92 * scale),
            segments=max(10, segments // 4), rings=6)
    toes = [(-0.070, 0.070), (-0.024, 0.105), (0.024, 0.105), (0.070, 0.070)]
    for i, (tx, tz) in enumerate(toes):
        _sphere(f'{prefix}_Toe_{i+1}', 1.0, collection, parent,
                location=(tx * scale, y * scale, (z + tz) * scale),
                scale=(0.026 * scale, 0.020 * scale, 0.032 * scale),
                segments=max(10, segments // 4), rings=6)


def _dogcat_pawn(name, scale, segments, collection, parent):
    # Cat pawn: seated cat silhouette with compact ears and muzzle.
    profile = [
        (0.31, 0.00), (0.39, 0.05), (0.40, 0.10), (0.36, 0.15),
        (0.28, 0.23), (0.24, 0.33), (0.20, 0.48), (0.18, 0.64),
        (0.19, 0.72), (0.16, 0.78),
    ]
    _standard_body(name + '_Body', scale, segments, collection, parent, profile)
    _detail_band(name + '_BaseBand', scale, segments, collection, parent, 0.20, 0.30, 0.065, 0.026)
    _detail_band(name + '_Collar', scale, segments, collection, parent, 0.70, 0.16, 0.050, 0.024)
    _sphere(name + '_Head', 1.0, collection, parent,
            location=(0, 0, 0.87 * scale),
            scale=(0.17 * scale, 0.17 * scale, 0.16 * scale),
            segments=max(16, segments // 2), rings=8)
    _cat_ear_pair(name, scale, collection, parent, 0.96, spread=0.10, width=0.07, height=0.12, depth=0.07)
    _muzzle(name, scale, segments, collection, parent, 0.11, 0.84, sx=0.08, sy=0.07, sz=0.055)


def _dogcat_rook(name, scale, segments, collection, parent):
    # Pet-house rook with curved roofline and a front paw medallion.
    profile = [
        (0.36, 0.00), (0.44, 0.05), (0.45, 0.11), (0.40, 0.16),
        (0.32, 0.23), (0.29, 0.31), (0.255, 0.43), (0.245, 0.76),
        (0.28, 0.84), (0.31, 0.90), (0.28, 0.98),
    ]
    _standard_body(name + '_Tower', scale, segments, collection, parent, profile)
    _detail_band(name + '_BaseBand', scale, segments, collection, parent, 0.23, 0.31, 0.075, 0.030)
    _detail_band(name + '_ShoulderBand', scale, segments, collection, parent, 0.79, 0.28, 0.075, 0.030)
    _paw_medallion(name + '_FrontPaw', scale, segments, collection, parent, 0.24, 0.55, pad=0.050)
    _detail_band(name + '_ParapetBand', scale, segments, collection, parent, 0.98, 0.31, 0.070, 0.024)
    for i in range(6):
        a = pi / 6 + 2.0 * pi * i / 6
        r = 0.23 * scale
        _sphere(f'{name}_RoofLobe_{i+1}', 1.0, collection, parent,
                location=(r * cos(a), r * sin(a), 1.07 * scale),
                scale=(0.09 * scale, 0.09 * scale, 0.10 * scale),
                segments=max(12, segments // 3), rings=8)
    _sphere(name + '_RoofBoss', 1.0, collection, parent,
            location=(0, 0, 1.08 * scale),
            scale=(0.11 * scale, 0.11 * scale, 0.07 * scale),
            segments=max(12, segments // 3), rings=8)


def _dogcat_knight(name, scale, segments, collection, parent):
    # Dog-head knight with broad muzzle and floppy ears.
    profile = [
        (0.35, 0.00), (0.43, 0.05), (0.44, 0.10), (0.39, 0.15),
        (0.31, 0.23), (0.27, 0.31), (0.23, 0.42), (0.20, 0.63),
        (0.19, 0.72), (0.17, 0.78),
    ]
    _standard_body(name + '_Body', scale, segments, collection, parent, profile)
    _detail_band(name + '_BaseBand', scale, segments, collection, parent, 0.22, 0.30, 0.070, 0.028)
    neck = [
        (-0.11 * scale, 0.00), (0.11 * scale, 0.00),
        (0.15 * scale, 0.25 * scale), (0.12 * scale, 0.44 * scale),
        (0.07 * scale, 0.58 * scale), (-0.07 * scale, 0.58 * scale),
        (-0.12 * scale, 0.44 * scale), (-0.15 * scale, 0.25 * scale),
    ]
    _outline_prism(name + '_Neck', neck, 0.18 * scale, collection, parent,
                   location=(0, 0, 0.74 * scale))
    _sphere(name + '_Head', 1.0, collection, parent,
            location=(0, 0.03 * scale, 1.00 * scale),
            scale=(0.17 * scale, 0.14 * scale, 0.18 * scale),
            segments=max(16, segments // 2), rings=8)
    _muzzle(name, scale, segments, collection, parent, 0.16, 0.97, sx=0.11, sy=0.11, sz=0.07)
    _dog_ear_pair(name, scale, segments, collection, parent, 1.05, spread=0.13)
    _detail_band(name + '_Collar', scale, segments, collection, parent, 0.79, 0.18, 0.060, 0.024)


def _dogcat_bishop(name, scale, segments, collection, parent):
    # Tall cat bishop with a broad almond-shaped emblem instead of a thin slit.
    profile = [
        (0.35, 0.00), (0.43, 0.05), (0.44, 0.10), (0.39, 0.15),
        (0.31, 0.22), (0.27, 0.31), (0.22, 0.43), (0.17, 0.77),
        (0.18, 0.88), (0.17, 1.00),
    ]
    _standard_body(name + '_Body', scale, segments, collection, parent, profile)
    _detail_band(name + '_BaseBand', scale, segments, collection, parent, 0.22, 0.31, 0.075, 0.030)
    _detail_band(name + '_Collar', scale, segments, collection, parent, 0.80, 0.18, 0.060, 0.024)
    _sphere(name + '_Head', 1.0, collection, parent,
            location=(0, 0, 1.05 * scale),
            scale=(0.16 * scale, 0.16 * scale, 0.17 * scale),
            segments=max(16, segments // 2), rings=8)
    _cat_ear_pair(name, scale, collection, parent, 1.14, spread=0.10, width=0.07, height=0.12, depth=0.07)
    eye = [
        (-0.09 * scale, 0.0), (0.0, 0.08 * scale), (0.09 * scale, 0.0), (0.0, -0.08 * scale),
    ]
    _outline_prism(name + '_EyeGlyph', eye, 0.07 * scale, collection, parent,
                   location=(0, 0.20 * scale, 0.63 * scale), rotation=(radians(90), 0, 0))


def _dogcat_queen(name, scale, segments, collection, parent):
    # Cat queen with coronet and bead tiara.
    profile = [
        (0.37, 0.00), (0.45, 0.05), (0.46, 0.10), (0.41, 0.15),
        (0.32, 0.23), (0.28, 0.32), (0.22, 0.42), (0.17, 0.76),
        (0.22, 0.93), (0.24, 1.04), (0.20, 1.10),
    ]
    _standard_body(name + '_Body', scale, segments, collection, parent, profile)
    _detail_band(name + '_BaseBand', scale, segments, collection, parent, 0.23, 0.32, 0.075, 0.030)
    _detail_band(name + '_WaistBand', scale, segments, collection, parent, 0.50, 0.205, 0.060, 0.024)
    _detail_band(name + '_ShoulderBand', scale, segments, collection, parent, 0.91, 0.23, 0.075, 0.030)
    _sphere(name + '_Head', 1.0, collection, parent,
            location=(0, 0, 1.17 * scale),
            scale=(0.17 * scale, 0.17 * scale, 0.16 * scale),
            segments=max(16, segments // 2), rings=8)
    _cat_ear_pair(name, scale, collection, parent, 1.26, spread=0.10, width=0.07, height=0.12, depth=0.07)
    _muzzle(name, scale, segments, collection, parent, 0.10, 1.15, sx=0.08, sy=0.07, sz=0.055)
    _detail_band(name + '_TiaraBand', scale, segments, collection, parent, 1.22, 0.18, 0.055, 0.020)
    _bead_ring(name + '_TiaraPearl', 6, 0.16, 1.32, 0.035, scale,
               segments, collection, parent, squash=0.9, phase=pi / 6)
    _sphere(name + '_TiaraOrb', 1.0, collection, parent,
            location=(0, 0, 1.40 * scale),
            scale=(0.06 * scale, 0.06 * scale, 0.06 * scale),
            segments=max(12, segments // 3), rings=6)


def _dogcat_king(name, scale, segments, collection, parent):
    # Dog king with broad crown band, floppy ears, and chunky cross finial.
    profile = [
        (0.38, 0.00), (0.46, 0.05), (0.47, 0.10), (0.42, 0.15),
        (0.33, 0.23), (0.29, 0.32), (0.23, 0.43), (0.18, 0.81),
        (0.23, 0.99), (0.27, 1.09), (0.21, 1.16),
    ]
    _standard_body(name + '_Body', scale, segments, collection, parent, profile)
    _detail_band(name + '_BaseBand', scale, segments, collection, parent, 0.23, 0.33, 0.080, 0.032)
    _detail_band(name + '_WaistBand', scale, segments, collection, parent, 0.51, 0.215, 0.065, 0.027)
    _detail_band(name + '_ShoulderBand', scale, segments, collection, parent, 0.96, 0.24, 0.080, 0.032)
    _sphere(name + '_Head', 1.0, collection, parent,
            location=(0, 0.01 * scale, 1.19 * scale),
            scale=(0.18 * scale, 0.16 * scale, 0.18 * scale),
            segments=max(16, segments // 2), rings=8)
    _muzzle(name, scale, segments, collection, parent, 0.16, 1.16, sx=0.11, sy=0.11, sz=0.07)
    _dog_ear_pair(name, scale, segments, collection, parent, 1.24, spread=0.14)
    _detail_band(name + '_CrownBand', scale, segments, collection, parent, 1.28, 0.22, 0.080, 0.028)
    _sphere(name + '_CrownCore', 1.0, collection, parent,
            location=(0, 0, 1.38 * scale),
            scale=(0.10 * scale, 0.10 * scale, 0.08 * scale),
            segments=max(12, segments // 3), rings=6)
    cross_stem = [
        (-0.045 * scale, -0.19 * scale), (0.045 * scale, -0.19 * scale),
        (0.045 * scale, 0.19 * scale), (-0.045 * scale, 0.19 * scale),
    ]
    cross_arm = [
        (-0.14 * scale, -0.04 * scale), (0.14 * scale, -0.04 * scale),
        (0.14 * scale, 0.04 * scale), (-0.14 * scale, 0.04 * scale),
    ]
    _outline_prism(name + '_CrossStem', cross_stem, 0.10 * scale,
                   collection, parent, location=(0, 0, 1.55 * scale))
    _outline_prism(name + '_CrossArm', cross_arm, 0.10 * scale,
                   collection, parent, location=(0, 0, 1.63 * scale))


DOGCAT_PIECE_BUILDERS = {
    'Pawn': _dogcat_pawn,
    'Rook': _dogcat_rook,
    'Knight': _dogcat_knight,
    'Bishop': _dogcat_bishop,
    'Queen': _dogcat_queen,
    'King': _dogcat_king,
}

STYLE_BUILDERS = {
    "ELF": PIECE_BUILDERS,
    "SAMURAI": SAMURAI_PIECE_BUILDERS,
    "DOGCAT": DOGCAT_PIECE_BUILDERS,
}

STYLE_LABELS = {
    'ELF': 'Elf',
    'SAMURAI': 'Samurai',
    'DOGCAT': 'DogCat',
}

STYLE_COLLECTION_LABELS = {
    'ELF': 'ELVES',
    'SAMURAI': 'SAMURAI',
    'DOGCAT': 'DOG_CAT',
}


def _side_collection_name(style, side):
    style_name = STYLE_COLLECTION_LABELS.get(style, str(style).upper())
    side_name = 'WHITE' if side == 'White' else 'BLACK'
    return f"{style_name}_{side_name}"


def _find_side_collection(pieces, side, style=None):
    """Find a generated side collection, preferring the requested/current style."""
    if pieces is None:
        return None
    if style:
        found = _find_child(pieces, _side_collection_name(style, side))
        if found:
            return found
    suffix = '_WHITE' if side == 'White' else '_BLACK'
    for child in pieces.children:
        if child.name.upper().endswith(suffix):
            return child
    # Backward compatibility with older generated scenes.
    legacy = WHITE_NAME if side == 'White' else BLACK_NAME
    return _find_child(pieces, legacy)


def _merge_piece_parts(root, collection, final_name):
    """Merge all geometry under one chess piece root into one selectable object.

    This is deliberately a plain mesh join, not a voxel/remesh operation, so it
    preserves the original detailed silhouettes. Curves are evaluated to mesh
    first, then every child is transformed into the piece root's local space.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    root_inv = root.matrix_world.inverted()

    verts = []
    faces = []
    smooth_flags = []

    children = list(root.children)
    for obj in children:
        if obj.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
            continue

        eval_obj = obj.evaluated_get(depsgraph)
        try:
            temp_mesh = bpy.data.meshes.new_from_object(
                eval_obj, preserve_all_data_layers=False, depsgraph=depsgraph
            )
        except TypeError:
            temp_mesh = bpy.data.meshes.new_from_object(eval_obj, depsgraph=depsgraph)

        rel = root_inv @ obj.matrix_world
        offset = len(verts)
        verts.extend([tuple(rel @ v.co) for v in temp_mesh.vertices])
        faces.extend([tuple(offset + i for i in p.vertices) for p in temp_mesh.polygons])
        smooth_flags.extend([p.use_smooth for p in temp_mesh.polygons])
        bpy.data.meshes.remove(temp_mesh)

    mesh = bpy.data.meshes.new(final_name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    for poly, use_smooth in zip(mesh.polygons, smooth_flags):
        poly.use_smooth = use_smooth

    merged = bpy.data.objects.new(final_name, mesh)
    collection.objects.link(merged)
    merged.matrix_world = root.matrix_world.copy()

    # Remove the original construction objects and the temporary Empty root.
    for obj in children:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.objects.remove(root, do_unlink=True)

    return merged



# -----------------------------------------------------------------------------
# Render material helpers
# -----------------------------------------------------------------------------

def _set_node_input(node, names, value):
    """Set the first matching socket name; keeps Blender 4.x/5.x compatibility."""
    if isinstance(names, str):
        names = (names,)
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return True
    return False


def _material_name(kind, side, color):
    return f"FantasyChess_{kind.title()}_{side}_{color.title()}"


PIECE_COLOR_LABELS = {
    'WHITE': "White",
    'BLACK': "Black",
    'RED': "Red",
    'BLUE': "Blue",
    'PURPLE': "Purple",
    'ORANGE': "Orange",
    'YELLOW': "Yellow",
    'NATURAL': "Natural",
}


def _clamp01(value):
    return max(0.0, min(1.0, value))


def _mix_rgb(a, b, t):
    return tuple(a[i] * (1.0 - t) + b[i] * t for i in range(3))


def _scale_rgb(rgb, factor):
    return tuple(_clamp01(c * factor) for c in rgb)


def _piece_tint_rgb(color):
    """Pure hue choices. These add color independent of the material type.

    Keep saturated hues a little restrained so they read clearly in renders
    without drifting too bright, too dark, or too pastel.
    """
    palette = {
        'WHITE': (1.0, 1.0, 1.0),
        'BLACK': (0.10, 0.10, 0.11),
        'RED': (0.78, 0.09, 0.08),
        'BLUE': (0.10, 0.28, 0.82),
        'PURPLE': (0.44, 0.15, 0.66),
        'ORANGE': (0.90, 0.36, 0.07),
        'YELLOW': (0.88, 0.72, 0.10),
        'GOLD': (0.84, 0.68, 0.16),
        'SILVER': (0.72, 0.74, 0.78),
    }
    return palette.get(color)



def _piece_color_values(kind, color):
    """Return shader colors for a selected piece material/color combination.

    The selected material defines *how* the piece looks (glass, metal, stone,
    wood). The selected color supplies the hue, and should remain a true color
    rather than washing toward white or black.
    """
    tint = _piece_tint_rgb(color)

    if kind == 'GLASS':
        # Natural glass remains clear; colored glass uses the chosen hue with
        # only a very small lift so it stays transparent but not pastel.
        if color == 'NATURAL' or tint is None:
            return (1.0, 1.0, 1.0, 1.0)
        if color == 'BLACK':
            return (0.16, 0.17, 0.19, 1.0)
        return (*_mix_rgb(tint, (1.0, 1.0, 1.0), 0.04), 1.0)

    if kind == 'METAL':
        # Natural metal is neutral steel. Colored metal keeps a metallic value
        # range, but the hue stays close to the selected color.
        if color == 'NATURAL' or tint is None:
            dark = (0.26, 0.27, 0.30, 1.0)
            light = (0.86, 0.88, 0.92, 1.0)
            return dark, light
        dark_rgb = _scale_rgb(tint, 0.28)
        light_rgb = _mix_rgb(_scale_rgb(tint, 0.88), (1.0, 1.0, 1.0), 0.05)
        return (*dark_rgb, 1.0), (*light_rgb, 1.0)

    if kind == 'STONE':
        # Natural stone is gray. Colored stone uses the chosen hue directly,
        # with value changes coming from the stone material rather than from a
        # white tint that would push red toward pink.
        if color == 'NATURAL' or tint is None:
            dark = (0.18, 0.18, 0.18, 1.0)
            light = (0.66, 0.66, 0.63, 1.0)
            return dark, light
        dark_rgb = _scale_rgb(tint, 0.46)
        light_rgb = _scale_rgb(tint, 0.88)
        return (*dark_rgb, 1.0), (*light_rgb, 1.0)

    # Natural wood remains brown. Colored wood preserves grain while keeping a
    # true version of the chosen hue instead of drifting pastel.
    if color == 'NATURAL' or tint is None:
        return (0.10, 0.030, 0.008, 1.0), (0.52, 0.22, 0.055, 1.0)
    dark_rgb = _scale_rgb(tint, 0.30)
    light_rgb = _scale_rgb(tint, 0.82)
    return (*dark_rgb, 1.0), (*light_rgb, 1.0)


def _ensure_piece_material(kind, side, color):
    """Create/reuse a render material while keeping Solid viewport neutral gray."""
    name = _material_name(kind, side, color)
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True

    # Keep Solid viewport neutral even when Solid shading uses Material color.
    # Selected colors are expressed by shader nodes in Material Preview/Rendered.
    mat.diffuse_color = (0.62, 0.62, 0.62, 1.0)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (520, 0)

    if kind == 'GLASS':
        # Use a dedicated Glass BSDF with lighter tinting and slightly softer
        # reflections so detailed chess geometry reads more clearly in Cycles.
        base = _piece_color_values('GLASS', color)
        glass = nodes.new("ShaderNodeBsdfGlass")
        glass.location = (180, 70)
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        transparent.location = (180, -120)
        mix = nodes.new("ShaderNodeMixShader")
        mix.location = (390, 20)

        _set_node_input(glass, "Color", base)
        _set_node_input(glass, "Roughness", 0.028 if color == 'NATURAL' else 0.045)
        _set_node_input(glass, "IOR", 1.45)
        _set_node_input(transparent, "Color", (1.0, 1.0, 1.0, 1.0))

        # Keep colored glass visibly transparent, especially the darker colors.
        mix.inputs[0].default_value = 0.16 if color == 'BLACK' else 0.11
        links.new(glass.outputs.get("BSDF"), mix.inputs[1])
        links.new(transparent.outputs.get("BSDF"), mix.inputs[2])
        links.new(mix.outputs.get("Shader"), output.inputs.get("Surface"))
    else:
        principled = nodes.new("ShaderNodeBsdfPrincipled")
        principled.location = (220, 0)
        links.new(principled.outputs.get("BSDF"), output.inputs.get("Surface"))

        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-720, 20)
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-540, 20)
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-320, 20)
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (-80, 40)

        links.new(texcoord.outputs.get("Generated"), mapping.inputs.get("Vector"))
        links.new(mapping.outputs.get("Vector"), noise.inputs.get("Vector"))
        links.new(noise.outputs.get("Fac"), ramp.inputs.get("Fac"))
        links.new(ramp.outputs.get("Color"), principled.inputs.get("Base Color"))

        cr = ramp.color_ramp
        e0 = cr.elements[0]
        e1 = cr.elements[1]
        e0.position = 0.22
        e1.position = 0.78

        if kind == 'METAL':
            mapping.inputs.get("Scale").default_value = (8.0, 8.0, 8.0)
            noise.inputs.get("Scale").default_value = 7.5
            noise.inputs.get("Detail").default_value = 8.0
            noise.inputs.get("Roughness").default_value = 0.42
            if noise.inputs.get("Distortion") is not None:
                noise.inputs.get("Distortion").default_value = 0.05
            e0.color, e1.color = _piece_color_values('METAL', color)
            if color == 'NATURAL':
                # Natural metal should read as exposed steel.
                _set_node_input(principled, "Metallic", 1.0)
                _set_node_input(principled, "Roughness", 0.18)
                _set_node_input(principled, ("Coat Weight", "Clearcoat"), 0.04)
                _set_node_input(principled, ("Coat Roughness", "Clearcoat Roughness"), 0.10)
            else:
                # Colored metal should look painted/coated, not like tinted raw steel.
                _set_node_input(principled, "Metallic", 0.0)
                _set_node_input(principled, "Roughness", 0.24)
                _set_node_input(principled, ("Coat Weight", "Clearcoat"), 0.30)
                _set_node_input(principled, ("Coat Roughness", "Clearcoat Roughness"), 0.14)
        elif kind == 'STONE':
            mapping.inputs.get("Scale").default_value = (2.8, 2.8, 2.8)
            noise.inputs.get("Scale").default_value = 5.5
            noise.inputs.get("Detail").default_value = 6.0
            noise.inputs.get("Roughness").default_value = 0.72
            if noise.inputs.get("Distortion") is not None:
                noise.inputs.get("Distortion").default_value = 0.08
            e0.color, e1.color = _piece_color_values('STONE', color)
            _set_node_input(principled, "Metallic", 0.0)
            _set_node_input(principled, "Roughness", 0.34)
            _set_node_input(principled, ("Coat Weight", "Clearcoat"), 0.02)
        else:
            # Stretch the procedural texture vertically for a subdued wood-grain feel.
            mapping.inputs.get("Scale").default_value = (4.5, 4.5, 0.75)
            noise.inputs.get("Scale").default_value = 3.2
            noise.inputs.get("Detail").default_value = 4.0
            noise.inputs.get("Roughness").default_value = 0.68
            if noise.inputs.get("Distortion") is not None:
                noise.inputs.get("Distortion").default_value = 0.18
            e0.color, e1.color = _piece_color_values('WOOD', color)
            _set_node_input(principled, "Roughness", 0.42)
            _set_node_input(principled, "Metallic", 0.0)
            _set_node_input(principled, ("Coat Weight", "Clearcoat"), 0.08)
            _set_node_input(principled, ("Coat Roughness", "Clearcoat Roughness"), 0.22)

    return mat

def _piece_material_is_current(obj, material):
    if obj is None or obj.type != 'MESH' or material is None:
        return False
    mats = obj.data.materials
    return len(mats) == 1 and mats[0] == material


def _assign_piece_material(obj, material):
    """Assign a piece material only when the object does not already use it."""
    if obj is None or obj.type != 'MESH' or material is None:
        return False
    if _piece_material_is_current(obj, material):
        return False
    obj.data.materials.clear()
    obj.data.materials.append(material)
    # Also keep the per-object viewport display neutral.
    obj.color = (0.62, 0.62, 0.62, 1.0)
    return True


def _side_material_setting(scene, side):
    return scene.elf_chess_white_material if side == "White" else scene.elf_chess_black_material


def _side_color_setting(scene, side):
    return scene.elf_chess_white_color if side == "White" else scene.elf_chess_black_color


def _update_piece_materials_in_collection(collection, material, side=None, recursive=True):
    """Update only mesh objects that need a different piece material."""
    if collection is None or material is None:
        return 0
    updated = 0
    for obj in collection.objects:
        if obj.type != 'MESH':
            continue
        if side is not None and obj.get("chess_side") != side:
            continue
        if _assign_piece_material(obj, material):
            updated += 1
    if recursive:
        for child in collection.children:
            updated += _update_piece_materials_in_collection(child, material, side=side, recursive=True)
    return updated


def apply_material_to_side(scene, side):
    root = _find_child(scene.collection, ROOT_NAME)
    if not root:
        return 0
    pieces = _find_child(root, PIECES_NAME)
    if not pieces:
        return 0
    side_coll = _find_side_collection(pieces, side, scene.elf_chess_style)
    if not side_coll:
        side_coll = _find_side_collection(pieces, side)
    if not side_coll:
        return 0

    kind = _side_material_setting(scene, side)
    color = _side_color_setting(scene, side)
    material = _ensure_piece_material(kind, side, color)
    return _update_piece_materials_in_collection(side_coll, material, side=side, recursive=True)


def _sync_existing_side_material(scene, side):
    """Incrementally update an existing side and any showcase copies of that side."""
    root = _find_child(scene.collection, ROOT_NAME)
    if not root:
        return 0

    kind = _side_material_setting(scene, side)
    color = _side_color_setting(scene, side)
    material = _ensure_piece_material(kind, side, color)
    updated = 0

    # Main generated side, if it exists.
    pieces = _find_child(root, PIECES_NAME)
    if pieces:
        side_coll = _find_side_collection(pieces, side, scene.elf_chess_style)
        if not side_coll:
            side_coll = _find_side_collection(pieces, side)
        if side_coll:
            updated += _update_piece_materials_in_collection(side_coll, material, side=side, recursive=True)

    # Full-set render sequence contains both White and Black showcase copies.
    sequence_coll = _find_child(root, RENDER_SEQUENCE_NAME)
    if sequence_coll:
        updated += _update_piece_materials_in_collection(sequence_coll, material, side=side, recursive=True)

    # Update the individual showcase only when it is currently using this side.
    showcase_side = getattr(scene, "elf_chess_showcase_side", "White")
    if side == showcase_side:
        individual_coll = _find_child(root, INDIVIDUAL_SHOWCASE_NAME)
        if individual_coll:
            updated += _update_piece_materials_in_collection(individual_coll, material, side=side, recursive=True)

    return updated


def _on_white_piece_material_changed(scene, context):
    try:
        _sync_existing_side_material(scene, "White")
    except Exception:
        pass


def _on_black_piece_material_changed(scene, context):
    try:
        _sync_existing_side_material(scene, "Black")
    except Exception:
        pass


def _adjust_render_lighting_for_board_material(scene):
    """Retune an existing still-render light rig for the current board material.

    This function never creates a render scene or light. It only modifies the
    existing FantasyChess still-render rig when that rig is already present.
    """
    root = _find_child(scene.collection, ROOT_NAME)
    render_coll = _find_child(root, RENDER_SCENE_NAME) if root else None
    if render_coll is None:
        return False

    lights = {
        'KEY': render_coll.objects.get("FantasyChess_Key"),
        'FILL': render_coll.objects.get("FantasyChess_Fill"),
        'RIM': render_coll.objects.get("FantasyChess_Rim"),
        'LOWFILL': render_coll.objects.get("FantasyChess_LowFill"),
        'DARKFILL': render_coll.objects.get("FantasyChess_DarkFill"),
    }

    s = scene.elf_chess_square_size
    board = 8.0 * s
    outer = board + 2.0 * scene.elf_chess_border_width
    power_scale = max(0.25, s * s)
    kind = scene.elf_chess_board_material
    target_z = scene.elf_chess_board_base_height + scene.elf_chess_tile_height + 0.58 * s
    target = (0.0, 0.0, target_z)

    # If a still render rig exists but newer dark-side fill lights are missing,
    # add them during adjustment rather than requiring the user to rebuild.
    if lights['LOWFILL'] is None:
        lights['LOWFILL'] = _add_area_light(
            "FantasyChess_LowFill", render_coll,
            (-outer * 1.02, -outer * 0.58, outer * 0.34), target,
            520.0 * power_scale, outer * 0.80,
        )
    if lights['DARKFILL'] is None:
        lights['DARKFILL'] = _add_area_light(
            "FantasyChess_DarkFill", render_coll,
            (-outer * 1.18, -outer * 0.12, outer * 0.58), target,
            430.0 * power_scale, outer * 0.92,
        )

    lights = {role: obj for role, obj in lights.items() if obj is not None and obj.type == 'LIGHT'}
    if not lights:
        return False

    # Energy, area size, color, and placement are tuned per board surface.
    # Glass and metal use broader, softer sources plus two dedicated dark-side
    # fill lights so the near corner stays readable without harsh hotspots.
    presets = {
        'WOOD': {
            'KEY': (2200.0, 1.18, (1.00, 0.96, 0.90), (-0.50, -1.05, 1.35)),
            'FILL': (1125.0, 1.28, (0.94, 0.97, 1.00), (1.10, -0.35, 0.95)),
            'RIM': (650.0, 1.02, (1.00, 0.95, 0.88), (-0.10, 1.10, 1.15)),
            'LOWFILL': (400.0, 0.82, (0.95, 0.97, 1.00), (-1.00, -0.64, 0.42)),
            'DARKFILL': (260.0, 0.90, (0.95, 0.97, 1.00), (-1.12, -0.12, 0.60)),
            'WORLD': ((0.085, 0.090, 0.105, 1.0), 0.56),
        },
        'STONE': {
            'KEY': (2050.0, 1.28, (0.98, 0.99, 1.00), (-0.50, -1.02, 1.32)),
            'FILL': (1050.0, 1.38, (0.95, 0.98, 1.00), (1.08, -0.32, 0.92)),
            'RIM': (600.0, 1.08, (1.00, 0.98, 0.94), (-0.10, 1.10, 1.12)),
            'LOWFILL': (440.0, 0.86, (0.96, 0.98, 1.00), (-1.00, -0.62, 0.44)),
            'DARKFILL': (300.0, 0.94, (0.96, 0.98, 1.00), (-1.14, -0.10, 0.62)),
            'WORLD': ((0.080, 0.085, 0.100, 1.0), 0.52),
        },
        'GLASS': {
            'KEY': (1300.0, 1.88, (0.97, 0.985, 1.00), (-0.42, -1.12, 1.28)),
            'FILL': (860.0, 2.02, (0.94, 0.975, 1.00), (1.18, -0.30, 0.90)),
            'RIM': (440.0, 1.60, (1.00, 0.97, 0.92), (-0.08, 1.14, 1.02)),
            'LOWFILL': (880.0, 1.28, (0.92, 0.96, 1.00), (-1.14, -0.78, 0.26)),
            'DARKFILL': (700.0, 1.18, (0.93, 0.97, 1.00), (-1.24, -0.14, 0.50)),
            'WORLD': ((0.060, 0.067, 0.082, 1.0), 0.42),
        },
        'METAL': {
            'KEY': (1450.0, 1.72, (0.98, 0.99, 1.00), (-0.46, -1.08, 1.28)),
            'FILL': (940.0, 1.88, (0.95, 0.98, 1.00), (1.14, -0.28, 0.92)),
            'RIM': (490.0, 1.50, (1.00, 0.965, 0.90), (-0.08, 1.12, 1.02)),
            'LOWFILL': (820.0, 1.20, (0.94, 0.97, 1.00), (-1.10, -0.76, 0.28)),
            'DARKFILL': (620.0, 1.10, (0.94, 0.97, 1.00), (-1.22, -0.12, 0.52)),
            'WORLD': ((0.064, 0.070, 0.086, 1.0), 0.46),
        },
    }
    preset = presets.get(kind, presets['WOOD'])

    for role, obj in lights.items():
        values = preset.get(role)
        if values is None:
            continue
        energy, size_mult, color, loc_mult = values
        data = obj.data
        data.energy = energy * power_scale
        if hasattr(data, 'size'):
            data.size = outer * size_mult
        obj.location = (outer * loc_mult[0], outer * loc_mult[1], outer * loc_mult[2])
        _look_at(obj, target)
        try:
            data.color = color[:3]
        except Exception:
            pass

    # Only tune world illumination when the render light rig actually exists.
    if scene.world is not None and scene.world.use_nodes:
        bg = scene.world.node_tree.nodes.get("Background")
        if bg is not None:
            world_color, world_strength = preset['WORLD']
            bg.inputs.get("Color").default_value = world_color
            bg.inputs.get("Strength").default_value = world_strength
    return True


def _on_board_material_changed(scene, context):
    """Update the board and retune an already-created still-render light rig."""
    try:
        apply_board_material(scene)
        _adjust_render_lighting_for_board_material(scene)
    except Exception:
        pass


def _on_showcase_floor_material_changed(scene, context):
    """Update an existing full-set showcase floor without rebuilding the showcase."""
    try:
        root = _find_child(scene.collection, ROOT_NAME)
        sequence = _find_child(root, RENDER_SEQUENCE_NAME) if root else None
        floor = sequence.objects.get("Showcase_Floor") if sequence else None
        if floor is not None:
            _assign_render_material(
                floor,
                _ensure_showcase_floor_material(scene.elf_chess_showcase_floor_material),
            )
    except Exception:
        pass


def _on_individual_background_material_changed(scene, context):
    """Update an existing individual-showcase backdrop without rebuilding it."""
    try:
        root = _find_child(scene.collection, ROOT_NAME)
        showcase = _find_child(root, INDIVIDUAL_SHOWCASE_NAME) if root else None
        backdrop = showcase.objects.get("PieceShowcase_Backdrop") if showcase else None
        if backdrop is not None:
            _assign_render_material(
                backdrop,
                _ensure_individual_showcase_backdrop_material(scene.elf_chess_individual_background_material),
            )
    except Exception:
        pass


def apply_selected_materials(scene):
    return (
        apply_material_to_side(scene, "White")
        + apply_material_to_side(scene, "Black")
        + apply_board_material(scene)
    )


def _create_piece(kind, square, side, style, x, y, z, scale, segments, collection, material=None):
    rotation = 0.0 if side == "White" else pi
    style_label = STYLE_LABELS.get(style, 'Elf')
    final_name = f"{side}_{style_label}_{kind}_{square}"
    root = _empty(final_name + "_BUILD", collection, (x, y, z), rotation)
    builders = STYLE_BUILDERS.get(style, PIECE_BUILDERS)
    builders[kind](final_name, scale, segments, collection, root)

    piece = _merge_piece_parts(root, collection, final_name)
    piece["chess_side"] = side
    piece["chess_piece"] = kind
    piece["chess_square"] = square
    piece["chess_style"] = style_label
    piece["elf_chess_generator"] = True
    _assign_piece_material(piece, material)
    return piece


def build_piece_side(scene, side):
    if side not in {"White", "Black"}:
        raise ValueError("side must be 'White' or 'Black'")

    root = _root_collection(scene)
    pieces = _get_or_create_collection(root, PIECES_NAME)
    side_name = _side_collection_name(scene.elf_chess_style, side)
    # Rebuilding a side replaces any older generated collection for that side,
    # even if it was created using a different style.
    old_side = _find_side_collection(pieces, side)
    if old_side:
        _remove_collection_tree(old_side)
    side_coll = _get_or_create_collection(pieces, side_name)

    s = scene.elf_chess_square_size
    scale = scene.elf_chess_piece_scale * s
    segments = scene.elf_chess_radial_segments
    style = scene.elf_chess_style
    material_kind = _side_material_setting(scene, side)
    material_color = _side_color_setting(scene, side)
    material = _ensure_piece_material(material_kind, side, material_color)
    z = scene.elf_chess_board_base_height + scene.elf_chess_tile_height

    files = "ABCDEFGH"
    back = ["Rook", "Knight", "Bishop", "Queen", "King", "Bishop", "Knight", "Rook"]

    if side == "White":
        back_rank = 0
        pawn_rank = 1
        back_rank_number = 1
        pawn_rank_number = 2
    else:
        back_rank = 7
        pawn_rank = 6
        back_rank_number = 8
        pawn_rank_number = 7

    for file_index, kind in enumerate(back):
        x = (file_index - 3.5) * s

        y_back = (back_rank - 3.5) * s
        sq_back = files[file_index] + str(back_rank_number)
        _create_piece(kind, sq_back, side, style, x, y_back, z, scale, segments, side_coll, material)

        y_pawn = (pawn_rank - 3.5) * s
        sq_pawn = files[file_index] + str(pawn_rank_number)
        _create_piece("Pawn", sq_pawn, side, style, x, y_pawn, z, scale, segments, side_coll, material)

    _focus_generated_chess_view(scene)
    return side_coll


def remove_piece_side(scene, side):
    root = _find_child(scene.collection, ROOT_NAME)
    if not root:
        return False
    pieces = _find_child(root, PIECES_NAME)
    if not pieces:
        return False
    side_coll = _find_side_collection(pieces, side, scene.elf_chess_style)
    if not side_coll:
        side_coll = _find_side_collection(pieces, side)
    if not side_coll:
        return False
    _remove_collection_tree(side_coll)
    return True


# -----------------------------------------------------------------------------
# Render scene helpers
# -----------------------------------------------------------------------------

def _look_at(obj, target):
    direction = Vector(target) - obj.location
    if direction.length > 1e-6:
        obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def _ensure_scene_surface_material():
    name = "FantasyChess_RenderSurface"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (0.045, 0.050, 0.060, 1.0)

    # Simple dark studio floor with no visible texture so the chess set remains
    # the focus. Keep only a restrained reflection.
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (520, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (250, 0)
    links.new(bsdf.outputs.get("BSDF"), out.inputs.get("Surface"))

    _set_node_input(bsdf, "Base Color", (0.018, 0.020, 0.026, 1.0))
    _set_node_input(bsdf, "Metallic", 0.0)
    _set_node_input(bsdf, "Roughness", 0.52)
    _set_node_input(bsdf, "Specular IOR Level", 0.24)
    _set_node_input(bsdf, ("Coat Weight", "Clearcoat"), 0.01)
    _set_node_input(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.30)
    return mat


def _ensure_showcase_floor_material(kind='STUDIO'):
    """Create the selected full-set showcase floor material."""
    kind = kind or 'STUDIO'
    name = f"FantasyChess_ShowcaseFloor_{kind.title()}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (0.30, 0.31, 0.34, 1.0)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (520, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (250, 0)
    links.new(bsdf.outputs.get("BSDF"), out.inputs.get("Surface"))

    if kind in {'WOOD', 'STONE'}:
        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-650, 0)
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-470, 0)
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-270, 0)
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (-30, 0)
        links.new(texcoord.outputs.get("Generated"), mapping.inputs.get("Vector"))
        links.new(mapping.outputs.get("Vector"), noise.inputs.get("Vector"))
        links.new(noise.outputs.get("Fac"), ramp.inputs.get("Fac"))
        links.new(ramp.outputs.get("Color"), bsdf.inputs.get("Base Color"))
        e0, e1 = ramp.color_ramp.elements[0], ramp.color_ramp.elements[1]
        if kind == 'WOOD':
            mapping.inputs.get("Scale").default_value = (3.0, 8.0, 0.8)
            noise.inputs.get("Scale").default_value = 3.5
            noise.inputs.get("Detail").default_value = 5.0
            e0.color = (0.025, 0.010, 0.005, 1.0)
            e1.color = (0.18, 0.070, 0.020, 1.0)
            _set_node_input(bsdf, "Roughness", 0.30)
            _set_node_input(bsdf, ("Coat Weight", "Clearcoat"), 0.12)
        else:
            noise.inputs.get("Scale").default_value = 5.5
            noise.inputs.get("Detail").default_value = 5.0
            e0.color = (0.030, 0.032, 0.038, 1.0)
            e1.color = (0.16, 0.17, 0.19, 1.0)
            _set_node_input(bsdf, "Roughness", 0.32)
            _set_node_input(bsdf, ("Coat Weight", "Clearcoat"), 0.08)
        _set_node_input(bsdf, "Metallic", 0.0)
        _set_node_input(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.18)
    elif kind == 'METAL':
        _set_node_input(bsdf, "Base Color", (0.055, 0.065, 0.080, 1.0))
        _set_node_input(bsdf, "Metallic", 0.82)
        _set_node_input(bsdf, "Roughness", 0.25)
    elif kind == 'GLASS':
        _set_node_input(bsdf, "Base Color", (0.070, 0.085, 0.105, 1.0))
        _set_node_input(bsdf, "Metallic", 0.0)
        _set_node_input(bsdf, "Roughness", 0.16)
        _set_node_input(bsdf, ("Transmission Weight", "Transmission"), 0.58)
        _set_node_input(bsdf, "IOR", 1.45)
        _set_node_input(bsdf, ("Coat Weight", "Clearcoat"), 0.10)
    else:
        # Default studio floor: dark with a restrained reflection.
        _set_node_input(bsdf, "Base Color", (0.055, 0.060, 0.072, 1.0))
        _set_node_input(bsdf, "Roughness", 0.24)
        _set_node_input(bsdf, "Specular IOR Level", 0.55)
        _set_node_input(bsdf, ("Coat Weight", "Clearcoat"), 0.12)
        _set_node_input(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.20)
    return mat

def _ensure_showcase_backdrop_material():
    name = "FantasyChess_ShowcaseBackdrop"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (0.18, 0.19, 0.22, 1.0)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (780, 0)
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (520, 0)
    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-640, 0)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-460, 0)
    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.location = (-250, 0)
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (40, 0)

    links.new(texcoord.outputs.get("Generated"), mapping.inputs.get("Vector"))
    links.new(mapping.outputs.get("Vector"), separate.inputs.get("Vector"))
    links.new(separate.outputs.get("Z"), ramp.inputs.get("Fac"))
    links.new(ramp.outputs.get("Color"), principled.inputs.get("Base Color"))
    links.new(principled.outputs.get("BSDF"), out.inputs.get("Surface"))

    try:
        mapping.inputs.get("Scale").default_value = (1.0, 1.0, 1.0)
    except Exception:
        pass
    cr = ramp.color_ramp
    e0 = cr.elements[0]
    e1 = cr.elements[1]
    e0.position = 0.06
    e1.position = 0.94
    e0.color = (0.055, 0.060, 0.068, 1.0)
    e1.color = (0.20, 0.22, 0.26, 1.0)
    if len(cr.elements) < 3:
        e2 = cr.elements.new(0.50)
    else:
        e2 = cr.elements[1]
    e2.position = 0.50
    e2.color = (0.11, 0.12, 0.14, 1.0)
    _set_node_input(principled, "Roughness", 0.88)
    _set_node_input(principled, "Metallic", 0.0)
    return mat


def _ensure_individual_showcase_backdrop_material(kind='MATTE'):
    """Create the selected individual-showcase backdrop material."""
    kind = kind or 'MATTE'
    name = f"FantasyChess_IndividualShowcaseBackdrop_{kind.title()}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (0.08, 0.08, 0.09, 1.0)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (760, 0)

    if kind == 'MATTE':
        # Non-reflective dark gradient remains the default so the piece is the focus.
        emission = nodes.new("ShaderNodeEmission")
        emission.location = (500, 0)
        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-620, 0)
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-430, 0)
        separate = nodes.new("ShaderNodeSeparateXYZ")
        separate.location = (-220, 0)
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (30, 0)
        links.new(texcoord.outputs.get("Generated"), mapping.inputs.get("Vector"))
        links.new(mapping.outputs.get("Vector"), separate.inputs.get("Vector"))
        links.new(separate.outputs.get("Z"), ramp.inputs.get("Fac"))
        links.new(ramp.outputs.get("Color"), emission.inputs.get("Color"))
        links.new(emission.outputs.get("Emission"), out.inputs.get("Surface"))
        cr = ramp.color_ramp
        e0, e1 = cr.elements[0], cr.elements[1]
        e0.position = 0.02
        e1.position = 0.96
        e0.color = (0.018, 0.019, 0.022, 1.0)
        e1.color = (0.085, 0.090, 0.105, 1.0)
        e2 = cr.elements.new(0.50)
        e2.color = (0.040, 0.043, 0.050, 1.0)
        _set_node_input(emission, "Strength", 0.30)
        return mat

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (500, 0)
    links.new(bsdf.outputs.get("BSDF"), out.inputs.get("Surface"))

    if kind in {'WOOD', 'STONE'}:
        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-620, 0)
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-440, 0)
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-250, 0)
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (0, 0)
        links.new(texcoord.outputs.get("Generated"), mapping.inputs.get("Vector"))
        links.new(mapping.outputs.get("Vector"), noise.inputs.get("Vector"))
        links.new(noise.outputs.get("Fac"), ramp.inputs.get("Fac"))
        links.new(ramp.outputs.get("Color"), bsdf.inputs.get("Base Color"))
        e0, e1 = ramp.color_ramp.elements[0], ramp.color_ramp.elements[1]
        if kind == 'WOOD':
            mapping.inputs.get("Scale").default_value = (3.5, 3.5, 0.75)
            noise.inputs.get("Scale").default_value = 3.0
            noise.inputs.get("Detail").default_value = 4.0
            e0.color = (0.018, 0.006, 0.003, 1.0)
            e1.color = (0.11, 0.035, 0.012, 1.0)
            _set_node_input(bsdf, "Roughness", 0.56)
        else:
            noise.inputs.get("Scale").default_value = 5.2
            noise.inputs.get("Detail").default_value = 5.0
            e0.color = (0.020, 0.022, 0.026, 1.0)
            e1.color = (0.10, 0.105, 0.12, 1.0)
            _set_node_input(bsdf, "Roughness", 0.76)
        _set_node_input(bsdf, "Metallic", 0.0)
    elif kind == 'METAL':
        _set_node_input(bsdf, "Base Color", (0.035, 0.042, 0.055, 1.0))
        _set_node_input(bsdf, "Metallic", 0.82)
        _set_node_input(bsdf, "Roughness", 0.36)
    elif kind == 'GLASS':
        _set_node_input(bsdf, "Base Color", (0.035, 0.050, 0.065, 1.0))
        _set_node_input(bsdf, "Metallic", 0.0)
        _set_node_input(bsdf, "Roughness", 0.30)
        _set_node_input(bsdf, ("Transmission Weight", "Transmission"), 0.42)
        _set_node_input(bsdf, "IOR", 1.45)
    return mat

def _add_area_light(name, collection, location, target, energy, size):
    data = bpy.data.lights.new(name + "_Data", type='AREA')
    data.energy = energy
    data.shape = 'DISK'
    data.size = size
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    _look_at(obj, target)
    return obj


def _clear_showcase_camera_markers(scene):
    for marker in list(scene.timeline_markers):
        if marker.name.startswith("FantasyChess_Showcase_"):
            scene.timeline_markers.remove(marker)


def _create_showcase_camera(scene, collection, name, location, target, lens=48.0):
    cam_data = bpy.data.cameras.new(name + "_Data")
    cam_data.lens = lens
    cam_data.sensor_width = 36.0
    cam_obj = bpy.data.objects.new(name, cam_data)
    collection.objects.link(cam_obj)
    cam_obj.location = location
    _look_at(cam_obj, target)
    return cam_obj


def _set_object_keyframes_linear(obj):
    """Set keyframes on an object to linear interpolation across Blender versions."""
    anim_data = getattr(obj, "animation_data", None)
    if anim_data is None or anim_data.action is None:
        return False

    curves = []
    action = anim_data.action

    # Blender 4.x legacy Action API.
    legacy_fcurves = getattr(action, "fcurves", None)
    if legacy_fcurves is not None:
        try:
            curves = list(legacy_fcurves)
        except Exception:
            curves = []

    # Blender 5.x layered Action API. F-Curves live in the channel bag for the
    # Action slot assigned to this object's AnimData.
    if not curves:
        try:
            from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot
            channelbag = animdata_get_channelbag_for_assigned_slot(anim_data)
            if channelbag is not None:
                curves = list(channelbag.fcurves)
        except Exception:
            curves = []

    changed = False
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'
            changed = True
    return changed


def _apply_sequence_output_settings(scene, base_name="fantasy_chess_showcase"):
    """Apply Blender 5.2-compatible video output settings for a showcase animation."""
    image_settings = scene.render.image_settings
    video_enabled = False

    # Blender 5.2+: Video is a Media Type, not an Image File Format.
    if hasattr(image_settings, 'media_type'):
        image_settings.media_type = 'VIDEO'
        video_enabled = (image_settings.media_type == 'VIDEO')
    else:
        # Compatibility fallback for older Blender releases.
        try:
            image_settings.file_format = 'FFMPEG'
            video_enabled = True
        except Exception:
            video_enabled = False

    try:
        image_settings.color_mode = 'RGB'
    except Exception:
        pass
    try:
        image_settings.color_depth = '8'
    except Exception:
        pass
    try:
        scene.render.use_file_extension = True
    except Exception:
        pass
    if hasattr(scene.render, 'save_output'):
        try:
            scene.render.save_output = True
        except Exception:
            pass

    ffmpeg = getattr(scene.render, 'ffmpeg', None)
    if ffmpeg is not None:
        for attr, value in (
            ('format', 'MPEG4'),
            ('codec', 'H264'),
            ('constant_rate_factor', 'MEDIUM'),
            ('ffmpeg_preset', 'GOOD'),
            ('gopsize', 12),
            ('video_bitrate', 6000),
            ('maxrate', 9000),
            ('buffersize', 1792),
            ('audio_codec', 'NONE'),
        ):
            if hasattr(ffmpeg, attr):
                try:
                    setattr(ffmpeg, attr, value)
                except Exception:
                    pass

    # Save the finished showcase video in the current user's Downloads folder.
    # Blender/FFmpeg appends the .mp4 extension when File Extensions is enabled.
    downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    try:
        os.makedirs(downloads_dir, exist_ok=True)
    except OSError:
        downloads_dir = os.path.expanduser("~")
    scene.render.filepath = os.path.join(downloads_dir, base_name)
    return video_enabled


def apply_sequence_render_settings(scene):
    """Apply the dedicated 10-second full-set showcase animation render preset."""
    apply_best_render_settings(scene)

    # The sequence is intended to render faster than a high-quality still.
    cycles = getattr(scene, 'cycles', None)
    if cycles is not None:
        if hasattr(cycles, 'samples'):
            cycles.samples = 128
        if hasattr(cycles, 'preview_samples'):
            cycles.preview_samples = 64
        if hasattr(cycles, 'use_denoising'):
            cycles.use_denoising = True
        if hasattr(cycles, 'use_adaptive_sampling'):
            cycles.use_adaptive_sampling = True
        if hasattr(cycles, 'adaptive_threshold'):
            cycles.adaptive_threshold = 0.015

    scene.frame_start = 1
    scene.frame_end = 240
    try:
        scene.render.fps = 24
        scene.render.fps_base = 1.0
    except Exception:
        pass

    # Full-set video preset belongs to the animated sweeping showcase camera.
    _activate_render_camera(scene, "FantasyChess_Showcase_Camera")
    return _apply_sequence_output_settings(scene, "fantasy_chess_showcase")


def apply_individual_piece_showcase_render_settings(scene):
    """Apply the dedicated 5-second individual-piece showcase animation render preset."""
    apply_best_render_settings(scene)

    cycles = getattr(scene, 'cycles', None)
    if cycles is not None:
        if hasattr(cycles, 'samples'):
            cycles.samples = 128
        if hasattr(cycles, 'preview_samples'):
            cycles.preview_samples = 64
        if hasattr(cycles, 'use_denoising'):
            cycles.use_denoising = True
        if hasattr(cycles, 'use_adaptive_sampling'):
            cycles.use_adaptive_sampling = True
        if hasattr(cycles, 'adaptive_threshold'):
            cycles.adaptive_threshold = 0.015

    scene.frame_start = 1
    scene.frame_end = 120
    try:
        scene.render.fps = 24
        scene.render.fps_base = 1.0
    except Exception:
        pass

    # Individual-piece preset belongs to the dedicated single-piece camera.
    _activate_render_camera(scene, "FantasyChess_PieceShowcase_Camera")
    return _apply_sequence_output_settings(scene, "fantasy_chess_piece_showcase")


def render_individual_piece_showcase(scene):
    """Build, configure, and render the currently selected individual piece showcase video."""
    piece_kind = scene.elf_chess_showcase_piece
    showcase_side = getattr(scene, "elf_chess_showcase_side", "White")
    build_individual_piece_showcase(scene, piece_kind=piece_kind)
    video_enabled = apply_individual_piece_showcase_render_settings(scene)
    if not video_enabled:
        raise RuntimeError("Could not switch Blender to Video output")

    # Use a piece-specific filename so rendering another piece does not
    # overwrite the previous individual showcase by accident.
    output_dir = os.path.dirname(scene.render.filepath)
    scene.render.filepath = os.path.join(
        output_dir,
        f"fantasy_chess_{showcase_side.lower()}_{piece_kind.lower()}_showcase"
    )
    scene.frame_set(scene.frame_start)
    bpy.ops.render.render(animation=True)
    return scene.render.filepath


def build_render_sequence(scene):
    """Create a separate showcase area with one of each piece and a single sweeping camera."""
    root = _root_collection(scene)
    _remove_named_child(root, RENDER_SEQUENCE_NAME)
    _clear_showcase_camera_markers(scene)
    coll = _get_or_create_collection(root, RENDER_SEQUENCE_NAME)

    s = scene.elf_chess_square_size
    scale = scene.elf_chess_piece_scale * s
    segments = scene.elf_chess_radial_segments
    style = scene.elf_chess_style
    outer = 8.0 * s + 2.0 * scene.elf_chess_border_width
    offset_y = outer * 6.0

    white_material = _ensure_piece_material(scene.elf_chess_white_material, "White", scene.elf_chess_white_color)
    black_material = _ensure_piece_material(scene.elf_chess_black_material, "Black", scene.elf_chess_black_color)
    backdrop_mat = _ensure_showcase_backdrop_material()

    # Oversize the stage so the backdrop fully fills the single sweeping camera view.
    # The floor is intentionally much larger than the displayed piece area so the
    # camera can never see beyond the stage during the left-to-right sweep.
    stage_width = 14.0 * s
    stage_depth = 8.0 * s
    stage_height = max(0.06 * s, 0.04)
    wall_height = 8.8 * s
    wall_thickness = 0.12 * s
    wing_depth = 4.8 * s
    back_width = stage_width * 2.45
    floor_width = back_width * 1.10
    floor_depth = stage_depth * 2.20
    floor_center_y = offset_y - stage_depth * 0.60

    floor = _box(
        "Showcase_Floor",
        (floor_width, floor_depth, stage_height),
        (0.0, floor_center_y, -stage_height * 0.5),
        coll,
    )
    _assign_render_material(floor, _ensure_showcase_floor_material(scene.elf_chess_showcase_floor_material))

    back_y = offset_y + stage_depth * 0.5 - wall_thickness * 0.5
    back_wall = _box(
        "Showcase_Backdrop_Back",
        (back_width, wall_thickness, wall_height),
        (0.0, back_y, wall_height * 0.5 - 0.02 * s),
        coll,
    )
    _assign_render_material(back_wall, backdrop_mat)

    side_x = back_width * 0.5 - wall_thickness * 0.5
    side_y = back_y - wing_depth * 0.5 + wall_thickness * 0.5
    left_wall = _box(
        "Showcase_Backdrop_Left",
        (wall_thickness, wing_depth, wall_height),
        (-side_x, side_y, wall_height * 0.5 - 0.02 * s),
        coll,
    )
    right_wall = _box(
        "Showcase_Backdrop_Right",
        (wall_thickness, wing_depth, wall_height),
        (side_x, side_y, wall_height * 0.5 - 0.02 * s),
        coll,
    )
    _assign_render_material(left_wall, backdrop_mat)
    _assign_render_material(right_wall, backdrop_mat)

    # Join the flat backdrop walls together, then bevel only the corner creases
    # slightly so the background reads softer and less attention-grabbing.
    backdrop = _join_objects_as_single(
        coll,
        [back_wall, left_wall, right_wall],
        "Showcase_Backdrop",
    )
    if backdrop is not None:
        bev = backdrop.modifiers.new(name="BackdropCreaseBevel", type='BEVEL')
        bev.limit_method = 'ANGLE'
        bev.angle_limit = radians(20.0)
        bev.width = 0.12 * s
        bev.segments = 4
        bev.profile = 0.70
        try:
            bev.harden_normals = True
        except Exception:
            pass

    pieces_coll = _get_or_create_collection(coll, "Showcase Pieces")
    white_coll = _get_or_create_collection(pieces_coll, "White Showcase")
    black_coll = _get_or_create_collection(pieces_coll, "Black Showcase")

    kinds = ["Pawn", "Rook", "Knight", "Bishop", "Queen", "King"]
    spacing = 1.62 * s
    start_x = -spacing * 2.5
    z = 0.0
    white_y = offset_y - 0.95 * s
    black_y = offset_y + 0.95 * s

    for i, kind in enumerate(kinds):
        x = start_x + i * spacing
        _create_piece(kind, f"SHOW_W_{kind}", "White", style, x, white_y, z, scale, segments, white_coll, white_material)
        _create_piece(kind, f"SHOW_B_{kind}", "Black", style, x, black_y, z, scale, segments, black_coll, black_material)

    target = (0.0, offset_y, 0.98 * s)
    power_scale = max(0.25, s * s)
    _add_area_light(
        "FantasyChess_Showcase_Key", coll,
        (-stage_width * 0.34, offset_y - stage_depth * 1.05, 5.2 * s), target,
        2400.0 * power_scale, stage_width * 0.48,
    )
    _add_area_light(
        "FantasyChess_Showcase_Fill", coll,
        (stage_width * 0.44, offset_y - stage_depth * 0.56, 4.0 * s), target,
        1350.0 * power_scale, stage_width * 0.56,
    )
    _add_area_light(
        "FantasyChess_Showcase_Rim", coll,
        (0.0, offset_y + stage_depth * 0.92, 4.8 * s), target,
        900.0 * power_scale, stage_width * 0.52,
    )

    # Single camera that sweeps slowly from left to right over the full 240 frames.
    cam_target = _empty("FantasyChess_Showcase_Target", coll, location=target)
    cam = _create_showcase_camera(
        scene, coll, "FantasyChess_Showcase_Camera",
        (-stage_width * 0.62, offset_y - stage_depth * 2.05, 2.65 * s), target, lens=48.0,
    )
    cam_constraint = cam.constraints.new(type='TRACK_TO')
    cam_constraint.target = cam_target
    cam_constraint.track_axis = 'TRACK_NEGATIVE_Z'
    cam_constraint.up_axis = 'UP_Y'

    scene.camera = cam
    scene.frame_start = 1
    scene.frame_end = 240
    try:
        scene.render.fps = 24
        scene.render.fps_base = 1.0
    except Exception:
        pass

    cam.location = (-stage_width * 0.62, offset_y - stage_depth * 2.05, 2.65 * s)
    cam.keyframe_insert(data_path="location", frame=1)
    cam.location = (stage_width * 0.62, offset_y - stage_depth * 2.05, 2.65 * s)
    cam.keyframe_insert(data_path="location", frame=240)
    _set_object_keyframes_linear(cam)

    if scene.world is None:
        scene.world = bpy.data.worlds.new("FantasyChess_World")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs.get("Color").default_value = (0.05, 0.055, 0.065, 1.0)
        bg.inputs.get("Strength").default_value = 0.35

    return coll


def remove_render_sequence(scene):
    root = _find_child(scene.collection, ROOT_NAME)
    if not root:
        _clear_showcase_camera_markers(scene)
        return False
    sequence_coll = _find_child(root, RENDER_SEQUENCE_NAME)
    if not sequence_coll:
        _clear_showcase_camera_markers(scene)
        return False
    if scene.camera and scene.camera.name.startswith("FantasyChess_Showcase_"):
        scene.camera = None
    _clear_showcase_camera_markers(scene)
    _remove_collection_tree(sequence_coll)
    return True


def build_individual_piece_showcase(scene, piece_kind=None):
    """Create a clean single-piece showcase using the selected side's material and color."""
    root = _root_collection(scene)
    _remove_named_child(root, INDIVIDUAL_SHOWCASE_NAME)
    coll = _get_or_create_collection(root, INDIVIDUAL_SHOWCASE_NAME)

    s = scene.elf_chess_square_size
    scale = scene.elf_chess_piece_scale * s * 1.12
    segments = scene.elf_chess_radial_segments
    style = scene.elf_chess_style
    piece_kind = piece_kind or scene.elf_chess_showcase_piece
    showcase_side = getattr(scene, "elf_chess_showcase_side", "White")
    outer = 8.0 * s + 2.0 * scene.elf_chess_border_width
    offset_x = outer * 6.0
    offset_y = 0.0

    piece_material = _ensure_piece_material(
        _side_material_setting(scene, showcase_side),
        showcase_side,
        _side_color_setting(scene, showcase_side),
    )
    backdrop_mat = _ensure_individual_showcase_backdrop_material(scene.elf_chess_individual_background_material)

    # Product-showcase best practices: a darker, simple backdrop with no specular
    # response, broad soft lights, and a slow turntable rotation so the piece
    # stays the focus and the background does not compete with the model.
    # Oversize the backdrop so the camera view cannot see past it.
    backdrop_width = 18.0 * s
    backdrop_height = 14.0 * s
    backdrop = _box(
        "PieceShowcase_Backdrop",
        (backdrop_width, 0.08 * s, backdrop_height),
        (offset_x, offset_y + 3.8 * s, backdrop_height * 0.5),
        coll,
    )
    _assign_render_material(backdrop, backdrop_mat)

    piece = _create_piece(
        piece_kind,
        f"SHOWCASE_{piece_kind}",
        showcase_side,
        style,
        0.0,
        0.0,
        0.0,
        scale,
        segments,
        coll,
        piece_material,
    )

    spinner = _empty(
        "FantasyChess_PieceShowcase_Spinner",
        coll,
        location=(offset_x, offset_y, 1.20 * s),
    )
    tilt = _empty("FantasyChess_PieceShowcase_Tilt", coll, location=(0.0, 0.0, 0.0))
    tilt.parent = spinner
    tilt.rotation_euler = (radians(10), radians(0), radians(-12))

    piece.parent = tilt
    piece.matrix_parent_inverse = tilt.matrix_world.inverted()
    piece.location = (0.0, 0.0, 0.0)

    # Aim slightly above the geometric midpoint so tall pieces sit a little lower
    # in the frame and have more breathing room above crowns/crosses.
    target = (offset_x, offset_y, 2.02 * s)
    power_scale = max(0.25, s * s)

    # Softer, broader product lighting reduces clipped highlights on reflective
    # metal/glass materials while keeping enough edge definition to show detail.
    _add_area_light(
        "FantasyChess_PieceShowcase_Key", coll,
        (offset_x - 3.2 * s, offset_y - 3.0 * s, 4.7 * s), target,
        1180.0 * power_scale, 4.0 * s,
    )
    _add_area_light(
        "FantasyChess_PieceShowcase_Fill", coll,
        (offset_x + 3.0 * s, offset_y - 2.0 * s, 3.4 * s), target,
        480.0 * power_scale, 3.4 * s,
    )
    _add_area_light(
        "FantasyChess_PieceShowcase_Rim", coll,
        (offset_x, offset_y + 2.9 * s, 4.0 * s), target,
        620.0 * power_scale, 3.8 * s,
    )

    cam_target = _empty("FantasyChess_PieceShowcase_Target", coll, location=target)
    cam = _create_showcase_camera(
        scene,
        coll,
        "FantasyChess_PieceShowcase_Camera",
        (offset_x + 0.18 * s, offset_y - 7.25 * s, 2.02 * s),
        target,
        lens=58.0,
    )
    cam_constraint = cam.constraints.new(type='TRACK_TO')
    cam_constraint.target = cam_target
    cam_constraint.track_axis = 'TRACK_NEGATIVE_Z'
    cam_constraint.up_axis = 'UP_Y'

    scene.camera = cam
    scene.frame_start = 1
    scene.frame_end = 120
    try:
        scene.render.fps = 24
        scene.render.fps_base = 1.0
    except Exception:
        pass

    spinner.rotation_euler = (0.0, 0.0, 0.0)
    spinner.keyframe_insert(data_path="rotation_euler", frame=1)
    spinner.rotation_euler = (0.0, 0.0, 2.0 * pi)
    spinner.keyframe_insert(data_path="rotation_euler", frame=120)
    _set_object_keyframes_linear(spinner)

    if scene.world is None:
        scene.world = bpy.data.worlds.new("FantasyChess_World")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs.get("Color").default_value = (0.040, 0.042, 0.048, 1.0)
        bg.inputs.get("Strength").default_value = 0.20

    return coll



def remove_individual_piece_showcase(scene):
    root = _find_child(scene.collection, ROOT_NAME)
    if not root:
        return False
    showcase_coll = _find_child(root, INDIVIDUAL_SHOWCASE_NAME)
    if not showcase_coll:
        return False
    if scene.camera and scene.camera.name.startswith("FantasyChess_PieceShowcase_"):
        scene.camera = None
    _remove_collection_tree(showcase_coll)
    return True


def _activate_render_camera(scene, camera_name):
    """Make a generated camera active when it exists; leave the current camera unchanged otherwise."""
    camera = bpy.data.objects.get(camera_name)
    if camera is not None and camera.type == 'CAMERA':
        scene.camera = camera
        return True
    return False


def apply_best_render_settings(scene):
    """Apply a clean product-render configuration tuned for this add-on."""
    try:
        scene.render.engine = 'CYCLES'
    except Exception:
        pass

    scene.render.resolution_x = 2560
    scene.render.resolution_y = 1920
    scene.render.resolution_percentage = 100

    # Blender 5.2 separates Image and Video under Media Type. If Video is
    # currently active, PNG is not a valid file_format enum until we switch
    # Media Type back to Image first. Older Blender versions do not expose
    # media_type, so they continue using file_format directly.
    image_settings = scene.render.image_settings
    if hasattr(image_settings, 'media_type'):
        try:
            image_settings.media_type = 'IMAGE'
        except Exception:
            pass
    try:
        image_settings.file_format = 'PNG'
    except Exception:
        # A final retry after explicitly selecting Image mode handles Blender
        # builds that refresh the valid file-format enum lazily.
        if hasattr(image_settings, 'media_type'):
            try:
                image_settings.media_type = 'IMAGE'
                image_settings.file_format = 'PNG'
            except Exception:
                pass
    try:
        image_settings.color_mode = 'RGB'
    except Exception:
        pass
    try:
        image_settings.color_depth = '16'
    except Exception:
        pass
    # PNG compression is lossless. A moderate value keeps saves reasonably fast
    # without producing needlessly large files.
    try:
        image_settings.compression = 30
    except Exception:
        pass
    scene.render.film_transparent = False

    try:
        scene.view_settings.look = 'AgX - Medium High Contrast'
    except Exception:
        pass
    try:
        scene.view_settings.exposure = 0.25
    except Exception:
        pass
    try:
        scene.render.use_compositing = True
    except Exception:
        pass

    cycles = getattr(scene, 'cycles', None)
    if cycles is not None:
        for name, value in (
            ('samples', 1024),
            ('preview_samples', 128),
            ('max_bounces', 16),
            ('diffuse_bounces', 6),
            ('glossy_bounces', 6),
            ('transmission_bounces', 12),
            ('transparent_max_bounces', 12),
            ('volume_bounces', 0),
            ('filter_glossy', 0.15),
            ('adaptive_threshold', 0.004),
        ):
            if hasattr(cycles, name):
                setattr(cycles, name, value)
        for name, value in (
            ('use_adaptive_sampling', True),
            ('use_denoising', True),
            ('use_preview_denoising', True),
            ('caustics_reflective', False),
            ('caustics_refractive', False),
        ):
            if hasattr(cycles, name):
                setattr(cycles, name, value)
        if hasattr(cycles, 'denoiser'):
            try:
                cycles.denoiser = 'OPENIMAGEDENOISE'
            except Exception:
                pass
        if hasattr(cycles, 'device'):
            try:
                cycles.device = 'GPU'
            except Exception:
                pass

    view_layer = bpy.context.view_layer
    view_layer_cycles = getattr(view_layer, 'cycles', None)
    if view_layer_cycles is not None:
        if hasattr(view_layer_cycles, 'use_denoising'):
            view_layer_cycles.use_denoising = True
        if hasattr(view_layer_cycles, 'denoising_store_passes'):
            view_layer_cycles.denoising_store_passes = True

    # Still-image preset belongs to the camera created by Create Render Scene.
    _activate_render_camera(scene, "FantasyChess_Camera")
    return True


def build_render_scene(scene):
    # Build the chess-set camera/light rig without changing heavy render/output
    # settings. High-quality settings are a separate, explicitly confirmed step.
    apply_selected_materials(scene)
    root = _root_collection(scene)
    _remove_named_child(root, RENDER_SCENE_NAME)
    coll = _get_or_create_collection(root, RENDER_SCENE_NAME)

    s = scene.elf_chess_square_size
    board = 8.0 * s
    outer = board + 2.0 * scene.elf_chess_border_width
    target_z = scene.elf_chess_board_base_height + scene.elf_chess_tile_height + 0.58 * s
    target = (0.0, 0.0, target_z)

    # Oversized dark studio floor placed lower so it sits clearly beneath the
    # chess set and fully covers the render camera view.
    floor_width = outer * 6.2
    floor_depth = outer * 7.2
    floor_thickness = max(0.08 * s, 0.04)
    floor = _box(
        "Render_Floor",
        (floor_width, floor_depth, floor_thickness),
        (0.0, -outer * 0.55, -max(0.18 * s, 0.09)),
        coll,
    )
    _assign_render_material(floor, _ensure_scene_surface_material())

    # Camera is placed slightly lower and closer than before so the pieces show
    # more side detail and read better in the final render.
    cam_data = bpy.data.cameras.new("FantasyChess_Camera_Data")
    cam_data.lens = 58.0
    cam_data.sensor_width = 36.0
    cam_obj = bpy.data.objects.new("FantasyChess_Camera", cam_data)
    coll.objects.link(cam_obj)
    cam_obj.location = (outer * 1.10, -outer * 1.35, outer * 0.95)
    _look_at(cam_obj, target)
    scene.camera = cam_obj

    # Five-light studio rig for the chess set and board render scene. The low
    # fill plus an extra dark-side fill help keep the near corner readable,
    # especially on glass and metal boards.
    power_scale = max(0.25, s * s)
    _add_area_light(
        "FantasyChess_Key", coll,
        (-outer * 0.50, -outer * 1.05, outer * 1.35), target,
        2300.0 * power_scale, outer * 1.10,
    )
    _add_area_light(
        "FantasyChess_Fill", coll,
        (outer * 1.10, -outer * 0.35, outer * 0.95), target,
        1200.0 * power_scale, outer * 1.20,
    )
    _add_area_light(
        "FantasyChess_Rim", coll,
        (-outer * 0.10, outer * 1.10, outer * 1.15), target,
        700.0 * power_scale, outer * 0.95,
    )
    _add_area_light(
        "FantasyChess_LowFill", coll,
        (-outer * 1.02, -outer * 0.58, outer * 0.34), target,
        520.0 * power_scale, outer * 0.80,
    )
    _add_area_light(
        "FantasyChess_DarkFill", coll,
        (-outer * 1.18, -outer * 0.12, outer * 0.58), target,
        430.0 * power_scale, outer * 0.92,
    )

    # Set a brighter studio-like world for clearer transparent and reflective materials.
    if scene.world is None:
        scene.world = bpy.data.worlds.new("FantasyChess_World")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs.get("Color").default_value = (0.10, 0.11, 0.13, 1.0)
        bg.inputs.get("Strength").default_value = 0.65

    # Once the standard rig exists, tune it for the currently selected board.
    _adjust_render_lighting_for_board_material(scene)
    return coll


def remove_render_scene(scene):
    root = _find_child(scene.collection, ROOT_NAME)
    if not root:
        return False
    render_coll = _find_child(root, RENDER_SCENE_NAME)
    if not render_coll:
        return False
    if scene.camera and scene.camera.name == "FantasyChess_Camera":
        scene.camera = None
    _remove_collection_tree(render_coll)
    return True


# -----------------------------------------------------------------------------
# Operators
# -----------------------------------------------------------------------------

class ELFCHESS_OT_build_board(bpy.types.Operator):
    bl_idname = "elf_chess.build_board"
    bl_label = "Create Board"
    bl_description = "Create or replace the chess board geometry"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        build_board(context.scene)
        self.report({'INFO'}, "Chess board created")
        return {'FINISHED'}


class ELFCHESS_OT_remove_board(bpy.types.Operator):
    bl_idname = "elf_chess.remove_board"
    bl_label = "Remove Board"
    bl_description = "Remove only the generated board; piece sets are left untouched"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed = remove_board(context.scene)
        self.report({'INFO'}, "Board removed" if removed else "No generated board found")
        return {'FINISHED'}


class ELFCHESS_OT_build_white(bpy.types.Operator):
    bl_idname = "elf_chess.build_white"
    bl_label = "Create White Set"
    bl_description = "Create or replace the 16 White-side pieces using the selected style and White render material"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        build_piece_side(context.scene, "White")
        self.report({'INFO'}, f"White-side {context.scene.elf_chess_style.title()} set created: 16 pieces")
        return {'FINISHED'}


class ELFCHESS_OT_remove_white(bpy.types.Operator):
    bl_idname = "elf_chess.remove_white"
    bl_label = "Remove White Set"
    bl_description = "Remove only the generated White-side pieces"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed = remove_piece_side(context.scene, "White")
        self.report({'INFO'}, "White-side pieces removed" if removed else "No White-side set found")
        return {'FINISHED'}


class ELFCHESS_OT_build_black(bpy.types.Operator):
    bl_idname = "elf_chess.build_black"
    bl_label = "Create Black Set"
    bl_description = "Create or replace the 16 Black-side pieces using the selected style and Black render material"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        build_piece_side(context.scene, "Black")
        self.report({'INFO'}, f"Black-side {context.scene.elf_chess_style.title()} set created: 16 pieces")
        return {'FINISHED'}


class ELFCHESS_OT_remove_black(bpy.types.Operator):
    bl_idname = "elf_chess.remove_black"
    bl_label = "Remove Black Set"
    bl_description = "Remove only the generated Black-side pieces"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed = remove_piece_side(context.scene, "Black")
        self.report({'INFO'}, "Black-side pieces removed" if removed else "No Black-side set found")
        return {'FINISHED'}


class ELFCHESS_OT_apply_materials(bpy.types.Operator):
    bl_idname = "elf_chess.apply_materials"
    bl_label = "Apply Materials"
    bl_description = "Apply the selected render materials to the board and any already-generated White/Black piece sets"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = apply_selected_materials(context.scene)
        if count:
            self.report({'INFO'}, f"Materials applied to {count} generated mesh objects")
        else:
            self.report({'INFO'}, "No generated board or chess pieces found")
        return {'FINISHED'}


class ELFCHESS_OT_build_scene(bpy.types.Operator):
    bl_idname = "elf_chess.build_scene"
    bl_label = "Add Camera And Light: Chess Set"
    bl_description = "Add the chess-set camera, studio floor, world background, and material-aware five-light rig without changing render quality settings"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        build_render_scene(context.scene)
        self.report({'INFO'}, "Chess set camera and lighting added: camera, floor, and five lights")
        return {'FINISHED'}


class ELFCHESS_OT_build_sequence(bpy.types.Operator):
    bl_idname = "elf_chess.build_sequence"
    bl_label = "Create Full Set Showcase"
    bl_description = "Create a staged showcase of both sides with one of each piece and a 10-second sweeping camera"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        build_render_sequence(context.scene)
        self.report({'INFO'}, "Full set showcase created. Apply Video Render Settings before rendering the animation.")
        return {'FINISHED'}


class ELFCHESS_OT_sequence_render_settings(bpy.types.Operator):
    bl_idname = "elf_chess.sequence_render_settings"
    bl_label = "Apply Video Render Settings"
    bl_description = "Set the showcase animation to Cycles 128 samples, Video / MPEG-4 / H.264, and save to the user Downloads folder"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Apply full-set video settings?", icon='QUESTION')
        col.label(text="Sets H.264 video output and activates the showcase camera.")
        col.label(text="Press Numpad 0 for camera view.")
        warn = layout.column(align=True)
        warn.alert = True
        warn.label(text="Overwrites current render/output settings.", icon='ERROR')
        warn.label(text="Rendering may temporarily slow or freeze your computer.", icon='ERROR')

    def execute(self, context):
        video_enabled = apply_sequence_render_settings(context.scene)
        if video_enabled:
            self.report({'WARNING'}, "Sequence render settings applied and showcase camera activated: 128 samples, 24 fps, MPEG-4/H.264, output Downloads/fantasy_chess_showcase.mp4.")
            return {'FINISHED'}
        self.report({'ERROR'}, "Could not switch this Blender build to Video output. Check Output > Media Type manually.")
        return {'CANCELLED'}


class ELFCHESS_OT_remove_sequence(bpy.types.Operator):
    bl_idname = "elf_chess.remove_sequence"
    bl_label = "Remove Full Set Showcase"
    bl_description = "Remove the generated full-set showcase stage and sweeping camera"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed = remove_render_sequence(context.scene)
        self.report({'INFO'}, "Full set showcase removed" if removed else "No generated full set showcase found")
        return {'FINISHED'}


class ELFCHESS_OT_build_individual_showcase(bpy.types.Operator):
    bl_idname = "elf_chess.build_individual_showcase"
    bl_label = "Create Individual Piece Showcase"
    bl_description = "Create a clean 5-second showcase video setup for one chess piece using the selected White or Black side material and color"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        build_individual_piece_showcase(context.scene)
        self.report({'INFO'}, "Individual piece showcase created. Use Apply Individual Video Settings before rendering the animation.")
        return {'FINISHED'}


class ELFCHESS_OT_individual_showcase_render_settings(bpy.types.Operator):
    bl_idname = "elf_chess.individual_showcase_render_settings"
    bl_label = "Apply Individual Video Settings"
    bl_description = "Set the individual-piece showcase to Cycles 128 samples, a 120-frame video, Video / MPEG-4 / H.264, and save to the user Downloads folder"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        piece_kind = context.scene.elf_chess_showcase_piece
        showcase_side = getattr(context.scene, "elf_chess_showcase_side", "White")
        col = layout.column(align=True)
        col.label(text=f"Apply {showcase_side} {piece_kind} video settings?", icon='QUESTION')
        col.label(text="Sets H.264 video output and activates the individual camera.")
        col.label(text="Press Numpad 0 for camera view.")
        warn = layout.column(align=True)
        warn.alert = True
        warn.label(text="Overwrites current render/output settings.", icon='ERROR')
        warn.label(text="Rendering may temporarily slow or freeze your computer.", icon='ERROR')

    def execute(self, context):
        video_enabled = apply_individual_piece_showcase_render_settings(context.scene)
        if video_enabled:
            self.report({'WARNING'}, "Individual showcase settings applied and individual camera activated: 128 samples, 24 fps, 120 frames, MPEG-4/H.264, output Downloads/fantasy_chess_piece_showcase.mp4.")
            return {'FINISHED'}
        self.report({'ERROR'}, "Could not switch this Blender build to Video output. Check Output > Media Type manually.")
        return {'CANCELLED'}


class ELFCHESS_OT_render_individual_showcase(bpy.types.Operator):
    bl_idname = "elf_chess.render_individual_showcase"
    bl_label = "Render Individual Piece Video"
    bl_description = "Build the selected individual piece showcase, apply the 5-second H.264 video settings, and render the finished MP4 to the Downloads folder"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        piece_kind = context.scene.elf_chess_showcase_piece
        showcase_side = getattr(context.scene, "elf_chess_showcase_side", "White")
        col = layout.column(align=True)
        col.label(text=f"Render a {showcase_side} {piece_kind} showcase video?", icon='QUESTION')
        col.label(text="This will build the individual piece showcase, apply video settings,")
        col.label(text="and render a 5-second MP4 to your Downloads folder.")
        warn = layout.column(align=True)
        warn.alert = True
        warn.label(text="Rendering is resource intensive and may slow down or temporarily freeze your computer.", icon='ERROR')

    def execute(self, context):
        try:
            piece_kind = context.scene.elf_chess_showcase_piece
            showcase_side = getattr(context.scene, "elf_chess_showcase_side", "White")
            render_individual_piece_showcase(context.scene)
        except Exception as exc:
            self.report({'ERROR'}, f"Individual piece showcase render failed: {exc}")
            return {'CANCELLED'}
        self.report({'WARNING'}, f"Rendered {showcase_side} {piece_kind} showcase video to Downloads/fantasy_chess_{showcase_side.lower()}_{piece_kind.lower()}_showcase.mp4")
        return {'FINISHED'}



class ELFCHESS_OT_remove_individual_showcase(bpy.types.Operator):
    bl_idname = "elf_chess.remove_individual_showcase"
    bl_label = "Remove Individual Piece Showcase"
    bl_description = "Remove the separate single-piece showcase, its lighting, backdrop, and animated camera"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed = remove_individual_piece_showcase(context.scene)
        self.report({'INFO'}, "Individual piece showcase removed" if removed else "No generated individual piece showcase found")
        return {'FINISHED'}


class ELFCHESS_OT_best_render_settings(bpy.types.Operator):
    bl_idname = "elf_chess.best_render_settings"
    bl_label = "High Quality Image Settings"
    bl_description = "Apply a high-quality 2560x1920 Cycles still-image preset with 1024 samples, 16-bit PNG, denoising, higher light-path bounces, and the chess-set camera"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Apply high-quality image settings?", icon='QUESTION')
        col.label(text="Cycles, 1024 samples, 2560x1920, 16-bit PNG.")
        col.label(text="Denoising + higher bounces; activates chess-set camera.")
        col.label(text="Press Numpad 0 for camera view.")
        warn = layout.column(align=True)
        warn.alert = True
        warn.label(text="Changes current render/output settings and renders slower.", icon='ERROR')

    def execute(self, context):
        apply_best_render_settings(context.scene)
        self.report({'INFO'}, "High-quality image settings applied: Cycles 1024 samples, 2560x1920, 16-bit PNG, denoising, higher bounces, chess-set camera active")
        return {'FINISHED'}


class ELFCHESS_OT_remove_scene(bpy.types.Operator):
    bl_idname = "elf_chess.remove_scene"
    bl_label = "Remove Render Scene"
    bl_description = "Remove the generated chess set and board render scene camera, floor, and lights without touching the board or chess pieces"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed = remove_render_scene(context.scene)
        self.report({'INFO'}, "Render scene removed" if removed else "No generated render scene found")
        return {'FINISHED'}


class ELFCHESS_OT_clear(bpy.types.Operator):
    bl_idname = "elf_chess.clear"
    bl_label = "Remove Everything"
    bl_description = "Remove the board, both generated piece sets, the render scene, the full-set showcase, and the individual-piece showcase"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        root = _find_child(context.scene.collection, ROOT_NAME)
        _clear_showcase_camera_markers(context.scene)
        if root:
            if context.scene.camera and (
                context.scene.camera.name == "FantasyChess_Camera"
                or context.scene.camera.name.startswith("FantasyChess_Showcase_")
                or context.scene.camera.name.startswith("FantasyChess_PieceShowcase_")
            ):
                context.scene.camera = None
            _remove_collection_tree(root)
            self.report({'INFO'}, "All generated chess geometry, render-scene, full-set showcase, and individual-piece showcase objects removed")
        else:
            self.report({'INFO'}, "No generated chess geometry found")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Export helpers / operators
# -----------------------------------------------------------------------------

def _selected_meshes(context):
    return [obj for obj in context.selected_objects if obj and obj.type == 'MESH']


def _safe_export_basename(context):
    meshes = _selected_meshes(context)
    if len(meshes) == 1:
        raw = meshes[0].name
    elif context.active_object and context.active_object.type == 'MESH':
        raw = f"{context.active_object.name}_selection"
    else:
        raw = "fantasy_chess_selection"
    cleaned = ''.join(ch if (ch.isalnum() or ch in '-_.') else '_' for ch in raw)
    cleaned = cleaned.strip('._')
    return cleaned or "fantasy_chess_export"


def _export_directory():
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    try:
        os.makedirs(downloads, exist_ok=True)
        return downloads
    except Exception:
        return os.path.expanduser("~")


def _export_selected_stl(context):
    if not _selected_meshes(context):
        raise ValueError("Select at least one mesh object before exporting")
    filepath = os.path.join(_export_directory(), _safe_export_basename(context) + ".stl")
    # Blender 4.x/5.x built-in STL exporter.
    try:
        bpy.ops.wm.stl_export(
            filepath=filepath,
            export_selected_objects=True,
            apply_modifiers=True,
        )
    except (AttributeError, TypeError):
        # Compatibility fallback for older Blender installations.
        bpy.ops.export_mesh.stl(
            filepath=filepath,
            use_selection=True,
            use_mesh_modifiers=True,
        )
    return filepath


def _export_selected_gltf(context, export_format):
    if not _selected_meshes(context):
        raise ValueError("Select at least one mesh object before exporting")
    if export_format == 'GLB':
        extension = ".glb"
    else:
        extension = ".gltf"
    filepath = os.path.join(_export_directory(), _safe_export_basename(context) + extension)
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format=export_format,
        use_selection=True,
        export_materials='EXPORT',
        export_colors=True,
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_apply=True,
        check_existing=False,
    )
    return filepath


class ELFCHESS_OT_export_stl(bpy.types.Operator):
    bl_idname = "elf_chess.export_stl"
    bl_label = "Export Selected to STL"
    bl_description = "Export selected mesh objects to Downloads as STL; STL stores geometry, not Blender materials or colors"

    @classmethod
    def poll(cls, context):
        return bool(_selected_meshes(context))

    def execute(self, context):
        try:
            path = _export_selected_stl(context)
        except Exception as exc:
            self.report({'ERROR'}, f"STL export failed: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"STL exported to {path}")
        return {'FINISHED'}


class ELFCHESS_OT_export_gltf(bpy.types.Operator):
    bl_idname = "elf_chess.export_gltf"
    bl_label = "Export Selected to glTF"
    bl_description = "Export selected objects to Downloads as glTF 2.0 with supported materials and colors"

    @classmethod
    def poll(cls, context):
        return bool(_selected_meshes(context))

    def execute(self, context):
        try:
            path = _export_selected_gltf(context, 'GLTF_SEPARATE')
        except Exception as exc:
            self.report({'ERROR'}, f"glTF export failed: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"glTF exported to {path}")
        return {'FINISHED'}


class ELFCHESS_OT_export_glb(bpy.types.Operator):
    bl_idname = "elf_chess.export_glb"
    bl_label = "Export Selected to GLB"
    bl_description = "Export selected objects to Downloads as a single GLB file with supported materials and colors"

    @classmethod
    def poll(cls, context):
        return bool(_selected_meshes(context))

    def execute(self, context):
        try:
            path = _export_selected_gltf(context, 'GLB')
        except Exception as exc:
            self.report({'ERROR'}, f"GLB export failed: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"GLB exported to {path}")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------

class ELFCHESS_PT_panel(bpy.types.Panel):
    bl_label = "Fantasy Chess"
    bl_idname = "ELFCHESS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Fantasy Chess"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Keep the main workflow compact; detailed guidance lives in tooltips and confirmation dialogs.
        box = layout.box()
        box.label(text="1. Create")
        box.prop(scene, "elf_chess_style", text="Chess Set Style")
        box.operator("elf_chess.build_board", text="Create Board", icon='MESH_GRID')
        row = box.row(align=True)
        row.operator("elf_chess.build_white", text="Create White Set", icon='ADD')
        row.operator("elf_chess.build_black", text="Create Black Set", icon='ADD')

        box = layout.box()
        box.label(text="2. Materials")
        box.label(text="White Side")
        row = box.row(align=True)
        row.prop(scene, "elf_chess_white_material", text="Material")
        row.prop(scene, "elf_chess_white_color", text="Color")
        box.label(text="Black Side")
        row = box.row(align=True)
        row.prop(scene, "elf_chess_black_material", text="Material")
        row.prop(scene, "elf_chess_black_color", text="Color")
        box.prop(scene, "elf_chess_board_material", text="Board")
        box.operator("elf_chess.apply_materials", text="Apply Materials", icon='MATERIAL')

        box = layout.box()
        box.label(text="3. Chess Set Render Scene")
        create_scene = box.row()
        create_scene.scale_y = 1.15
        create_scene.operator("elf_chess.build_scene", text="Add Camera And Light: Chess Set", icon='SCENE_DATA')
        quality_row = box.row()
        quality_row.scale_y = 1.10
        quality_row.operator("elf_chess.best_render_settings", text="High Quality Image Settings", icon='RENDER_STILL')

        box = layout.box()
        box.label(text="4. Full Set Showcase")
        box.prop(scene, "elf_chess_showcase_floor_material", text="Floor Material")
        seq_row = box.row()
        seq_row.scale_y = 1.15
        seq_row.operator("elf_chess.build_sequence", text="Create Full Set Showcase", icon='RENDER_ANIMATION')
        settings_row = box.row()
        settings_row.scale_y = 1.10
        settings_row.operator("elf_chess.sequence_render_settings", text="Apply Video Render Settings", icon='OUTPUT')

        box = layout.box()
        box.label(text="5. Individual Piece Showcase")
        box.prop(scene, "elf_chess_showcase_piece", text="Piece to Showcase")
        box.prop(scene, "elf_chess_showcase_side", text="Showcase Side")
        box.prop(scene, "elf_chess_individual_background_material", text="Background Material")
        show_row = box.row()
        show_row.scale_y = 1.15
        show_row.operator("elf_chess.build_individual_showcase", text="Create Individual Piece Showcase", icon='MESH_UVSPHERE')
        show_settings = box.row()
        show_settings.scale_y = 1.10
        show_settings.operator("elf_chess.individual_showcase_render_settings", text="Apply Individual Video Settings", icon='OUTPUT')
        render_one = box.row()
        render_one.scale_y = 1.15
        render_one.operator("elf_chess.render_individual_showcase", text="Render Individual Piece Video", icon='RENDER_ANIMATION')

        box = layout.box()
        box.label(text="6. Export")
        row = box.row(align=True)
        row.operator("elf_chess.export_stl", text="STL", icon='EXPORT')
        row.operator("elf_chess.export_gltf", text="glTF", icon='EXPORT')
        row.operator("elf_chess.export_glb", text="GLB", icon='EXPORT')

        box = layout.box()
        box.label(text="7. Clear")
        box.operator("elf_chess.remove_board", text="Remove Board", icon='TRASH')
        row = box.row(align=True)
        row.operator("elf_chess.remove_white", text="Remove White Set", icon='TRASH')
        row.operator("elf_chess.remove_black", text="Remove Black Set", icon='TRASH')
        box.operator("elf_chess.remove_scene", text="Remove Render Scene", icon='TRASH')
        box.operator("elf_chess.remove_sequence", text="Remove Full Set Showcase", icon='TRASH')
        box.operator("elf_chess.remove_individual_showcase", text="Remove Individual Piece Showcase", icon='TRASH')

        box = layout.box()
        box.label(text="8. Board Settings")
        box.prop(scene, "elf_chess_board_geometry", text="Board Geometry")
        box.prop(scene, "elf_chess_square_size")
        box.prop(scene, "elf_chess_board_base_height")
        box.prop(scene, "elf_chess_tile_height")
        box.prop(scene, "elf_chess_tile_gap")
        box.prop(scene, "elf_chess_border_width")

        box = layout.box()
        box.label(text="9. Piece Settings")
        box.prop(scene, "elf_chess_piece_scale")
        box.prop(scene, "elf_chess_radial_segments")

        layout.separator()
        remove_all = layout.row()
        remove_all.scale_y = 1.25
        remove_all.operator("elf_chess.clear", text="Remove Everything", icon='TRASH')


classes = (
    ELFCHESS_OT_build_board,
    ELFCHESS_OT_remove_board,
    ELFCHESS_OT_build_white,
    ELFCHESS_OT_remove_white,
    ELFCHESS_OT_build_black,
    ELFCHESS_OT_remove_black,
    ELFCHESS_OT_apply_materials,
    ELFCHESS_OT_build_scene,
    ELFCHESS_OT_build_sequence,
    ELFCHESS_OT_sequence_render_settings,
    ELFCHESS_OT_build_individual_showcase,
    ELFCHESS_OT_individual_showcase_render_settings,
    ELFCHESS_OT_render_individual_showcase,
    ELFCHESS_OT_best_render_settings,
    ELFCHESS_OT_remove_scene,
    ELFCHESS_OT_remove_sequence,
    ELFCHESS_OT_remove_individual_showcase,
    ELFCHESS_OT_clear,
    ELFCHESS_OT_export_stl,
    ELFCHESS_OT_export_gltf,
    ELFCHESS_OT_export_glb,
    ELFCHESS_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.elf_chess_square_size = FloatProperty(
        name="Square Size",
        description="Width of one chess square",
        default=1.0,
        min=0.20,
        max=10.0,
        unit='LENGTH',
    )
    bpy.types.Scene.elf_chess_board_base_height = FloatProperty(
        name="Base Height",
        default=0.18,
        min=0.02,
        max=2.0,
        unit='LENGTH',
    )
    bpy.types.Scene.elf_chess_tile_height = FloatProperty(
        name="Tile Height",
        default=0.08,
        min=0.01,
        max=1.0,
        unit='LENGTH',
    )
    bpy.types.Scene.elf_chess_tile_gap = FloatProperty(
        name="Tile Gap",
        default=0.035,
        min=0.0,
        max=0.25,
        unit='LENGTH',
    )
    bpy.types.Scene.elf_chess_border_width = FloatProperty(
        name="Border Width",
        default=0.36,
        min=0.08,
        max=2.0,
        unit='LENGTH',
    )
    bpy.types.Scene.elf_chess_board_geometry = EnumProperty(
        name="Board Geometry",
        description="Choose whether the board is created as one object or with a separate base and individually selectable checker tiles",
        items=(
            ('JOINED', "Single Object", "Create the entire board as one joined object"),
            ('SEPARATE', "Separate Tiles", "Create the board base as one object and keep each checker tile selectable as its own object"),
        ),
        default='JOINED',
    )
    bpy.types.Scene.elf_chess_style = EnumProperty(
        name="Chess Set Style",
        description="Geometry style used when creating White or Black pieces",
        items=(
            ('ELF', "Elves", "Organic elven chess pieces; leaves are used only on pawns"),
            ('SAMURAI', "Samurai", "Samurai-inspired armored chess pieces with kabuto and castle motifs"),
            ('DOGCAT', "Dog & Cat", "Dog-and-cat themed chess pieces with pet-inspired silhouettes"),
        ),
        default='ELF',
    )
    material_items = (
        ('WOOD', "Wood", "Procedural wood shader tinted by the selected side color"),
        ('GLASS', "Glass", "Transparent glass shader tinted by the selected side color"),
        ('METAL', "Metal", "Metal surface: Natural gives exposed steel; other colors use a painted/coated finish"),
        ('STONE', "Stone", "Carved stone shader tinted by the selected side color"),
    )
    bpy.types.Scene.elf_chess_white_material = EnumProperty(
        name="White Set Material",
        description="Render material assigned to White pieces; changing it updates existing White pieces and showcase copies automatically",
        items=material_items,
        default='WOOD',
        update=_on_white_piece_material_changed,
    )
    bpy.types.Scene.elf_chess_black_material = EnumProperty(
        name="Black Set Material",
        description="Render material assigned to Black pieces; changing it updates existing Black pieces and showcase copies automatically",
        items=material_items,
        default='WOOD',
        update=_on_black_piece_material_changed,
    )
    white_color_items = (
        ('WHITE', "White", "White-tinted material"),
        ('RED', "Red", "Red-tinted material"),
        ('BLUE', "Blue", "Blue-tinted material"),
        ('PURPLE', "Purple", "Purple-tinted material"),
        ('ORANGE', "Orange", "Orange-tinted material"),
        ('YELLOW', "Yellow", "Yellow-tinted material"),
        ('GOLD', "Gold", "Gold color"),
        ('SILVER', "Silver", "Silver color"),
        ('NATURAL', "Natural", "Clear glass, brown wood, gray stone, or steel metal"),
    )
    black_color_items = (
        ('BLACK', "Black", "Black/dark-tinted material"),
        ('RED', "Red", "Red-tinted material"),
        ('BLUE', "Blue", "Blue-tinted material"),
        ('PURPLE', "Purple", "Purple-tinted material"),
        ('ORANGE', "Orange", "Orange-tinted material"),
        ('YELLOW', "Yellow", "Yellow-tinted material"),
        ('GOLD', "Gold", "Gold color"),
        ('SILVER', "Silver", "Silver color"),
        ('NATURAL', "Natural", "Clear glass, brown wood, gray stone, or steel metal"),
    )
    bpy.types.Scene.elf_chess_white_color = EnumProperty(
        name="White Side Color",
        description="Render color for White-side pieces; changing it updates existing White pieces and showcase copies automatically",
        items=white_color_items,
        default='WHITE',
        update=_on_white_piece_material_changed,
    )
    bpy.types.Scene.elf_chess_black_color = EnumProperty(
        name="Black Side Color",
        description="Render color for Black-side pieces; changing it updates existing Black pieces and showcase copies automatically",
        items=black_color_items,
        default='BLACK',
        update=_on_black_piece_material_changed,
    )
    board_material_items = (
        ('WOOD', "Wood", "Alternating light/dark procedural wood squares with a darker wood frame"),
        ('STONE', "Stone", "Alternating light/dark polished stone squares with a stone frame"),
        ('GLASS', "Glass", "Alternating translucent glass squares with a smoked glass frame"),
        ('METAL', "Metal", "Alternating polished metal squares with a metal frame"),
    )
    bpy.types.Scene.elf_chess_board_material = EnumProperty(
        name="Board Material",
        description="Board material; changing it updates the existing board and, if the still render light rig already exists, retunes that lighting for the selected surface",
        items=board_material_items,
        default='WOOD',
        update=_on_board_material_changed,
    )
    bpy.types.Scene.elf_chess_showcase_floor_material = EnumProperty(
        name="Showcase Floor Material",
        description="Material used for the Full Set Showcase floor; changing it updates an existing showcase floor automatically",
        items=(
            ('STUDIO', "Studio", "Dark slightly reflective studio floor"),
            ('WOOD', "Wood", "Dark wood floor with a subtle reflective finish"),
            ('STONE', "Stone", "Dark stone floor with a subtle reflective finish"),
            ('METAL', "Metal", "Dark metallic showcase floor"),
            ('GLASS', "Glass", "Dark translucent glass showcase floor"),
        ),
        default='STUDIO',
        update=_on_showcase_floor_material_changed,
    )
    bpy.types.Scene.elf_chess_individual_background_material = EnumProperty(
        name="Individual Background Material",
        description="Material used for the Individual Piece Showcase backdrop; changing it updates an existing backdrop automatically",
        items=(
            ('MATTE', "Dark Matte", "Dark non-reflective gradient backdrop"),
            ('WOOD', "Wood", "Dark wood backdrop"),
            ('STONE', "Stone", "Dark stone backdrop"),
            ('METAL', "Metal", "Dark metal backdrop"),
            ('GLASS', "Glass", "Dark frosted glass backdrop"),
        ),
        default='MATTE',
        update=_on_individual_background_material_changed,
    )
    bpy.types.Scene.elf_chess_showcase_side = EnumProperty(
        name="Showcase Side",
        description="Choose whether the individual showcase uses the White-side or Black-side material and color settings",
        items=(
            ('White', "White", "Use the White-side material and color settings"),
            ('Black', "Black", "Use the Black-side material and color settings"),
        ),
        default='White',
    )
    bpy.types.Scene.elf_chess_showcase_piece = EnumProperty(
        name="Showcase Piece",
        description="Which chess piece to use in the individual showcase video",
        items=(
            ('Pawn', "Pawn", "Showcase the pawn"),
            ('Rook', "Rook", "Showcase the rook"),
            ('Knight', "Knight", "Showcase the knight"),
            ('Bishop', "Bishop", "Showcase the bishop"),
            ('Queen', "Queen", "Showcase the queen"),
            ('King', "King", "Showcase the king"),
        ),
        default='King',
    )

    bpy.types.Scene.elf_chess_piece_scale = FloatProperty(
        name="Piece Scale",
        description="Piece size relative to the square size",
        default=0.80,
        min=0.35,
        max=1.10,
    )
    bpy.types.Scene.elf_chess_radial_segments = IntProperty(
        name="Radial Segments",
        description="Roundness of revolved piece bodies",
        default=40,
        min=12,
        max=96,
    )


def unregister():
    del bpy.types.Scene.elf_chess_radial_segments
    del bpy.types.Scene.elf_chess_piece_scale
    del bpy.types.Scene.elf_chess_individual_background_material
    del bpy.types.Scene.elf_chess_showcase_floor_material
    del bpy.types.Scene.elf_chess_board_material
    del bpy.types.Scene.elf_chess_showcase_piece
    del bpy.types.Scene.elf_chess_showcase_side
    del bpy.types.Scene.elf_chess_black_color
    del bpy.types.Scene.elf_chess_white_color
    del bpy.types.Scene.elf_chess_black_material
    del bpy.types.Scene.elf_chess_white_material
    del bpy.types.Scene.elf_chess_style
    del bpy.types.Scene.elf_chess_border_width
    del bpy.types.Scene.elf_chess_board_geometry
    del bpy.types.Scene.elf_chess_tile_gap
    del bpy.types.Scene.elf_chess_tile_height
    del bpy.types.Scene.elf_chess_board_base_height
    del bpy.types.Scene.elf_chess_square_size

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

