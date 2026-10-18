# Municipality area check (tile 9/459/186)

Cells assigned by center point to N03 (2026-01-01) polygons. `area from cells` = sum of per-row ground cell area; `polygon area in tile` = geodesic area of the polygon clipped to the tile extent.

**Not an official-area comparison.** N03 carries no area attribute and the official area table (GSI) was not fetched, so the official check required by HANDOFF section 6(d) is still **unchecked**. The columns below only verify the cell assignment against the same polygons.

| code | name | cells | area from cells (km2) | polygon area in tile (km2) | diff % | full polygon (km2) |
|---|---|---:|---:|---:|---:|---:|
| 01204 | 旭川市 | 79 | 0.96 | 0.98 | -1.82 | 747.7 |
| 01208 | 北見市 | 22584 | 275.86 | 275.88 | -0.01 | 1427.4 |
| 01219 | 紋別市 | 9576 | 115.59 | 115.68 | -0.07 | 834.6 |
| 01220 | 士別市 | 16556 | 200.15 | 200.08 | +0.03 | 1119.2 |
| 01456 | 愛別町 | 774 | 9.38 | 9.37 | +0.16 | 250.1 |
| 01457 | 上川町 | 76658 | 934.58 | 934.34 | +0.03 | 1049.5 |
| 01458 | 東川町 | 7790 | 95.29 | 95.29 | -0.01 | 247.3 |
| 01459 | 美瑛町 | 5811 | 71.20 | 71.11 | +0.13 | 676.8 |
| 01550 | 置戸町 | 12581 | 154.11 | 153.94 | +0.12 | 527.3 |
| 01555 | 遠軽町 | 81781 | 992.68 | 992.18 | +0.05 | 1331.8 |
| 01560 | 滝上町 | 27375 | 330.90 | 330.99 | -0.03 | 766.9 |
| 01633 | 上士幌町 | 579 | 7.10 | 7.12 | -0.28 | 696.0 |

- 262,144 cells, all inside some municipality (no sea cells in this tile). Water bodies are not masked (no source yet).
- Largest deviation: Asahikawa (-1.8%, 79 cells; edge sliver). All others within +/-0.3%.
