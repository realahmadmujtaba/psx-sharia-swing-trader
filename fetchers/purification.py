import argparse
import io
import re
from pathlib import Path

import pandas as pd
import pypdf
import requests

RATIOS_PATH = Path(__file__).resolve().parent.parent / "data" / "purification_ratios.csv"
COLUMNS = ["symbol", "non_compliant_income_pct", "shariah_status", "accounts_as_of", "source"]

_ROW_START = re.compile(r"^\s*\d+\s+[A-Z][A-Z0-9]*\s")
_ROW = re.compile(
    r"^\s*\d+\s+(?P<symbol>[A-Z][A-Z0-9]*)\s+.*?\s(?P<ratio>N/A|\d+(?:\.\d+)?%)\s+(?P<status>Compliant|Non-Compliant)\b",
    re.S,
)


def parse_pdf_text(text: str) -> pd.DataFrame:
    chunks: list[str] = []
    for line in text.splitlines():
        if _ROW_START.match(line):
            chunks.append(line)
        elif chunks and not _ROW.match(chunks[-1]):
            chunks[-1] += " " + line

    rows = []
    for chunk in chunks:
        match = _ROW.match(chunk)
        if not match:
            continue
        ratio = match["ratio"]
        rows.append(
            {
                "symbol": match["symbol"],
                # N/A = Islamic bank/modaraba/fund: no non-compliant income by construction.
                "non_compliant_income_pct": 0.0 if ratio == "N/A" else float(ratio.rstrip("%")),
                "shariah_status": match["status"],
            }
        )
    return pd.DataFrame(rows).drop_duplicates("symbol", keep="last")


def build(pdf_source: str, accounts_as_of: str, source_label: str) -> pd.DataFrame:
    if pdf_source.startswith("http"):
        response = requests.get(pdf_source, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        response.raise_for_status()
        reader = pypdf.PdfReader(io.BytesIO(response.content))
    else:
        reader = pypdf.PdfReader(pdf_source)

    df = parse_pdf_text("\n".join(page.extract_text() or "" for page in reader.pages))
    if df.empty:
        raise RuntimeError("No company rows found; the PDF layout may have changed or it is a scanned image.")
    df["accounts_as_of"] = accounts_as_of
    df["source"] = source_label
    RATIOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    df[COLUMNS].sort_values("symbol").to_csv(RATIOS_PATH, index=False)
    return df


def load_ratios() -> dict[str, dict]:
    if not RATIOS_PATH.exists():
        return {}
    df = pd.read_csv(RATIOS_PATH)
    return df.set_index("symbol").to_dict(orient="index")


def purification_amount(amount: float, ratio_pct: float) -> float:
    return round(max(amount, 0.0) * ratio_pct / 100, 2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rebuild data/purification_ratios.csv from Al-Meezan's ratio PDF")
    parser.add_argument("pdf", help="Path or URL of the 'complete ratios' recomposition PDF")
    parser.add_argument("--as-of", required=True, help="Accounts date the ratios are based on, e.g. 2025-12-31")
    parser.add_argument("--source", required=True, help="Human-readable source label")
    args = parser.parse_args()
    built = build(args.pdf, args.as_of, args.source)
    print(f"Wrote {len(built)} companies to {RATIOS_PATH}")
