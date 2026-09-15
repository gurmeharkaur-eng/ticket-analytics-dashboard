"""Entry point: `streamlit run app.py`.

Upload today's raw ticket export (required) and the Seller -> Sales Person
mapping (required the first time; re-upload only when it changes) in the
sidebar. Everything downstream - every KPI, table, and the Executive Summary -
recalculates automatically. Nothing here hard-codes a filename, date, row
count, or person.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from config import APP_TITLE
from src import dashboard
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
def _cached_load_and_compute(raw_bytes: bytes, raw_name: str, map_bytes: bytes, map_name: str):
    import io
    raw_buf = io.BytesIO(raw_bytes)
    raw_buf.name = raw_name
    map_buf = io.BytesIO(map_bytes)
    map_buf.name = map_name
    result = load_all(raw_buf, map_buf)
    computed = compute(result.raw, result.mapping)
    reps = sorted(result.mapping["_sales_person_norm"].dropna().unique().tolist())
    return result, computed, reps


def _read_bytes(source) -> bytes:
    if hasattr(source, "getvalue"):
        return source.getvalue()
    return Path(source).read_bytes()


with st.sidebar:
    st.header("Data Upload")
    raw_file = st.file_uploader(
        "Raw Ticket Export (required)", type=["csv", "xlsx"],
        help="Daily ticket export. Replace this any day with a fresh file - the whole dashboard recalculates.",
    )
    map_file = st.file_uploader(
        "Sales Person Mapping (required)", type=["csv", "xlsx"],
        help="Seller ID -> Seller Name -> Sales Person. Re-upload only when the mapping changes.",
    )
    st.caption("Replace either file to recalculate the entire dashboard from that file.")

raw_source = raw_file or _default_or_none(SAMPLE_DIR, "raw_tickets.csv")
map_source = map_file or _default_or_none(SAMPLE_DIR, "seller_mapping.csv")

if raw_source is None or map_source is None:
    st.title(APP_TITLE)
    st.info("Upload the Raw Ticket Export and the Sales Person Mapping file in the sidebar to get started.")
    st.stop()

raw_name = getattr(raw_source, "name", str(raw_source))
map_name = getattr(map_source, "name", str(map_source))

with st.spinner("Reading, validating, and calculating..."):
    try:
        load_result, computed_data, reps = _cached_load_and_compute(
            _read_bytes(raw_source), raw_name, _read_bytes(map_source), map_name
        )
    except Exception as e:
        st.error(f"Could not process the uploaded files: {e}")
        st.stop()

c = computed_data.df
as_of = computed_data.as_of

dashboard.render_header(c, as_of)
for w in load_result.warnings:
    st.warning(w)

tabs = st.tabs([
    "Executive Summary", "Overall Analysis", "Performance Drivers & Actions",
    "Backlog & Ageing", "TAT Diagnostics", "Data Quality", "Logic Validation", "Detailed Data",
])
with tabs[0]:
    dashboard.render_executive_summary(c, reps)
with tabs[1]:
    dashboard.render_overall_analysis(c, as_of)
with tabs[2]:
    dashboard.render_performance_drivers_actions(c, load_result.mapping, reps)
with tabs[3]:
    dashboard.render_backlog_ageing(c)
with tabs[4]:
    dashboard.render_tat_diagnostics(c, reps)
with tabs[5]:
    dashboard.render_data_quality(c, load_result.raw, load_result.mapping, reps)
with tabs[6]:
    dashboard.render_logic_validation()
with tabs[7]:
    dashboard.render_detailed_data(c)
