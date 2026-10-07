# OpenTrace BIM 0.12.8

OpenTrace BIM continues its evolution from a parametric architecture toolkit into a broader openBIM authoring environment for IngeTrazo.

This release significantly expands IFC interoperability and BIM data management, adds reusable BIM resources, introduces an experimental boundary-driven Membrane surface, and standardizes the OpenTrace interface in English for a consistent international release.

## Highlights

- Expanded **IFC4 BIM support** with official Property Sets and Quantity Sets, richer element semantics, material structures, classifications, groups, systems, zones, georeferencing and appearances.
- Added **reusable BIM libraries** for types, classifications and material styles.
- Added **Spaces / Zones / Systems / Groups** workflows.
- Added semantic support for **Roof, Stair, Ramp, Railing, Door and Window**.
- Added construction lifecycle/status metadata: **New, Existing, Demolish and Temporary**.
- Added **IfcMaterialConstituentSet** and **IfcMaterialProfileSetUsage** where appropriate.
- Added **IfcRepresentationMap** support for compatible repeated instances/components.
- Expanded **Open / Import / Link IFC** handling, including model units, nested placements, rotations, mapped items, additional geometry, materials, LayerSets, Psets and imported quantities.
- Strengthened **OpenTrace round-trip metadata** and persistent IFC identities.
- Added **material appearances/styles** to IFC export.
- Added a **simplified georeferencing interface** while retaining advanced IFC georeferencing data.
- Added an **experimental Membrane** object based on boundary-controlled smooth architectural surfaces.
- Expanded reusable **construction composition** workflows.
- Standardized the extension-owned interface in **English** for this release to avoid partial host-locale translations.
- Added a **Python installer** plus a separate illustrated manual-install package.

## IFC interoperability

OpenTrace now treats IFC as a BIM exchange layer rather than only as a geometry export format.

Projects can carry spatial hierarchy, GlobalIds, element types, classifications, official Property/Quantity Sets, material layer/profile/constituent structures, lifecycle status, systems, groups, zones, appearances and georeferencing information.

Compatibility profiles remain separate for **OpenTrace / IFC4 fidelity**, **Bonsai / Blender**, **Archicad** and **Revit-oriented** workflows.

OpenTrace remains the authority for its own parametric geometry. It deliberately avoids advertising OpenTrace walls as editable Bonsai Dumb* geometry when doing so could cause Bonsai to regenerate or simplify geometry.

## IFC import and round-trip

The external IFC reader has been expanded to understand model units, chained `IfcLocalPlacement`, rotations, `IfcMappedItem`, `IfcRepresentationMap`, common swept solids, polygonal/triangulated geometry, material associations, LayerSets, type + occurrence Psets and imported quantities.

When an IFC exported by OpenTrace contains OpenTrace round-trip metadata, the importer attempts to restore the original parametric record and persistent identity instead of treating the object only as generic geometry.

External objects that cannot be reconstructed safely remain BIM/reference geometry rather than being forced into an incorrect OpenTrace parametric type.

## Membrane — experimental

The Membrane tool is being developed as a lightweight architectural freeform surface, not as a structural membrane solver.

Its boundary is the controlling geometry. Curved boundary edges remain curved, the surface remains attached to them, and the object can carry thickness and OpenTrace construction compositions.

This workflow is intended for architectural skins, canopies, curved closures and other freeform surfaces. It remains **experimental** in 0.12.8.

## Installation

This release provides two user-facing installation options:

**Installer package** — extract the ZIP and run `INSTALL_OPENTRACE_BIM.py` with Python 3. The installer installs or updates OpenTrace BIM in the IngeTrazo user plugins directory and keeps any backup **outside** the plugins directory so IngeTrazo cannot load the backup as a second extension.

**Manual package** — in IngeTrazo choose **Extensions → Open plugins folder**, close IngeTrazo, copy the `OpenTrace_BIM` folder there, and restart IngeTrazo.

The correct layout is:

`.../plugins/OpenTrace_BIM/__init__.py`

Do **not** leave:

`.../plugins/OpenTrace_BIM/OpenTrace_BIM/__init__.py`

### Updating from 0.11.1 or earlier

Older releases used the folder name `arquitetura_parametrica`.

Do **not** leave both `arquitetura_parametrica` and `OpenTrace_BIM` inside the IngeTrazo plugins directory. The installer migrates this automatically. For a manual update, delete the old folder or move it **outside** the plugins directory.

0.12.8 preserves the legacy OpenTrace document-data namespace internally so existing `.igz` BIM project data remains readable after the folder rename.

A third asset named **`OpenTrace_BIM_0.12.8.zip`** is the catalogue/update package used to keep the 0.11.1 in-app updater compatible during this folder-name transition. Normal users should choose the Installer or Manual package.

## Language

The OpenTrace-owned interface is standardized in **English** in 0.12.8. The internal localization layer remains in the codebase and can be re-enabled once complete translation coverage is available.

## Notes

Some imported IFC elements may remain generic/reference geometry when their original application's parametric model cannot be reconstructed safely.

Likewise, advanced OpenTrace geometry may appear as non-native geometry in applications whose native wall, beam or column systems cannot represent the same shape.

The priority is **correct geometry and BIM semantics without data corruption**, rather than forcing every exchanged element into another application's proprietary parametric tool.

OpenTrace BIM remains GPL-3.0-or-later and does not modify the IngeTrazo core.
