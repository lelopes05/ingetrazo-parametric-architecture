# OpenTrace BIM — Feature Matrix

This document separates the **published user-tested baseline (0.11.1)** from the **0.12.8 release-candidate work** that is still receiving broader real-world validation.

## Walls

| Capability | Status |
|---|---|
| Straight parametric wall | ✅ Tested |
| Curved parametric wall | ✅ Tested |
| Exterior / center / interior alignment | ✅ Tested |
| Editable thickness / height / base | ✅ Tested |
| Base-level link | ✅ Tested |
| Top-level link + offset | ✅ Tested |
| Independent endpoint heights | ✅ Tested |
| Sloped top | ✅ Tested |
| Lean/twist workflow | ✅ Tested |
| Insert/move vertices | ✅ Tested |
| Continue/extend endpoint | ✅ Tested |
| Curve existing segment | ✅ Tested |
| Hosted rectangular opening | ✅ Tested |
| Hosted opening on curved wall | ✅ Tested |
| Composite multilayer assembly | ✅ Tested |
| Per-layer materials | ✅ Tested |
| Semantic layer functions/core | ✅ Tested |
| Straight/mixed automatic junctions | ✅ Partial/tested cases |
| Curve + curve / external T cleanup | 🚧 Active |
| IFC wall type / lifecycle metadata | 🧪 0.12.8 RC |
| Inclined-wall UV / total-height refinements | 🧪 0.12.8 RC — validation active |

## Slabs

| Capability | Status |
|---|---|
| Rectangle by diagonal | ✅ Tested |
| Rectangle by base + width | ✅ Tested |
| Free polygon | ✅ Tested |
| Move vertex | ✅ Tested |
| Insert vertex | ✅ Tested |
| Stretch edge | ✅ Tested |
| Curved edge | ✅ Tested |
| Chamfer / fillet | ✅ Tested |
| Boundary offset | ✅ Tested with known edge cases |
| Hosted polygonal openings | ✅ Tested |
| Editable/curved/chamfered/filleted opening edges | ✅ Tested |
| Level anchoring | ✅ Tested |
| Simple / composite structure | ✅ Tested |
| Multilayer assembly + materials | ✅ Tested |

## Columns

| Capability | Status |
|---|---|
| Rectangular | ✅ Tested |
| Circular | ✅ Tested |
| Complex Profile section | ✅ Tested |
| 3×3 insertion anchors | ✅ Tested |
| Base/top level links | ✅ Tested |
| Offsets | ✅ Tested |
| Inclination | ✅ Tested |
| Rotation | ✅ Tested |
| Multisegment definition | ✅ Tested |
| Per-segment dimensions | ✅ Tested |
| Per-segment materials | ✅ Tested |
| Fixed or percentage segment heights | ✅ Tested |
| Local curvature on selected segment | ✅ Tested |
| Insert segment vertex | ✅ Tested |
| Grid/array placement | 🧭 Planned |
| IFC profile/material usage metadata | 🧪 0.12.8 RC |

## Beams

| Capability | Status |
|---|---|
| Rectangular section | ✅ Tested |
| Circular section | ✅ Tested |
| Complex Profile section | ✅ Tested |
| Editable length/width/height | ✅ Tested |
| Rotation | ✅ Tested |
| Level/base anchoring | ✅ Tested |
| Inclination | ✅ Tested |
| Horizontal curvature | ✅ Tested |
| Vertical curvature | 🚧 Active |
| Cleaner curved-mesh presentation | 🚧 Active |
| IFC profile/material usage metadata | 🧪 0.12.8 RC |

## Complex Profiles

| Capability | Status |
|---|---|
| Native-2D-tool profile editing | ✅ Tested |
| Outer loops + holes | ✅ Tested |
| User insertion origin | ✅ Tested |
| Save reusable favourite | ✅ Tested |
| Use in beam/column | ✅ Tested |
| Embedded geometry snapshot in model | ✅ Tested |
| Profile folders/categories | ✅ Implemented |
| Built-in structural catalogues | ✅ Implemented |

## Layer Combinations

| Capability | Status |
|---|---|
| Named combinations | ✅ Tested |
| Visibility state | ✅ Tested |
| Lock state | ✅ Tested |
| Intersection group | ✅ Tested |
| Virtual folders | ✅ Tested |
| Bottom selector | ✅ Tested |
| Architectural templates | ✅ Tested |
| Personal templates | ✅ Tested |
| Import/export templates | ✅ Tested |
| First-run project template chooser | ✅ Tested |
| Automatic geometry behavior based on groups | 🚧 Integration underway |

## BIM / IFC4 — 0.12.8 release candidate

| Capability | Status |
|---|---|
| Persistent IFC GlobalIds / spatial hierarchy | 🧪 0.12.8 RC |
| IFC export profiles | 🧪 0.12.8 RC |
| Official IFC4 Pset / Qto catalogue | 🧪 0.12.8 RC |
| IfcMaterialLayerSet | 🧪 0.12.8 RC |
| IfcMaterialProfileSetUsage | 🧪 0.12.8 RC |
| IfcMaterialConstituentSet | 🧪 0.12.8 RC |
| BIM type / classification / appearance libraries | 🧪 0.12.8 RC |
| Spaces / Zones / Systems / Groups semantics | 🧪 0.12.8 RC |
| Roof / Stair / Ramp / Railing semantics | 🧪 0.12.8 RC |
| Door / Window fill relationships | 🧪 0.12.8 RC |
| Simplified georeferencing | 🧪 0.12.8 RC |
| IfcRepresentationMap | 🧪 0.12.8 RC |
| Open / Import / Link IFC | 🧪 0.12.8 RC |
| External IFC units / placements / mapped items | 🧪 0.12.8 RC — validation active |
| OpenTrace IFC round-trip metadata | 🧪 0.12.8 RC |

## Membrane — experimental

| Capability | Status |
|---|---|
| Polygon / rectangle / ellipse creation | 🧪 0.12.8 RC |
| Boundary-driven smooth surface | 🧪 0.12.8 RC |
| Horizontal / vertical curved boundary controls | 🧪 0.12.8 RC |
| Editable boundary vertices | 🧪 0.12.8 RC |
| Interior control points | 🧪 0.12.8 RC — validation active |
| Thickness / OpenTrace composition support | 🧪 0.12.8 RC |

## 0.12.8 release-candidate integration

- unified OpenTrace BIM panel and reusable composition editor;
- English-only extension-owned UI for this public release;
- BIM/IFC advanced editor and official IFC4 catalogue data;
- reusable BIM libraries and relations;
- expanded IFC import/export/round-trip foundation;
- experimental Membrane object;
- Python installer plus illustrated multilingual manual-install instructions.

## Planned platform reach

| Host | Status |
|---|---|
| IngeTrazo | ✅ Current reference implementation |
| Blender / Bonsai | 🧭 Planned adapter |
| FreeCAD | 🧭 Planned adapter |
