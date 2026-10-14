# Architecture

Two halves: an offline **pipeline** (Python, `pipeline/econviz/`) turns official statistics and boundary files into four static files, and a **web app** (TypeScript, `web/`) draws them. The four files in `web/public/` are the only interface; fields are added, never renamed.

```
fetch -> load -> boundaries, crosswalk -> layers -> select -> fill -> zones -> indicators -> validate -> levels -> export
                                                                                     -> tiles  -> regions.pmtiles
                                                                                     -> smooth -> smooth/
                                                                             export  -> indicators.json, sources.json
```

## Decisions

- **Sourced values only.** GDP, population and area come from statistics offices or aggregators that republish them (Eurostat, OECD, DOSE). Secondary fallbacks are flagged: Wikipedia tables (stored with revision and the source they cite; `estimate` when that source is a model) and, for population gaps only, Wikidata and republishers of a census (citypopulation.de, OCHA COD-PS). Modelled grids (night lights, ML downscaling, GHS-POP, Kummu 2025) are never used.
- **Finest official level per country**, whole country when none exists; small countries, islands and city-states stay whole. Coarser levels are sums and dissolves of the finest, never a second source.
- **Regions are shares.** Each region's share of its country's regional sum times the World Bank's national GDP (current US$, reference year), so regions add up to the country exactly and source currencies cancel.
- **One reference year**, 2024 (`paths.REF_YEAR`, `ECONVIZ_REF_YEAR`): one GDP year per country (the latest year up to 2024 in which 95% of regions have a value, at most 8 years back), population the latest per region in the same window; every offset is flagged.
- **Population is sourced, never modelled**, and scaled to the national total where a country's set is complete (`pop_scaled`, raw value kept).
- **Constant dollars** are derived in the browser with the US GDP deflator (base year selectable).
- **No basemap**: the map is the project's own polygons on a plain ocean. Static files only, no keys, no server.
- **GADM** geometry is never shipped (its licence forbids it); its keys only match DOSE values to Natural Earth shapes.
- The 90% case first: large economies and regular sources; edge cases only when cheap.

## Pipeline

`python -m econviz.build` (tables and web JSON), then `econviz.tiles` and `econviz.smooth`.

- **fetch**: every download goes through `fetch.get` into `data/raw/<source_id>/` with a sidecar (URL, date, SHA-256); raw files are never edited. Wikipedia pages are fetched at the revisions in `data/reference/wiki_pins.csv`.
- **load**: one module per source in `load/`, each returning the long table `region_id, iso3, variable (gdp | gdp_extra | pop | area_km2), year, value, unit, source_id, note` (`note` holds `;`-separated flags; `gdp_extra` is extra-regio GDP).
- **boundaries, crosswalk**: shapes from Natural Earth 1:10m (countries, admin-1), US Census, GISCO NUTS, ONS, IBGE, INEGI, StatCan and OCHA COD-AB. `data/reference/crosswalk.csv` maps OECD, DOSE and Wikipedia regions to Natural Earth or ONS units (`python -m econviz.crosswalk` proposes exact and fuzzy matches; manual rows are never overwritten).
- **layers, select**: per country the candidate layers, finest first (US counties, NUTS3, OECD TL3, OECD TL2, DOSE, DOSM, Wikipedia, Ukrstat, and the Russian and Kazakh Wikipedia lists). A layer is taken if it has at least 2 regions, GDP for 95% of them in one year, covers the country within 1% of its area, has no overlaps and puts at most 1% of GDP in regions without shape. National-source layers replace a usable one when 2 years newer. A guard rejects crosswalks whose population differs from Wikidata's by 3x for over 25% of units (swapped rows). `data/processed/selection.csv` records every choice and rejection.
- **Second subdivisions** (`select.refine`): Brazil (509 immediate regions), Mexico (92 metropolises cut by state, plus the rest of each state), China (prefectures) and Canada (metropolitan areas, plus the rest of each province) replace their parent where they pass the same checks. Their shares split the parent's GDP; their meshes are fitted to tile the country outline (`layers.fit`).
- **fill**: missing population from `data/reference/population_manual.csv` (each row with URL and a check figure), then Wikidata (rejected outside the year window, with area off by 3x, or a regional total off by 5%).
- **zones** (`zones.py`): a large country no source splits (land above 300,000 km² or 25 M people) whose admin-1 units all have population is grouped into at most 3 density zones (dense, middle, sparse; units with 15% of the people stand alone). GDP is split by population (`pop_share`), so per capita is the national value; skipped when one zone would hold over 70% of the land.
- **holes**: `attach.csv` joins units without a national total (Somaliland, Western Sahara, Baikonur, Northern Cyprus, Siachen); `holes.py` reports any uncovered area of 100 km² or more; known enclaves are listed in `holes_ok.csv`.
- **indicators, validate**: shares, scaling, derived ratios. The build fails if regions do not cover the country or overlap, GDP does not sum to the national total (1e-6), a region has no area, per capita is outside 0.02x to 50x the national value (unless whitelisted) or a value lacks source and year.
- **levels**: 0 continent, 1 country, 2 first and 3 second subdivision; every chain ends at a continent. Aggregates sum GDP, area and population of the finest regions; country rows take the national population. Crimea is a separate disputed region in no country.

**Ids** are `<scheme>:<code>`: `ISO3:DEU`, `NUTS2024:DE111`, `OECD:JPA01`, `GID:CHN.1_1` (DOSE), `FIPS:06037`, `WP:NGA-lagos-state`, `IBGE:…`, `COD:…`, `CMA:…`, `ZM:…`, `ZONE:DZA-1`, `CONT:europe`, `DISPUTED:crimea`.

**Flags** (shown in plain words in the app): `gdp_year_offset`, `pop_year_offset`, `national_year_offset`, `fiscal_year`, `constant_prices`, `remainder`, `census_va_share`, `area_computed`, `whole_country`, `imf_estimate`, `wikipedia_secondary`, `wikidata`, `pop_secondary`, `pop_scaled`, `pop_share`, `estimate`, `partial_population`, `aggregated` with `contains_<flag>`, `disputed`.

## The four files

- **`indicators.json`**: `meta` (reference year, price basis, columns, US deflator, unallocated GDP) and `regions: {id: [values]}` for all levels, 6 significant digits. Columns in fixed order, new ones appended: `gdp_usd, pop, area_km2, gdp_per_km2, gdp_per_capita, pop_density, gdp_year, pop_year, area_year, gdp_source, pop_source, area_source, flags, level_no, parent_id, name, iso2, pop_raw`.
- **`sources.json`**: the credits, generated from `data/reference/sources.csv` (licence, link) plus the Wikipedia revisions used.
- **`regions.pmtiles`** (tippecanoe, z0 to 9): polygon layers `l0` to `l3`, each a complete cover of the world at that level (countries that stop above it appear whole); properties `region_id, iso3, name, level_no`. Nothing is dropped: a region smaller than a tile unit becomes a small square. Point layer `labels` with a GDP `rank` per level.
- **`smooth/`**: 30 lossless WebP surfaces (3 indicators × 2 kernels × 5 radii) and `smooth.json` (ranges, file names). GDP, land area and population are spread over a Web Mercator raster (5 or 10 km cells, mass conserved) and smoothed separately: GDP per km² = (K∗GDP) / (K∗land), "GDP within reach per km² of land within reach"; likewise population density and GDP per capita. Kernels: inverse square (median-matched, cut at 4r) and Gaussian; radii 15, 30, 50, 100, 150 km. Pixel encoding: R,G a 16-bit log10 code, B the land fraction within reach (for "Include sea"), A whether the pixel is land, sea or undefined.

## Web app

Vite, TypeScript, MapLibre GL JS with the `pmtiles` protocol, d3-scale-chromatic; no UI framework.

| Module | Role |
|---|---|
| `main.ts` | Start-up, wiring of controls to state, render |
| `state/state.ts` | The whole view as one object, serialised to the URL hash (defaults omitted, unknown or invalid keys ignored, old keys migrated): every view is a link |
| `data/` | Parsing `indicators.json`, levels, focus, price rescaling, search, flag words |
| `map/map.ts` | MapLibre layers: values joined as `feature-state` by `region_id`, so changing indicator, year or colours never reloads tiles; relief as `fill-extrusion` |
| `map/smooth.ts`, `map/gpu.ts` | Smoothed view: WebP read bit-exact through a WebGL texture, coloured by a shader (palette, classes, sea, focus as uniforms); relief as a MapLibre terrain served from the surface |
| `scales/scales.ts` | Indicators, log scales, classes, palettes (dark and light, none blue in light where the sea is blue; contrast is tested) |
| `ui/ui.ts`, `style.css` | Legend, tooltip, panel, credits, cards; phone layout |
| `export.ts`, `frame.ts` | Export image (Full HD or more, header, legend, credits) and the area frame for focus and export |
| `track.ts` | GoatCounter counts on the published address only: page view and each control used, by id; typed text is never sent |

Views: **regions** (log colour, gradient or 3 to 7 classes), **relief** (tilted, heights by log value), **smoothed** (surface of the chosen radius and kernel; "Include sea" divides by all area within reach), **local excess** (a place against its Gaussian surroundings one radius up). **Focus** limits drawing and scale to chosen regions or a drawn box. Estimates off shows a zone as its whole country.

## Tests

`pytest` (offline; `-m network` downloads, `-m slow` reads every tile), Vitest for the web logic against a small fixture, Playwright end-to-end on a real build (features, layouts on a device matrix, a pairwise state matrix). CI runs pytest, `tsc` and Vitest.
