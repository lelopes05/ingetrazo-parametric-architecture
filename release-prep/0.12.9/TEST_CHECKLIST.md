# OpenTrace BIM 0.12.9 — smoke/regression test

1. **Startup / crash regression** — open Wall, Slab, Column, Beam, Complex Profiles and BIM / IFC. Each page must open without closing IngeTrazo. Open Membrane and confirm it only shows “Under evaluation”.
2. **Wall UVW** — paint a straight wall with a textured material; edit height, one endpoint/top elevation, lean/twist where applicable, and reopen the file. Texture scale/orientation/position should remain coherent. No triangulation edges should be introduced solely for mapping.
3. **Parametric persistence** — create/edit wall, slab, beam and column, save .igz, close/reopen, and edit them again.
4. **Wall BIM** — test IFC PredefinedType (SOLIDWALL, ELEMENTEDWALL, etc.) and construction status (NEW, EXISTING, DEMOLISH, TEMPORARY). Undo/Redo a metadata edit.
5. **LayerSet** — select a composite wall/slab and inspect BIM advanced material/layer data.
6. **Zones / Systems / Groups** — create a definition with +, choose it and assign the selected element.
7. **Georeferencing** — use the simplified Coordinate system + origin E/N/Z + rotation flow; advanced fields remain optional/collapsed.
8. **External IFC regression** — import the Archicad and FreeCAD IFC samples that previously arrived at the wrong scale/position. Confirm metre conversion and nested placements.
9. **Round-trip** — export OpenTrace fidelity IFC, open it in a new document, and verify available parametric payload/GlobalId restoration.
10. **Installer/update layout** — final installation must contain plugins/OpenTrace_BIM/__init__.py, never OpenTrace_BIM/OpenTrace_BIM; no OpenTrace_BIM_backup_* directory may remain inside plugins.
