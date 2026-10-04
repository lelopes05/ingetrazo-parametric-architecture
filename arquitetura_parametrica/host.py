# SPDX-License-Identifier: GPL-3.0-or-later
"""Version-pinned adapter for IngeTrazo 0.5.7 tool routing."""
from core.version import __version__ as HOST_VERSION

WALL_TOOL_KEY = "arquitetura_parametrica_wall"
CURVED_WALL_TOOL_KEY = "arquitetura_parametrica_curved_wall"
VERTEX_TOOL_KEY = "arquitetura_parametrica_insert_vertex"
MOVE_XY_TOOL_KEY = "arquitetura_parametrica_move_xy"
MOVE_Z_TOOL_KEY = "arquitetura_parametrica_move_z"
HEIGHT_TOOL_KEY = "arquitetura_parametrica_height"
ARC_TOOL_KEY = "arquitetura_parametrica_arc"
MOVE_VERTEX_FREE_TOOL_KEY = "arquitetura_parametrica_move_vertex_free"
MOVE_VERTEX_CONTINUE_TOOL_KEY = "arquitetura_parametrica_move_vertex_continue"
WALL_STATION_Z_TOOL_KEY = "arquitetura_parametrica_wall_station_z"
WALL_LEAN_TOOL_KEY = "arquitetura_parametrica_wall_lean"


def require_reference_host(app):
    if HOST_VERSION != "0.5.7":
        raise RuntimeError("Esta versão do plugin requer IngeTrazo 0.5.7. "
                           "Compatibilidade com outras versões ainda não validada.")
    for name in ("_tools", "_tool_actions", "_tool_group", "_activate_tool"):
        if not hasattr(app.window, name):
            raise RuntimeError("A integração de ferramentas desta instalação não é compatível.")
    if WALL_TOOL_KEY in app.window._tools:
        raise RuntimeError("Ferramentas arquitetônicas já carregadas nesta janela.")


def register_tool(app, tool, action=None, key=WALL_TOOL_KEY):
    win = app.window
    win._tools[key] = tool
    if action is not None:
        win._tool_actions[key] = action
        win._tool_group.addAction(action)


def activate_wall(app):
    app.window._activate_tool(WALL_TOOL_KEY)


def activate_curved_wall(app):
    app.window._activate_tool(CURVED_WALL_TOOL_KEY)


def activate_vertex_insert(app):
    app.window._activate_tool(VERTEX_TOOL_KEY)


def activate_move_xy(app):
    app.window._activate_tool(MOVE_XY_TOOL_KEY)


def activate_move_z(app):
    app.window._activate_tool(MOVE_Z_TOOL_KEY)


def activate_height(app):
    app.window._activate_tool(HEIGHT_TOOL_KEY)


def activate_arc(app):
    app.window._activate_tool(ARC_TOOL_KEY)


def activate_move_vertex_free(app):
    app.window._activate_tool(MOVE_VERTEX_FREE_TOOL_KEY)


def activate_move_vertex_continue(app):
    app.window._activate_tool(MOVE_VERTEX_CONTINUE_TOOL_KEY)

def activate_wall_station_z(app):
    app.window._activate_tool(WALL_STATION_Z_TOOL_KEY)

def activate_wall_lean(app):
    app.window._activate_tool(WALL_LEAN_TOOL_KEY)


def activate_select(app):
    app.window._activate_tool("select")

SLAB_TOOL_KEY = "arquitetura_parametrica_slab"
SLAB_INSERT_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_insert_vertex"
SLAB_STRETCH_EDGE_TOOL_KEY = "arquitetura_parametrica_slab_stretch_edge"
SLAB_MOVE_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_move_vertex"
SLAB_CURVE_EDGE_TOOL_KEY = "arquitetura_parametrica_slab_curve_edge"
SLAB_CHAMFER_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_chamfer_vertex"
SLAB_FILLET_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_fillet_vertex"


def activate_slab(app):
    app.window._activate_tool(SLAB_TOOL_KEY)


def activate_slab_insert_vertex(app):
    app.window._activate_tool(SLAB_INSERT_VERTEX_TOOL_KEY)


def activate_slab_stretch_edge(app):
    app.window._activate_tool(SLAB_STRETCH_EDGE_TOOL_KEY)


def activate_slab_move_vertex(app):
    app.window._activate_tool(SLAB_MOVE_VERTEX_TOOL_KEY)

def activate_slab_curve_edge(app):
    app.window._activate_tool(SLAB_CURVE_EDGE_TOOL_KEY)

def activate_slab_chamfer_vertex(app):
    app.window._activate_tool(SLAB_CHAMFER_VERTEX_TOOL_KEY)

def activate_slab_fillet_vertex(app):
    app.window._activate_tool(SLAB_FILLET_VERTEX_TOOL_KEY)

COLUMN_TOOL_KEY = "arquitetura_parametrica_column"
COLUMN_HEIGHT_TOOL_KEY = "arquitetura_parametrica_column_height"

def activate_column(app):
    app.window._activate_tool(COLUMN_TOOL_KEY)

def activate_column_height(app):
    app.window._activate_tool(COLUMN_HEIGHT_TOOL_KEY)

SLAB_MOVE_XY_TOOL_KEY = "arquitetura_parametrica_slab_move_xy"
SLAB_MOVE_Z_TOOL_KEY = "arquitetura_parametrica_slab_move_z"
SLAB_THICKNESS_TOOL_KEY = "arquitetura_parametrica_slab_thickness"
SLAB_OFFSET_TOOL_KEY = "arquitetura_parametrica_slab_offset"

def activate_slab_move_xy(app):
    app.window._activate_tool(SLAB_MOVE_XY_TOOL_KEY)

def activate_slab_move_z(app):
    app.window._activate_tool(SLAB_MOVE_Z_TOOL_KEY)

def activate_slab_thickness(app):
    app.window._activate_tool(SLAB_THICKNESS_TOOL_KEY)

def activate_slab_offset(app):
    app.window._activate_tool(SLAB_OFFSET_TOOL_KEY)

SLAB_OPENING_TOOL_KEY = "arquitetura_parametrica_slab_opening"

def activate_slab_opening(app):
    app.window._activate_tool(SLAB_OPENING_TOOL_KEY)

SLAB_OPENING_INSERT_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_opening_insert_vertex"
SLAB_OPENING_STRETCH_EDGE_TOOL_KEY = "arquitetura_parametrica_slab_opening_stretch_edge"
SLAB_OPENING_MOVE_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_opening_move_vertex"
SLAB_OPENING_CURVE_EDGE_TOOL_KEY = "arquitetura_parametrica_slab_opening_curve_edge"
SLAB_OPENING_CHAMFER_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_opening_chamfer_vertex"
SLAB_OPENING_FILLET_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_opening_fillet_vertex"
SLAB_OPENING_OFFSET_TOOL_KEY = "arquitetura_parametrica_slab_opening_offset"
SLAB_OPENING_MOVE_TOOL_KEY = "arquitetura_parametrica_slab_opening_move"

def activate_slab_opening_insert_vertex(app): app.window._activate_tool(SLAB_OPENING_INSERT_VERTEX_TOOL_KEY)
def activate_slab_opening_stretch_edge(app): app.window._activate_tool(SLAB_OPENING_STRETCH_EDGE_TOOL_KEY)
def activate_slab_opening_move_vertex(app): app.window._activate_tool(SLAB_OPENING_MOVE_VERTEX_TOOL_KEY)
def activate_slab_opening_curve_edge(app): app.window._activate_tool(SLAB_OPENING_CURVE_EDGE_TOOL_KEY)
def activate_slab_opening_chamfer_vertex(app): app.window._activate_tool(SLAB_OPENING_CHAMFER_VERTEX_TOOL_KEY)
def activate_slab_opening_fillet_vertex(app): app.window._activate_tool(SLAB_OPENING_FILLET_VERTEX_TOOL_KEY)
def activate_slab_opening_offset(app): app.window._activate_tool(SLAB_OPENING_OFFSET_TOOL_KEY)
def activate_slab_opening_move(app): app.window._activate_tool(SLAB_OPENING_MOVE_TOOL_KEY)

BEAM_TOOL_KEY = "arquitetura_parametrica_beam"

def activate_beam(app):
    app.window._activate_tool(BEAM_TOOL_KEY)

BEAM_MOVE_FREE_TOOL_KEY = "arquitetura_parametrica_beam_move_free"
BEAM_MOVE_CONTINUE_TOOL_KEY = "arquitetura_parametrica_beam_move_continue"
BEAM_MOVE_VERTICAL_TOOL_KEY = "arquitetura_parametrica_beam_move_vertical"

def activate_beam_move_free(app): app.window._activate_tool(BEAM_MOVE_FREE_TOOL_KEY)
def activate_beam_move_continue(app): app.window._activate_tool(BEAM_MOVE_CONTINUE_TOOL_KEY)
def activate_beam_move_vertical(app): app.window._activate_tool(BEAM_MOVE_VERTICAL_TOOL_KEY)

# Structural whole-object move and curvature tools (0.7.x)
COLUMN_MOVE_TOOL_KEY = "arquitetura_parametrica_column_move"
COLUMN_CURVE_TOOL_KEY = "arquitetura_parametrica_column_curve"
BEAM_MOVE_TOOL_KEY = "arquitetura_parametrica_beam_move"
BEAM_CURVE_TOOL_KEY = "arquitetura_parametrica_beam_curve"

def activate_column_move(app): app.window._activate_tool(COLUMN_MOVE_TOOL_KEY)
def activate_column_curve(app): app.window._activate_tool(COLUMN_CURVE_TOOL_KEY)
def activate_beam_move(app): app.window._activate_tool(BEAM_MOVE_TOOL_KEY)
def activate_beam_curve(app): app.window._activate_tool(BEAM_CURVE_TOOL_KEY)

# Spatial structural editing additions (0.8.x)
COLUMN_INCLINE_TOOL_KEY = "arquitetura_parametrica_column_incline"
COLUMN_STATION_Z_TOOL_KEY = "arquitetura_parametrica_column_station_z"
BEAM_VERTICAL_CURVE_TOOL_KEY = "arquitetura_parametrica_beam_curve_vertical"
BEAM_INCLINE_TOOL_KEY = "arquitetura_parametrica_beam_incline"

def activate_column_incline(app): app.window._activate_tool(COLUMN_INCLINE_TOOL_KEY)
def activate_column_station_z(app): app.window._activate_tool(COLUMN_STATION_Z_TOOL_KEY)
def activate_beam_vertical_curve(app): app.window._activate_tool(BEAM_VERTICAL_CURVE_TOOL_KEY)
def activate_beam_incline(app): app.window._activate_tool(BEAM_INCLINE_TOOL_KEY)