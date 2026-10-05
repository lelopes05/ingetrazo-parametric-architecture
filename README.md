# IngeTrazo Architecture

Experimental parametric architecture and structure tools for [IngeTrazo](https://ingetrazo.com/).

Current development version: **0.10.2-dev**.

The project is being developed from an architect's workflow perspective, with iterative real-world testing. The main principle is simple: **reuse IngeTrazo's native tools and extension APIs whenever possible, and add only the architectural/BIM behavior that is missing.**

## Current tools

- Parametric straight and curved walls
- Independent wall base/top controls, sloped tops, leaning and twisted walls
- Hosted openings, including curved walls
- Composite wall and slab layers
- Parametric slabs with editable vertices and curved edges
- Straight, inclined and curved beams
- Straight, inclined, curved and segmented columns with variable sections
- Building levels and vertical anchoring
- Contextual radial editing controls
- Reusable **Complex Profiles**, drawn with IngeTrazo's native 2D tools and usable as beam/column sections
- Parametric data persisted inside `.igz` files through `group.ext`

## Status

This is **early experimental software** and the IngeTrazo extension API is still evolving during the 0.x series. Expect changes and occasional breakage.

The current focus is on stabilizing architectural modeling behavior before expanding documentation and packaging.

## Installation

1. In IngeTrazo, open **Extensions → Open plugins folder**.
2. Copy the `arquitetura_parametrica` folder into that plugins directory.
3. Restart IngeTrazo.

On Windows, the user plugin directory is normally `%APPDATA%\ingetrazo\plugins\`.

## Testing and contributions

Testers, bug reports, workflow feedback and code contributions are welcome. Architectural edge cases are especially useful: curved walls, unusual junctions, sloped/twisted walls, complex sections and mixed-height conditions.

## Author / development

Architecture, workflow design and testing: **Leandro Lopes**.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).