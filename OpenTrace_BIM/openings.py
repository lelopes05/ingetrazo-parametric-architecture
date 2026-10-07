# SPDX-License-Identifier: GPL-3.0-or-later
"""Generic host/opening contract shared by slabs today and walls/windows later.

The host owns the cut geometry.  Hosted objects (future Windowizer/doors or a
universal Opening tool) only describe an opening request.  This keeps
parametric hosts regenerable without destructive booleans.
"""
from __future__ import annotations
import copy, uuid

HOST_OPENING_API = 1


def new_opening(kind="embedded", polygon=None, edges=None, source_id=None):
    return {"id":uuid.uuid4().hex, "kind":kind,
            "polygon":copy.deepcopy(polygon or []), "edges":copy.deepcopy(edges or []),
            "source_id":source_id}


def host_kind(group):
    ext=getattr(group,"ext",None) or {}
    rec=ext.get("arquitetura_parametrica") if isinstance(ext,dict) else None
    return rec.get("kind") if isinstance(rec,dict) else None


def host_capabilities(group):
    kind=host_kind(group)
    if kind=="slab": return {"api":HOST_OPENING_API,"embedded_polygon":True,"hosted_object":True}
    if kind=="wall": return {"api":HOST_OPENING_API,"embedded_polygon":False,"embedded_rect":True,"hosted_object":True}
    return None
