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

from src import data_quality as dq
from src import performance as perf
from src import seller_analysis as sa
from src import trend_matrix as tm
from src.logic_validation import LOGIC_VALIDATION_ROWS
from src.styling import (
    bar_ranking, color_legend, fmt_hrs, fmt_int, fmt_pct, kpi_row, movement_badge,
    priority_badge, section, show_matrix, show_table,
)

FLAG_COLOR = {"High Priority": tm.RED, "Medium Priority": tm.AMBER, "Opportunity": tm.GREEN}
RANK_COLS = ["Total Raised", "Resolution Rate", "RR vs Benchmark (pp)",
             "Median First Resp TAT", "Median Resolution TAT", "Flag"]


def _reps(mapping: pd.DataFrame, team_data: pd.DataFrame | None, team_lists: pd.DataFrame | None) -> list[str]:
    reps = set(mapping["_sales_person_norm"].dropna().unique().tolist())
    if team_data is not None:
        reps |= set(team_data["_sales_person_norm"].dropna().unique().tolist())
    if team_lists is not None:
        reps |= set(team_lists["_sales_person_norm"].dropna().unique().tolist())
    return sorted(reps)


def _week_over_week(c_f: pd.DataFrame, periods_map: dict) -> tuple[float, float]:
    """(Resolution Rate delta, Backlog % delta) between W-1 and W-2 - the
    'major movement' callout at CRO level. NaN if either week has no data."""
    w1 = c_f[tm.period_mask(c_f, *periods_map["W-1"])]
    w2 = c_f[tm.period_mask(c_f, *periods_map["W-2"])]
    if w1.empty or w2.empty:
        return float("nan"), float("nan")
    rr_delta = (1 - w1["Backlog"].mean()) - (1 - w2["Backlog"].mean())
    bl_delta = w1["Backlog"].mean() - w2["Backlog"].mean()
    return rr_delta, bl_delta


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


def _ranking_table(perf_df: pd.DataFrame, label_col: str) -> None:
    ranked = perf_df.sort_values("RR vs Benchmark (pp)", ascending=False)
    display = ranked[[label_col] + RANK_COLS]
    row_colors = ranked["Flag"].map(FLAG_COLOR)
    show_table(display, pct_cols=["Resolution Rate", "RR vs Benchmark (pp)"], int_cols=["Total Raised"],
               dec_cols=["Median First Resp TAT", "Median Resolution TAT"],
               row_colors=row_colors, height=min(420, 38 * len(display) + 40))


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
    section("CRO — Executive Overview", "Topline performance for the current selection.")
    kpi_row([
        ("TOTAL TICKETS", fmt_int(bm_scope.total)),
        ("BACKLOG %", fmt_pct(bm_scope.total_backlog / bm_scope.total if bm_scope.total else 0)),
        ("RESOLUTION RATE", fmt_pct(bm_scope.resolution_rate)),
        ("MEDIAN FIRST RESP TAT (hrs)", fmt_hrs(bm_scope.median_fr_tat)),
        ("MEDIAN RESOLUTION TAT (hrs)", fmt_hrs(bm_scope.median_res_tat)),
    ])

    rr_delta, bl_delta = _week_over_week(c_f, periods_map)
    mc1, mc2 = st.columns(2)
    with mc1:
        st.markdown(
            f'<div class="kf-card"><div class="kf-label">Resolution Rate - this week vs last</div>'
            f'<div class="kf-text">{movement_badge(rr_delta, higher_is_better=True)}</div></div>',
            unsafe_allow_html=True)
    with mc2:
        st.markdown(
            f'<div class="kf-card"><div class="kf-label">Backlog % - this week vs last</div>'
            f'<div class="kf-text">{movement_badge(bl_delta, higher_is_better=False)}</div></div>',
            unsafe_allow_html=True)

    st.markdown('<div class="section-sub">Needs Attention</div>', unsafe_allow_html=True)
    if selected_group == "All Groups":
        st.markdown(_attention_html(grp_perf, "Group"), unsafe_allow_html=True)
    else:
        st.markdown(_attention_html(typ_perf, "Type"), unsafe_allow_html=True)

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

    # =============================================================== HOD ===
    hod_note = ("Which Groups are performing well, and which need attention." if selected_group == "All Groups"
                else f"Filtered to <b>{selected_group}</b> - select \"All Groups\" above to compare across Groups.")
    section("HOD — Group Performance", hod_note)
    _best_worst_html(*perf.best_worst(grp_perf, "Group", n=3), "Group")
    _ranking_table(grp_perf, "Group")

    with st.expander("Group Performance — Time Period Trend"):
        group_labels = grp_perf["Group"].tolist()
        gtrend_rows = tm.segment_trend_rows(c_f, "Group", group_labels, periods, bm_company)
        gtdata, gtcolors = tm.build_matrix(gtrend_rows, periods)
        show_matrix(gtdata, gtcolors, height=min(680, 36 * len(gtrend_rows) + 40))

    # ================================================================ L1 ===
    l1_scope_note = f"within <b>{selected_group}</b>" if selected_group != "All Groups" else "across all Groups"
    section("L1 — Type Performance", f"Which Types are performing well, and which need attention, {l1_scope_note}.")
    _best_worst_html(*perf.best_worst(typ_perf, "Type", n=3), "Type")
    _ranking_table(typ_perf, "Type")

    with st.expander("Type Performance — Time Period Trend"):
        type_labels = typ_perf["Type"].tolist()
        ttrend_rows = tm.segment_trend_rows(c_f, "Type", type_labels, periods, bm_company)
        ttdata, ttcolors = tm.build_matrix(ttrend_rows, periods)
        show_matrix(ttdata, ttcolors, height=min(680, 36 * len(ttrend_rows) + 40))

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
