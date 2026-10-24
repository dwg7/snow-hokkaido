# Winter trial: 2026-02-09 .. 02-15 (algo-v1-dev3), run 2026-10-24

Seven days of winter 2025/26 were processed (season 2025, 154 pass x tile files, no failures after the retry fix). Read as a test of the **winter regime**; there is still no ground truth.

## Speed

154 files took 120 s each on average with 4 workers in parallel, which is about 11 min per day: the same as the October backfill (about 13 min/day). The SCL-first skip gave no visible speed-up here (35 of the files were reused from the interrupted first run, so the sample is mixed); 150 days would still take about 27 h, more if the network is slower. **Not measured separately for skipped windows.**

## What the days look like (cells of the whole scan)

| day | scanned cells | cloud | clear | snow share of clear |
|---|---|---|---|---|
| 02-09 | 4.1 M | 65% | 35% | 3% |
| 02-10 | 9.3 M | 51% | 48% | 30% |
| 02-11 | 0.4 M | 100% | 0% | - |
| 02-12 | 6.8 M | 59% | 40% | 29% |
| 02-13 | 3.8 M | 93% | 7% | 0% |
| 02-14 | 4.1 M | 65% | 33% | 12% |
| 02-15 | 9.3 M | 95% | 5% | 8% |

Winter is cloudier than October (clear 0-48%, and passes cover only part of Hokkaido on some days).

## Problem: snow is under-counted in forested hills

In February most of Hokkaido is snow covered, but the snow share of clear cells is 3-30%. A window of 2000 x 2000 pixels near Kamikawa (tile 9/459/186, 2026-02-10, `docs/validation/winter-kamikawa-2026-02-10.jpg`; panels: true colour, our classes, NDSI, SCL):

- The image shows snow-covered hills with dark forest and shaded slopes. Our classes (blue = snow, green = clear and no snow) call a large part of this "green": the forest pixels have low NDSI, and a cell with less than half snow pixels becomes green.
- Against SCL: 31% of the window is SCL snow, but only 68% of those pixels reach NDSI 0.42 (median NDSI 0.54, B03 only 0.36: low sun and tree cover). SCL "bare/not vegetated" (11%, 16% of it above 0.42) and "dark" (12%, 39% above 0.42) hold more probable snow. 62% of SCL medium-probability cloud pixels exceed NDSI 0.42 as well (cloud over snow), which the rule correctly removes.
- Our own snow pixels are consistent with SCL (85-91% of them are SCL snow on 02-09..02-14, 76% on 02-15): few false positives, but **many misses**.

So the cell rule "snow if more snow than green pixels among the clear ones" is wrong for a winter landscape of snow with trees: the cell is snow-covered but reads as "green". This is the canopy problem (D3) that the design deferred; in winter it dominates.

## Options (not applied; the owner decides)

1. **Mark forest cells as not judgeable** (`static_flags` bit 0, D3): needs a forest mask (land cover data or a summer-imagery rule); then snow rate is computed on open land only. Honest but leaves most mountain municipalities with few valid cells.
2. **Store the snow fraction instead of a majority vote**: keep `n_snow / n_clear` per cell (a 0-100 band) and decide the class from a lower threshold (for example snow if at least 30% of the clear pixels are snow). Needs a validation against imagery; changes results again (new `algo_version`, re-derivation needs imagery because the fraction is not stored; `ndsi_q` is only an average).
3. **Use SCL snow (class 11) as an extra vote** (snow if our NDSI test or SCL says snow): simple, but SCL's own errors enter.
4. Accept the under-count for now and show winter values as "open land only"; label the dashboard accordingly.

Nothing was changed. A 150-day backfill with the current rule would produce winter snow rates that are too low.

## Rule comparison on winter windows (2026-10-24)

Owner's direction: do not special-case forests; the goal is to *recognise the snow situation in our own representation*, not to compute a better index, so simply trusting SCL is acceptable. Five cell rules were drawn side by side (11 x 11 pixel blocks, approximate; only cells with at least 80% clear pixels are judged; `docs/validation/winter-rules-*.jpg`, panels left to right: true colour, A, B, C, D, E):

| rule | definition | Kamikawa hills 02-10 (snow share of clear cells) | coast 02-12 |
|---|---|---|---|
| A | current: NDSI >= 0.42, snow if >= 50% of clear pixels | 42% | 7% |
| B | NDSI >= 0.36, snow if >= 30% | 59% | 12% |
| C | cell mean NDSI >= 0.20 (water not excluded) | 66% | 61% (**paints the sea as snow**) |
| D | pixel NDSI/NDVI forest-aware, >= 30% (untuned) | 72% | 26% (speckled) |
| E | SCL class 11, snow if a majority of clear pixels | 52% | 21% |

By eye: A leaves snow-covered hills with trees green. **B and E look almost the same** and follow the white ground in the true-colour panel; C fails over water and D is noisy. October (Daisetsuzan 10-18): SCL and our rule already agree (96.6% of our snow pixels are SCL snow), and on the cloud-edge case SCL is far more conservative (4 pixels against 2,480). There is **no ground truth** here either; "looks right" means it matches the visible white ground.
