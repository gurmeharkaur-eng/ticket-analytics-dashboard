"""The single consolidated report - one continuous page, no tabs. Replaces
the earlier multi-tab layout. Combines Group, Type, Sales Person, Seller and
TAT analysis into one management-report information architecture:
KPI strip -> Executive Summary -> Top 5 Problems -> Group -> Type -> Seller
hierarchy -> TAT Analysis -> Seller Problem Table -> Key Actions, with
Data Quality and Logic Validation demoted to collapsed sections at the
bottom (still there, just not competing for attention).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import MIN_SEGMENT_VOLUME
from src import aggregations as agg
from src import data_quality as dq
from src import performance as perf
from src import seller_analysis as sa
from src import tat_diagnostics as tatd
from src.logic_validation import LOGIC_VALIDATION_ROWS
from src.styling import fmt_hrs, fmt_int, fmt_pct, kpi_row, priority_badge, section, show_table

SEVERITY_BADGE = {
    "Critical": ("badge-high", "\U0001F534"),
    "Attention": ("badge-medium", "\U0001F7E0"),
    "Watch": ("badge-medium", "\U0001F7E1"),
    "Healthy": ("badge-opportunity", "\U0001F7E2"),
}


def _severity_badge(label: str) -> str:
    cls, dot = SEVERITY_BADGE.get(label, ("badge-medium", ""))
    return f'<span class="badge {cls}">{dot} {label}</span>'


def _all_problem_insights(c: pd.DataFrame, reps: list[str], bm) -> pd.DataFrame:
    """Group x Type, Sales Rep, Sales Rep x Group, and Seller findings,
    combined into one impact-ranked list. This is the shared pool that Top 5
    Problems, Executive Summary and Key Actions all draw from, so the report
    tells one consistent story rather than three separately-ranked lists."""
    perf_insights = perf.mine_actionable_insights(c, reps, bm)
    seller_insights = sa.mine_seller_insights(c, bm)
    combined = pd.concat([perf_insights, seller_insights], ignore_index=True) if len(seller_insights) else perf_insights
    if combined.empty:
        return combined
    priority_rank = {"High Priority": 0, "Medium Priority": 1, "Opportunity": 2}
    combined = combined.assign(_prank=combined["Priority"].map(priority_rank)) \
        .sort_values(["_prank", "_impact"], ascending=[True, False]).drop(columns="_prank")
    return combined.reset_index(drop=True)


def _classify_severity(all_insights: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Buckets the already-priority-ranked combined list into the four
    report-level severity tiers - a display grouping of the same
    Priority/Impact computation used everywhere else, not a new threshold."""
    if all_insights.empty:
        return {k: all_insights for k in ("Critical", "Attention", "Watch", "Healthy")}
    high = all_insights[all_insights["Priority"] == "High Priority"]
    medium = all_insights[all_insights["Priority"] == "Medium Priority"]
    opportunity = all_insights[all_insights["Priority"] == "Opportunity"]
    return {
        "Critical": high.head(3),
        "Attention": pd.concat([high.iloc[3:6], medium.head(2)]),
        "Watch": medium.iloc[2:5],
        "Healthy": opportunity.head(3),
    }


def _hierarchy_row(label: str, tickets, pct, avg_tat, backlog_pct, rr_dev, indent: int = 0) -> str:
    flag = ""
    if rr_dev is not None:
        if rr_dev <= -0.10:
            flag = "\U0001F534 "
        elif rr_dev >= 0.10:
            flag = "\U0001F7E2 "
    pad = "&nbsp;&nbsp;&nbsp;&nbsp;" * indent
    pct_txt = f" ({pct:.1%} of total)" if pct is not None else ""
    dev_txt = f", {rr_dev * 100:+.1f}pp vs benchmark" if rr_dev is not None else ""
    tat_txt = f"{avg_tat:.1f}h avg TAT" if pd.notna(avg_tat) else "no resolved tickets yet"
    return (f'<div style="font-size:0.82rem;padding:2px 0">{pad}{flag}<b>{label}</b> - {tickets:,.0f} tickets'
            f'{pct_txt} | {tat_txt} | {backlog_pct:.1%} backlog{dev_txt}</div>')


def render(c: pd.DataFrame, as_of: pd.Timestamp, reps: list[str], mapping: pd.DataFrame,
           raw: pd.DataFrame, team_data: pd.DataFrame | None, team_lists: pd.DataFrame | None) -> None:
    bm = perf.compute_benchmark(c)
    total = len(c)
    coverage = sa.seller_mapping_coverage(c)

    # ---------------------------------------------------------------- Header --
    st.title("Support Performance Report")
    period = f"{c['Created'].min():%d-%b-%Y} to {c['Created'].max():%d-%b-%Y}"
    st.caption(f"Data as of **{as_of:%d-%b-%Y %H:%M}** | Report period: {period}")
    kpi_row([
        ("TOTAL TICKETS", fmt_int(total)),
        ("BACKLOG %", fmt_pct(bm.total_backlog / bm.total if bm.total else 0)),
        ("RESOLUTION RATE", fmt_pct(bm.resolution_rate)),
        ("AVG RESOLUTION TAT (hrs)", fmt_hrs(bm.avg_res_tat)),
        ("AVG FIRST RESP TAT (hrs)", fmt_hrs(bm.avg_fr_tat)),
        ("TICKETS MAPPED TO A SELLER OWNER", fmt_pct(coverage["mapped_pct"])),
    ])

    all_insights = _all_problem_insights(c, reps, bm)
    tiers = _classify_severity(all_insights)

    # ------------------------------------------------------- Executive Summary --
    section("Executive Summary")
    for tier in ("Critical", "Attention", "Watch", "Healthy"):
        rows = tiers[tier]
        if rows.empty:
            continue
        st.markdown(_severity_badge(tier), unsafe_allow_html=True)
        for _, row in rows.iterrows():
            st.markdown(f'<div style="font-size:0.82rem;padding:2px 0 6px 4px">{row["Finding"]}</div>',
                        unsafe_allow_html=True)

    # ----------------------------------------------------------- Top 5 Problems --
    section("Top 5 Problems", "Ranked by business impact (volume affected x performance gap vs benchmark).")
    problems = all_insights[all_insights["Priority"] != "Opportunity"].head(5)
    if problems.empty:
        st.caption("No segment currently crosses the minimum volume + deviation thresholds.")
    for _, row in problems.iterrows():
        st.markdown(
            f'{priority_badge(row["Priority"])}&nbsp;&nbsp;<span style="font-size:0.7rem;color:#6B7280;'
            f'text-transform:uppercase;font-weight:700">{row["Area"]}</span>&nbsp;&nbsp;'
            f'<b>{row["Owner / Segment"]}</b><br>'
            f'<span style="font-size:0.8rem">{row["Finding"]}</span><br>'
            f'<span style="font-size:0.78rem;color:#374151">{row["Evidence"]}</span>',
            unsafe_allow_html=True,
        )
        st.markdown("<hr style='margin:6px 0;border-color:#E5E7EB'>", unsafe_allow_html=True)

    # --------------------------------------------------- Group -> Type -> Seller --
    section("Group -> Type -> Seller", "Curated: top Groups by volume (plus any flagged Group even if smaller), "
            "their top Types, and the Sellers driving each Type where volume is meaningful "
            f"(>= {MIN_SEGMENT_VOLUME} tickets in that exact Group x Type x Seller cell).")
    grp_perf = perf.group_rollup_performance(c, bm)
    grp_curated = perf.curate(grp_perf, n=5)
    gts = sa.group_type_seller_table(c, bm=bm)

    for _, grow in grp_curated.iterrows():
        st.markdown(_hierarchy_row(grow["Group"], grow["Total Raised"], grow["% of Total"],
                                    grow["Avg Resolution TAT"], grow["% Backlog"], grow["RR vs Benchmark (pp)"]),
                    unsafe_allow_html=True)
        gt_perf = perf.group_type_performance(c, bm)
        gt_this_group = gt_perf[gt_perf["Group"] == grow["Group"]]
        gt_this_group_curated = perf.curate(gt_this_group, n=3)
        for _, trow in gt_this_group_curated.iterrows():
            st.markdown(_hierarchy_row(trow["Type"], trow["Total Raised"], trow["% of Group"],
                                        trow["Avg Resolution TAT"], trow["% Backlog"], trow["RR vs Benchmark (pp)"],
                                        indent=1), unsafe_allow_html=True)
            sellers = sa.top_sellers_for(gts, grow["Group"], trow["Type"], n=3)
            for _, srow in sellers.iterrows():
                sp_note = f" | {srow['SalesPerson']} ({srow['Team']})"
                st.markdown(_hierarchy_row(f"{srow['SellerLabel']}{sp_note}", srow["Tickets"], None,
                                            srow["Avg Resolution TAT"], srow["Backlog %"],
                                            srow["RR vs Benchmark (pp)"], indent=2), unsafe_allow_html=True)
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ------------------------------------------------------------ TAT Analysis --
    section("TAT Analysis", "Resolution TAT bucket distribution - long-TAT buckets highlighted.")
    res_bt = agg.tat_bucket_table(c, "RESBucket")
    res_bt = res_bt.iloc[:-1].copy()  # drop the "VALID TAT TICKETS" summary row for this compact view
    res_bt["Bucket"] = res_bt["Bucket"].apply(lambda b: ("\U0001F534 " if b in (">24h",) else
                                                          "\U0001F7E0 " if b in ("20-24h", "16-20h") else "") + b)
    show_table(res_bt, int_cols=["Ticket Count"], pct_cols=["% of Valid TAT Tickets"])

    # ------------------------------------------------------ Seller Problem Table --
    section("Seller Problem Table", "Only sellers with meaningful volume in a given Group x Type. "
            "High-volume underperformer = fix first; Low-volume outlier = real, but limited impact today.")
    problem_sellers = gts[gts["Status"].isin(["High-volume underperformer", "Low-volume outlier"])] \
        .sort_values("Impact Score", ascending=False).head(20)
    if problem_sellers.empty:
        st.caption("No seller currently meets the problem thresholds.")
    else:
        show_table(
            problem_sellers[["Group", "Type", "SellerLabel", "SalesPerson", "Team", "Tickets",
                              "Avg Resolution TAT", "Backlog %", ">16h", ">24h", "Status"]]
            .rename(columns={"SellerLabel": "Seller"}),
            int_cols=["Tickets", ">16h", ">24h"], pct_cols=["Backlog %"], dec_cols=["Avg Resolution TAT"],
            height=420,
        )

    # --------------------------------------------------------------- Key Actions --
    section("Key Actions / Takeaways")
    action_pool = all_insights[all_insights["Priority"] != "Opportunity"].head(6)
    if action_pool.empty:
        st.caption("No priority actions currently flagged.")
    for i, (_, row) in enumerate(action_pool.iterrows(), start=1):
        st.markdown(f'<div class="finding">{i}. <b>{row["Owner / Segment"]}</b> - {row["Recommended Action"]}</div>',
                    unsafe_allow_html=True)

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
