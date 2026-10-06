# OpenTrace BIM — Feature Matrix

This document separates the **current user-tested baseline** from work that exists only in the newer development snapshot.

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

## Complex Profiles

| Capability | Status |
|---|---|
| Native-2D-tool profile editing | ✅ Tested |
| Outer loops + holes | ✅ Tested |
| User insertion origin | ✅ Tested |
| Save reusable favourite | ✅ Tested |
| Use in beam/column | ✅ Tested |
| Embedded geometry snapshot in model | ✅ Tested |
| Profile folders/categories | 🧪 0.11 snapshot |
| Built-in structural catalogues | 🧪 0.11 snapshot |

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

## 0.11 development snapshot

The 0.11 branch/package is a broader integration snapshot. It introduces:

- a single OpenTrace BIM side panel;
- unified navigation for Walls / Slabs / Columns / Beams / Profiles;
- revised icons;
- initial wall and slab preset libraries;
- concrete/timber structural presets;
- steel profile catalogue work;
- profile folders/categories;
- larger built-in profile libraries;
- stronger Layer Combinations integration.

It is **not yet the user-tested baseline**.

## Planned platform reach

| Host | Status |
|---|---|
| IngeTrazo | ✅ Current reference implementation |
| Blender / Bonsai | 🧭 Planned adapter |
| FreeCAD | 🧭 Planned adapter |
