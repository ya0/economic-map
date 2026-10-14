import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("ECONVIZ_DATA", ROOT / "data"))
RAW, INTERIM, PROCESSED, REFERENCE = DATA / "raw", DATA / "interim", DATA / "processed", DATA / "reference"
WEB_PUBLIC = ROOT / "web" / "public"
REF_YEAR = int(os.environ.get("ECONVIZ_REF_YEAR", 2024))  # the one reference year config; shares and totals refer to it
