# Economic map

Where on Earth is the world's economic output made? A static web map of GDP per km² for countries and, where official statistics exist, for states, counties, prefectures and metropolitan areas: about 6,500 regions holding 94% of world GDP below country level (reference year 2024). It also shows population density and GDP per capita, smoothed "GDP within reach" surfaces, a relief view and a globe. Every view is a shareable link.

**Live: https://yammann.ch/economic-map/**

- [ARCHITECTURE.md](ARCHITECTURE.md): decisions, data rules, pipeline, web app
- [DATA.md](DATA.md): sources and licences, coverage, known gaps

## Build

The repository holds the recipe, not the data: the pipeline downloads about 390 MB from the official sources (no API keys, no manual downloads) and builds everything else. Commands are for Windows; on Linux and macOS use `.venv/bin/` instead of `.venv/Scripts/`.

| Needs | |
|---|---|
| Python 3.11+, Node.js 20.19+ or 22.12+, git | |
| tippecanoe 2.x (tiles only) | Windows: in WSL (`sudo apt install build-essential zlib1g-dev git curl unzip`, then `wsl bash pipeline/build_tippecanoe.sh`); macOS: `brew install tippecanoe`; elsewhere the same script or a package; or set `TIPPECANOE=/path` |
| 2 GB disk, 4 GB free RAM | |

```
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python -m econviz.build     # downloads, tables, web/public/indicators.json and sources.json
.venv/Scripts/python -m econviz.tiles     # web/public/regions.pmtiles, about 3 minutes
.venv/Scripts/python -m econviz.smooth    # web/public/smooth/, about 9 minutes
cd web && npm ci && npm run dev           # open the printed URL; npm run build -> web/dist
```

Downloads are cached and checksummed, so a rerun resumes. Wikipedia pages are read at the revisions pinned in `data/reference/wiki_pins.csv` (delete a row to take the current one); the other sources are live, so a fresh build follows their latest releases and can differ slightly from the published site.

To work on the web app only, copy `regions.pmtiles`, `indicators.json`, `sources.json` and `smooth/` from the `gh-pages` branch into `web/public/`.

## Test

```
.venv/Scripts/python -m pytest                    # offline; -m network downloads, -m slow reads every tile
cd web && npx tsc --noEmit && npm test            # type check, unit tests
npx playwright install chromium && npm run e2e    # browser tests on a build of their own (needs the data)
```

Without a usable GPU, run the browser tests with `E2E_ANGLE=swiftshader` (software GL, about 20 minutes).

## Deploy

`python scripts/deploy_pages.py` builds `web/dist`, asks, and force-pushes it as the single commit of the `gh-pages` branch, which GitHub Pages serves. The address follows from the owner's user site (`yammann.ch`): a repository's Pages site appears at `/<repository name>/`. Limits: files up to 100 MB, site up to 1 GB.

## Contributing

Run the tests before a pull request and keep to the rules in [ARCHITECTURE.md](ARCHITECTURE.md#decisions). A new source is one loader in `pipeline/econviz/load/` with `download()` through `fetch.get`, a row in `data/reference/sources.csv` with its licence (the credits are generated from it), crosswalk rows if its regions are matched to Natural Earth units, and offline tests with small inline fixtures.

## Licence and privacy

Code and reference tables: MIT ([LICENSE](LICENSE)). Data: each source keeps its licence ([DATA.md](DATA.md)). The site counts page views and which controls are used with [GoatCounter](https://www.goatcounter.com/): no cookies, no personal data, nothing typed.
