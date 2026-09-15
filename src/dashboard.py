"""Render functions for every tab - one function per Excel-tab equivalent.
Keeps all business logic out of this file (it only formats and lays out
DataFrames/figures produced by calculations.py / aggregations.py / insights.py
/ data_quality.py).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config as cfg
from config import AGE_BUCKETS, TAT_BUCKETS
from src import aggregations as agg
from src import data_quality as dq
from src import insights
from src import performance as perf
from src import tat_diagnostics as tatd
from src.styling import fmt_hrs, fmt_int, fmt_pct, kpi_row, priority_badge, section, show_table

DIM_INT_COLS = ["Total Raised", "Open", "New", "Pending", "Re-Opened", "Total Backlog"]
DIM_PCT_COLS = ["% of Total", "% Backlog", "% of Group"]
DIM_DEC_COLS = ["Avg First Resp TAT", "Median First Resp TAT", "Avg Resolution TAT", "Median Resolution TAT"]


def render_header(c: pd.DataFrame, as_of: pd.Timestamp) -> None:
    st.title("Support Ticket Analytics Dashboard")
    period = f"{c['Created'].min():%d-%b-%Y}  to  {c['Created'].max():%d-%b-%Y}"
    st.caption(f"Data as of **{as_of:%d-%b-%Y %H:%M}**  |  Report period: {period}")


def _overall_kpis(c: pd.DataFrame) -> list[tuple[str, str]]:
    total = len(c)
    backlog = int(c["Backlog"].sum())
    return [
        ("TOTAL TICKETS", fmt_int(total)),
        ("TOTAL BACKLOG", fmt_int(backlog)),
        ("BACKLOG %", fmt_pct(backlog / total if total else 0)),
        ("AVG FIRST RESP TAT (hrs)", fmt_hrs(c["FRTAT"].mean())),
        ("AVG RESOLUTION TAT (hrs)", fmt_hrs(c["RESTAT"].mean())),
        ("1ST RESPONSE COVERAGE", fmt_pct(c["FRTAT"].notna().sum() / total if total else 0)),
        ("RESOLUTION COVERAGE", fmt_pct(c["RESTAT"].notna().sum() / total if total else 0)),
        ("SELLER-MAPPED TICKETS", fmt_pct((c["MappingStatus"] == "Mapped").sum() / total if total else 0)),
    ]


# ---------------------------------------------------------------- Executive --
def render_executive_summary(c: pd.DataFrame, reps: list[str]) -> None:
    kf = insights.compute_key_figures(c, reps)
    total = len(c)
    backlog = int(c["Backlog"].sum())
    kpi_row([
        ("TOTAL TICKETS", fmt_int(total)),
        ("TOTAL BACKLOG", fmt_int(backlog)),
        ("BACKLOG %", fmt_pct(backlog / total if total else 0)),
        ("AVG FIRST RESP TAT (hrs)", fmt_hrs(c["FRTAT"].mean())),
        ("AVG RESOLUTION TAT (hrs)", fmt_hrs(c["RESTAT"].mean())),
        ("% BACKLOG > 7 DAYS", fmt_pct(kf.backlog7d_pct)),
        ("TICKETS UNMAPPED TO A REP", fmt_int(round(kf.unmapped_pct * total))),
    ])

    section("What happened / Where is the problem / How big / Why it matters / What to do next")
    for line in insights.build_narrative(kf):
        st.markdown(f'<div class="finding">- {line}</div>', unsafe_allow_html=True)

    section("Actionable Items")
    ai = insights.build_actionable_items(kf)
    for _, row in ai.iterrows():
        cls = f"priority-{row['Priority']}"
        st.markdown(
            f'<span class="{cls}">{row["Priority"]}</span>&nbsp;&nbsp;**{row["Problem / Finding"]}**<br>'
            f'<span style="font-size:0.78rem;color:#374151">Evidence: {row["Evidence"]}</span><br>'
            f'<span style="font-size:0.78rem;">Action: {row["Recommended Action"]}</span><br>'
            f'<span style="font-size:0.78rem;color:#6B7280">Expected impact: {row["Expected Impact"]}</span>',
            unsafe_allow_html=True,
        )
        st.markdown("<hr style='margin:6px 0;border-color:#E5E7EB'>", unsafe_allow_html=True)


# ------------------------------------------------------------------ Overall --
def render_overall_analysis(c: pd.DataFrame, as_of: pd.Timestamp) -> None:
    kpi_row(_overall_kpis(c))

    section("01. Ticket Volume")
    show_table(pd.DataFrame({"Metric": ["Total tickets raised", "Duplicate ticket IDs detected"],
                              "Value": [len(c), int(c["Ticket ID"].duplicated().sum())]}),
               int_cols=["Value"])

    section("02. Status Distribution - Overall")
    show_table(agg.status_distribution(c), int_cols=["Ticket Count"], pct_cols=["% of Total"])

    section("03. Backlog Summary - Overall (Open + New + Pending + Re-Opened)")
    show_table(agg.backlog_summary(c), int_cols=["Ticket Count"], pct_cols=["% of Backlog"])

    section("04. Month-on-Month Analysis (trailing 12 months, ending in the AS-OF month)")
    mom = agg.month_on_month(c, as_of)
    show_table(mom, int_cols=["Total", "New", "Open", "Pending", "Re-Opened", "Closed", "Resolved",
                               "Waiting on Customer", "Total Backlog", "MoM Ticket Change"],
               pct_cols=["Backlog %", "MoM Ticket %"])


# ------------------------------------------ Group, Type & Sales Performance --
PERF_INT_COLS = DIM_INT_COLS + ["Rank (by Volume)"]
PERF_PCT_COLS = ["% of Total", "% Backlog", "% of Group", "Resolution Rate", "RR vs Benchmark (pp)", "TAT vs Benchmark (%)"]
PERF_DEC_COLS = DIM_DEC_COLS


def _kf_card(label: str, cls: str, text: str) -> str:
    return f'<div class="kf-card {cls}"><div class="kf-label">{label}</div><div class="kf-text">{text}</div></div>'


def _insight_card(row: pd.Series, area_key: str = "Area", finding_key: str = "Finding",
                   evidence_key: str = "Evidence", impact_key: str = "Impact",
                   impact_label: str = "Impact") -> None:
    st.markdown(
        f'{priority_badge(row["Priority"])}&nbsp;&nbsp;<span style="font-size:0.7rem;color:#6B7280;'
        f'text-transform:uppercase;font-weight:700">{row[area_key]}</span>&nbsp;&nbsp;'
        f'<b>{row[finding_key]}</b><br>'
        f'<span style="font-size:0.78rem;color:#374151">Evidence: {row[evidence_key]}</span><br>'
        f'<span style="font-size:0.78rem;">{impact_label}: {row[impact_key]}</span><br>'
        f'<span style="font-size:0.78rem;">Action: {row["Recommended Action"]}</span>',
        unsafe_allow_html=True,
    )
    st.markdown("<hr style='margin:6px 0;border-color:#E5E7EB'>", unsafe_allow_html=True)


def _snapshot_card(label: str, row, name_key: str, cls: str) -> str:
    if row is None:
        return _kf_card(label, "", "Not enough data for this cut.")
    dev = row["RR vs Benchmark (pp)"]
    return _kf_card(label, cls,
                     f"<b>{row[name_key]}</b><br>{row['Resolution Rate']:.1%} resolution rate "
                     f"({'+' if dev >= 0 else ''}{dev * 100:.1f}pp vs benchmark), {row['Total Raised']:,} tickets")


QUADRANT_ORDER = ["High Priority", "Best Practice - Scale", "Potential Opportunity", "Low Priority"]
QUADRANT_NOTE = {
    "High Priority": "High volume + underperforming - fix this first.",
    "Best Practice - Scale": "High volume + outperforming - study and scale this.",
    "Potential Opportunity": "Low volume + outperforming - small, worth a closer look.",
    "Low Priority": "Low volume + underperforming - real, but limited business impact today.",
}


def render_performance_drivers_actions(c: pd.DataFrame, mapping: pd.DataFrame, reps: list[str]) -> None:
    bm = perf.compute_benchmark(c)
    insights_df = perf.mine_actionable_insights(c, reps, bm)

    st.markdown(
        '<div class="note">Resolution Rate = 1 - Backlog Rate (share of a segment\'s tickets NOT currently stuck '
        'in backlog) - the "conversion %" analog for ticket support, higher is better. Every comparison below is '
        'against the overall benchmark, and only for segments with at least 20 tickets, to avoid small-sample '
        'noise. Tables show the segments that matter most (top by volume, plus anything flagged) - full data is '
        'in Data Quality (reconciliation) and Detailed Data.</div>',
        unsafe_allow_html=True,
    )

    section("Management Focus", "The top issues and opportunities across Group, Type and Sales Rep cuts, "
            "ranked by business impact (volume affected x performance gap vs benchmark).")
    if insights_df.empty:
        st.caption("No segment currently meets the minimum volume + deviation thresholds for a flagged insight.")
    else:
        for _, row in perf.management_focus(insights_df, 5).iterrows():
            _insight_card(row)

    section("Performance Snapshot")
    kpi_row([
        ("TOTAL TICKETS", fmt_int(bm.total)),
        ("OVERALL RESOLUTION RATE", fmt_pct(bm.resolution_rate)),
        ("AVG RESOLUTION TAT (hrs)", fmt_hrs(bm.avg_res_tat)),
        ("AVG FIRST RESP TAT (hrs)", fmt_hrs(bm.avg_fr_tat)),
    ])
    snap = perf.performance_snapshot(c, reps, bm)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(_snapshot_card("Best-Performing Group", snap["best_group"], "Group", "positive"), unsafe_allow_html=True)
        st.markdown(_snapshot_card("Worst-Performing Group", snap["worst_group"], "Group", "negative"), unsafe_allow_html=True)
    with col2:
        st.markdown(_snapshot_card("Best-Performing Type", snap["best_type"], "Type", "positive"), unsafe_allow_html=True)
        st.markdown(_snapshot_card("Worst-Performing Type", snap["worst_type"], "Type", "negative"), unsafe_allow_html=True)
    with col3:
        st.markdown(_snapshot_card("Best-Performing Sales Rep", snap["best_rep"], "Sales Person", "positive"), unsafe_allow_html=True)
        biggest = None
        if len(insights_df):
            risk_rows = insights_df[insights_df["Priority"] != "Opportunity"]
            biggest = risk_rows.iloc[0] if len(risk_rows) else None
        st.markdown(_kf_card("Biggest Underperforming Segment", "negative" if biggest is not None else "",
                              biggest["Finding"] if biggest is not None else "None flagged."), unsafe_allow_html=True)

    section("Performance Drivers", "Curated to the segments that matter: top segments by volume, plus any "
            "segment flagged for a meaningful deviation even if smaller.")
    st.markdown('<div class="section-sub">Group Roll-up (all Groups)</div>', unsafe_allow_html=True)
    grp = perf.group_rollup_performance(c, bm)
    show_table(grp.drop(columns=["Meets Min Volume"]), int_cols=PERF_INT_COLS, pct_cols=PERF_PCT_COLS, dec_cols=PERF_DEC_COLS)
    st.caption(f"Reconciliation: Sum of Groups vs Overall Total = {grp['Total Raised'].sum() - len(c):+,} (should be 0)")

    st.markdown('<div class="section-sub">Group x Type (curated - top segments by volume + all flagged)</div>', unsafe_allow_html=True)
    gt = perf.group_type_performance(c, bm)
    gt_curated = perf.curate(gt)
    show_table(gt_curated.drop(columns=["Meets Min Volume", "Group", "Type"]).set_index("Group | Type").reset_index(),
               int_cols=PERF_INT_COLS, pct_cols=PERF_PCT_COLS, dec_cols=PERF_DEC_COLS, height=380)
    st.caption(f"Showing {len(gt_curated)} of {len(gt)} combinations, covering "
               f"{gt_curated['Total Raised'].sum() / len(c):.0%} of ticket volume. "
               f"Reconciliation (full data): Sum vs Overall Total = {gt['Total Raised'].sum() - len(c):+,} (should be 0)")

    st.markdown('<div class="section-sub">Sales Performance (curated - top reps by volume + all flagged)</div>', unsafe_allow_html=True)
    show_table(dq.mapping_validation(mapping, c), int_cols=["Value"])
    sp = perf.sales_performance(c, reps, bm)
    sp_curated = perf.curate(sp)
    show_table(sp_curated.drop(columns=["Meets Min Volume"]), int_cols=PERF_INT_COLS, pct_cols=PERF_PCT_COLS,
               dec_cols=PERF_DEC_COLS, height=380)
    st.caption(f"Showing {len(sp_curated)} of {len(sp)} reps, covering {sp_curated['Total Raised'].sum() / sp['Total Raised'].sum():.0%} "
               "of mapped-rep ticket volume.")

    st.markdown('<div class="section-sub">Rep Performance Within Their Primary Group</div>', unsafe_allow_html=True)
    st.caption("Compares each rep to peers working the same Group, not the company-wide benchmark - a fairer, "
               "segment-specific read. Shows only reps with a meaningful deviation.")
    outliers = perf.rep_primary_group_outliers(c, reps, bm)
    if len(outliers):
        show_table(outliers, int_cols=["Tickets in Primary Group"],
                   pct_cols=["Rep Resolution Rate (this Group)", "Group Average Resolution Rate", "Deviation (pp)"])
    else:
        st.caption("No rep currently shows a meaningful deviation from their primary Group's average.")

    section("Opportunity & Problem Segments", "HIGH VOLUME + POOR PERFORMANCE = High Priority. HIGH VOLUME + "
            "GOOD PERFORMANCE = Best Practice to scale. LOW VOLUME + GOOD PERFORMANCE = Potential Opportunity. "
            "LOW VOLUME + POOR PERFORMANCE = Low Priority. Volume split is the median among segments large "
            "enough to assess.")
    quad_cols = ["Total Raised", "Resolution Rate", "RR vs Benchmark (pp)", "Quadrant"]
    gt_q = perf.classify_quadrant(gt).assign(Cut="Group x Type")
    sp_q = perf.classify_quadrant(sp).assign(Cut="Sales Rep")
    quad = pd.concat([
        gt_q[["Cut", "Group | Type"] + quad_cols].rename(columns={"Group | Type": "Segment"}),
        sp_q[["Cut", "Sales Person"] + quad_cols].rename(columns={"Sales Person": "Segment"}),
    ], ignore_index=True)
    quad = quad[quad["Quadrant"].isin(QUADRANT_ORDER)]
    quad["_qrank"] = quad["Quadrant"].map({q: i for i, q in enumerate(QUADRANT_ORDER)})
    quad = quad.sort_values(["_qrank", "Total Raised"], ascending=[True, False]).drop(columns="_qrank")
    for q in QUADRANT_ORDER:
        sub = quad[quad["Quadrant"] == q]
        if sub.empty:
            continue
        st.markdown(f'<div class="section-sub">{q} ({len(sub)}) - {QUADRANT_NOTE[q]}</div>', unsafe_allow_html=True)
        show_table(sub.drop(columns="Quadrant"), int_cols=["Total Raised"],
                   pct_cols=["Resolution Rate", "RR vs Benchmark (pp)"])

    section("Priority Actions", "Every flagged finding, ranked by business impact - the Management Focus panel "
            "above is the top 5 of this same list.")
    if insights_df.empty:
        st.caption("No segment currently meets the minimum volume + deviation thresholds for a flagged insight.")
    else:
        show_table(insights_df.drop(columns=["Owner / Segment"]), hide_index=True, height=420)


# ------------------------------------------------------------- Backlog/Ageing --
def render_backlog_ageing(c: pd.DataFrame) -> None:
    backlog = int(c["Backlog"].sum())
    total = len(c)
    bl = c[c["Backlog"] == 1]
    b7 = bl["AgeBucket"].isin(["7-14 Days", "14-30 Days", ">30 Days"]).sum()
    b14 = bl["AgeBucket"].isin(["14-30 Days", ">30 Days"]).sum()
    b30 = (bl["AgeBucket"] == ">30 Days").sum()
    kpi_row([
        ("TOTAL BACKLOG", fmt_int(backlog)),
        ("BACKLOG %", fmt_pct(backlog / total if total else 0)),
        ("BACKLOG > 7 DAYS OLD", fmt_int(b7)),
        ("% BACKLOG > 7 DAYS", fmt_pct(b7 / backlog if backlog else 0)),
        ("% BACKLOG > 14 DAYS", fmt_pct(b14 / backlog if backlog else 0)),
        ("% BACKLOG > 30 DAYS", fmt_pct(b30 / backlog if backlog else 0)),
        ("OLDEST BACKLOG (days)", fmt_int(bl["AgeDays"].max() if len(bl) else 0)),
        ("AVG BACKLOG AGE (days)", fmt_hrs(bl["AgeDays"].mean() if len(bl) else 0)),
    ])

    section("01. Overall Backlog Ageing")
    show_table(agg.overall_ageing(c), int_cols=["Ticket Count"], pct_cols=["% of Total Backlog"])

    section("02. Status x Ageing")
    show_table(agg.status_x_ageing(c), int_cols=AGE_BUCKETS + ["Total Backlog"])

    section("03. Group x Ageing (backlogged Groups only, sorted by backlog volume)")
    show_table(agg.group_x_ageing(c), int_cols=AGE_BUCKETS + ["Total Backlog"], dec_cols=["Oldest (days)", "Avg Age (days)"])

    section("04. Type x Ageing (backlogged Types only, sorted by backlog volume)")
    show_table(agg.type_x_ageing(c), int_cols=AGE_BUCKETS + ["Total Backlog"], dec_cols=["Oldest (days)", "Avg Age (days)"])

    section("05. Backlog Contribution Ranking - Group (with running share)")
    show_table(agg.backlog_contribution_ranking(c, "Group"), int_cols=["Total Backlog"],
               pct_cols=["% of Total Backlog", "Cumulative %"])


# ------------------------------------------------------------ TAT Diagnostics --
def render_tat_diagnostics(c: pd.DataFrame, reps: list[str]) -> None:
    bm = perf.compute_benchmark(c)
    tat_insights_df = tatd.mine_tat_insights(c, reps, bm)

    st.markdown(
        '<div class="note">Concentration Ratio = a segment\'s share of a slow-TAT (or aged-backlog) bucket, '
        "divided by its share of overall volume. 1.0x = represented exactly proportional to its size; above "
        f"{cfg.TAT_CONCENTRATION_RATIO_FLAG:.1f}x means it's genuinely overrepresented among the delayed "
        "tickets - not just large.</div>",
        unsafe_allow_html=True,
    )

    section("Management Focus", "The top TAT problems across Group, Type and Sales Rep cuts, ranked by "
            "business impact (tickets affected x severity).")
    if tat_insights_df.empty:
        st.caption("No segment currently meets the minimum volume + concentration thresholds for a flagged insight.")
    else:
        for _, row in tatd.mine_tat_insights(c, reps, bm).head(5).iterrows():
            _insight_card(row, area_key="Area", finding_key="TAT Problem", evidence_key="Volume Impact",
                          impact_key="Driver / Pattern", impact_label="Driver / Pattern")

    section("TAT Snapshot")
    snap = tatd.tat_snapshot(c, bm)
    kpi_row([
        ("AVG / MEDIAN FIRST RESP TAT (hrs)", f"{snap['avg_fr_tat']:.1f} / {snap['median_fr_tat']:.1f}"),
        ("AVG / MEDIAN RESOLUTION TAT (hrs)", f"{snap['avg_res_tat']:.1f} / {snap['median_res_tat']:.1f}"),
        ("FIRST RESPONSE >24h", f"{fmt_int(snap['fr_over24_count'])} ({fmt_pct(snap['fr_over24_pct'])})"),
        ("RESOLUTION >24h", f"{fmt_int(snap['res_over24_count'])} ({fmt_pct(snap['res_over24_pct'])})"),
    ])

    section("Where TAT is Concentrated", "Each segment's share of >24h Resolution TAT tickets vs its share of "
            "overall volume. Sorted by ticket count, highest first - the top rows are where the volume of "
            "delay actually sits, regardless of ratio.")
    st.markdown('<div class="section-sub">By Group</div>', unsafe_allow_html=True)
    conc_grp = tatd.concentration_table(c, "Group", "RESBucket", ">24h")
    show_table(conc_grp, int_cols=["Volume", "Tickets >24h"],
               pct_cols=["% of Total Volume", "% of All >24h Tickets"], dec_cols=["Concentration Ratio"])

    st.markdown('<div class="section-sub">By Type (curated - top by >24h volume + all flagged)</div>', unsafe_allow_html=True)
    conc_typ = tatd.concentration_table(c, "Type", "RESBucket", ">24h")
    conc_typ_curated = pd.concat([
        conc_typ.head(cfg.CURATED_TOP_N),
        conc_typ[(conc_typ["Disproportionate?"] == "Yes") & (~conc_typ.index.isin(conc_typ.head(cfg.CURATED_TOP_N).index))],
    ]).sort_values("Tickets >24h", ascending=False)
    show_table(conc_typ_curated, int_cols=["Volume", "Tickets >24h"],
               pct_cols=["% of Total Volume", "% of All >24h Tickets"], dec_cols=["Concentration Ratio"])

    with st.expander("Full TAT bucket distribution (detail)"):
        st.markdown('<div class="section-sub">First Response TAT - Overall</div>', unsafe_allow_html=True)
        show_table(agg.tat_bucket_table(c, "FRBucket"), int_cols=["Ticket Count"], pct_cols=["% of Valid TAT Tickets"])
        st.markdown('<div class="section-sub">Resolution TAT - Overall</div>', unsafe_allow_html=True)
        show_table(agg.tat_bucket_table(c, "RESBucket"), int_cols=["Ticket Count"], pct_cols=["% of Valid TAT Tickets"])

        group_order = c["Group"].value_counts().index.tolist()
        type_order = c["Type"].value_counts().index.tolist()
        st.markdown('<div class="section-sub">First Response TAT Buckets by Group</div>', unsafe_allow_html=True)
        show_table(agg.tat_bucket_by_dim(c, "Group", "FRBucket", group_order), int_cols=TAT_BUCKETS + ["Valid TAT Count"])
        st.markdown('<div class="section-sub">Resolution TAT Buckets by Group</div>', unsafe_allow_html=True)
        show_table(agg.tat_bucket_by_dim(c, "Group", "RESBucket", group_order), int_cols=TAT_BUCKETS + ["Valid TAT Count"])
        st.markdown('<div class="section-sub">First Response TAT Buckets by Type</div>', unsafe_allow_html=True)
        show_table(agg.tat_bucket_by_dim(c, "Type", "FRBucket", type_order), int_cols=TAT_BUCKETS + ["Valid TAT Count"])
        st.markdown('<div class="section-sub">Resolution TAT Buckets by Type</div>', unsafe_allow_html=True)
        show_table(agg.tat_bucket_by_dim(c, "Type", "RESBucket", type_order), int_cols=TAT_BUCKETS + ["Valid TAT Count"])

    section("TAT Drivers & Actions", "Every flagged TAT finding, ranked by business impact - the Management "
            "Focus panel above is the top 5 of this same list.")
    if tat_insights_df.empty:
        st.caption("No segment currently meets the minimum volume + concentration thresholds for a flagged insight.")
    else:
        show_table(tat_insights_df, hide_index=True, height=380)


# --------------------------------------------------------------- Data Quality --
def render_data_quality(c: pd.DataFrame, raw: pd.DataFrame, mapping: pd.DataFrame, reps: list[str]) -> None:
    section("01. Ticket Total Reconciliation", "Every 'Diff' below should read 0.")
    show_table(dq.ticket_total_reconciliation(c, reps), int_cols=["Diff (should be 0)"])

    section("02. Backlog & TAT Reconciliation", "Every 'Diff' below should read 0.")
    show_table(dq.backlog_tat_reconciliation(c), int_cols=["Diff (should be 0)"])

    section("Informational - Negative TAT values excluded", "Expected to be small, not necessarily zero.")
    show_table(dq.excluded_tat_counts(raw), int_cols=["Count"])
    st.caption(f"Duplicate Ticket IDs in Raw Data (should be 0): {dq.duplicate_ticket_ids(c)}")

    section("03. Missing / Blank Field Rates")
    show_table(dq.missing_field_rates(c), int_cols=["Missing / Blank"], pct_cols=["% of Total Tickets"])


# ------------------------------------------------------------- Logic Validation --
LOGIC_VALIDATION_ROWS = [
    ("First Response TAT source columns",
     "Brief specifies Column P (Initial Response Time) minus Column I (Created Time).",
     "Column letters shift with export configuration - in a typical export, 'Initial response time' and "
     "'Created time' are not literally P and I.",
     "Matched by COLUMN NAME instead of letter: First Response TAT = 'Initial response time' - 'Created time'."),
    ("Resolution TAT source columns",
     "Brief specifies Column L (Resolved Time) minus Column I (Created Time).",
     "Same column-letter-drift issue as above.",
     "Matched by column NAME: Resolution TAT = 'Resolved time' - 'Created time'."),
    ("Raw pre-computed TAT (in hrs) columns",
     "These pre-computed columns look ready to use directly.",
     "They zero-fill tickets with no Initial Response / no Resolution instead of leaving them blank, and "
     "where a timestamp does exist the value often doesn't match simple elapsed time (likely a "
     "business-hours SLA calculation).",
     "TAT is recomputed directly from timestamps, excluding rows with a missing timestamp rather than "
     "trusting the pre-computed hour columns."),
    ("Negative TAT values",
     "Not addressed in raw data.",
     "A small number of tickets have a response/resolution timestamp earlier than the Created time "
     "(likely merged/relinked tickets).",
     "Negative TAT values are excluded from TAT calculations and bucket distributions (treated as missing, "
     "not as zero)."),
    ("TAT buckets",
     "An earlier formula reference used 5 buckets: <=1h, >1-4h, >4-24h, >24-72h, >72h.",
     "This brief specifies a different, more granular 7-bucket scheme.",
     "Uses the 7 buckets specified in this brief: <=1h, 1-4h, 4-8h, 8-16h, 16-20h, 20-24h, >24h "
     "(mutually exclusive, upper-bound inclusive)."),
    ("Group -> Type hierarchy",
     "Brief assumes Type is a clean subset of a single Group (each Type belongs to exactly one Group).",
     "In the raw data, most Types occur under more than one Group (e.g. 'Tech Queries' can appear under "
     "10+ different Groups) - Type is a general issue classification shared across teams, not "
     "Group-exclusive.",
     "The Group -> Type table is built on Group x Type COMBINATIONS rather than assuming one parent "
     "Group per Type, keeping roll-ups exact. Type Analysis additionally shows each Type's single "
     "largest-contributing 'Primary Group' for context."),
    ("Sales Person name casing",
     "Mapping sheet's 'Sales Person Name' values were assumed clean.",
     "The same person can appear under multiple casings (e.g. 'Pankaj Pareek' / 'pankaj Pareek'), which "
     "would fragment one person's workload into two rows.",
     "Names are normalized to title case (trimmed) during mapping cleanup so each person is counted once."),
    ("Sales mapping file size",
     "Uploaded mapping file treated as a simple lookup table.",
     "The file can contain many repeated rows for the same seller (a large historical export).",
     "Deduplicated to one row per Seller ID (first non-null Sales Person Name kept) before use."),
    ("Backlog status matching",
     "Backlog = Open + New + Pending + Re-Opened, matched on exact status text.",
     "A future upload could contain trimming/casing variants (e.g. 'open ', 'Reopened') that would "
     "silently fall outside an exact-match set.",
     "Backlog matching is case- and whitespace-insensitive, and recognizes both 'Re-Opened' and "
     "'Reopened' as the same status."),
    ("Backlog ageing 'as of' date",
     "Brief implies a fixed reference date for ageing.",
     "A hardcoded date would go stale the moment new raw data is loaded.",
     "AS_OF_DATE is computed live as end-of-day of the latest Created time in the currently loaded raw "
     "data, so ageing recalculates correctly on every upload."),
    ("'Waiting on Customer' status",
     "Brief's backlog definition lists Open, New, Pending, Re-Opened only.",
     "Raw data can also contain a 'Waiting on Customer' status, which is active/unresolved but not in "
     "the requested backlog set.",
     "Kept out of Backlog totals per the brief's literal definition, but shown separately in Overall "
     "Analysis so it isn't silently dropped from status reporting."),
]


def render_logic_validation() -> None:
    st.markdown(
        "Corrections made to the brief's assumed logic after inspecting the actual raw data. "
        "Only changed where the original would have been incorrect or misleading."
    )
    df = pd.DataFrame(LOGIC_VALIDATION_ROWS, columns=["Original Logic", "Issue Found", "Corrected Logic", "Reason"])
    st.dataframe(df, hide_index=True, use_container_width=True, height=560)


# ------------------------------------------------------------------ Detail ---
def render_detailed_data(c: pd.DataFrame) -> None:
    st.caption("Per-ticket computed fields (the code equivalent of the Excel 'Computed' sheet). "
               "Use the filters to narrow down, then download as CSV.")
    col1, col2, col3 = st.columns(3)
    with col1:
        groups = st.multiselect("Group", sorted(c["Group"].unique()))
    with col2:
        statuses = st.multiselect("Status", sorted(c["Status"].unique()))
    with col3:
        mapping_status = st.multiselect("Mapping Status", sorted(c["MappingStatus"].unique()))

    view = c.copy()
    if groups:
        view = view[view["Group"].isin(groups)]
    if statuses:
        view = view[view["Status"].isin(statuses)]
    if mapping_status:
        view = view[view["MappingStatus"].isin(mapping_status)]

    st.caption(f"{len(view):,} of {len(c):,} tickets shown")
    st.dataframe(view, hide_index=True, use_container_width=True, height=480)
    st.download_button("Download filtered data as CSV", view.to_csv(index=False).encode("utf-8"),
                        file_name="ticket_computed_data.csv", mime="text/csv")
