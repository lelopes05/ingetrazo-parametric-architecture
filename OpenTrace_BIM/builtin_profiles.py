# SPDX-License-Identifier: GPL-3.0-or-later
"""Built-in complex-profile catalogue.

Steel profiles use nominal catalogue dimensions.  Geometry intentionally omits
root/toe fillets: the profile is meant for BIM/model representation and remains
lightweight.  The nominal family/code and source stay attached as metadata.
"""
from __future__ import annotations

import math


def _loop(points):
    return {"points": [[float(x), float(y)] for x, y in points],
            "edges": [{} for _ in points], "hole": False}


def _profile(pid, name, points, folder, *, source=None, catalog=None, code=None,
             category=None, metadata=None):
    xs=[p[0] for p in points]; ys=[p[1] for p in points]
    return {
        "id": pid, "name": name, "schema_version": 1,
        "loops": [_loop(points)],
        "bounds": {"width": max(xs)-min(xs), "height": max(ys)-min(ys)},
        "folder": folder, "category": category or "profile",
        "source": source, "catalog": catalog, "code": code or name,
        "readonly": True, "builtin": True,
        "metadata": dict(metadata or {}),
    }


def _i_points(d_mm, bf_mm, tw_mm, tf_mm):
    d=d_mm/1000.0; b=bf_mm/1000.0; tw=tw_mm/1000.0; tf=tf_mm/1000.0
    x0=-b/2; x1=-tw/2; x2=tw/2; x3=b/2
    y0=-d/2; y1=y0+tf; y2=d/2-tf; y3=d/2
    return [(x0,y0),(x3,y0),(x3,y1),(x2,y1),(x2,y2),(x3,y2),
            (x3,y3),(x0,y3),(x0,y2),(x1,y2),(x1,y1),(x0,y1)]


def _rect(w_mm,h_mm):
    w=w_mm/1000.0; h=h_mm/1000.0
    return [(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)]


def _circle(d_mm, segments=32):
    r=d_mm/2000.0
    return [(r*math.cos(2*math.pi*i/segments), r*math.sin(2*math.pi*i/segments))
            for i in range(segments)]


# Nominal d, bf, tw, tf dimensions in mm.  Gerdau entries are from the
# manufacturer's structural-shape tables (ASTM A572 Gr.50 family).
GERDAU_W = [
    ("W 150 x 13,0",148,100,4.3,4.9),("W 150 x 18,0",153,102,5.8,7.1),
    ("W 150 x 22,5",152,152,5.8,6.6),("W 150 x 24,0",160,102,6.6,10.3),
    ("W 150 x 29,8",157,153,6.6,9.3),("W 150 x 37,1",162,154,8.1,11.6),
    ("W 200 x 15,0",200,100,4.3,5.2),("W 200 x 19,3",203,102,5.8,6.5),
    ("W 200 x 22,5",206,102,6.2,8.0),("W 200 x 26,6",207,133,5.8,8.4),
    ("W 200 x 31,3",210,134,6.4,10.2),
    ("W 250 x 17,9",251,101,4.8,5.3),("W 250 x 22,3",254,102,5.8,6.9),
    ("W 250 x 25,3",257,102,6.1,8.4),("W 250 x 28,4",260,102,6.4,10.0),
    ("W 250 x 32,7",258,146,6.1,9.1),("W 250 x 38,5",262,147,6.6,11.2),
    ("W 250 x 44,8",266,148,7.6,13.0),
    ("W 310 x 21,0",303,101,5.1,5.7),("W 310 x 23,8",305,101,5.6,6.7),
    ("W 310 x 28,3",309,102,6.0,8.9),("W 310 x 32,7",313,102,6.6,10.8),
    ("W 310 x 38,7",310,165,5.8,9.7),("W 310 x 44,5",313,166,6.6,11.2),
    ("W 310 x 52,0",317,167,7.6,13.2),
    ("W 360 x 32,9",349,127,5.8,8.5),("W 360 x 39,0",353,128,6.5,10.7),
    ("W 360 x 44,0",352,171,6.9,9.8),("W 360 x 51,0",355,171,7.2,11.6),
    ("W 360 x 57,8",358,172,7.9,13.1),("W 360 x 64,0",347,203,7.7,13.5),
    ("W 360 x 72,0",350,204,8.6,15.1),("W 360 x 79,0",354,205,9.4,16.8),
    ("W 410 x 38,8",399,140,6.4,8.8),("W 410 x 46,1",403,140,7.0,11.2),
    ("W 410 x 53,0",403,177,7.5,10.9),("W 410 x 60,0",407,178,7.7,12.8),
    ("W 410 x 67,0",410,179,8.8,14.4),("W 410 x 75,0",413,180,9.7,16.0),
    ("W 410 x 85,0",417,181,10.9,18.2),
    ("W 460 x 52,0",450,152,7.6,10.8),("W 460 x 60,0",455,153,8.0,13.3),
    ("W 460 x 68,0",459,154,9.1,15.4),("W 460 x 74,0",457,190,9.0,14.5),
    ("W 460 x 82,0",460,191,9.9,16.0),("W 460 x 89,0",463,192,10.5,17.7),
    ("W 460 x 97,0",466,193,11.4,19.0),("W 460 x 106,0",469,194,12.6,20.6),
    ("W 530 x 66,0",525,165,8.9,11.4),
]

IPE = [
    ("IPE 80",80,46,3.8,5.2),("IPE 100",100,55,4.1,5.7),("IPE 120",120,64,4.4,6.3),
    ("IPE 140",140,73,4.7,6.9),("IPE 160",160,82,5.0,7.4),("IPE 180",180,91,5.3,8.0),
    ("IPE 200",200,100,5.6,8.5),("IPE 220",220,110,5.9,9.2),("IPE 240",240,120,6.2,9.8),
    ("IPE 270",270,135,6.6,10.2),("IPE 300",300,150,7.1,10.7),
]
HEA = [
    ("HEA 100",96,100,5.0,8.0),("HEA 120",114,120,5.0,8.0),("HEA 140",133,140,5.5,8.5),
    ("HEA 160",152,160,6.0,9.0),("HEA 180",171,180,6.0,9.5),("HEA 200",190,200,6.5,10.0),
    ("HEA 220",210,220,7.0,11.0),("HEA 240",230,240,7.5,12.0),("HEA 260",250,260,7.5,12.5),
    ("HEA 280",270,280,8.0,13.0),("HEA 300",290,300,8.5,14.0),
]
HEB = [
    ("HEB 100",100,100,6.0,10.0),("HEB 120",120,120,6.5,11.0),("HEB 140",140,140,7.0,12.0),
    ("HEB 160",160,160,8.0,13.0),("HEB 180",180,180,8.5,14.0),("HEB 200",200,200,9.0,15.0),
    ("HEB 220",220,220,9.5,16.0),("HEB 240",240,240,10.0,17.0),("HEB 260",260,260,10.0,17.5),
    ("HEB 280",280,280,10.5,18.0),("HEB 300",300,300,11.0,19.0),
]


def builtin_profiles():
    out=[]
    for family, rows, folder, source, catalog in (
        ("gerdau_w", GERDAU_W, "Estruturais / Aço / Gerdau W", "Gerdau", "Perfis Estruturais W"),
        ("ipe", IPE, "Estruturais / Aço / IPE", "ArcelorMittal / EN 10365", "IPE"),
        ("hea", HEA, "Estruturais / Aço / HEA", "ArcelorMittal / EN 10365", "HEA"),
        ("heb", HEB, "Estruturais / Aço / HEB", "ArcelorMittal / EN 10365", "HEB"),
    ):
        for name,d,bf,tw,tf in rows:
            slug=name.lower().replace(" ","").replace(",",".").replace("/","-")
            out.append(_profile(
                f"builtin:steel:{family}:{slug}", name,
                _i_points(d,bf,tw,tf), folder, source=source, catalog=catalog,
                code=name, category="steel_section",
                metadata={"d_mm":d,"bf_mm":bf,"tw_mm":tw,"tf_mm":tf,
                          "geometry_note":"nominal sem raios de concordância",
                          "source_url": ("https://mais.gerdau.com.br/produtos/perfil-estrutural" if family=="gerdau_w" else "https://orangebook.arcelormittal.com/")},
            ))

    out.extend([
        _profile("builtin:arch:baseboard:100x15","Rodapé 100 × 15 mm",_rect(15,100),"Arquitetônicos / Rodapés",category="baseboard"),
        _profile("builtin:arch:baseboard:150x15","Rodapé 150 × 15 mm",_rect(15,150),"Arquitetônicos / Rodapés",category="baseboard"),
        _profile("builtin:arch:trim:50x20","Faixa / Moldura 50 × 20 mm",_rect(20,50),"Arquitetônicos / Faixas & Molduras",category="trim"),
        _profile("builtin:arch:handrail:42.4","Corrimão redondo Ø42,4 mm",_circle(42.4),"Arquitetônicos / Corrimãos",category="handrail"),
        _profile("builtin:arch:handrail:40x60","Corrimão retangular 40 × 60 mm",_rect(40,60),"Arquitetônicos / Corrimãos",category="handrail"),
        _profile("builtin:arch:wallcap:150x30","Cimalha / faixa de parede 150 × 30 mm",_rect(30,150),"Arquitetônicos / Parede",category="wall_profile"),
    ])
    return out
