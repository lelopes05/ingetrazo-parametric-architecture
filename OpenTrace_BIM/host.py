# SPDX-License-Identifier: GPL-3.0-or-later
"""Compatibility adapter for IngeTrazo 0.5.7+ tool routing."""
from core.version import __version__ as HOST_VERSION

from .i18n import english

MIN_HOST_VERSION = (0, 5, 7)


def _host_version_tuple(raw):
    """Return the numeric major/minor/patch prefix of an IngeTrazo version.

    Suffixes such as 0.5.8-dev are accepted. The structural attribute checks
    below remain the real compatibility guard for later host versions.
    """
    parts = []
    for chunk in str(raw).split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
        if len(parts) == 3:
            break
    if len(parts) < 2:
        return None
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


WALL_TOOL_KEY = "arquitetura_parametrica_wall"
CURVED_WALL_TOOL_KEY = "arquitetura_parametrica_curved_wall"
VERTEX_TOOL_KEY = "arquitetura_parametrica_insert_vertex"
MOVE_XY_TOOL_KEY = "arquitetura_parametrica_move_xy"
MOVE_Z_TOOL_KEY = "arquitetura_parametrica_move_z"
HEIGHT_TOOL_KEY = "arquitetura_parametrica_height"
WALL_TOTAL_HEIGHT_TOOL_KEY = "arquitetura_parametrica_total_height"
ARC_TOOL_KEY = "arquitetura_parametrica_arc"
MOVE_VERTEX_FREE_TOOL_KEY = "arquitetura_parametrica_move_vertex_free"
MOVE_VERTEX_CONTINUE_TOOL_KEY = "arquitetura_parametrica_move_vertex_continue"
WALL_STATION_Z_TOOL_KEY = "arquitetura_parametrica_wall_station_z"
WALL_LEAN_TOOL_KEY = "arquitetura_parametrica_wall_lean"
WALL_OPENING_TOOL_KEY = "arquitetura_parametrica_wall_opening"
WALL_POLYGON_TOOL_KEY = "arquitetura_parametrica_wall_polygon"


def require_reference_host(app):
    host_version = _host_version_tuple(HOST_VERSION)
    if host_version is None or host_version < MIN_HOST_VERSION:
        raise RuntimeError("This plugin requires IngeTrazo 0.5.7 or later.")
    for name in ("_tools", "_tool_actions", "_tool_group", "_activate_tool"):
        if not hasattr(app.window, name):
            raise RuntimeError("The tool integration in this IngeTrazo installation is not compatible.")
    if WALL_TOOL_KEY in app.window._tools:
        raise RuntimeError("Architecture tools are already loaded in this window.")


def register_tool(app, tool, action=None, key=WALL_TOOL_KEY):
    """Register one OpenTrace tool through the 0.5.7 compatibility adapter.

    IngeTrazo 0.5.7 does not expose public tool-registration methods, so the
    private host collections are intentionally isolated in this module.  Other
    OpenTrace modules should use these helpers instead of reaching into the
    main window internals directly.
    """
    tool.name = english(getattr(tool, "name", ""))
    desc = getattr(tool, "description", None)
    if isinstance(desc, str):
        tool.description = english(desc)
    win = app.window
    win._tools[key] = tool
    if action is not None:
        try:
            action.setText(english(action.text()))
            action.setToolTip(english(action.toolTip()))
            action.setStatusTip(english(action.statusTip()))
        except (AttributeError, RuntimeError):
            pass
        win._tool_actions[key] = action
        win._tool_group.addAction(action)


def activate_tool(app, key):
    """Activate a host tool by key through the single compatibility boundary."""
    app.window._activate_tool(str(key))


def host_tool(app, key):
    """Return a registered host tool without leaking host internals to callers."""
    return app.window._tools.get(str(key))


def activate_wall(app):
    activate_tool(app, WALL_TOOL_KEY)


def activate_curved_wall(app):
    activate_tool(app, CURVED_WALL_TOOL_KEY)


def activate_vertex_insert(app):
    activate_tool(app, VERTEX_TOOL_KEY)


def activate_move_xy(app):
    activate_tool(app, MOVE_XY_TOOL_KEY)


def activate_move_z(app):
    activate_tool(app, MOVE_Z_TOOL_KEY)


def activate_height(app):
    activate_tool(app, HEIGHT_TOOL_KEY)

def activate_wall_total_height(app):
    activate_tool(app, WALL_TOTAL_HEIGHT_TOOL_KEY)


def activate_arc(app):
    activate_tool(app, ARC_TOOL_KEY)


def activate_move_vertex_free(app):
    activate_tool(app, MOVE_VERTEX_FREE_TOOL_KEY)


def activate_move_vertex_continue(app):
    activate_tool(app, MOVE_VERTEX_CONTINUE_TOOL_KEY)

def activate_wall_station_z(app):
    activate_tool(app, WALL_STATION_Z_TOOL_KEY)

def activate_wall_lean(app):
    activate_tool(app, WALL_LEAN_TOOL_KEY)

def activate_wall_opening(app):
    activate_tool(app, WALL_OPENING_TOOL_KEY)

def activate_wall_polygon(app):
    activate_tool(app, WALL_POLYGON_TOOL_KEY)


def activate_select(app):
    activate_tool(app, "select")

SLAB_TOOL_KEY = "arquitetura_parametrica_slab"
SLAB_INSERT_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_insert_vertex"
SLAB_STRETCH_EDGE_TOOL_KEY = "arquitetura_parametrica_slab_stretch_edge"
SLAB_MOVE_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_move_vertex"
SLAB_CURVE_EDGE_TOOL_KEY = "arquitetura_parametrica_slab_curve_edge"
SLAB_CHAMFER_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_chamfer_vertex"
SLAB_FILLET_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_fillet_vertex"


def activate_slab(app):
    activate_tool(app, SLAB_TOOL_KEY)


def activate_slab_insert_vertex(app):
    activate_tool(app, SLAB_INSERT_VERTEX_TOOL_KEY)


def activate_slab_stretch_edge(app):
    activate_tool(app, SLAB_STRETCH_EDGE_TOOL_KEY)


def activate_slab_move_vertex(app):
    activate_tool(app, SLAB_MOVE_VERTEX_TOOL_KEY)

def activate_slab_curve_edge(app):
    activate_tool(app, SLAB_CURVE_EDGE_TOOL_KEY)

def activate_slab_chamfer_vertex(app):
    activate_tool(app, SLAB_CHAMFER_VERTEX_TOOL_KEY)

def activate_slab_fillet_vertex(app):
    activate_tool(app, SLAB_FILLET_VERTEX_TOOL_KEY)

COLUMN_TOOL_KEY = "arquitetura_parametrica_column"
COLUMN_HEIGHT_TOOL_KEY = "arquitetura_parametrica_column_height"

def activate_column(app):
    activate_tool(app, COLUMN_TOOL_KEY)

def activate_column_height(app):
    activate_tool(app, COLUMN_HEIGHT_TOOL_KEY)

SLAB_MOVE_XY_TOOL_KEY = "arquitetura_parametrica_slab_move_xy"
SLAB_MOVE_Z_TOOL_KEY = "arquitetura_parametrica_slab_move_z"
SLAB_THICKNESS_TOOL_KEY = "arquitetura_parametrica_slab_thickness"
SLAB_OFFSET_TOOL_KEY = "arquitetura_parametrica_slab_offset"

def activate_slab_move_xy(app):
    activate_tool(app, SLAB_MOVE_XY_TOOL_KEY)

def activate_slab_move_z(app):
    activate_tool(app, SLAB_MOVE_Z_TOOL_KEY)

def activate_slab_thickness(app):
    activate_tool(app, SLAB_THICKNESS_TOOL_KEY)

def activate_slab_offset(app):
    activate_tool(app, SLAB_OFFSET_TOOL_KEY)

SLAB_OPENING_TOOL_KEY = "arquitetura_parametrica_slab_opening"

def activate_slab_opening(app):
    activate_tool(app, SLAB_OPENING_TOOL_KEY)

SLAB_OPENING_INSERT_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_opening_insert_vertex"
SLAB_OPENING_STRETCH_EDGE_TOOL_KEY = "arquitetura_parametrica_slab_opening_stretch_edge"
SLAB_OPENING_MOVE_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_opening_move_vertex"
SLAB_OPENING_CURVE_EDGE_TOOL_KEY = "arquitetura_parametrica_slab_opening_curve_edge"
SLAB_OPENING_CHAMFER_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_opening_chamfer_vertex"
SLAB_OPENING_FILLET_VERTEX_TOOL_KEY = "arquitetura_parametrica_slab_opening_fillet_vertex"
SLAB_OPENING_OFFSET_TOOL_KEY = "arquitetura_parametrica_slab_opening_offset"
SLAB_OPENING_MOVE_TOOL_KEY = "arquitetura_parametrica_slab_opening_move"

def activate_slab_opening_insert_vertex(app): activate_tool(app, SLAB_OPENING_INSERT_VERTEX_TOOL_KEY)
def activate_slab_opening_stretch_edge(app): activate_tool(app, SLAB_OPENING_STRETCH_EDGE_TOOL_KEY)
def activate_slab_opening_move_vertex(app): activate_tool(app, SLAB_OPENING_MOVE_VERTEX_TOOL_KEY)
def activate_slab_opening_curve_edge(app): activate_tool(app, SLAB_OPENING_CURVE_EDGE_TOOL_KEY)
def activate_slab_opening_chamfer_vertex(app): activate_tool(app, SLAB_OPENING_CHAMFER_VERTEX_TOOL_KEY)
def activate_slab_opening_fillet_vertex(app): activate_tool(app, SLAB_OPENING_FILLET_VERTEX_TOOL_KEY)
def activate_slab_opening_offset(app): activate_tool(app, SLAB_OPENING_OFFSET_TOOL_KEY)
def activate_slab_opening_move(app): activate_tool(app, SLAB_OPENING_MOVE_TOOL_KEY)

BEAM_TOOL_KEY = "arquitetura_parametrica_beam"

def activate_beam(app):
    activate_tool(app, BEAM_TOOL_KEY)

BEAM_MOVE_FREE_TOOL_KEY = "arquitetura_parametrica_beam_move_free"
BEAM_MOVE_CONTINUE_TOOL_KEY = "arquitetura_parametrica_beam_move_continue"
BEAM_MOVE_VERTICAL_TOOL_KEY = "arquitetura_parametrica_beam_move_vertical"

def activate_beam_move_free(app): activate_tool(app, BEAM_MOVE_FREE_TOOL_KEY)
def activate_beam_move_continue(app): activate_tool(app, BEAM_MOVE_CONTINUE_TOOL_KEY)
def activate_beam_move_vertical(app): activate_tool(app, BEAM_MOVE_VERTICAL_TOOL_KEY)

# Structural whole-object move and curvature tools (0.7.x)
COLUMN_MOVE_TOOL_KEY = "arquitetura_parametrica_column_move"
COLUMN_CURVE_TOOL_KEY = "arquitetura_parametrica_column_curve"
BEAM_MOVE_TOOL_KEY = "arquitetura_parametrica_beam_move"
BEAM_CURVE_TOOL_KEY = "arquitetura_parametrica_beam_curve"

def activate_column_move(app): activate_tool(app, COLUMN_MOVE_TOOL_KEY)
def activate_column_curve(app): activate_tool(app, COLUMN_CURVE_TOOL_KEY)
def activate_beam_move(app): activate_tool(app, BEAM_MOVE_TOOL_KEY)
def activate_beam_curve(app): activate_tool(app, BEAM_CURVE_TOOL_KEY)

# Spatial structural editing additions (0.8.x)
COLUMN_INCLINE_TOOL_KEY = "arquitetura_parametrica_column_incline"
COLUMN_STATION_Z_TOOL_KEY = "arquitetura_parametrica_column_station_z"
BEAM_VERTICAL_CURVE_TOOL_KEY = "arquitetura_parametrica_beam_curve_vertical"
BEAM_INCLINE_TOOL_KEY = "arquitetura_parametrica_beam_incline"

def activate_column_incline(app): activate_tool(app, COLUMN_INCLINE_TOOL_KEY)
def activate_column_station_z(app): activate_tool(app, COLUMN_STATION_Z_TOOL_KEY)
def activate_beam_vertical_curve(app): activate_tool(app, BEAM_VERTICAL_CURVE_TOOL_KEY)
def activate_beam_incline(app): activate_tool(app, BEAM_INCLINE_TOOL_KEY)

# OpenTrace membrane tools
MEMBRANE_DRAW_TOOL_KEY = "arquitetura_parametrica_membrane_draw"
MEMBRANE_EDIT_TOOL_KEY = "arquitetura_parametrica_membrane_edit"

def activate_membrane_draw(app): activate_tool(app, MEMBRANE_DRAW_TOOL_KEY)
def activate_membrane_edit(app): activate_tool(app, MEMBRANE_EDIT_TOOL_KEY)
