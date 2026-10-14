"""Indicator maths (pure functions): year selection, regional shares scaled to the national total, derived ratios, flags."""
import numpy as np
import pandas as pd

from .paths import REF_YEAR

MAX_OFFSET = 8  # earliest usable year is 2016, as before the move to 2024
SCALE_TOL = 1e-9  # a population scaled by a factor closer to 1 than this counts as unchanged


def nearest_year(years, ref=REF_YEAR, max_offset=MAX_OFFSET):
    """The reference year if present, else the closest earlier year within max_offset; None if there is none."""
    ok = [y for y in years if 0 <= ref - y <= max_offset]
    return max(ok) if ok else None


def shared_year(obs, ref=REF_YEAR, max_offset=MAX_OFFSET, min_coverage=0.95):
    """One year for all regions of a country so shares are comparable: nearest to ref among years in which at
    least min_coverage of the best-covered year's regions have a value."""
    n = obs.dropna(subset=["value"]).groupby("year")["region_id"].nunique()
    n = n[n >= min_coverage * n.max()] if len(n) else n
    return nearest_year(n.index, ref, max_offset)


def _nearest_per_region(obs, ref, max_offset, earlier=True):
    """Per region the observation at ref, else the closest earlier year within max_offset (any year if earlier=False)."""
    obs = obs.dropna(subset=["value"]).assign(d=lambda d: (ref - d["year"]).abs() if not earlier else ref - d["year"])
    obs = obs[(obs["d"] >= 0) & (obs["d"] <= max_offset)] if earlier else obs
    return obs.sort_values(["region_id", "d", "year"], ascending=[True, True, False]).drop_duplicates("region_id").set_index("region_id")


def national_value(obs, variable, ref=REF_YEAR, max_offset=MAX_OFFSET):
    """(value, year, source_id, note) of a country's national series nearest to ref, or None."""
    o = _nearest_per_region(obs[obs["variable"] == variable], ref, max_offset)
    return None if o.empty else tuple(o.iloc[0][["value", "year", "source_id", "note"]])


def national_population(obs, ref=REF_YEAR, max_offset=MAX_OFFSET):
    """Per country id (`ISO3:<iso3>`) the national population nearest to ref: value, year, source_id."""
    return _nearest_per_region(obs[obs["variable"] == "pop"], ref, max_offset)[["value", "year", "source_id"]]


def same_year_pop(tab, national_obs):
    """National population in the year most of the table's regional populations refer to (None if unknown), so that
    regional and national totals are compared at the same date."""
    years = tab["pop_year"].dropna()
    return None if years.empty else national_value(national_obs, "pop", int(years.mode().iloc[0]), 0)


def split_country(obs, national_gdp, ref=REF_YEAR, max_offset=MAX_OFFSET):
    """Indicators for the regions of ONE country. obs: observations of its regions (gdp, gdp_extra, pop, area_km2).
    GDP shares come from a single shared year; each region's share of (regional sum + extra-regio) times the national
    total gives gdp_usd. Returns (table indexed by region_id, unallocated_usd)."""
    ids = obs.loc[obs["variable"] != "gdp_extra", "region_id"].unique()
    out = pd.DataFrame(index=pd.Index(ids, name="region_id"))
    gdp = obs[obs["variable"] == "gdp"]
    y = shared_year(gdp, ref, max_offset)
    if y is not None:
        g = gdp[gdp["year"] == y].drop_duplicates("region_id").set_index("region_id")
        extra = obs[(obs["variable"] == "gdp_extra") & (obs["year"] == y)]["value"].sum()
        share = g["value"] / (g["value"].sum() + extra)
        out["gdp_share"], out["gdp_year"], out["gdp_source"] = share, y, g["source_id"]
        out["gdp_usd"] = out["gdp_share"] * national_gdp
        out["_gdp_note"] = g["note"]
        unallocated = extra / (g["value"].sum() + extra) * national_gdp
    else:
        unallocated = 0.0
    for var, col in (("pop", "pop"), ("area_km2", "area_km2")):
        v = obs[obs["variable"] == var]
        o = _nearest_per_region(v, ref, max_offset, earlier=var != "area_km2")
        waived = v[v["note"].fillna("").str.contains("pop_year_offset")]  # window waiver (pop_year_waivers.csv)
        if var == "pop" and len(waived):
            o = pd.concat([o, _nearest_per_region(waived, ref, 99).drop(o.index, errors="ignore")])
        out[col], out[f"{var.split('_')[0]}_year"], out[f"{var.split('_')[0]}_source"] = o["value"], o["year"], o["source_id"]
        out[f"_{var}_note"] = o["note"]
    return out, unallocated


def ratios(df: pd.DataFrame) -> pd.DataFrame:
    pos = lambda s: s.where(s > 0)
    return df.assign(gdp_per_km2=df["gdp_usd"] / pos(df["area_km2"]), gdp_per_capita=df["gdp_usd"] / pos(df["pop"]),
                     pop_density=df["pop"] / pos(df["area_km2"]))


def derive(df: pd.DataFrame, ref=REF_YEAR) -> pd.DataFrame:
    """Ratios and flags on a table with gdp_usd, pop, area_km2 and *_year columns."""
    df = ratios(df)
    flags = []
    for _, r in df.iterrows():
        f = set()
        for part, key in (("gdp", "gdp_year"), ("pop", "pop_year")):
            if pd.notna(r.get(key)) and r[key] != ref:
                f.add(f"{part}_year_offset")
        for k in ("_gdp_note", "_pop_note", "_area_km2_note"):
            f |= {n for n in str(r.get(k) or "").split(";") if n and n != "nan"}
        flags.append(sorted(f))
    df["flags"] = flags
    return df.drop(columns=[c for c in df if c.startswith("_")])


def scale_population(top: pd.DataFrame, ind: pd.DataFrame, parent: pd.Series, national: pd.Series):
    """Regional population scaled top-down to the national total, flag `pop_scaled`, raw value in `pop_raw`.
    `top`: the regions chosen before second subdivisions (iso3, pop; their parents included); `ind`: the finest rows
    after them; `parent`: child id -> id of the chosen region it replaces; `national`: `ISO3:<iso3>` -> population.
    A country with split regions has them multiplied by national / sum when all of them have a population; a refined
    region's children by its (scaled) population / their sum when all have one. Incomplete sets stay as they are.
    Returns (ind, the refined regions' scaled `pop` and `pop_raw`, log with one row per set: factor or why not)."""
    pop, out, log = top["pop"].copy(), ind.copy(), []

    def factor(name, kind, have, target):
        row = {"set": name, "kind": kind, "n": len(have), "missing": int(have.isna().sum()), "raw_sum": have.sum(), "target": target}
        ok = row["missing"] == 0 and target > 0
        log.append({**row, "factor": target / have.sum() if ok else np.nan})
        return log[-1]["factor"] if ok else None

    for iso3, g in top.groupby("iso3"):
        if len(g) > 1:
            f = factor(iso3, "country", g["pop"], national.get(f"ISO3:{iso3}", np.nan))
            pop[g.index] = g["pop"] * f if f else g["pop"]
    for pid, kids in parent.groupby(parent):
        f = factor(pid, "children", ind.loc[kids.index, "pop"], pop[pid])
        out.loc[kids.index, "pop"] = ind.loc[kids.index, "pop"] * f if f else ind.loc[kids.index, "pop"]
    direct = out.index.intersection(top.index)
    out.loc[direct, "pop"] = pop[direct]
    changed = out["pop"].notna() & ~np.isclose(out["pop"], ind["pop"], rtol=SCALE_TOL, atol=0)
    out["pop_raw"] = ind["pop"].where(changed)
    out["flags"] = [sorted({*f, "pop_scaled"}) if c else f for f, c in zip(ind["flags"], changed)]
    out.loc[changed, ["gdp_per_capita", "pop_density"]] = ratios(out.loc[changed])[["gdp_per_capita", "pop_density"]]
    refined = pop.index.intersection(parent.unique())
    return out, pd.DataFrame({"pop": pop[refined], "pop_raw": top["pop"][refined].where(~np.isclose(pop[refined], top["pop"][refined], rtol=SCALE_TOL, atol=0))}), pd.DataFrame(log)


def compute(levels: pd.Series, obs: pd.DataFrame, national: pd.DataFrame, ref=REF_YEAR):
    """All countries at once. levels: region_id -> level of the chosen regions. Returns (indicators, unallocated by iso3).
    Each country's regions are scaled to its national GDP (`national` observations at ref, else the latest earlier year,
    flagged `national_year_offset` on split countries)."""
    parts, unalloc, stale = [], {}, set()
    for iso3, o in obs.groupby("iso3"):
        gdp = national_value(national[national["iso3"] == iso3], "gdp", ref)
        tab, un = split_country(o, gdp[0] if gdp else np.nan, ref)
        tab.insert(0, "iso3", iso3)
        parts.append(tab)
        unalloc[iso3] = un
        if gdp and gdp[1] != ref:
            stale.add(iso3)
    out = derive(pd.concat(parts), ref)
    out["level"] = levels.reindex(out.index)
    add = lambda r: (["whole_country"] if r["level"] == "country" else []) + (["national_year_offset"] if r["iso3"] in stale and r["level"] != "country" else [])
    out["flags"] = [sorted(f + add(r)) for f, (_, r) in zip(out["flags"], out.iterrows())]
    out.insert(1, "year", ref)
    return out.drop(columns="level"), pd.Series(unalloc, name="unallocated_gdp_usd")
