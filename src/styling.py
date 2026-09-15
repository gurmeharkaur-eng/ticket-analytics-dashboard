"""Custom CSS and small rendering helpers for a compact, founder-friendly,
data-first layout: small consistent fonts, dense tables, compact KPI cards,
minimal color, horizontal tab navigation. No large fonts, no big cards, no
decorative charts.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

CSS = """
<style>
html, body, [class*="css"]  { font-size: 13px; }
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }
h1 { font-size: 1.35rem !important; font-weight: 700; margin-bottom: 0.1rem; }
h2 { font-size: 1.05rem !important; font-weight: 700; margin-top: 1.1rem; margin-bottom: 0.3rem; }
h3, .section-sub { font-size: 0.82rem !important; font-weight: 600; color: #6B7280;
    text-transform: none; margin-top: 0.9rem; margin-bottom: 0.35rem; }
p, .stMarkdown, .stCaption { font-size: 0.82rem; }
.stTabs [data-baseweb="tab-list"] { gap: 2px; }
.stTabs [data-baseweb="tab"] { height: 34px; padding: 4px 14px; font-size: 0.8rem; font-weight: 600; }
.stDataFrame, .stTable { font-size: 0.78rem !important; }
div[data-testid="stMetricValue"] { font-size: 1.15rem; }
div[data-testid="stMetricLabel"] { font-size: 0.7rem; color: #6B7280; }

.kpi-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 6px; }
.kpi-card { background: #F3F4F6; border: 1px solid #E5E7EB; border-radius: 6px;
    padding: 7px 12px; min-width: 128px; flex: 1 1 128px; }
.kpi-label { font-size: 0.66rem; font-weight: 700; color: #6B7280; letter-spacing: .02em;
    text-transform: uppercase; margin-bottom: 2px; }
.kpi-value { font-size: 1.25rem; font-weight: 700; color: #111827; line-height: 1.15; }
.kpi-def { font-size: 0.66rem; color: #6B7280; margin-top: 3px; line-height: 1.25; }

.status-badge { font-weight:700; padding:2px 8px; border-radius:4px; font-size:0.7rem; white-space:nowrap; }
.status-Critical { background:#FEE2E2; color:#991B1B; }
.status-Action-Required { background:#FFEDD5; color:#9A3412; }
.status-Watch { background:#FEF3C7; color:#92400E; }
.status-On-Track { background:#DCFCE7; color:#166534; }
.status-Low-Sample-Validate { background:#F3F4F6; color:#4B5563; }
.status-No-Baseline-Available { background:#F3F4F6; color:#4B5563; }

.note { font-size: 0.75rem; color: #6B7280; font-style: italic; margin: 2px 0 8px 0; }
.finding { font-size: 0.85rem; padding: 3px 0; }
.priority-High { background:#FEE2E2; font-weight:700; padding:2px 8px; border-radius:4px; }
.priority-Medium { background:#FEF3C7; font-weight:700; padding:2px 8px; border-radius:4px; }
.priority-Low { background:#DCFCE7; font-weight:700; padding:2px 8px; border-radius:4px; }
.badge { font-weight:700; padding:2px 9px; border-radius:4px; font-size:0.74rem; white-space:nowrap; }
.badge-high { background:#FEE2E2; color:#991B1B; }
.badge-medium { background:#FEF3C7; color:#92400E; }
.badge-opportunity { background:#DCFCE7; color:#166534; }

.kf-card { background:#FFFFFF; border:1px solid #E5E7EB; border-left:4px solid #9CA3AF;
    border-radius:6px; padding:8px 12px; margin-bottom:6px; }
.kf-card.positive { border-left-color:#16A34A; }
.kf-card.negative { border-left-color:#DC2626; }
.kf-card.opportunity { border-left-color:#2563EB; }
.kf-label { font-size:0.66rem; font-weight:700; color:#6B7280; text-transform:uppercase; letter-spacing:.02em; }
.kf-text { font-size:0.85rem; color:#111827; margin-top:2px; }

.rank-list { display: flex; flex-direction: column; gap: 5px; margin-bottom: 10px; }
.rank-row { display: flex; align-items: center; gap: 8px; font-size: 0.78rem; }
.rank-label { width: 200px; flex-shrink: 0; color: #111827; font-weight: 600; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
.rank-track { flex: 1 1 auto; background: #F3F4F6; border-radius: 3px; height: 14px; overflow: hidden; }
.rank-fill { height: 100%; border-radius: 3px; }
.rank-value { width: 130px; flex-shrink: 0; text-align: right; color: #374151;
    font-variant-numeric: tabular-nums; white-space: nowrap; }

.move-up { color: #166534; font-weight: 700; }
.move-down { color: #991B1B; font-weight: 700; }
.move-flat { color: #6B7280; }
</style>
"""

PRIORITY_BADGE = {
    "High Priority": ("badge-high", "\U0001F534"),
    "Medium Priority": ("badge-medium", "\U0001F7E1"),
    "Opportunity": ("badge-opportunity", "\U0001F7E2"),
}


def priority_badge(priority: str) -> str:
    cls, dot = PRIORITY_BADGE.get(priority, ("badge-medium", ""))
    return f'<span class="badge {cls}">{dot} {priority}</span>'


def status_badge(label: str) -> str:
    """Small colored label for the wireframe's status vocabulary (Critical
    / Action Required / Watch / On Track / Low Sample - Validate / No
    Baseline Available) - a restrained text badge, not a decorative icon."""
    cls = "status-" + label.replace(" ", "-").replace("---", "-")
    return f'<span class="status-badge {cls}">{label}</span>'


def inject_custom_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def kpi_row_with_defs(items: list[tuple[str, str, str]]) -> None:
    """Like kpi_row, but each card also carries a one-line plain-language
    definition underneath the value - used for the First Response /
    Resolution TAT sections, where a bare number invites misreading.
    items: list of (label, formatted_value, definition)."""
    cards = "".join(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-def">{definition}</div></div>'
        for label, value, definition in items
    )
    st.markdown(f'<div class="kpi-row">{cards}</div>', unsafe_allow_html=True)


def kpi_row(items: list[tuple[str, str]]) -> None:
    """items: list of (label, formatted_value)."""
    cards = "".join(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div></div>'
        for label, value in items
    )
    st.markdown(f'<div class="kpi-row">{cards}</div>', unsafe_allow_html=True)


def section(title: str, note: str | None = None) -> None:
    st.markdown(f"### {title}")
    if note:
        st.markdown(f'<div class="note">{note}</div>', unsafe_allow_html=True)


def fmt_int(x) -> str:
    if pd.isna(x):
        return "-"
    return f"{int(round(x)):,}"


def fmt_pct(x, decimals: int = 1) -> str:
    if pd.isna(x):
        return "-"
    return f"{x * 100:.{decimals}f}%"


def fmt_hrs(x, decimals: int = 1) -> str:
    if pd.isna(x):
        return "-"
    return f"{x:.{decimals}f}"


PCT_COLS_HINT = ("%", "pct", "Pct")


def show_table(df: pd.DataFrame, pct_cols: list[str] | None = None, int_cols: list[str] | None = None,
               dec_cols: list[str] | None = None, height: int | None = None, hide_index: bool = True,
               row_colors: "pd.Series | None" = None) -> None:
    """Compact, formatted dataframe display. `row_colors`, if given, is a
    Series aligned to df's index holding a hex color (or falsy for no
    color) - the whole row is tinted so problem rows are scannable without
    filtering them out of view.

    Columns are pre-formatted to plain strings here (NaN -> "-") rather
    than left as numbers with a pandas Styler `.format(..., na_rep="-")` -
    confirmed the Styler itself renders NaN as "-" correctly, but
    Streamlit's dataframe grid does not reliably respect a Styler's
    `na_rep` for a NaN cell in a column that also has a `.format()` spec,
    occasionally showing the literal string "None" instead. Pre-formatting
    sidesteps that bridge entirely - the same reliable approach already
    used for the MIS matrix tables (see trend_matrix.build_matrix)."""
    pct_cols = pct_cols or [c for c in df.columns if any(h in c for h in PCT_COLS_HINT)]
    int_cols = int_cols or []
    dec_cols = dec_cols or []
    display = df.copy()
    for c in pct_cols:
        if c in display.columns:
            display[c] = display[c].map(lambda x: "-" if pd.isna(x) else f"{x * 100:.1f}%")
    for c in int_cols:
        if c in display.columns:
            display[c] = display[c].map(lambda x: "-" if pd.isna(x) else f"{x:,.0f}")
    for c in dec_cols:
        if c in display.columns:
            display[c] = display[c].map(lambda x: "-" if pd.isna(x) else f"{x:.1f}")
    styler = display.style
    if row_colors is not None:
        def _row_style(row):
            color = row_colors.get(row.name)
            return [f"background-color: {color}" if color else "" for _ in row]
        styler = styler.apply(_row_style, axis=1)
    kwargs = {"height": height} if height is not None else {}
    st.dataframe(styler, hide_index=hide_index, use_container_width=True, **kwargs)


def show_matrix(data: pd.DataFrame, colors: pd.DataFrame, height: int | None = None) -> None:
    """Renders a pre-formatted (text-valued) matrix with a same-shape
    DataFrame of CSS background-color strings applied per cell - the
    MIS-style time-period x metric/segment tables in trend_matrix.py.
    Streamlit's dataframe grid only renders cell-level Styler colors, not
    index-level ones, so the "Segment" row label is a real data column
    (see trend_matrix.build_matrix), not the DataFrame index."""
    styler = data.style.apply(lambda _: colors, axis=None)
    kwargs = {"height": height} if height is not None else {}
    st.dataframe(styler, hide_index=True, use_container_width=True, **kwargs)


def bar_ranking(rows: list[dict]) -> None:
    """Compact horizontal bar-list ranking - a minimal, scannable
    alternative to a full data table for a "best/worst performing X" view.
    Each row: {"label": str, "value_text": str, "pct": float in 0..1 (bar
    fill width), "color": hex string}."""
    html = ['<div class="rank-list">']
    for r in rows:
        pct = max(0.0, min(1.0, r["pct"])) * 100
        html.append(
            f'<div class="rank-row">'
            f'<div class="rank-label">{r["label"]}</div>'
            f'<div class="rank-track"><div class="rank-fill" '
            f'style="width:{pct:.1f}%;background:{r["color"]}"></div></div>'
            f'<div class="rank-value">{r["value_text"]}</div>'
            f'</div>'
        )
    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


def movement_badge(delta: float, higher_is_better: bool = True, min_meaningful: float = 0.005) -> str:
    """A small colored movement label for 'this week vs last week'-style
    deltas (e.g. Resolution Rate or Backlog %, both in fraction form). The
    ARROW direction always reflects which way the metric actually moved;
    the COLOR reflects whether that move is good or bad, which is why
    `higher_is_better` is separate from the arrow - a rising Backlog % is
    an up-arrow (it did go up) colored red (that's bad), not a down-arrow.
    Anything under `min_meaningful` reads as flat/gray rather than a
    false-precision +0.3pp in either color."""
    if pd.isna(delta) or abs(delta) < min_meaningful:
        return '<span class="move-flat">flat</span>'
    arrow = "&#9650;" if delta > 0 else "&#9660;"
    improved = (delta > 0) == higher_is_better
    cls = "move-up" if improved else "move-down"
    sign = "+" if delta > 0 else ""
    return f'<span class="{cls}">{arrow} {sign}{delta * 100:.1f}pp</span>'


def color_legend() -> None:
    st.markdown(
        '<div style="font-size:0.75rem;display:flex;gap:14px;align-items:center;margin:2px 0 8px 0">'
        '<span><span style="background:#FCA5A5;padding:1px 8px;border-radius:3px">&nbsp;</span> Critical</span>'
        '<span><span style="background:#FDE68A;padding:1px 8px;border-radius:3px">&nbsp;</span> Attention / Watch</span>'
        '<span><span style="background:#86EFAC;padding:1px 8px;border-radius:3px">&nbsp;</span> Healthy / Outperforming</span>'
        '<span style="color:#6B7280">Uncolored = near benchmark or not enough data (shown as "-")</span>'
        '</div>', unsafe_allow_html=True,
    )
