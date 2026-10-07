# OpenTrace BIM

**Open-source parametric architecture for IngeTrazo — designed to grow beyond a single host.**

> Formerly developed under the working names **IngeTrazo Architecture** / **Parametric Architecture**.

![Status](https://img.shields.io/badge/status-active%20development-2ea44f)
![Tested build](https://img.shields.io/badge/tested-0.11.1-blue)
![IngeTrazo](https://img.shields.io/badge/IngeTrazo-0.5.7%2B-blueviolet)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)

OpenTrace BIM is an architect-driven parametric/BIM toolkit focused on **editable building elements, reusable construction assemblies, hosted relationships, architectural geometry and interoperable data**.

The current host is [IngeTrazo](https://ingetrazo.com/). The long-term architecture is intentionally being shaped so the modeling concepts and resource libraries can later be adapted to **Blender/Bonsai** and **FreeCAD** instead of being locked to one application.

## Current status

**Latest user-tested build:** `0.11.1`

The tested build already covers a broad architectural modeling workflow. It is still experimental software, but the core objects survive save/close/reopen in `.igz` files and remain parametrically editable.

**0.11.1** adds the unified OpenTrace BIM panel, expanded presets/catalog work, profile folders, the bundled Layer Combinations companion with preset templates, and opt-in update checks.

See [FEATURES.md](FEATURES.md) for the detailed capability matrix and [ROADMAP.md](ROADMAP.md) for active development.

For version-by-version changes see [CHANGELOG.md](CHANGELOG.md). The 0.12.9 release candidate is documented in [release notes](release-prep/0.12.9/RELEASE_NOTES.md) and the [technical audit](release-prep/0.12.9/AUDIT_SUMMARY.md); it is **not** the currently published build.

## Development previews

<img width="1910" height="1031" alt="image" src="https://github.com/user-attachments/assets/0b05b4fa-0de4-4d39-89a7-569fba6abab1" />


---

## What is already implemented

### Parametric Walls

- Straight and curved parametric walls.
- Straight-wall creation by two points.
- Curved-wall creation with multiple arc methods.
- Exterior / center / interior reference alignment.
- Editable thickness, height and base elevation.
- Building-level anchoring for base and top.
- Independent top/base endpoint control.
- Sloped tops, vertical station editing and wall leaning/twisting workflows.
- Vertex insertion and endpoint movement.
- Extend/trim-style path editing.
- Curving of existing wall segments.
- Hosted rectangular openings.
- Hosted openings also supported on curved walls.
- Automatic wall junction logic for the currently supported straight/mixed cases.
- Parametric state stored with the object, not just baked mesh geometry.

### Composite Wall Assemblies

Walls can be simple or multilayered.

Composite walls use semantic layers with:

- layer name;
- function;
- named material;
- thickness;
- exactly one structural/core layer;
- physical order from exterior to interior.

The geometry is derived from the assembly while the reference line remains tied to the **core**, so adding finishes does not arbitrarily move the architectural reference.

### Parametric Slabs

- Rectangle by diagonal.
- Rectangle by base + width.
- Free polygon creation.
- Editable vertices and edges.
- Stretch/move edge operations.
- Curved slab edges.
- Chamfer and fillet editing.
- Boundary offset.
- Polygonal hosted openings.
- Editable opening vertices/edges.
- Curved, chamfered, filleted and offset openings.
- Level anchoring with offset.
- Bottom/top reference-plane behavior.
- Simple and multilayer slab assemblies.
- Per-layer materials.

### Parametric Columns

- Rectangular sections.
- Circular sections.
- Reusable Complex Profile sections.
- 3×3 insertion/anchor system.
- Base and top level links.
- Base/top offsets.
- Width, depth, diameter and rotation controls.
- Inclination.
- Segmented columns.
- Per-segment dimensions and materials.
- Percentage or fixed-height segment definitions.
- Curvature applied to the selected segment instead of propagating through the whole column.
- Vertex insertion for additional segments.

### Parametric Beams

- Editable length, width and height.
- Rectangular and circular simple sections.
- Reusable Complex Profile sections.
- Rotation.
- Level/base anchoring.
- Inclination from beam endpoints.
- Horizontal curvature.
- Parametric editing after creation.

Vertical curvature and several higher-order beam editing cases are still under active development.

### Complex Profiles

OpenTrace BIM includes a reusable 2D profile workflow built on IngeTrazo's native drawing tools.

- Draw the profile with native 2D geometry.
- Closed outer loops and inner voids.
- User-defined insertion origin.
- Save profiles as reusable user favourites.
- Use saved profiles as beam or column sections.
- Profile geometry is embedded into parametric objects so a model does not depend on another computer having the same favourite library.

### Levels

The architecture tools integrate with building levels:

- base level;
- top level;
- offsets;
- automatic updates when linked levels change;
- independent free-elevation mode where needed.

### Contextual editing

Instead of forcing every operation into permanent toolbars, OpenTrace BIM uses contextual editing controls:

- radial palettes for edge/vertex operations;
- dedicated wall/slab/column/beam controls;
- viewport handles and reference overlays;
- snap-aware architectural editing;
- direct numeric editing.

### Persistence

Parametric information is stored inside the `.igz` document. Real testing has confirmed that saved parametric objects reopen and remain editable.

---

## Layer Combinations companion module

The project also contains a companion **Layer Combinations** system for reusable model-visibility states.

It is intentionally different from Scenes:

- **Layer Combination** = reusable visibility / lock / interaction configuration.
- **Scene** = saved view/snapshot.

Current Layer Combinations capabilities include:

- named combinations;
- layer visibility;
- layer locking;
- per-layer intersection groups;
- virtual hierarchical folders while keeping native IngeTrazo layers flat;
- apply/update/duplicate/rename/delete workflows;
- bottom-bar combination selector;
- built-in architectural templates;
- personal templates;
- import/export of templates;
- first-run template chooser for new projects;
- service interface that parametric geometry can query before automatic intersections/junctions.

This is the foundation for rules such as “walls in different intersection groups do not automatically clean up with each other”.

---

## Resource and preset direction

OpenTrace BIM is moving toward reusable architectural resources rather than forcing every project to start from blank parameters.

The active development snapshot includes work on:

- wall assembly presets;
- slab assembly presets;
- concrete, timber and steel member presets;
- structural profile catalogues;
- profile folders/categories;
- personal office libraries;
- import/export of reusable resources.

The goal is to let an office build a library once and reuse it across projects — and eventually across supported hosts.

---

## Design principles

1. **Architectural behavior first.** Geometry should behave like a building element, not merely like an extrusion.
2. **Editable after creation.** Parametric data remains attached to the object.
3. **Use host-native tools where possible.** OpenTrace BIM adds BIM/architectural behavior instead of replacing IngeTrazo's entire modeling stack.
4. **No hidden dependency on a local favourite.** Objects embed the geometry/data they need to survive file transfer.
5. **Open formats and open source.** GPL-3.0-or-later.
6. **Host portability.** Modeling concepts are being separated from host-specific UI so the project can later target IngeTrazo, Blender/Bonsai and FreeCAD.

---

## Installation — tested IngeTrazo build

1. In IngeTrazo, open **Extensions → Open plugins folder**.
2. Copy the `arquitetura_parametrica` folder into the plugin directory.
3. Restart IngeTrazo.

On Windows the user plugin directory is normally:

`%APPDATA%\ingetrazo\plugins\`

The package/folder name remains `arquitetura_parametrica` for compatibility while the project transitions to the **OpenTrace BIM** name.

---

## Production-oriented IngeTrazo API consumer

OpenTrace BIM is also the **production-oriented API consumer** behind the proposed generic IngeTrazo Resource / Library API currently under review.

That proposal is being exercised against real architectural resource needs — construction assemblies, complete element presets, reusable Complex Profiles, structural catalogues and portable office libraries — rather than only against a minimal demonstration plugin.

The intended boundary is deliberate: IngeTrazo core remains domain-neutral while OpenTrace BIM owns architectural schemas, validation, UI and geometry.

---

## Development visibility

This repository is intentionally public **before the toolkit is “finished”**.

The reason is coordination: walls, slabs, columns, beams, profiles, BIM resources and architectural automation are large areas, and parallel implementations can easily duplicate months of work. The repository and roadmap are meant to make active development visible so other IngeTrazo contributors can coordinate, reuse ideas and avoid unnecessary duplication.

If you are working on overlapping architectural/BIM tools, please open an issue or discussion here before rebuilding the same subsystem in isolation.

---

## Target architecture

```text
OpenTrace BIM
├── architecture core
│   ├── walls
│   ├── slabs
│   ├── columns
│   ├── beams
│   ├── openings
│   ├── assemblies
│   ├── profiles
│   └── BIM/resource semantics
│
├── reusable resources
│   ├── construction assemblies
│   ├── presets
│   ├── structural profiles
│   └── office libraries
│
└── host adapters
    ├── IngeTrazo        ← current implementation
    ├── Blender / Bonsai ← planned
    └── FreeCAD          ← planned
```

---

## Testing and contributions

Architectural edge cases are especially useful:

- unusual wall junctions;
- curve + curve intersections;
- T/X/Y conditions;
- sloped/twisted walls;
- mixed-height conditions;
- hosted openings on curved walls;
- multisegment/curved columns;
- curved/inclined beams;
- complex section profiles;
- multilayer wall/slab assemblies.

Bug reports, workflow criticism and code contributions are welcome.

## Author / development

Architecture, product direction, workflow design and real-world testing: **Leandro Lopes**.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
