# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure alignment and equal-clear-gap distribution in global X/Y/Z.

Each bound is ((xmin,xmax),(ymin,ymax),(zmin,zmax)), in model metres.
No Qt and no scene mutation. A transform/undo command applies each delta.
"""
from __future__ import annotations
import math


def _check(bounds, axis):
    if axis not in (0, 1, 2):
        raise ValueError("O eixo deve ser X, Y ou Z.")
    for item in bounds:
        if len(item) != 3 or any(len(pair) != 2 or
                                  not all(math.isfinite(v) for v in pair) or
                                  pair[0] > pair[1] for pair in item):
            raise ValueError("Limites do objeto inválidos.")


def align_offsets(bounds, axis, edge):
    """Align each bound by the common selection min, centre or max."""
    _check(bounds, axis)
    if edge not in ("min", "center", "max"):
        raise ValueError("Referência de alinhamento inválida.")
    if len(bounds) < 2:
        raise ValueError("Selecione pelo menos dois objetos.")
    low = min(b[axis][0] for b in bounds)
    high = max(b[axis][1] for b in bounds)
    target = low if edge == "min" else high if edge == "max" else (low + high) / 2.0
    result = []
    for b in bounds:
        a, z = b[axis]
        reference = a if edge == "min" else z if edge == "max" else (a+z)/2.0
        result.append(target-reference)
    return result


def distribute_offsets(bounds, axis):
    """Distribute clear spaces equally, holding outermost objects fixed."""
    _check(bounds, axis)
    if len(bounds) < 3:
        raise ValueError("Selecione pelo menos três objetos para distribuir.")
    order = sorted(range(len(bounds)), key=lambda i: (bounds[i][axis][0], bounds[i][axis][1], i))
    low, high = bounds[order[0]][axis][0], bounds[order[-1]][axis][1]
    widths = [bounds[i][axis][1]-bounds[i][axis][0] for i in order]
    gap = (high-low-sum(widths))/(len(order)-1)
    if gap < -1.e-8:
        raise ValueError("Os objetos ocupam mais espaço do que o intervalo disponível.")
    delta = [0.0]*len(bounds)
    cursor = low
    for i,width in zip(order,widths):
        delta[i] = cursor-bounds[i][axis][0]
        cursor += width+gap
    return delta
