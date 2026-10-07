# OpenTrace BIM 0.12.9

0.12.9 is a stability and BIM-interoperability build based on the last user-confirmed functional 0.12.7 runtime.

## Highlights

- Fixes the 0.12.8 native crash caused by application-wide Qt translation interception.
- Keeps the OpenTrace UI in English using explicit, local translation only.
- Fixes installer backups being detected as duplicate extensions.
- Reworks wall UVW preservation without triangulating wall geometry.
- Makes interactive IFC metadata/identity changes undoable.
- Hardens updater extraction and rollback.
- Preserves IFC unit/placement/mapped-item import improvements and BIM metadata workflows.
- Keeps IFC wall predefined types and construction status/phase controls.
- Keeps LayerSet inspection, reusable BIM libraries, zones/systems/groups and simplified georeferencing.
- **Membrane is temporarily disabled and shown as “Under evaluation”.**

## Compatibility

- IngeTrazo: 0.5.7+
- IFC export: IFC4
- IFC profiles: OpenTrace fidelity, Bonsai/Blender, Archicad and Revit

## Important test targets

Before publishing as a stable release, test the package inside IngeTrazo on the target Windows installation, especially: opening each OpenTrace modelling page, wall UVW after parametric edits, existing `.igz` persistence, and the Archicad/FreeCAD IFC samples that previously exposed scale/placement errors.
