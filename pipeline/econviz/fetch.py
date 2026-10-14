"""Idempotent downloads into data/raw/<source_id>/ with a checksum sidecar. Raw files are never edited."""
import csv
import hashlib
import json
import re
import time
from datetime import date
from functools import cache
from pathlib import Path

import requests

from .paths import RAW, REFERENCE


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@cache
def pins() -> dict[str, str]:
    """Wikipedia API url -> pinned revision id (`data/reference/wiki_pins.csv`): a fresh build reads the same revisions."""
    with open(REFERENCE / "wiki_pins.csv", encoding="utf-8") as f:
        return {row["url"]: row["revid"] for row in csv.DictReader(f)}


def pinned(url: str) -> str:
    """`url` asking for the pinned revision instead of the page's current one (unpinned urls unchanged)."""
    rev = pins().get(url)
    return url if rev is None else re.sub(r"page=[^&]*", f"oldid={rev}", url)


def get(source_id: str, url: str, name: str, *, headers: dict | None = None, refresh: bool = False) -> Path:
    """`url` is also the cache key; a pinned Wikipedia url is fetched at its pinned revision (`pinned`)."""
    path, side = RAW / source_id / name, RAW / source_id / (name + ".json")
    if path.exists() and side.exists() and not refresh:
        meta = json.loads(side.read_text())
        if meta["sha256"] == sha256(path) and meta["url"] == url:
            return path
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):  # server errors, rate limits and dropped connections are retried
        try:
            r = requests.get(pinned(url), headers={"User-Agent": "econviz/0.1 (economic-map, https://github.com/ya0/economic-map)", **(headers or {})}, timeout=600)
            if r.status_code < 500 and r.status_code != 429:
                break
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError):
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)
    r.raise_for_status()
    path.write_bytes(r.content)
    side.write_text(json.dumps({"url": url, "retrieved_on": date.today().isoformat(),
                                "sha256": sha256(path), "bytes": len(r.content)}, indent=1))
    return path


def retrieved_on(source_id: str) -> str:
    sidecars = [p for p in (RAW / source_id).glob("*.json") if p.with_suffix("").exists()]  # data files may be .json too
    dates = [json.loads(p.read_text())["retrieved_on"] for p in sidecars]
    return max(dates, default="")
