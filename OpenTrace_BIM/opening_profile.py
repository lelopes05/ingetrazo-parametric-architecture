# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure numeric planning for cuts that may reach a wall base or top.

This module does not make faces or manipulate the scene; the wall generator
uses it to split its longitudinal strips when a sloped top crosses the sill
or head of an opening. This avoids partially cut strips with phantom caps.
"""
from __future__ import annotations

import math

EPS = 1.0e-8


def opening_slice(wall_height, sill, opening_height):
    """Which portions of a vertical cross-section contain wall material?

    The opening's nominal height may exceed the wall's available height.
    In that case the remaining wall around the opening is retained.
    """
    wall_height = float(wall_height)
    sill = float(sill)
    opening_height = float(opening_height)
    if not all(math.isfinite(v) for v in (wall_height, sill, opening_height)):
        raise ValueError("Dimensões de abertura não finitas.")
    if wall_height <= 0 or sill < 0 or opening_height <= 0:
        raise ValueError("Dimensões de abertura inválidas.")
    cuts_wall = sill < wall_height - EPS
    return {
        "cut": cuts_wall,
        "below": cuts_wall and sill > EPS,
        "above": cuts_wall and sill + opening_height < wall_height - EPS,
    }


def profile_crossings(length, base_profile, top_profile, openings):
    """Stations where sloping wall clearance crosses an opening sill/head.

    An opening interval already has s0/s1 from the wall's free-clearance
    solver. Height profiles interpolate linearly over the full wall station.
    These crossings partition strips so each is wholly below/above a cut,
    except for a zero-width transition at a strip endpoint.
    """
    length = float(length)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("Comprimento da parede inválido.")
    h0 = float(top_profile[0]) - float(base_profile[0])
    h1 = float(top_profile[1]) - float(base_profile[1])
    if not all(math.isfinite(x) for x in (h0, h1)):
        raise ValueError("Alturas da parede inválidas.")
    dh = h1 - h0
    if abs(dh) <= EPS:
        return []
    result = []
    for op in openings:
        s0 = float(op["s0"])
        s1 = float(op["s1"])
        sill = float(op["sill"])
        height = float(op["height"])
        for boundary in (sill, sill + height):
            station = length * (boundary - h0) / dh
            if s0 + EPS < station < s1 - EPS:
                result.append(station)
    return sorted(set(round(x, 10) for x in result))
