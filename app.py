"""Entry point: `streamlit run app.py`.

One consolidated report, no tabs. Upload today's raw ticket export (required)
and the Seller -> Sales Person mapping (required) in the sidebar; the Team
Level Data and Team Lists files are optional but sharpen seller ownership
(Sales Person + Team) considerably where they cover a seller. Everything
downstream - every KPI, table, and the Executive Summary - recalculates
automatically. Nothing here hard-codes a filename, date, row count, or
person.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from config import APP_TITLE
from src import report
from src.calculations import compute
from src.ingestion import load_all
from src.styling import inject_custom_css

SAMPLE_DIR = Path(__file__).parent / "sample_data"

st.set_page_config(page_title=APP_TITLE, layout="wide")
inject_custom_css()


def _default_or_none(folder: Path, filename: str):
    p = folder / filename
    return p if p.exists() else None


@st.cache_data(show_spinner=False)
def _cached_load_and_compute(raw_bytes, raw_name, map_bytes, map_name,
                              team_data_bytes, team_data_name, team_lists_bytes, team_lists_name):
    import io
    raw_buf = io.BytesIO(raw_bytes)
    raw_buf.name = raw_name
    map_buf = io.BytesIO(map_bytes)
    map_buf.name = map_name
    team_data_buf = None
    if team_data_bytes is not None:
        team_data_buf = io.BytesIO(team_data_bytes)
        team_data_buf.name = team_data_name
    team_lists_buf = None
    if team_lists_bytes is not None:
        team_lists_buf = io.BytesIO(team_lists_bytes)
        team_lists_buf.name = team_lists_name

    result = load_all(raw_buf, map_buf, team_data_buf, team_lists_buf)
    computed = compute(result.raw, result.mapping, result.team_data, result.team_lists)

    reps = set(result.mapping["_sales_person_norm"].dropna().unique().tolist())
    if result.team_data is not None:
        reps |= set(result.team_data["_sales_person_norm"].dropna().unique().tolist())
    if result.team_lists is not None:
        reps |= set(result.team_lists["_sales_person_norm"].dropna().unique().tolist())
    reps = sorted(reps)

    return result, computed, reps


def _read_bytes(source):
    if source is None:
        return None
    if hasattr(source, "getvalue"):
        return source.getvalue()
    return Path(source).read_bytes()


with st.sidebar:
    st.header("Data Upload")
    raw_file = st.file_uploader(
        "Raw Ticket Export (required)", type=["csv", "xlsx"],
        help="Daily ticket export. Replace this any day with a fresh file - the whole report recalculates.",
    )
    map_file = st.file_uploader(
        "Sales Person Mapping (required)", type=["csv", "xlsx"],
        help="Seller ID -> Seller Name -> Sales Person. Re-upload only when the mapping changes.",
    )
    team_data_file = st.file_uploader(
        "Team Level Data (optional)", type=["csv", "xlsx"],
        help="seller Id -> Sales Person -> Team -> Owner/KAM Person. More complete than the plain mapping "
             "file - wins over it wherever it covers a Seller ID.",
    )
    team_lists_file = st.file_uploader(
        "Team Lists (optional)", type=["csv", "xlsx"],
        help="Sales Person -> Team roster. Fills in Team for a Sales Person that Team Level Data names but "
             "doesn't tag with a Team.",
    )
    st.caption("Replace any file to recalculate the entire report from that file.")

raw_source = raw_file or _default_or_none(SAMPLE_DIR, "raw_tickets.csv")
map_source = map_file or _default_or_none(SAMPLE_DIR, "seller_mapping.csv")
team_data_source = team_data_file or _default_or_none(SAMPLE_DIR, "team_level_data.xlsx")
team_lists_source = team_lists_file or _default_or_none(SAMPLE_DIR, "team_lists.xlsx")

if raw_source is None or map_source is None:
    st.title(APP_TITLE)
    st.info("Upload the Raw Ticket Export and the Sales Person Mapping file in the sidebar to get started.")
    st.stop()

raw_name = getattr(raw_source, "name", str(raw_source))
map_name = getattr(map_source, "name", str(map_source))
team_data_name = getattr(team_data_source, "name", str(team_data_source)) if team_data_source is not None else None
team_lists_name = getattr(team_lists_source, "name", str(team_lists_source)) if team_lists_source is not None else None

with st.spinner("Reading, validating, and calculating..."):
    try:
        load_result, computed_data, reps = _cached_load_and_compute(
            _read_bytes(raw_source), raw_name, _read_bytes(map_source), map_name,
            _read_bytes(team_data_source), team_data_name, _read_bytes(team_lists_source), team_lists_name,
        )
    except Exception as e:
        st.error(f"Could not process the uploaded files: {e}")
        st.stop()

for w in load_result.warnings:
    st.warning(w)

report.render(
    computed_data.df, computed_data.as_of, reps, load_result.mapping, load_result.raw,
    load_result.team_data, load_result.team_lists,
)
