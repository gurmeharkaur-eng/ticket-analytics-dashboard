"""The single-page report - MIS matrix format: metrics/segments as rows,
time periods (D-1..D-7, W-1..W-4, MTD, M-1..M-3) as columns, color-coded red
/ amber / green against the same benchmark and thresholds used throughout
the app. Replaces the earlier card-based diagnostic layout at the user's
explicit direction, modeled on their own Freshdesk MIS report format with
color-coding and our Group/Type/Sales Person/Seller cuts layered in.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import data_quality as dq
from src import performance as perf
from src import seller_analysis as sa
from src import trend_matrix as tm
from src.logic_validation import LOGIC_VALIDATION_ROWS
from src.styling import color_legend, fmt_hrs, fmt_int, fmt_pct, kpi_row, section, show_matrix, show_table


def render(c: pd.DataFrame, as_of: pd.Timestamp, reps: list[str], mapping: pd.DataFrame,
           raw: pd.DataFrame, team_data: pd.DataFrame | None, team_lists: pd.DataFrame | None) -> None:
    bm = perf.compute_benchmark(c)
    total = len(c)
    coverage = sa.seller_mapping_coverage(c)
    periods = tm.period_definitions(as_of)
    pcoverage = tm.period_coverage(c, periods)

    # ---------------------------------------------------------------- Header --
    st.title("Support Performance Report")
    period_str = f"{c['Created'].min():%d-%b-%Y} to {c['Created'].max():%d-%b-%Y}"
    st.caption(f"Data as of **{as_of:%d-%b-%Y %H:%M}** | Raw data loaded covers: {period_str}")
    kpi_row([
        ("TOTAL TICKETS", fmt_int(total)),
        ("BACKLOG %", fmt_pct(bm.total_backlog / bm.total if bm.total else 0)),
        ("RESOLUTION RATE", fmt_pct(bm.resolution_rate)),
        ("MEDIAN RESOLUTION TAT (hrs)", fmt_hrs(bm.median_res_tat)),
        ("MEDIAN FIRST RESP TAT (hrs)", fmt_hrs(bm.median_fr_tat)),
        ("TICKETS MAPPED TO A SELLER OWNER", fmt_pct(coverage["mapped_pct"])),
    ])

    color_legend()
    empty_periods = [label for label, n in pcoverage.items() if n == 0]
    if empty_periods:
        st.markdown(
            f'<div class="note">No tickets in the loaded raw data fall in: {", ".join(empty_periods)} - '
            f'shown as "-", not a misleading 0%. Upload a longer trailing history to populate these; the '
            f'table structure won\'t need to change.</div>',
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------- Overall Matrix --
    section("Overall Performance - Time Period Trend")
    st.markdown(
        '<div class="note">D-1 and D-2 rate/TAT cells are shown uncolored on purpose: most of "today" and '
        '"yesterday"\'s tickets haven\'t had time to resolve yet, so Resolution Rate reads artificially low '
        'and Median TAT of the few already-resolved ones reads artificially fast - neither reflects true '
        'performance yet. Volume/count cells are unaffected. TAT figures exclude Sunday (non-working day) '
        '- see Logic Validation.</div>',
        unsafe_allow_html=True,
    )
    overall_rows = tm.overall_matrix_rows(c, periods, bm)
    data, colors = tm.build_matrix(overall_rows, periods)
    show_matrix(data, colors)

    # ----------------------------------------------- Group -> Type -> Sales Person --
    grp_labels = perf.curate(perf.group_rollup_performance(c, bm), n=6)["Group"].tolist()
    section("Group -> Type -> Sales Person: First Response TAT - Time Period Trend",
            "One table, not three: Type is a subset of Group, and each Sales Person's work within a Group x "
            "Type is a further subset - shown nested rather than as three disconnected cuts. Curated: top "
            "Groups by volume, their top Types, and the Sales Persons driving each Type.")
    fr_rows = tm.group_type_person_hierarchy_rows(c, periods, "FRTAT", bm.median_fr_tat, grp_labels)
    frdata, frcolors = tm.build_matrix(fr_rows, periods)
    show_matrix(frdata, frcolors, height=680)
    st.caption("Segment color: dark = Group, blue = Type, purple = Sales Person.")

    section("Group -> Type -> Sales Person: Resolution TAT - Time Period Trend",
            "Same hierarchy, Resolution TAT instead of First Response TAT.")
    res_rows = tm.group_type_person_hierarchy_rows(c, periods, "RESTAT", bm.median_res_tat, grp_labels)
    resdata, rescolors = tm.build_matrix(res_rows, periods)
    show_matrix(resdata, rescolors, height=680)
    st.caption("Segment color: dark = Group, blue = Type, purple = Sales Person.")

    # --------------------------------------------------------------- Seller Matrix --
    section("Seller Performance - Time Period Trend", "Top sellers by ticket volume (real Seller IDs only).")
    seller_labels = sa.top_sellers_overall(c, n=10)
    seller_rows = tm.segment_trend_rows(c, "SellerLabel", seller_labels, periods, bm)
    seldata, selcolors = tm.build_matrix(seller_rows, periods)
    show_matrix(seldata, selcolors, height=680)

    section("Seller Problem Table", f"Every Group x Type x Seller combination with >= {sa.MIN_SEGMENT_VOLUME} "
            "tickets - not filtered down to a shortlist. Row color marks the problem: "
            "red = High-volume underperformer (fix first), amber = Low-volume outlier (real, limited impact "
            "today), green = Healthy. Uncolored = Typical / near benchmark.")
    gts = sa.group_type_seller_table(c, bm=bm).sort_values("Impact Score", ascending=False).reset_index(drop=True)
    if gts.empty:
        st.caption(f"No Group x Type x Seller combination currently reaches {sa.MIN_SEGMENT_VOLUME} tickets.")
    else:
        status_color = {"High-volume underperformer": tm.RED, "Low-volume outlier": tm.AMBER, "Healthy": tm.GREEN}
        display = gts[["Group", "Type", "SellerLabel", "SalesPerson", "Team", "Tickets",
                        "Avg Resolution TAT", "Backlog %", ">16h", ">24h", "Status"]] \
            .rename(columns={"SellerLabel": "Seller"})
        row_colors = gts["Status"].map(status_color)
        show_table(display, int_cols=["Tickets", ">16h", ">24h"], pct_cols=["Backlog %"],
                   dec_cols=["Avg Resolution TAT"], height=500, row_colors=row_colors)

    # ----------------------------------------------------------- Priority Actions --
    section("Priority Actions", "Mined from the current snapshot, ranked by business impact "
            "(volume affected x performance gap vs benchmark).")
    perf_insights = perf.mine_actionable_insights(c, reps, bm)
    seller_insights = sa.mine_seller_insights(c, bm)
    all_insights = pd.concat([perf_insights, seller_insights], ignore_index=True) if len(seller_insights) else perf_insights
    if not all_insights.empty:
        priority_rank = {"High Priority": 0, "Medium Priority": 1, "Opportunity": 2}
        all_insights = all_insights.assign(_prank=all_insights["Priority"].map(priority_rank)) \
            .sort_values(["_prank", "_impact"], ascending=[True, False]).drop(columns=["_prank", "_impact"])
        show_table(all_insights.drop(columns=["Owner / Segment"]), hide_index=True, height=420)
    else:
        st.caption("No segment currently meets the minimum volume + deviation thresholds for a flagged insight.")

    # ----------------------------------------------------- Collapsed detail --
    with st.expander("Data Quality - reconciliation checks"):
        show_table(dq.ticket_total_reconciliation(c, reps), int_cols=["Diff (should be 0)"])
        show_table(dq.backlog_tat_reconciliation(c), int_cols=["Diff (should be 0)"])
        st.caption(f"Seller mapping coverage: {coverage['mapped']:,} mapped, "
                   f"{coverage['unmapped_seller']:,} unmapped seller, {coverage['no_seller_id']:,} no seller ID "
                   f"(of {coverage['total']:,} total tickets).")
        if team_data is not None:
            meta = team_data.attrs.get("dedup_meta", {})
            st.caption(f"Team Level Data: {meta.get('unique_sellers', '?'):,} unique sellers loaded "
                       f"({meta.get('conflicting_rows', 0)} rows had a conflicting duplicate Seller ID - "
                       "most recent month kept).")
        show_table(dq.missing_field_rates(c), int_cols=["Missing / Blank"], pct_cols=["% of Total Tickets"])

    with st.expander("Logic Validation - corrections made to the brief's assumed logic"):
        st.dataframe(pd.DataFrame(LOGIC_VALIDATION_ROWS,
                                   columns=["Original Logic", "Issue Found", "Corrected Logic", "Reason"]),
                     hide_index=True, use_container_width=True, height=400)

    with st.expander("Detailed per-ticket data"):
        st.dataframe(c, hide_index=True, use_container_width=True, height=420)
        st.download_button("Download computed data as CSV", c.to_csv(index=False).encode("utf-8"),
                            file_name="ticket_computed_data.csv", mime="text/csv")
