# OpenTrace BIM Roadmap

This roadmap is deliberately public while features are still being built. Its purpose is to make active work visible and reduce duplicated effort across the IngeTrazo ecosystem.

Legend:

- ✅ implemented and exercised in the current tested workflow
- 🧪 implemented or substantially changed in the development snapshot; awaiting broader real-world testing
- 🚧 actively being developed
- 🧭 planned

## Current tested baseline — 0.10.2-dev

### Architecture objects
- ✅ Straight parametric walls
- ✅ Curved parametric walls
- ✅ Core-based exterior/center/interior alignment
- ✅ Independent base/top wall editing
- ✅ Wall lean/twist and sloped-top workflows
- ✅ Hosted wall openings, including curved walls
- ✅ Parametric slabs with editable/curved boundaries
- ✅ Parametric slab openings
- ✅ Rectangular/circular/complex-profile columns
- ✅ Inclined, segmented and locally curved columns
- ✅ Straight/inclined/horizontally curved beams
- ✅ Reusable Complex Profiles
- ✅ Level anchoring and offsets
- ✅ Composite wall assemblies
- ✅ Composite slab assemblies
- ✅ Parametric persistence in .igz

### Editing
- ✅ Contextual radial palettes
- ✅ Vertex insertion/movement
- ✅ Edge/path editing
- ✅ Architectural snap/reference overlays
- ✅ Direct numeric controls

## Current companion module — Layer Combinations

- ✅ Named layer combinations
- ✅ Visibility and lock states
- ✅ Virtual layer folders
- ✅ Per-layer intersection groups
- ✅ Apply/update/duplicate/rename/delete
- ✅ Bottom-bar selector
- ✅ Built-in architectural templates
- ✅ Personal templates
- ✅ Import/export
- ✅ New-project template chooser
- 🚧 Parametric junctions progressively consuming intersection-group rules

## 0.11 development snapshot

- 🧪 Unified OpenTrace BIM side panel instead of many independent extension tabs
- 🧪 Reworked icon family
- 🧪 Built-in wall assembly presets
- 🧪 Built-in slab assembly presets
- 🧪 Beam/column presets for concrete and timber
- 🧪 Structural steel profile catalogue
- 🧪 Profile folder/category system
- 🧪 Larger built-in Complex Profile library
- 🧪 Deeper Layer Combinations integration

This snapshot is intentionally not promoted as the tested baseline until it passes real-world use.

## Next priorities

### Junction engine
- 🚧 Curve + curve wall junctions
- 🚧 External T conditions
- 🚧 More robust L/T/X/Y cleanup
- 🚧 Layer/intersection-group-aware automatic cleanup
- 🧭 Review compatible GPL implementations in the wider IngeTrazo ecosystem before duplicating algorithms

### Beams
- 🚧 Vertical curvature
- 🚧 Endpoint-centric inclination from either side
- 🚧 Cleaner curved-beam tessellation/soft-edge presentation
- 🧭 More structural profile metadata

### Columns
- 🚧 Further per-segment inclination control
- 🚧 Cleaner tessellation/soft-edge presentation
- 🧭 Array/grid placement workflows

### Slabs
- 🚧 More robust polygon offsets
- 🧭 Additional hosted relationships
- 🧭 richer floor/roof assembly presets

### Openings
- 🚧 More hosted opening types
- 🧭 Door/window semantic objects on top of hosted voids
- 🧭 richer opening metadata and scheduling

### Resources / office libraries
- 🚧 Exportable/importable wall and slab assemblies
- 🚧 Profile folders and catalogues
- 🧭 Project-independent office libraries
- 🧭 Favourites/presets for complete element configurations
- 🧭 Resource bundles compatible with the proposed IngeTrazo Resource Library API

### BIM / interoperability
- 🧭 IFC mapping for native OpenTrace BIM elements
- 🧭 Quantities derived from parametric definitions
- 🧭 Material and assembly takeoffs
- 🧭 Object classification/property sets
- 🧭 schedules and reports

## Host portability

The IngeTrazo implementation is the current reference host.

Planned adapters:

- 🧭 Blender / Bonsai
- 🧭 FreeCAD

The intention is not to mechanically copy UI code between applications. The long-term target is a reusable architectural core with host adapters for geometry, persistence, UI and selection.

## Coordination rule

Before implementing a large architectural subsystem, check:

1. IngeTrazo core issues/PRs/discussions;
2. the IngeTrazo extensions catalog;
3. public branches/forks of active contributors;
4. compatible GPL implementations that can be reused or adapted with attribution.

If you are already working on one of the roadmap items, please say so publicly. A short issue/comment is enough to prevent duplicated work.
