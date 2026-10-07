# OpenTrace BIM 0.12.9 — stability audit

This release was rebuilt from the last user-confirmed functional baseline, **0.12.7**. The 0.12.8 package was used only to recover intended changes; it was not used as the runtime base.

## Critical issues fixed

### 1. Qt-wide translation hook removed
0.12.8 installed a `QApplication` event filter that rewrote widget text during `Show`, `Polish`, `ChildAdded` and `LayoutRequest` events, and also replaced a host status method at runtime. That design could recursively retrigger Qt layout work and matched the reported native crash when opening an OpenTrace modelling page.

0.12.9 removes both mechanisms. English UI translation is now explicit and one-shot on OpenTrace-owned widget trees. No global Qt event filter and no host-method monkey patch are installed.

### 2. Installer backups no longer become plugins
Older installers placed `OpenTrace_BIM_backup_*` directories inside IngeTrazo's `plugins` directory. IngeTrazo scans package directories there, so the backups appeared as duplicate/load-error extensions.

0.12.9 stores backups in `ingetrazo/opentrace_backups`, outside the scanned plugin directory. The installer also moves stale OpenTrace backup folders left by older installers out of `plugins`.

### 3. Wall texture / UVW rebuild path corrected
The previous rebuild path discarded an explicit per-face `uvw` map and reconstructed only a generic tile scale/rotation. It also reused the first semantic `side` appearance for multiple regenerated wall faces. That could move, rotate or mirror a positioned texture after parametric edits.

0.12.9 transfers appearance face-by-face when semantic topology corresponds. Existing corner UVs are evaluated from the old map and re-fitted to the regenerated face as a full 3D affine world-to-UV map. This supports leaned/twisted four-corner wall faces without triangulating the wall. If topology no longer corresponds, the plugin deliberately falls back to the host planar texture mapping rather than guessing an invalid UVW.

### 4. Update rollback made atomic at file level
The updater previously restored overwritten files after a failed update but could leave files that existed only in the failed new package. That could create a mixed-version installation.

0.12.9 removes new-only files before restoring the backup. ZIP extraction is also explicit and path-validated rather than delegated to `extractall`.

### 5. BIM metadata edits use Undo/Redo
Interactive IFC metadata editing previously had paths that changed `group.ifc` directly and manually incremented the scene version. Element metadata changes and IFC identity preparation now go through the IngeTrazo history layer. IFC export reads metadata without mutating model objects.

### 6. Host-private tool access centralized
IngeTrazo 0.5.7 does not expose public registration/activation methods for persistent modelling tools. OpenTrace therefore still needs a compatibility boundary for `_tools` / `_activate_tool`, but those accesses are centralized in `host.py` instead of being spread through controllers.

### 7. Membrane runtime disabled
The experimental membrane implementation is retained only as dormant source for future work and old-file compatibility. It is not imported, registered, activated or given event filters/callbacks during normal startup. The UI shows **Membrane — Under evaluation** only.

### 8. Duplicate helper removed
`junctions.py` contained two implementations with the same `_point_segment_distance` name; the later definition silently shadowed the first. 0.12.9 keeps a single defensive implementation.

## Reviewed and intentionally retained

- Viewport event filters used by wall/slab/beam/column editing are scoped to the OpenTrace controllers and the viewport. They are not application-wide filters and are part of the interaction model.
- Single-point `_world_to_pixel` calls remain in editing code. IngeTrazo 0.5.7 itself uses the same projection helper in its tools/examples, while the public extension API only exposes the vectorized projection path. Treat this as a host-0.x compatibility dependency, not a candidate for speculative replacement in a stability release.
- Scene `version` increments inside OpenTrace command `do/undo` methods are retained: they are part of undoable command execution, unlike direct UI mutation.
- Broad exception isolation around optional IfcOpenShell/resource integrations remains where failure must degrade a feature rather than unload the whole extension.
- Large legacy UI/edit modules were not split merely for style. A structural rewrite of working modelling code would add regression risk without fixing a reported defect.

## IFC import review

The 0.12.7 fallback reader improvements are preserved: SI/conversion-based length units, recursive `IfcLocalPlacement`, mapped-item transforms, polygonal/tessellated/BRep/extruded representations and OpenTrace round-trip payload restoration. If IfcOpenShell is available, world-coordinate tessellation is preferred.

The Archicad/FreeCAD files that originally exposed scale/stacking problems are still required for a real-world regression test; the audit does not claim those external files were executed in this build environment.

## IngeTrazo core

No IngeTrazo source file is modified by this release. The IngeTrazo 0.5.7 source was consulted read-only to distinguish public extension API from compatibility dependencies.
