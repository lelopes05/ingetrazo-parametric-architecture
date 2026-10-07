# OpenTrace BIM 0.12.9 — BIM / IFC4 implementation

OpenTrace remains the authority for parametric geometry. IFC is a BIM/interoperability layer and does not replace OpenTrace geometry with Bonsai operators.

## Implemented BIM data

- Persistent GlobalId for OpenTrace elements and spatial structure.
- `IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey`.
- Wall, slab, beam and column entities/types, common property sets and quantities where parameters are reliable.
- Composite wall/slab material semantics through `IfcMaterialLayerSet` / `IfcMaterialLayerSetUsage`.
- Profile-set semantics for applicable beam/column sections.
- IFC classifications, reusable type/style libraries, zones, systems and groups.
- Wall PredefinedType and construction status/phase controls in the wall workflow.
- Friendly georeferencing entry with optional advanced CRS/MapConversion details.

## IFC export profiles

The export profiles are **OpenTrace fidelity**, **Bonsai / Blender**, **Archicad** and **Revit**. Native swept representations are used when the OpenTrace record maps safely to them; advanced geometry falls back to BRep/tessellation so curves, inclinations, custom profiles and resolved junction geometry are not silently flattened.

## Open / Import / Link IFC

IfcOpenShell is used when a compatible host build is available. The internal STEP fallback supports the IFC geometry families OpenTrace emits plus nested placements, mapped items and IFC length-unit conversion. Imported external elements remain generic BIM/reference geometry unless an OpenTrace round-trip payload is present; they are not falsely promoted to native parametric OpenTrace elements.

## Current limitations

- Real-world Archicad/FreeCAD regression files must still be smoke-tested on the target installation.
- Automatic linked-IFC reload is not implemented yet.
- Some arbitrary external IFC representation families still require IfcOpenShell.
- Membrane modelling is temporarily disabled and under evaluation.
