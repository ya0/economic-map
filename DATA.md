# Data

Where every number comes from, how much of the world it covers and where it is weak. Reference year 2024; state of the build of 2026-10-12 (`python -m econviz.coverage` prints the coverage table).

## Coverage

| Finest level | Regions | Share of world GDP |
|---|---|---|
| Below states (US counties, Brazilian immediate regions, Mexican and Canadian metro areas, Chinese prefectures) | 4,067 | 43.8% |
| NUTS3 / OECD TL3 | 1,558 | 28.5% |
| States and provinces (OECD TL2, DOSE, national and Wikipedia tables) and population zones | 754 | 21.4% |
| Whole country | 138 | 6.2% |

79 countries are split, 18 of them only into population zones (2.4% of world GDP, flagged and hidden with Estimates off). 93.6% of world GDP and 84.7% of the land lie below country level. GDP shares: 55.3% of world GDP from 2024, 40.1% from 2022 to 2023, 4.4% older.

## Sources and licences

The repository holds no downloaded data, only the recipe (`pipeline/econviz/load/`) and the reference tables in `data/reference/` (MIT, like the code). The published site carries values and shapes derived from these sources, each under its own licence; the app's credits dialog lists every source with licence and link.

| Publisher | Used for | Licence |
|---|---|---|
| World Bank (WDI) | national GDP, population, land area | CC BY 4.0 |
| IMF (WEO) | national GDP where WDI has none | IMF terms, attribution |
| Eurostat, GISCO | NUTS3 GDP, population, area, shapes | Eurostat re-use; © EuroGeographics for boundaries |
| OECD | regional GDP and population (TL2, TL3) | CC BY 4.0 |
| PIK, Wenz et al. (DOSE v2.14) | regional GDP elsewhere | CC BY 4.0 |
| US BEA, US Census Bureau | county GDP, deflator, population, shapes | public domain |
| Office for National Statistics | UK ITL3 | Open Government Licence v3 |
| Natural Earth | country and admin-1 shapes | public domain |
| Wikidata | population gaps | CC0 |
| Wikipedia (pinned revisions) | regional GDP of India, South Africa, Philippines, Nigeria, Pakistan, Chinese prefectures, Russia, Kazakhstan; Chinese prefecture population; some census tables | CC BY-SA 4.0 |
| citypopulation.de (Thomas Brinkhoff) | census tables republished (Egypt, Philippines, Albania, Iran, Ukraine, Russia, Kazakhstan, Iraq, Papua New Guinea, Mauritania, Congo, Oman) | CC BY 3.0; the offices' terms apply too |
| IBGE (Brazil) | municipal GDP, population, area, shapes | free use with attribution |
| INEGI, CONAPO, SEDATU (Mexico) | census value added, population, shapes, metropolises | INEGI free use; CC BY 4.0 |
| Statistics Canada | metro GDP, population, shapes | Statistics Canada Open Licence |
| Department of Statistics Malaysia | state GDP | CC BY 4.0 |
| State Statistics Service of Ukraine | regional GDP 2021 | CC BY (data.gov.ua) |
| OCHA (COD-AB, COD-PS) | Chinese prefecture shapes; admin-1 population of several African and Asian countries | CC BY-IGO |
| National offices of Pakistan, India, China, Algeria, DR Congo, Venezuela, Mozambique, Angola, Saudi Arabia | population tables | official statistics, attribution |

Software in the site: MapLibre GL JS, pmtiles, @mapbox/vector-tile, pbf (BSD-3-Clause), d3-scale-chromatic (ISC), flag-icons (MIT).

## Country notes

- **United States**: county GDP (BEA) and population (Census vintage 2025); Connecticut is one unit since its planning regions replaced counties.
- **Europe**: NUTS3 (Eurostat, 2024 codes); UK from ONS ITL3.
- **Brazil**: 509 immediate geographic regions summed from municipalities (IBGE GDP 2023, population 2024).
- **Mexico**: 92 metropolises and the rest of each state; the state's GDP is split by census value added 2023, which understates farming and government and overstates plant sites and head offices (`census_va_share`).
- **China**: prefecture GDP from Wikipedia citing the provincial yearbooks (2021 to 2023), population from the 2020 census via Chinese Wikipedia, checked against NBS province totals. Ten provinces stay whole (municipalities; Fujian, Tibet, Xinjiang with mixed years; Hubei, Henan, Hainan incomplete).
- **Canada**: 42 metropolitan areas and the rest of each province (StatCan, GDP 2022).
- **Russia and Kazakhstan**: Wikipedia lists citing Rosstat (2023) and the Bureau of National Statistics (2024); Rosstat's own site was unreachable without disabling TLS checks.
- **India** (FY2022-23 as 2022), **South Africa**, **Philippines**: Wikipedia tables citing MoSPI, Stats SA and PSA, spot-checked against the offices.
- **Nigeria, Pakistan**: Wikipedia tables whose origin is an estimate (`estimate`, hidden with Estimates off).
- **Malaysia**: DOSM state GDP at constant prices (`constant_prices`). **Ukraine**: Ukrstat 2021; Crimea and Sevastopol are a separate disputed region without values.
- **Population zones** (`pop_share`): Algeria, Angola, Chad, Congo, Ethiopia, Iraq, Kenya, Mali, Mauritania, Mongolia, Niger, Oman, Papua New Guinea, Paraguay, Saudi Arabia, Sudan, Turkmenistan, Venezuela. Algeria rests on its 2008 census, the only wilaya series.

## Known gaps

- **Whole although large**: Taiwan, Israel, Bangladesh, UAE, Morocco (no regional GDP found); Afghanistan, Cameroon, Ghana, Madagascar, Zambia, Zimbabwe, DR Congo, Myanmar, Tanzania, Mozambique (no usable regional population, or one zone would hold most of the land); Singapore and Hong Kong by rule.
- **Old shares**: Argentina, Egypt, Ecuador, Uzbekistan, Bolivia, Estonia, Albania 2019; Thailand, Vietnam 2018; Iran 2017.
- **Abuja (FCT)** has no GDP of its own and is part of Niger State; Panama Oeste has no shape, so Panama is whole.
- **Shapes** are Natural Earth 1:10m where no national file is used: right at world and country scale, coarse along coasts and at high zoom; slivers of a few hundred metres where two national sources meet (US–Mexico, NUTS3 against non-EU neighbours).
- **Population** is scaled to the national total; factors above 1.10 (Nigeria, Egypt, South Africa, Iran, Algeria, Mali, Oman, Paraguay and others) are listed in `data/processed/population_scaling.csv`.
- GDP is where production is booked: commuter hubs, head offices, tax havens and enclaves distort per capita and density. The smoothed surfaces carry no information finer than the regions they are made from.
