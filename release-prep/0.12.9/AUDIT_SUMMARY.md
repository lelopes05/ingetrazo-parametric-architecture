# OpenTrace BIM 0.12.9 — audit summary

0.12.9 is rebuilt from 0.12.7, the last user-confirmed functional runtime. 0.12.8 was used only to recover intended changes.

## Critical corrections
- removed the QApplication-wide translation event filter introduced in 0.12.8;
- removed host-method monkey patching from the translation layer;
- English UI now uses explicit/local translation on OpenTrace-owned widgets only;
- installer backups are stored outside IngeTrazo's scanned plugins directory and stale backup folders are migrated out;
- Membrane is not loaded or registered; the UI shows **Membrane — Under evaluation** only;
- wall UVW preservation is transferred face-by-face without triangulating wall geometry;
- interactive IFC metadata and identity preparation now use Undo/Redo history;
- updater validation/extraction/rollback is hardened;
- unavoidable IngeTrazo 0.5.7 private persistent-tool integration is centralized in host.py;
- duplicate helper shadowing in junctions.py was removed.

## Preserved BIM / IFC work
Wall PredefinedType, construction status/phase, Material LayerSet inspection, Zones/Systems/Groups, simplified georeferencing, IFC import units/recursive placements/mapped items, BIM libraries and IFC export profiles for OpenTrace, Bonsai/Blender, Archicad and Revit are retained.

## Conservative decisions
Large working UI/edit modules were not refactored merely for style. Scoped viewport event filters and compatibility projection calls were retained where they are part of established modelling interaction or host-0.x compatibility.

## Validation completed
- every Python file in the final packages compiles;
- final packages contain no __pycache__, .pyc or nested OpenTrace_BIM/OpenTrace_BIM;
- UPDATE package has one OpenTrace_BIM/ root and matches its manifest;
- installer integration test passed in a temporary user-data layout;
- wall UVW affine transfer unit tests passed for planar and twisted/non-planar quads;
- BIM metadata/identity Undo/Redo tests passed;
- updater security validation passed, including path-traversal rejection.

## Runtime gate
The candidate still needs a real IngeTrazo Windows smoke test before public release: page opening/crash regression, visual wall UVW, .igz save/reopen/edit, and the actual Archicad/FreeCAD IFC regression files.
