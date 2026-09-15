"""Load and lightly validate the two input files: raw ticket export and
Seller -> Sales Person mapping. Accepts .csv or .xlsx for either file.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

from config import (
    COL_CREATED, COL_INITIAL_RESPONSE, COL_RESOLVED, COL_SELLER_ID,
    MAP_SALES_PERSON, MAP_SELLER_ID, MAP_SELLER_NAME,
    REQUIRED_RAW_COLUMNS, RECOMMENDED_RAW_COLUMNS,
)

DATETIME_COLUMNS = [COL_CREATED, "Due by Time", COL_RESOLVED, "Closed time",
                    "Last update time", COL_INITIAL_RESPONSE]


@dataclass
class LoadResult:
    raw: pd.DataFrame
    mapping: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def _read_any(source, **kwargs) -> pd.DataFrame:
    """Read a CSV or XLSX from a path, UploadedFile, or bytes buffer."""
    name = getattr(source, "name", None) or str(source)
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    if str(name).lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(source, **kwargs)
    return pd.read_csv(source, low_memory=False, **kwargs)


def load_raw_tickets(source) -> pd.DataFrame:
    df = _read_any(source)
    df.columns = [str(c).strip() for c in df.columns]

    missing_required = [c for c in REQUIRED_RAW_COLUMNS if c not in df.columns]
    if missing_required:
        raise ValueError(
            "Raw ticket file is missing required column(s): " + ", ".join(missing_required)
            + ". Expected a Freshdesk-style export with headers matching the reference workbook."
        )
    for c in RECOMMENDED_RAW_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA

    for c in DATETIME_COLUMNS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")

    return df


def load_seller_mapping(source) -> pd.DataFrame:
    df = _read_any(source)
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in (MAP_SELLER_ID, MAP_SALES_PERSON) if c not in df.columns]
    if missing:
        raise ValueError(
            "Sales mapping file is missing required column(s): " + ", ".join(missing)
        )
    if MAP_SELLER_NAME not in df.columns:
        df[MAP_SELLER_NAME] = pd.NA

    df["_seller_id_num"] = pd.to_numeric(df[MAP_SELLER_ID], errors="coerce")
    df[MAP_SELLER_NAME] = df[MAP_SELLER_NAME].astype("string").str.strip()

    def _norm_name(x):
        if not isinstance(x, str) or not x.strip() or x.strip().lower() == "nan":
            return None
        return " ".join(w.capitalize() for w in x.strip().split())

    df[MAP_SALES_PERSON] = df[MAP_SALES_PERSON].astype("string").str.strip()
    df["_sales_person_norm"] = df[MAP_SALES_PERSON].apply(_norm_name)

    total_rows = len(df)
    df = df.dropna(subset=["_seller_id_num"]).drop_duplicates("_seller_id_num", keep="first").reset_index(drop=True)
    dedup_meta = {"raw_rows": total_rows, "unique_sellers": len(df)}
    df.attrs["dedup_meta"] = dedup_meta
    return df


def load_all(raw_source, mapping_source) -> LoadResult:
    warnings: list[str] = []
    raw = load_raw_tickets(raw_source)
    mapping = load_seller_mapping(mapping_source)

    dup_ids = raw[raw.columns[0]].duplicated().sum() if len(raw.columns) else 0
    if dup_ids:
        warnings.append(f"{dup_ids} duplicate Ticket ID(s) found in the raw file - see Data Quality tab.")

    return LoadResult(raw=raw, mapping=mapping, warnings=warnings)
