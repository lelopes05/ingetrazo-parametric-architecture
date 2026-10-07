# Changelog

All notable public changes to OpenTrace BIM are documented here.

## 0.12.8

### BIM / IFC

- Expanded the IFC4 foundation with a much broader official entity, Property Set and Quantity Set catalogue.
- Added reusable BIM libraries for element types, classifications and material appearances.
- Added richer material semantics with `IfcMaterialLayerSet`, `IfcMaterialProfileSetUsage` and `IfcMaterialConstituentSet` where appropriate.
- Added semantic support for Spaces, Zones, Systems and Groups.
- Added IFC semantics for Roof, Stair, Ramp, Railing, Door and Window workflows.
- Added construction lifecycle/status metadata such as New, Existing, Demolish and Temporary.
- Added simplified georeferencing controls backed by projected CRS / map-conversion data.
- Added IFC material appearance/style export.
- Added `IfcRepresentationMap` support for compatible repeated instances/components.
- Expanded Open / Import / Link IFC handling.
- Improved external IFC handling for units, chained local placements, rotations, mapped items, triangulated/polygonal geometry, material associations, LayerSets, occurrence/type Psets and imported quantities.
- Strengthened OpenTrace IFC round-trip metadata and identity preservation.
- Kept OpenTrace as geometry authority instead of advertising geometry as editable Bonsai Dumb* objects when that could cause unsafe regeneration.

### Architectural modelling

- Added the experimental Membrane architectural surface workflow.
- Boundary geometry is authoritative; curved boundaries remain true surface controls.
- Added smooth boundary-driven surface generation, editable boundary vertices, interior control points, thickness and OpenTrace composition support.
- Continued wall, slab, beam and column interaction/preview refinements.
- Continued inclined-wall texture and total-height editing work.

### Resources / UI

- Expanded reusable construction-composition and BIM resource workflows.
- Added an expanded composition editor for narrow-panel workflows.
- Standardized the extension-owned public UI in English for this release so changing the IngeTrazo locale no longer produces a partially translated OpenTrace interface.
- Retained the localization layer for a future release with complete translation coverage.

### Installation / updating

- Added a Python installer package for users with Python 3.
- Added a separate manual-install package with illustrated instructions in English, Spanish, Bahasa Indonesia, Italian, Brazilian Portuguese, Simplified Chinese, French and German.
- Added explicit protection against duplicated `OpenTrace_BIM/OpenTrace_BIM` folder layouts.
- Added migration handling for the former `arquitetura_parametrica` installation folder.
- Preserved the legacy OpenTrace document-data namespace so existing `.igz` BIM project data remains readable after the branded folder rename.
- Updated the in-plugin updater so releases after 0.12.8 can accept either the legacy or branded package-root name during the transition.

### Known / active validation areas

- External IFC reconstruction is intentionally conservative: geometry that cannot be safely reconstructed as a native OpenTrace parametric object remains imported/reference geometry.
- IFC import from different authoring applications still requires real-world validation, especially units, placements and application-specific representation patterns.
- Membrane remains experimental.
- Complex wall junctions and some higher-order curved geometry cases remain under active development.

## 0.11.1

- Unified OpenTrace BIM side panel.
- Expanded presets, catalogues and profile folders.
- Bundled Layer Combinations with architectural templates.
- Added opt-in update checks through the official IngeTrazo extensions catalogue.
