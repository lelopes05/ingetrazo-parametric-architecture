# Changelog

Notable OpenTrace BIM changes are documented here. The public release is currently **0.11.1**; **0.12.9 is a release candidate awaiting in-application validation**. Changes marked as candidate fixes are based on code audit and automated checks, not yet on a complete Windows/IngeTrazo acceptance test.

## [0.12.9] — Release candidate (unreleased)

### Fixed — candidate

- Removed the application-wide Qt translation event filter introduced in 0.12.8 and the host-method monkey patch used by that layer. The prior build could terminate IngeTrazo when a tool palette was opened.
- Moved installer backups outside the plugins discovery directory to avoid duplicate `OpenTrace_BIM_backup_*` extension load errors.
- Revised wall UVW transfer to preserve corresponding face mappings during parametric reconstruction, with a safe planar fallback where no reliable match exists; no experimental triangulation was added.
- Routed interactive IFC metadata/identity changes through Undo/Redo history instead of silent mutation.
- Hardened the updater's archive validation, extraction and rollback, including rejection of unsafe ZIP paths.
- Removed a redundant/shadowed junction helper.

### Changed

- OpenTrace-owned UI uses localized, explicit English text updates instead of intercepting events for the entire `QApplication`.
- Kept the existing parametric tool architecture; encapsulated necessary IngeTrazo 0.5.7 private compatibility hooks in `host.py` rather than making broad unrelated refactors.
- Disabled the unfinished Membrane tool; the interface presents **“Membrane — Under evaluation”** only.
- Prepared dedicated INSTALLER, MANUAL and updater-compatible UPDATE distribution packages.

### BIM and interoperability carried forward

- Wall IFC `PredefinedType` and construction status/phase editing.
- Material `LayerSet` inspection, composite assemblies and reusable resources.
- Zones, systems and groups metadata; simplified georeferencing interface.
- IFC import handling for units, recursive placements and mapped items.
- IFC export profiles intended for OpenTrace, Bonsai/Blender, Archicad and Revit workflows.

### Known issues / validation pending

- **Windows runtime:** confirm all tools and palettes open without process termination.
- **Wall textures:** verify UVW scale, orientation and position visually for straight, curved, inclined and composite walls after editing and reloading.
- **IFC import:** re-test real Archicad and FreeCAD samples for scale, hierarchy and element positioning. Improvements are included, but the reported regressions are **not yet confirmed resolved**.
- **Persistence:** re-check save → close → reopen → parametric edit in the candidate build.

**Publication gate:** no stable tag, public release or official catalog update until these tests pass.

See [release notes](release-prep/0.12.9/RELEASE_NOTES.md), [technical audit](release-prep/0.12.9/AUDIT_SUMMARY.md) and [acceptance checklist](release-prep/0.12.9/TEST_CHECKLIST.md).

## [0.11.1] — 2026-10-06

- Unified OpenTrace BIM tool panel.
- Bundled Layer Combinations with architectural templates.
- Expanded profile/preset library workflows.
- Added opt-in update checks.

This is the version currently published through the official IngeTrazo extensions catalog.
