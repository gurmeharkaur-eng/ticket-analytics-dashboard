"""The CRO -> HOD -> L1 leadership dashboard - a single consolidated page
(no tabs), driven by a Group/Type filter pair at the top. Group and Type are
the only analytical dimensions in the primary view: Sales Person / Seller-
level breakdowns were removed per the post-review redesign (kept only as
supplementary detail in the collapsed sections at the bottom, where they
still have standalone value but aren't part of the leadership narrative).

Filter scoping rule: the Group/Type picker narrows every section below it -
CRO KPIs, the HOD Group ranking, and the L1 Type ranking all recompute from
the currently filtered slice. What stays FIXED regardless of the filter is
the benchmark every segment is compared against (`bm_company`, computed from
the full unfiltered data) - so "RR vs Benchmark" always means the same thing
whether or not you've drilled in, instead of a filtered scope trivially
comparing itself to itself.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import (
    FR_BREACH_THRESHOLDS, RESOLUTION_BREACH_THRESHOLDS, TAT_BUCKETS, TAT_LOW_SAMPLE_THRESHOLD,
    TAT_MANAGEMENT_THRESHOLD_HOURS,
)
from src import aggregations as agg
from src import charts
from src import data_quality as dq
from src import performance as perf
from src import seller_analysis as sa
from src import tat_analysis as ta
from src import trend_matrix as tm
from src.logic_validation import LOGIC_VALIDATION_ROWS
from src.styling import (
    bar_ranking, color_legend, fmt_hrs, fmt_int, fmt_pct, kpi_row, kpi_row_with_defs,
    priority_badge, section, show_matrix, show_table, status_badge,
)

FLAG_COLOR = {"High Priority": tm.RED, "Medium Priority": tm.AMBER, "Opportunity": tm.GREEN}
AGED_BUCKETS_7PLUS = ("7-14 Days", "14-30 Days", ">30 Days")
RANK_COLS = [
    "Total Raised", "% of Total", "Open", "New", "Pending", "Re-Opened",
    "Total Backlog", "% Backlog", "Resolution Rate", "RR vs Benchmark (pp)",
    "Avg First Resp TAT", "Median First Resp TAT", "Avg Resolution TAT", "Median Resolution TAT",
    ">7 Days", ">14 Days", ">30 Days", "Flag",
]


def _reps(mapping: pd.DataFrame, team_data: pd.DataFrame | None, team_lists: pd.DataFrame | None) -> list[str]:
    reps = set(mapping["_sales_person_norm"].dropna().unique().tolist())
    if team_data is not None:
        reps |= set(team_data["_sales_person_norm"].dropna().unique().tolist())
    if team_lists is not None:
        reps |= set(team_lists["_sales_person_norm"].dropna().unique().tolist())
    return sorted(reps)


def _attention_html(df: pd.DataFrame, label_col: str, n: int = 3) -> str:
    """Top-N flagged (High/Medium Priority) segments by impact, as a small
    HTML list - the CRO-level 'which areas need attention' callout."""
    flagged = df[df["Flag"].isin(["High Priority", "Medium Priority"])] \
        .sort_values("Impact Score", ascending=False).head(n)
    if flagged.empty:
        return '<div class="note">No segment currently crosses the attention threshold.</div>'
    return "".join(
        f'<div class="finding">{priority_badge(row["Flag"])} <b>{row[label_col]}</b> - '
        f'{row["RR vs Benchmark (pp)"] * 100:+.1f}pp vs benchmark on {int(row["Total Raised"]):,} tickets</div>'
        for _, row in flagged.iterrows()
    )


def _best_worst_html(best: pd.DataFrame, worst: pd.DataFrame, label_col: str) -> None:
    bc1, bc2 = st.columns(2)
    with bc1:
        st.markdown(f'<div class="section-sub">Best-performing {label_col}s</div>', unsafe_allow_html=True)
        if best.empty:
            st.caption("Not enough data.")
        for _, row in best.iterrows():
            st.markdown(
                f'<div class="finding">\U0001F7E2 <b>{row[label_col]}</b> - {row["Resolution Rate"]:.1%} '
                f'({row["RR vs Benchmark (pp)"] * 100:+.1f}pp vs benchmark, {int(row["Total Raised"]):,} tickets)</div>',
                unsafe_allow_html=True)
    with bc2:
        st.markdown(f'<div class="section-sub">Worst-performing {label_col}s</div>', unsafe_allow_html=True)
        if worst.empty:
            st.caption("Not enough data.")
        for _, row in worst.iterrows():
            st.markdown(
                f'<div class="finding">\U0001F534 <b>{row[label_col]}</b> - {row["Resolution Rate"]:.1%} '
                f'({row["RR vs Benchmark (pp)"] * 100:+.1f}pp vs benchmark, {int(row["Total Raised"]):,} tickets)</div>',
                unsafe_allow_html=True)


def _ranking_table(c_f: pd.DataFrame, perf_df: pd.DataFrame, label_col: str) -> None:
    """Group/Type ranking table - Volume, status breakdown, Resolution Rate
    vs benchmark, Avg + Median TAT, and >7/14/30-day aged-backlog counts,
    every segment, row-colored by priority flag."""
    ageing = agg.ageing_breakdown_by_dim(c_f, label_col, perf_df[label_col].tolist())
    merged = perf_df.merge(ageing, on=label_col, how="left")
    for col in (">7 Days", ">14 Days", ">30 Days"):
        merged[col] = merged[col].fillna(0).astype(int)
    ranked = merged.sort_values("RR vs Benchmark (pp)", ascending=False)
    display = ranked[[label_col] + RANK_COLS]
    row_colors = ranked["Flag"].map(FLAG_COLOR)
    show_table(display, pct_cols=["% of Total", "% Backlog", "Resolution Rate", "RR vs Benchmark (pp)"],
               int_cols=["Total Raised", "Open", "New", "Pending", "Re-Opened", "Total Backlog",
                         ">7 Days", ">14 Days", ">30 Days"],
               dec_cols=["Avg First Resp TAT", "Median First Resp TAT", "Avg Resolution TAT", "Median Resolution TAT"],
               row_colors=row_colors, height=min(460, 38 * len(display) + 40))


def _tat_control_tables(c_f: pd.DataFrame, label_col: str, labels: list[str]) -> None:
    """First Response and Resolution TAT bucket control tables (count + %
    per bucket, plus a >72h escalation column on the Resolution side) - the
    'L1/L2 First Response / Resolution control table' from the wireframe."""
    st.markdown('<div class="section-sub">First Response TAT Control</div>', unsafe_allow_html=True)
    fr = agg.tat_bucket_pct_table(c_f, label_col, "FRTAT", "FRBucket", labels)
    fr_pct_cols = [f"{b} %" for b in TAT_BUCKETS]
    show_table(fr, pct_cols=fr_pct_cols, int_cols=["Valid Tickets"] + [f"{b} #" for b in TAT_BUCKETS],
               height=min(380, 38 * len(fr) + 40))

    st.markdown('<div class="section-sub">Resolution TAT Control</div>', unsafe_allow_html=True)
    res = agg.tat_bucket_pct_table(c_f, label_col, "RESTAT", "RESBucket", labels, extra_threshold_hours=72)
    res_pct_cols = [f"{b} %" for b in TAT_BUCKETS] + [">72h %"]
    show_table(res, pct_cols=res_pct_cols, int_cols=["Valid Tickets"] + [f"{b} #" for b in TAT_BUCKETS] + [">72h #"],
               height=min(380, 38 * len(res) + 40))


_L2_QUEUE_DESCRIPTIONS = {
    "Immediate Response Queue": "First Response TAT >24h and still unresolved - assign or escalate for first response.",
    "Ageing Queue": "Backlog aged >7 days - review status and next step.",
    "Resolution Escalation Queue": "Resolution TAT >72h - identify the blocker and escalate.",
    "Re-open Review": "Re-Opened / Reopened tickets - check whether closure was premature or the issue recurred.",
    "Classification Queue": "Unknown Type or missing Group - reclassify and assign the correct owner.",
}
_L2_TICKET_COLS = ["Ticket ID", "Group", "Type", "Status", "Created", "AgeDays", "FRTAT", "RESTAT", "SalesPerson", "Team"]


def _l2_action_queues(c_f: pd.DataFrame) -> None:
    """Five standing operational queues, each a live filter over the
    current selection - no Owner/Due-date columns invented, since there's
    no source data for who's assigned or when it's due; each queue is
    shown as a real, sorted ticket list with a live count."""
    status_norm = c_f["Status"].astype(str).str.upper().str.strip()
    queues = {
        "Immediate Response Queue": c_f[(c_f["FRTAT"] > 24) & (c_f["Backlog"] == 1)] \
            .sort_values("FRTAT", ascending=False),
        "Ageing Queue": c_f[(c_f["Backlog"] == 1) & (c_f["AgeDays"] > 7)].sort_values("AgeDays", ascending=False),
        "Resolution Escalation Queue": c_f[c_f["RESTAT"] > 72].sort_values("RESTAT", ascending=False),
        "Re-open Review": c_f[status_norm.isin(["RE-OPENED", "REOPENED"])],
        "Classification Queue": c_f[(c_f["Type"] == "Unknown") | (c_f["Group"] == "No Group")],
    }
    for name, qdf in queues.items():
        with st.expander(f"{name} — {len(qdf):,} tickets"):
            st.caption(_L2_QUEUE_DESCRIPTIONS[name])
            if qdf.empty:
                st.caption("No tickets currently in this queue.")
            else:
                show_table(qdf[_L2_TICKET_COLS].head(50), dec_cols=["AgeDays", "FRTAT", "RESTAT"],
                           height=min(380, 38 * min(len(qdf), 50) + 40))
                if len(qdf) > 50:
                    st.caption(f"Showing the 50 most urgent of {len(qdf):,} - see \"Detailed per-ticket data\" "
                               "at the bottom for the full list.")


def _what_changed_table(c_f: pd.DataFrame, periods_map: dict) -> None:
    """Previous-period (W-2) vs current-period (W-1) comparison for the
    headline metrics - shown at the top of every reporting cycle so
    attention goes to what actually moved, not the full dashboard."""
    w1_mask = tm.period_mask(c_f, *periods_map["W-1"])
    w2_mask = tm.period_mask(c_f, *periods_map["W-2"])
    wc = ta.what_changed(c_f, w1_mask, w2_mask)
    interp_color = {"Worsened": tm.RED, "Improved": tm.GREEN, "Flat": None, "Baseline not available": None}
    row_colors = wc["Interpretation"].map(interp_color)
    show_table(wc, pct_cols=["% Change"], dec_cols=["Previous", "Current", "Change"],
               row_colors=row_colors, height=min(320, 38 * len(wc) + 40))


def _top5_panel(c_f: pd.DataFrame, grp_perf: pd.DataFrame, typ_perf: pd.DataFrame) -> None:
    """Five specific Top-5 cuts for the executive view - never every Type,
    per the wireframe's 'Top Five Only' rule. Full detail stays available
    in the HOD/L1 ranking tables and drill-down sections below."""
    res_valid = typ_perf.merge(
        c_f.groupby("Type", observed=True)["RESTAT"].count().rename("Valid Res"), on="Type", how="left")
    res_valid = res_valid[res_valid["Valid Res"].fillna(0) >= TAT_LOW_SAMPLE_THRESHOLD]
    breach72 = c_f[c_f["RESTAT"] > 72].groupby("Type", observed=True).size().rename(">72h Breach")

    cuts = [
        ("Top 5 Types by Volume", typ_perf.nlargest(5, "Total Raised")[["Type", "Total Raised"]], "Total Raised", None),
        ("Top 5 Types by Backlog", typ_perf.nlargest(5, "Total Backlog")[["Type", "Total Backlog"]], "Total Backlog", None),
        ("Top 5 Types by Median Resolution TAT (min sample)",
         res_valid.nlargest(5, "Median Resolution TAT")[["Type", "Median Resolution TAT", "Valid Res"]],
         "Median Resolution TAT", None),
        ("Top 5 Types by >72h Resolution Breach",
         breach72.sort_values(ascending=False).head(5).reset_index(), ">72h Breach", None),
    ]
    cols = st.columns(2)
    for i, (label, df, sort_col, _) in enumerate(cuts):
        with cols[i % 2]:
            st.markdown(f'<div class="section-sub">{label}</div>', unsafe_allow_html=True)
            if df.empty:
                st.caption("Not enough data.")
            else:
                dec = [c for c in df.columns if "TAT" in c]
                show_table(df, int_cols=[c for c in df.columns if c not in dec and c != "Type"],
                           dec_cols=dec, height=min(220, 38 * len(df) + 40))


def _breach_cards(c_f: pd.DataFrame, tat_col: str, thresholds: list[int], key_prefix: str) -> None:
    """Breach counter cards for the given hour thresholds - each expands
    into the exact ticket list breaching that threshold."""
    counts = ta.breach_counts(c_f, tat_col, thresholds)
    cols = st.columns(len(counts))
    for col, info in zip(cols, counts):
        with col:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">&gt;{info["threshold"]}h</div>'
                f'<div class="kpi-value">{info["count"]:,}</div>'
                f'<div class="kpi-def">{info["pct"]:.1%} of valid tickets</div></div>',
                unsafe_allow_html=True)
    for info in counts:
        h = info["threshold"]
        with st.expander(f"Tickets >{h}h — {info['count']:,}", expanded=False):
            tix = ta.breach_tickets(c_f, tat_col, h)
            if tix.empty:
                st.caption("None.")
            else:
                show_table(tix[_L2_TICKET_COLS].head(50), dec_cols=["AgeDays", "FRTAT", "RESTAT"],
                           height=min(340, 38 * min(len(tix), 50) + 40),
                           row_colors=None)
                if len(tix) > 50:
                    st.caption(f"Showing the 50 worst of {len(tix):,}.")


def _tat_section(c_f: pd.DataFrame, bm_company, periods: list, tat_col: str, bucket_col: str,
                  breach_thresholds: list[int], title: str, subtitle: str, kpi_defs: list[tuple[str, str, str]],
                  key_prefix: str) -> None:
    """One full First Response / Resolution TAT section: definitions-
    annotated KPI cards, a distribution bar, breach cards with drill-down,
    a monthly trend line, a Group x Type heatmap, and Group/Type
    diagnostic + volume scatter charts. Shared shape for both metrics -
    only the column names, thresholds, and copy differ."""
    section(title, subtitle)
    kpis = ta.tat_kpis(c_f, tat_col)
    conf_level, conf_text = ta.confidence_label(kpis["valid"], kpis["total"])
    worst_g, worst_g_val, worst_g_n = ta.worst_segment(c_f, "Group", tat_col)
    worst_t, worst_t_val, worst_t_n = ta.worst_segment(c_f, "Type", tat_col)

    items = [(label, fmt_hrs(val) if unit == "hrs" else (fmt_int(val) if unit == "int" else fmt_pct(val)), defn)
             for label, val, unit, defn in kpi_defs(kpis)]
    kpi_row_with_defs(items)
    st.caption(f"Data confidence: {conf_level} - {conf_text}.")

    bm_tat_for_status = bm_company.median_fr_tat if tat_col == "FRTAT" else bm_company.median_res_tat
    wc1, wc2 = st.columns(2)
    with wc1:
        if worst_g:
            g_vol = int(c_f.loc[c_f["Group"] == worst_g].shape[0])
            g_backlog_rate = float(c_f.loc[c_f["Group"] == worst_g, "Backlog"].mean())
            g_status = ta.status_label(g_vol, g_backlog_rate, worst_g_val, bm_tat_for_status, worst_g_n)
            g_text = f"<b>{worst_g}</b> - {worst_g_val:.1f}h median ({worst_g_n} valid tickets) {status_badge(g_status)}"
        else:
            g_text = "No Group meets the minimum sample."
        st.markdown(f'<div class="finding">Highest meaningful Group: {g_text}</div>', unsafe_allow_html=True)
    with wc2:
        if worst_t:
            t_vol = int(c_f.loc[c_f["Type"] == worst_t].shape[0])
            t_backlog_rate = float(c_f.loc[c_f["Type"] == worst_t, "Backlog"].mean())
            t_status = ta.status_label(t_vol, t_backlog_rate, worst_t_val, bm_tat_for_status, worst_t_n)
            t_text = f"<b>{worst_t}</b> - {worst_t_val:.1f}h median ({worst_t_n} valid tickets) {status_badge(t_status)}"
        else:
            t_text = "No Type meets the minimum sample."
        st.markdown(f'<div class="finding">Highest meaningful Type: {t_text}</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-sub">Distribution</div>', unsafe_allow_html=True)
    dist = ta.distribution(c_f, bucket_col)
    st.plotly_chart(charts.stacked_distribution_bar(dist, title.split(" —")[0]),
                     use_container_width=True, key=f"{key_prefix}_dist")

    st.markdown('<div class="section-sub">Breach Thresholds</div>', unsafe_allow_html=True)
    _breach_cards(c_f, tat_col, breach_thresholds, key_prefix)

    with st.expander("Monthly Trend (M-3 .. MTD)"):
        trend = ta.monthly_trend(c_f, periods, tat_col)
        st.plotly_chart(charts.monthly_trend_line(trend), use_container_width=True, key=f"{key_prefix}_trend")
        st.caption("A period with fewer than 10 valid tickets is left blank rather than drawing a misleading line.")
        show_table(trend, int_cols=["Valid Count"], dec_cols=["Avg", "Median"], height=180)

    with st.expander("Group x Type Heatmap"):
        med, cnt = ta.heatmap_data(c_f, tat_col)
        if med.empty:
            st.caption("Not enough data for a heatmap.")
        else:
            st.plotly_chart(charts.tat_heatmap(med, cnt, TAT_LOW_SAMPLE_THRESHOLD), use_container_width=True,
                             key=f"{key_prefix}_heatmap")
            st.caption(f"* = fewer than {TAT_LOW_SAMPLE_THRESHOLD} valid tickets in that cell - treat as low sample.")

    with st.expander("Diagnostics: Average vs Median, and Volume vs TAT"):
        dim = st.radio("View by", ["Group", "Type"], horizontal=True, key=f"{key_prefix}_dim")
        bub = ta.diagnostic_bubbles(c_f, dim, tat_col)
        sc = ta.volume_tat_scatter(c_f, dim, tat_col)
        dcol1, dcol2 = st.columns(2)
        with dcol1:
            st.markdown('<div class="section-sub">Average vs Median (bubble = valid tickets)</div>',
                        unsafe_allow_html=True)
            if bub.empty:
                st.caption("Not enough data.")
            else:
                st.plotly_chart(charts.diagnostic_scatter(bub, TAT_MANAGEMENT_THRESHOLD_HOURS),
                                 use_container_width=True, key=f"{key_prefix}_diag_{dim}")
        with dcol2:
            st.markdown('<div class="section-sub">Volume vs Median TAT (bubble = backlog)</div>',
                        unsafe_allow_html=True)
            if sc.empty:
                st.caption("Not enough data.")
            else:
                st.plotly_chart(charts.volume_tat_scatter_chart(sc, TAT_MANAGEMENT_THRESHOLD_HOURS),
                                 use_container_width=True, key=f"{key_prefix}_scatter_{dim}")
        st.caption("High volume + high TAT = structural priority. High volume + low TAT = capacity pressure but "
                   "controlled. Low volume + high TAT = investigate individually, check sample size first.")


def _backlog_risk_section(c_f: pd.DataFrame) -> None:
    """Backlog composition and ageing - unresolved-ticket risk, kept
    explicitly separate from resolved-ticket TAT so a reader never mistakes
    one for the other."""
    section("Backlog Risk", "Unresolved-ticket risk - deliberately separate from the TAT sections above, "
            "which only describe tickets that have already been responded to or resolved.")
    bl = c_f[c_f["Backlog"] == 1]
    status_upper = bl["Status"].astype(str).str.upper().str.strip()
    status_counts = status_upper.value_counts()
    comp_cols = st.columns(4)
    for col, label in zip(comp_cols, ["Open", "New", "Pending", "Re-Opened"]):
        keys = ["RE-OPENED", "REOPENED"] if label == "Re-Opened" else [label.upper()]
        n = int(sum(status_counts.get(k, 0) for k in keys))
        with col:
            st.markdown(f'<div class="kpi-card"><div class="kpi-label">{label.upper()}</div>'
                        f'<div class="kpi-value">{n:,}</div></div>', unsafe_allow_html=True)

    age_dist = bl["AgeBucket"].value_counts().reindex(
        ["0-1 Day", "1-3 Days", "3-7 Days", "7-14 Days", "14-30 Days", ">30 Days"]).fillna(0).astype(int)
    st.markdown('<div class="section-sub">Backlog Ageing Distribution</div>', unsafe_allow_html=True)
    age_df = pd.DataFrame({"Age Bucket": age_dist.index, "Count": age_dist.values})
    age_df["Pct"] = age_df["Count"] / age_df["Count"].sum() if age_df["Count"].sum() else 0.0
    dist_for_chart = age_df.rename(columns={"Age Bucket": "Bucket"})
    st.plotly_chart(charts.stacked_distribution_bar(dist_for_chart, "Backlog Age"), use_container_width=True,
                     key="backlog_age_dist")
    if len(bl):
        oldest = bl.sort_values("AgeDays", ascending=False).head(1).iloc[0]
        st.caption(f"Oldest unresolved ticket: #{oldest['Ticket ID']} - {oldest['AgeDays']:.0f} days old "
                   f"({oldest['Group']} / {oldest['Type']}).")

    with st.expander("Oldest unresolved tickets"):
        if bl.empty:
            st.caption("No current backlog.")
        else:
            show_table(bl.sort_values("AgeDays", ascending=False).head(30)[_L2_TICKET_COLS],
                       dec_cols=["AgeDays", "FRTAT", "RESTAT"], height=340)


def _evidence_panel(c_f: pd.DataFrame) -> None:
    """Observed patterns associated with high TAT for the current
    selection - measurable correlates only, explicitly not claimed as
    causes."""
    section("Observed Patterns Associated with High TAT",
            "Not confirmed causes - measurable correlates for the current selection, for the L1/L2 owner to "
            "investigate before assuming a root cause.")
    total = len(c_f)
    status_upper = c_f["Status"].astype(str).str.upper().str.strip()
    attribution = perf.attribution_quality(c_f)
    coverage = sa.seller_mapping_coverage(c_f)
    missing_fr = int(c_f["FRTAT"].isna().sum())
    missing_res = int(c_f["RESTAT"].isna().sum())

    ecol1, ecol2, ecol3 = st.columns(3)
    with ecol1:
        st.markdown('<div class="section-sub">Status Mix</div>', unsafe_allow_html=True)
        for s, keys in [("Open", ["OPEN"]), ("New", ["NEW"]), ("Pending", ["PENDING"]),
                        ("Re-Opened", ["RE-OPENED", "REOPENED"])]:
            n = int(status_upper.isin(keys).sum())
            st.markdown(f'<div class="finding">{s}: {n:,} ({n / total:.1%})</div>' if total else "",
                        unsafe_allow_html=True)
    with ecol2:
        st.markdown('<div class="section-sub">Attribution & Mapping</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="finding">Unknown Type: {attribution["unknown_type"]:,} '
                    f'({attribution["unknown_type_rate"]:.1%})</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="finding">Unmapped Seller/Owner: {attribution["unattributed_owner"]:,} '
                    f'({attribution["unattributed_owner_rate"]:.1%})</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="finding">Mapped to a Seller: {coverage["mapped_pct"]:.1%}</div>',
                    unsafe_allow_html=True)
    with ecol3:
        st.markdown('<div class="section-sub">Timestamp Completeness</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="finding">Missing First Response time: {missing_fr:,} '
                    f'({missing_fr / total:.1%})</div>' if total else "", unsafe_allow_html=True)
        st.markdown(f'<div class="finding">Missing Resolution time: {missing_res:,} '
                    f'({missing_res / total:.1%})</div>' if total else "", unsafe_allow_html=True)
        st.markdown(f'<div class="finding">Re-Opened: {attribution["reopened"]:,} '
                    f'({attribution["reopened_rate"]:.1%})</div>', unsafe_allow_html=True)


def _funnel_section(c_f: pd.DataFrame) -> None:
    section("End-to-End TAT Funnel", "Timestamp completeness and resolution performance in one place.")
    stages = ta.funnel_stages(c_f)
    fcol1, fcol2 = st.columns([1.3, 1])
    with fcol1:
        st.plotly_chart(charts.tat_funnel(stages), use_container_width=True, key="tat_funnel")
    with fcol2:
        stage_df = pd.DataFrame(stages)
        show_table(stage_df, pct_cols=["Conversion %"], int_cols=["Count"], height=260)


def render(c: pd.DataFrame, as_of: pd.Timestamp, mapping: pd.DataFrame, raw: pd.DataFrame,
           team_data: pd.DataFrame | None, team_lists: pd.DataFrame | None,
           lsq_data: pd.DataFrame | None = None) -> None:
    bm_company = perf.compute_benchmark(c)
    periods = tm.period_definitions(as_of)
    periods_map = {label: (start, end) for label, start, end in periods}

    # ------------------------------------------------------------- Header --
    st.title("Support Performance Dashboard")
    period_str = f"{c['Created'].min():%d-%b-%Y} to {c['Created'].max():%d-%b-%Y}"
    st.caption(f"Data as of **{as_of:%d-%b-%Y %H:%M}** | Raw data loaded covers: {period_str}")

    # ------------------------------------------------------------- Filters --
    groups_by_vol = c["Group"].value_counts().index.tolist()
    fcol1, fcol2, fcol3 = st.columns([1.3, 1.3, 2.6])
    with fcol1:
        selected_group = st.selectbox("Group", ["All Groups"] + groups_by_vol, key="filter_group")
    with fcol2:
        if selected_group == "All Groups":
            st.selectbox("Type", ["All Types"], key="filter_type_all", disabled=True)
            selected_type = "All Types"
        else:
            types_by_vol = c.loc[c["Group"] == selected_group, "Type"].value_counts().index.tolist()
            selected_type = st.selectbox("Type", ["All Types"] + types_by_vol, key=f"filter_type_{selected_group}")
    with fcol3:
        st.markdown(
            '<div class="note" style="margin-top:1.9rem">Filters scope every section below. Leave at '
            '"All Groups" for the company-wide view; select a Group to focus everything on it, then a Type '
            'to focus further.</div>',
            unsafe_allow_html=True,
        )

    c_f = c
    if selected_group != "All Groups":
        c_f = c_f[c_f["Group"] == selected_group]
    if selected_type != "All Types":
        c_f = c_f[c_f["Type"] == selected_type]

    if c_f.empty:
        st.warning("No tickets match the current filter selection.")
        return

    bm_scope = perf.compute_benchmark(c_f)
    coverage = sa.seller_mapping_coverage(c_f)
    pcoverage = tm.period_coverage(c_f, periods)

    color_legend()
    empty_periods = [label for label, n in pcoverage.items() if n == 0]
    if empty_periods:
        st.markdown(
            f'<div class="note">No tickets in the current selection fall in: {", ".join(empty_periods)} - '
            f'shown as "-", not a misleading 0%.</div>',
            unsafe_allow_html=True,
        )

    grp_perf = perf.group_rollup_performance(c_f, bm_company)
    typ_perf = perf.type_performance(c_f, bm_company)

    # =============================================================== CRO ===
    section("CEO / CRO — Executive Overview", "Topline performance for the current selection.")
    attribution = perf.attribution_quality(c_f)
    backlog_f = c_f[c_f["Backlog"] == 1]
    backlog_over7 = int(backlog_f["AgeBucket"].isin(AGED_BUCKETS_7PLUS).sum())
    backlog_over7_pct = backlog_over7 / len(backlog_f) if len(backlog_f) else 0.0

    kpi_row([
        ("TOTAL TICKETS", fmt_int(bm_scope.total)),
        ("BACKLOG %", fmt_pct(bm_scope.total_backlog / bm_scope.total if bm_scope.total else 0)),
        ("RESOLUTION RATE", fmt_pct(bm_scope.resolution_rate)),
        ("MEDIAN FIRST RESP TAT (hrs)", fmt_hrs(bm_scope.median_fr_tat)),
        ("MEDIAN RESOLUTION TAT (hrs)", fmt_hrs(bm_scope.median_res_tat)),
    ])
    kpi_row([
        ("AVG FIRST RESP TAT (hrs)", fmt_hrs(bm_scope.avg_fr_tat)),
        ("AVG RESOLUTION TAT (hrs)", fmt_hrs(bm_scope.avg_res_tat)),
        ("BACKLOG >7 DAYS (% OF BACKLOG)", fmt_pct(backlog_over7_pct)),
        ("UNKNOWN / BLANK TYPE RATE", fmt_pct(attribution["unknown_type_rate"])),
        ("RE-OPENED RATE", fmt_pct(attribution["reopened_rate"])),
    ])

    st.markdown('<div class="section-sub">What Changed? (W-1 vs W-2)</div>', unsafe_allow_html=True)
    _what_changed_table(c_f, periods_map)

    st.markdown('<div class="section-sub">Needs Attention</div>', unsafe_allow_html=True)
    if selected_group == "All Groups":
        st.markdown(_attention_html(grp_perf, "Group"), unsafe_allow_html=True)
    else:
        st.markdown(_attention_html(typ_perf, "Type"), unsafe_allow_html=True)

    st.markdown('<div class="section-sub">Executive Problem Statement</div>', unsafe_allow_html=True)
    problem_df, low_vol_df = perf.executive_problem_statement(c_f, bm_company, n=8)
    if problem_df.empty:
        st.caption("No Group x Type segment in the current selection crosses the flagging threshold.")
    else:
        problem_colors = problem_df["Priority"].map(FLAG_COLOR)
        show_table(problem_df, pct_cols=["Backlog %"], int_cols=["Volume", "Backlog", ">7-day backlog"],
                   dec_cols=["Avg FR TAT", "Avg Resolution TAT"], row_colors=problem_colors,
                   height=min(360, 38 * len(problem_df) + 40))
    if not low_vol_df.empty:
        st.caption(f"Separately, {len(low_vol_df)} low-volume Group x Type combo(s) show a large deviation but "
                   f"fall under the {perf.MIN_SEGMENT_VOLUME}-ticket minimum sample size - real, but not mixed "
                   "into the ranking above:")
        show_table(low_vol_df, pct_cols=["Resolution Rate", "RR vs Benchmark (pp)"], int_cols=["Total Raised"],
                   height=min(220, 38 * len(low_vol_df) + 40))

    st.markdown('<div class="section-sub">Top 5 Only (full detail is in HOD / L1 below)</div>',
                unsafe_allow_html=True)
    _top5_panel(c_f, grp_perf, typ_perf)

    st.markdown('<div class="section-sub">Overall Group-level Performance</div>', unsafe_allow_html=True)
    if selected_group == "All Groups":
        bar_rows = [
            {
                "label": row["Group"],
                "value_text": f'{row["Resolution Rate"]:.0%}  ({int(row["Total Raised"]):,} tickets)',
                "pct": row["Resolution Rate"],
                "color": FLAG_COLOR.get(row["Flag"], "#9CA3AF"),
            }
            for _, row in grp_perf.sort_values("Total Raised", ascending=False).iterrows()
        ]
        bar_ranking(bar_rows)
    else:
        st.caption('Select "All Groups" above to see every Group\'s Resolution Rate side by side.')

    with st.expander("Overall Performance — Time Period Trend (D-1..M-3)"):
        st.markdown(
            '<div class="note">D-1 and D-2 rate/TAT cells are shown uncolored on purpose: most of "today" '
            'and "yesterday"\'s tickets haven\'t had time to resolve yet, so Resolution Rate reads '
            'artificially low and Median TAT of the few already-resolved ones reads artificially fast. '
            'TAT figures exclude Sunday (non-working day) - see Logic Validation.</div>',
            unsafe_allow_html=True,
        )
        overall_rows = tm.overall_matrix_rows(c_f, periods, bm_company)
        odata, ocolors = tm.build_matrix(overall_rows, periods)
        show_matrix(odata, ocolors)

    _funnel_section(c_f)

    # ---------------------------------------------------------- First Response --
    _tat_section(
        c_f, bm_company, periods, "FRTAT", "FRBucket", FR_BREACH_THRESHOLDS,
        "First Response TAT — How quickly are customers being acknowledged?",
        "Only first-response metrics - a fast acknowledgement is not the same thing as a fast resolution.",
        lambda k: [
            ("AVERAGE", k["avg"], "hrs", "Average time from ticket creation to the first agent response."),
            ("MEDIAN", k["median"], "hrs",
             "Typical ticket - half of valid tickets got a first response within this time."),
            ("VALID TICKETS", k["valid"], "int",
             "Tickets with a valid, non-negative Initial Response Time and Created Time."),
            ("WITHIN 1H", k["pct_le_1h"], "pct", "Share of valid tickets acknowledged within 1 hour."),
            ("WITHIN 4H", k["pct_le_4h"], "pct", "Share of valid tickets acknowledged within 4 hours."),
            ("ABOVE 24H", k["pct_gt_24h"], "pct", f'{k["count_gt_24h"]:,} tickets took over 24h for a first response.'),
        ],
        key_prefix="fr",
    )

    # ------------------------------------------------------------ Resolution --
    _tat_section(
        c_f, bm_company, periods, "RESTAT", "RESBucket", RESOLUTION_BREACH_THRESHOLDS,
        "Resolution TAT — How quickly are customer issues being closed?",
        "Only resolution metrics - see Backlog Risk below for tickets that haven't resolved at all yet.",
        lambda k: [
            ("AVERAGE", k["avg"], "hrs", "Average time from ticket creation to resolution."),
            ("MEDIAN", k["median"], "hrs",
             "Typical ticket - half of valid resolved tickets closed within this time."),
            ("VALID RESOLVED TICKETS", k["valid"], "int",
             "Tickets with a valid, non-negative Resolved Time and Created Time."),
            ("WITHIN 4H", k["pct_le_4h"], "pct", "Share of valid resolved tickets closed within 4 hours."),
            ("WITHIN 24H", k["pct_le_24h"], "pct", "Share of valid resolved tickets closed within 24 hours."),
            ("ABOVE 72H", k["pct_gt_72h"], "pct", f'{k["count_gt_72h"]:,} tickets took over 72h to resolve.'),
        ],
        key_prefix="res",
    )

    _backlog_risk_section(c_f)

    # =============================================================== HOD ===
    hod_note = ("Which Groups are performing well, and which need attention." if selected_group == "All Groups"
                else f"Filtered to <b>{selected_group}</b> - select \"All Groups\" above to compare across Groups.")
    section("HOD — Group Performance", hod_note)
    _best_worst_html(*perf.best_worst(grp_perf, "Group", n=3), "Group")
    _ranking_table(c_f, grp_perf, "Group")

    with st.expander("Group Performance — Time Period Trend"):
        group_labels = grp_perf["Group"].tolist()
        gtrend_rows = tm.segment_trend_rows(c_f, "Group", group_labels, periods, bm_company)
        gtdata, gtcolors = tm.build_matrix(gtrend_rows, periods)
        show_matrix(gtdata, gtcolors, height=min(680, 36 * len(gtrend_rows) + 40))

    with st.expander("Group First Response / Resolution TAT Control"):
        _tat_control_tables(c_f, "Group", grp_perf["Group"].tolist())

    # ================================================================ L1 ===
    l1_scope_note = f"within <b>{selected_group}</b>" if selected_group != "All Groups" else "across all Groups"
    section("L1 — Group Performance & TAT Control", f"Which Types are performing well, and which need "
            f"attention, {l1_scope_note}.")
    _best_worst_html(*perf.best_worst(typ_perf, "Type", n=3), "Type")
    _ranking_table(c_f, typ_perf, "Type")

    with st.expander("Type Performance — Time Period Trend"):
        type_labels = typ_perf["Type"].tolist()
        ttrend_rows = tm.segment_trend_rows(c_f, "Type", type_labels, periods, bm_company)
        ttdata, ttcolors = tm.build_matrix(ttrend_rows, periods)
        show_matrix(ttdata, ttcolors, height=min(680, 36 * len(ttrend_rows) + 40))

    with st.expander("L1 First Response / Resolution TAT Control"):
        _tat_control_tables(c_f, "Type", typ_perf["Type"].tolist())

    _evidence_panel(c_f)

    # ================================================================ L2 ===
    l2_scope_note = (f"<b>{selected_group}</b> → <b>{selected_type}</b>" if selected_type != "All Types"
                      else (f"<b>{selected_group}</b> (all Types)" if selected_group != "All Groups"
                            else "the full company (select a Group, then a Type, above to narrow it)"))
    section("L2 — Type Owner: Ticket-Level Action Queues",
            f"Scoped to {l2_scope_note}. Five standing queues, each a live filter over the current selection - "
            "no invented owner/due-date fields, just the tickets that meet each condition right now.")
    _l2_action_queues(c_f)

    # ----------------------------------------------------------- Priority Actions --
    section("Priority Actions", "Mined from the current selection, ranked by business impact "
            "(volume affected x performance gap vs benchmark). Group x Type only.")
    insights = perf.mine_actionable_insights(c_f, bm_company)
    if not insights.empty:
        show_table(insights.drop(columns=["_impact", "Owner / Segment", "Area"]), hide_index=True, height=380)
    else:
        st.caption("No Group x Type segment in the current selection meets the minimum volume + deviation "
                   "thresholds for a flagged insight.")

    # ----------------------------------------------------- Collapsed detail --
    reps = _reps(mapping, team_data, team_lists)
    with st.expander("Data Quality - reconciliation checks"):
        show_table(dq.ticket_total_reconciliation(c_f, reps), int_cols=["Diff (should be 0)"])
        show_table(dq.backlog_tat_reconciliation(c_f), int_cols=["Diff (should be 0)"])
        st.caption(f"Seller mapping coverage: {coverage['mapped']:,} mapped, "
                   f"{coverage['unmapped_seller']:,} unmapped seller, {coverage['no_seller_id']:,} no seller ID "
                   f"(of {coverage['total']:,} tickets in the current selection).")
        if team_data is not None:
            meta = team_data.attrs.get("dedup_meta", {})
            st.caption(f"Team Level Data: {meta.get('unique_sellers', '?'):,} unique sellers loaded "
                       f"({meta.get('conflicting_rows', 0)} rows had a conflicting duplicate Seller ID - "
                       "most recent month kept).")
        if lsq_data is not None:
            meta = lsq_data.attrs.get("dedup_meta", {})
            st.caption(f"LSQ Seller Data: {meta.get('unique_sellers', '?'):,} unique sellers loaded - used to "
                       "fill Seller Name gaps and provide Seller Company Name.")
        show_table(dq.missing_field_rates(c_f), int_cols=["Missing / Blank"], pct_cols=["% of Total Tickets"])

    with st.expander("Seller Detail (supplementary - not part of the Group/Type leadership view)"):
        gts = sa.group_type_seller_table(c_f, bm=bm_company).sort_values("Impact Score", ascending=False) \
            .reset_index(drop=True)
        if gts.empty:
            st.caption(f"No Group x Type x Seller combination in the current selection reaches "
                       f"{sa.MIN_SEGMENT_VOLUME} tickets.")
        else:
            status_color = {"High-volume underperformer": tm.RED, "Low-volume outlier": tm.AMBER, "Healthy": tm.GREEN}
            sdisplay = gts[["Group", "Type", "SellerLabel", "SellerCompanyName", "SalesPerson", "Team", "Tickets",
                            "Avg Resolution TAT", "Backlog %", ">16h", ">24h", "Status"]] \
                .rename(columns={"SellerLabel": "Seller", "SellerCompanyName": "Seller Company"})
            srow_colors = gts["Status"].map(status_color)
            show_table(sdisplay, int_cols=["Tickets", ">16h", ">24h"], pct_cols=["Backlog %"],
                       dec_cols=["Avg Resolution TAT"], height=400, row_colors=srow_colors)

    with st.expander("Logic Validation - corrections made to the brief's assumed logic"):
        st.dataframe(pd.DataFrame(LOGIC_VALIDATION_ROWS,
                                   columns=["Original Logic", "Issue Found", "Corrected Logic", "Reason"]),
                     hide_index=True, use_container_width=True, height=400)

    with st.expander("Detailed per-ticket data (current selection)"):
        st.dataframe(c_f, hide_index=True, use_container_width=True, height=420)
        st.download_button("Download computed data as CSV", c_f.to_csv(index=False).encode("utf-8"),
                            file_name="ticket_computed_data.csv", mime="text/csv")
