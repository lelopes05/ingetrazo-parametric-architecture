# OpenTrace BIM 0.12.9 — Release Notes (candidate)

**Status:** Pre-release candidate; not yet approved for public deployment. Based on the last user-confirmed functional 0.12.7 build, with a targeted stability audit. Version 0.12.8 is skipped because of a severe palette-opening regression.

## Highlights

OpenTrace BIM 0.12.9 focuses on stability, maintainability and IFC/BIM workflows rather than adding experimental modeling features.

### Fixed

- **Palette startup crash:** removed global Qt event interception and translation-related host monkey patching introduced in 0.12.8. This is the leading cause identified in the audit; real IngeTrazo confirmation is still required.
- **Duplicate extensions after installation:** backups no longer live inside the scanned plugins folder.
- **Wall texture mapping:** improved face-to-face UVW retention when rebuilding parametric walls, avoiding experimental triangulation and using a planar fallback where required.
- **BIM metadata reliability:** interactive IFC identity/property changes now participate in Undo/Redo.
- **Updater safety:** tightened ZIP layout/path checks, extraction and rollback.
- **Code hygiene:** eliminated a duplicated junction helper and centralized necessary host-internal compatibility calls.

### Changed

- English labels for the OpenTrace interface are applied locally rather than modifying unrelated IngeTrazo UI widgets.
- **Membrane — Under evaluation:** experimental membrane modeling is disabled; the feature remains visible only as an unavailable roadmap item.
- Separate install, manual-install and auto-update archives are prepared with compatible folder structures.

### BIM / IFC features retained

- Wall IFC predefined types and construction phases/status.
- Material LayerSet visibility for compound assemblies.
- Zones, groups, systems and BIM resource workflows.
- More approachable georeferencing controls.
- IFC unit, mapping and placement handling, plus export profiles for interoperability with Bonsai/Blender, Archicad and Revit.

## Compatibility

- IngeTrazo 0.5.7+ is the target host version.
- IFC4 interoperability is under active validation.

## Before publishing

Automated packaging and targeted code tests have been reported as passing. **This is not a substitute for testing in IngeTrazo on Windows.** The release is blocked until:

1. Wall, slab, column, beam, profiles and BIM panels open without a crash.
2. Texture mapping is checked visually after modifying and reopening walls.
3. The saved .igz document reopens with editable parametric elements.
4. The original Archicad and FreeCAD IFC regression samples are imported again at the correct scale and location.
5. INSTALLER, MANUAL and UPDATE package structures are confirmed in the intended installation flow.

See [CHANGELOG](../../CHANGELOG.md), [audit summary](AUDIT_SUMMARY.md) and [test checklist](TEST_CHECKLIST.md).

**Do not publish a v0.12.9 GitHub release or change the official catalog until validation is complete.**
