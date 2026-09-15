"""First Response / Resolution TAT-specific analysis: distributions, breach
counts, an end-to-end funnel, avg-vs-median and volume-vs-TAT diagnostics,
Group x Type heatmap data, status labels, and period-over-period "what
changed" comparisons.

Split out from performance.py (which ranks Group/Type by Resolution Rate)
because this is a different lens: the SHAPE of one TAT metric across the
population, not a Group/Type ranking. Every function here takes the
computed per-ticket DataFrame and returns plain pandas/dict output - no
Streamlit or plotting calls (those live in report.py and src/charts.py).
"""
from __future__ import annotations

import pandas as pd

from config import TAT_BUCKETS, TAT_DEVIATION_FLAG_PCT, TAT_LOW_SAMPLE_THRESHOLD
from src.trend_matrix import period_mask


def tat_kpis(c: pd.DataFrame, tat_col: str) -> dict:
    """Avg, median, valid count/coverage, and key threshold %s for one TAT
    column - the KPI-card numbers for the First Response / Resolution TAT
    sections. Every number here has a defined, valid-only population -
    never silently treating a missing timestamp as zero."""
    total = len(c)
    valid_mask = c[tat_col].notna()
    valid_n = int(valid_mask.sum())
    vals = c.loc[valid_mask, tat_col]
    return {
        "total": total, "valid": valid_n,
        "coverage": valid_n / total if total else 0.0,
        "avg": float(vals.mean()) if valid_n else float("nan"),
        "median": float(vals.median()) if valid_n else float("nan"),
        "pct_le_1h": float((vals <= 1).mean()) if valid_n else float("nan"),
        "pct_le_4h": float((vals <= 4).mean()) if valid_n else float("nan"),
        "pct_le_24h": float((vals <= 24).mean()) if valid_n else float("nan"),
        "pct_gt_24h": float((vals > 24).mean()) if valid_n else float("nan"),
        "count_gt_24h": int((vals > 24).sum()) if valid_n else 0,
        "pct_gt_72h": float((vals > 72).mean()) if valid_n else float("nan"),
        "count_gt_72h": int((vals > 72).sum()) if valid_n else 0,
    }


def worst_segment(c: pd.DataFrame, dim_col: str, tat_col: str, min_n: int = TAT_LOW_SAMPLE_THRESHOLD
                   ) -> tuple[str | None, float | None, int]:
    """The Group/Type with the highest MEDIAN tat_col among segments that
    meet the minimum valid-ticket sample - "meaningful" per the wireframe,
    so a tiny segment with one slow ticket can't claim this spot."""
    valid = c[c[tat_col].notna()]
    med = valid.groupby(dim_col, observed=True)[tat_col].median()
    n = valid.groupby(dim_col, observed=True)[tat_col].count()
    eligible = med[n >= min_n]
    if eligible.empty:
        return None, None, 0
    seg = eligible.idxmax()
    return seg, float(eligible[seg]), int(n[seg])


def distribution(c: pd.DataFrame, bucket_col: str) -> pd.DataFrame:
    """Count + % per TAT bucket - the stacked-bar distribution data."""
    vc = c[bucket_col].value_counts()
    total_valid = int(vc.sum())
    rows = [{"Bucket": b, "Count": int(vc.get(b, 0)),
             "Pct": (vc.get(b, 0) / total_valid) if total_valid else 0.0} for b in TAT_BUCKETS]
    return pd.DataFrame(rows)


def breach_counts(c: pd.DataFrame, tat_col: str, thresholds: list[int]) -> list[dict]:
    """[{'threshold': 24, 'count': N, 'pct': p}, ...] - pct is of the VALID
    population for that TAT column, not of all tickets."""
    valid_n = int(c[tat_col].notna().sum())
    out = []
    for h in thresholds:
        n = int((c[tat_col] > h).sum())
        out.append({"threshold": h, "count": n, "pct": n / valid_n if valid_n else 0.0})
    return out


def breach_tickets(c: pd.DataFrame, tat_col: str, threshold: float) -> pd.DataFrame:
    """The actual tickets breaching one threshold - drill-down for a
    breach card, sorted worst-first."""
    return c[c[tat_col] > threshold].sort_values(tat_col, ascending=False)


def funnel_stages(c: pd.DataFrame) -> list[dict]:
    """Ticket counts through the end-to-end TAT funnel: raised -> valid FR
    -> valid Resolution -> resolved<=24h -> resolved<=72h -> still
    backlog. Each stage carries its count and conversion % of the stage
    immediately before it."""
    total = len(c)
    valid_fr = int(c["FRTAT"].notna().sum())
    valid_res = int(c["RESTAT"].notna().sum())
    resolved_24 = int((c["RESTAT"] <= 24).sum())
    resolved_72 = int((c["RESTAT"] <= 72).sum())
    still_backlog = int(c["Backlog"].sum())

    stage_defs = [
        ("Total tickets raised", total, total),
        ("Valid First Response timestamp", valid_fr, total),
        ("Valid Resolution timestamp", valid_res, valid_fr or total),
        ("Resolved within 24h", resolved_24, valid_res or total),
        ("Resolved within 72h", resolved_72, valid_res or total),
        ("Still unresolved (current backlog)", still_backlog, total),
    ]
    return [{"Stage": label, "Count": count, "Conversion %": count / denom if denom else 0.0}
            for label, count, denom in stage_defs]


def diagnostic_bubbles(c: pd.DataFrame, dim_col: str, tat_col: str, min_n: int = TAT_LOW_SAMPLE_THRESHOLD
                        ) -> pd.DataFrame:
    """Per Group/Type: median TAT, avg TAT, valid ticket count, backlog
    rate - the avg-vs-median diagnostic bubble data. Segments under
    `min_n` valid tickets stay in (flagged Low Sample) rather than being
    dropped, so a real small-sample outlier is still visible, just marked."""
    valid = c[c[tat_col].notna()]
    med = valid.groupby(dim_col, observed=True)[tat_col].median()
    avg = valid.groupby(dim_col, observed=True)[tat_col].mean()
    n = valid.groupby(dim_col, observed=True)[tat_col].count()
    backlog_rate = c.groupby(dim_col, observed=True)["Backlog"].mean()
    out = pd.DataFrame({"Median TAT": med, "Avg TAT": avg, "Valid Tickets": n}).dropna()
    out["Backlog Rate"] = backlog_rate.reindex(out.index)
    out["Low Sample"] = out["Valid Tickets"] < min_n
    return out.reset_index().rename(columns={dim_col: "Segment"})


def volume_tat_scatter(c: pd.DataFrame, dim_col: str, tat_col: str) -> pd.DataFrame:
    """Per Group/Type: ticket volume, median TAT, current backlog, backlog
    % - the volume-vs-TAT scatter data (the chart layer draws the 4-zone
    split at the median volume / management threshold)."""
    total = c.groupby(dim_col, observed=True).size()
    valid = c[c[tat_col].notna()]
    med = valid.groupby(dim_col, observed=True)[tat_col].median()
    backlog = c.groupby(dim_col, observed=True)["Backlog"].sum()
    out = pd.DataFrame({"Volume": total, "Median TAT": med, "Backlog": backlog}).dropna(subset=["Median TAT"])
    out["Backlog %"] = out["Backlog"] / out["Volume"]
    return out.reset_index().rename(columns={dim_col: "Segment"})


def heatmap_data(c: pd.DataFrame, tat_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group x Type median TAT pivot, and a same-shape valid-count pivot
    (used to flag low-sample cells) - the heatmap data."""
    valid = c[c[tat_col].notna()]
    med = valid.pivot_table(index="Group", columns="Type", values=tat_col, aggfunc="median")
    cnt = valid.pivot_table(index="Group", columns="Type", values=tat_col, aggfunc="count")
    return med, cnt


def status_label(volume: int, backlog_rate: float, tat: float, bm_tat: float, valid_n: int,
                  min_n: int = TAT_LOW_SAMPLE_THRESHOLD, min_volume: int = 20) -> str:
    """One of: Low Sample - Validate / No Baseline Available / Critical /
    Action Required / Watch / On Track. Low-sample takes priority over
    everything else - nothing downstream is trustworthy below the sample
    floor regardless of how extreme it looks."""
    if valid_n < min_n or volume < min_volume:
        return "Low Sample - Validate"
    if pd.isna(tat) or pd.isna(bm_tat) or bm_tat == 0:
        return "No Baseline Available"
    tat_dev = (tat - bm_tat) / bm_tat
    high_vol = volume >= min_volume * 2
    if high_vol and backlog_rate >= 0.30 and tat_dev >= TAT_DEVIATION_FLAG_PCT:
        return "Critical"
    if backlog_rate >= 0.30 or tat_dev >= TAT_DEVIATION_FLAG_PCT:
        return "Action Required"
    if backlog_rate >= 0.15 or tat_dev >= TAT_DEVIATION_FLAG_PCT / 2:
        return "Watch"
    return "On Track"


_WHAT_CHANGED_METRICS = [
    "Avg First Resp TAT (hrs)", "Median Resolution TAT (hrs)", "Total Backlog", "Pending Backlog",
    ">24h First Response Tickets", ">72h Resolution Tickets", ">7-day Backlog",
]
_AGED_7PLUS = ("7-14 Days", "14-30 Days", ">30 Days")


def _period_metrics(sub: pd.DataFrame) -> dict:
    bl = sub[sub["Backlog"] == 1]
    status_norm = sub["Status"].astype(str).str.upper().str.strip()
    return {
        "Avg First Resp TAT (hrs)": sub["FRTAT"].mean(),
        "Median Resolution TAT (hrs)": sub["RESTAT"].median(),
        "Total Backlog": float(sub["Backlog"].sum()),
        "Pending Backlog": float((status_norm == "PENDING").sum()),
        ">24h First Response Tickets": float((sub["FRTAT"] > 24).sum()),
        ">72h Resolution Tickets": float((sub["RESTAT"] > 72).sum()),
        ">7-day Backlog": float(bl["AgeBucket"].isin(_AGED_7PLUS).sum()),
    }


def what_changed(c: pd.DataFrame, current_mask: pd.Series, previous_mask: pd.Series) -> pd.DataFrame:
    """Previous-period vs current-period comparison for the headline
    metrics the wireframe wants surfaced every reporting cycle - lower is
    better for every metric in this list, so the Interpretation is a
    simple Improved/Worsened/Flat, no per-metric direction logic needed.
    If either period is empty, every row reads "Baseline not available"
    rather than showing a misleading 0 or NaN delta."""
    cur, prev = c[current_mask], c[previous_mask]
    if cur.empty or prev.empty:
        return pd.DataFrame([{"Metric": m, "Previous": None, "Current": None, "Change": None,
                               "% Change": None, "Interpretation": "Baseline not available"}
                              for m in _WHAT_CHANGED_METRICS])
    cur_m, prev_m = _period_metrics(cur), _period_metrics(prev)
    rows = []
    for label in _WHAT_CHANGED_METRICS:
        c_val, p_val = cur_m[label], prev_m[label]
        if pd.isna(c_val) or pd.isna(p_val):
            rows.append({"Metric": label, "Previous": None, "Current": None, "Change": None,
                         "% Change": None, "Interpretation": "Baseline not available"})
            continue
        delta = c_val - p_val
        pct = (delta / p_val) if p_val else None
        interp = "Improved" if delta < 0 else ("Worsened" if delta > 0 else "Flat")
        rows.append({"Metric": label, "Previous": p_val, "Current": c_val,
                     "Change": delta, "% Change": pct, "Interpretation": interp})
    return pd.DataFrame(rows)


def monthly_trend(c: pd.DataFrame, periods: list[tuple], tat_col: str, min_n: int = 10) -> pd.DataFrame:
    """Avg/Median tat_col for M-3 -> M-2 -> M-1 -> MTD. Avg/Median are None
    (not 0 or a misleading single-ticket value) where a period has fewer
    than `min_n` valid tickets, so the line chart breaks there instead of
    drawing a trend through a near-empty period."""
    plabels = {p[0]: (p[1], p[2]) for p in periods}
    rows = []
    for label in ("M-3", "M-2", "M-1", "MTD"):
        if label not in plabels:
            continue
        start, end = plabels[label]
        sub = c[period_mask(c, start, end)]
        vals = sub[tat_col].dropna()
        n = len(vals)
        rows.append({
            "Period": label, "Valid Count": n,
            "Avg": float(vals.mean()) if n >= min_n else None,
            "Median": float(vals.median()) if n >= min_n else None,
        })
    return pd.DataFrame(rows)


def confidence_label(valid: int, total: int) -> tuple[str, str]:
    """('High'/'Moderate'/'Low', formatted caption) - the data-confidence
    indicator shown under every TAT KPI so a number computed on a small or
    incomplete sample is never mistaken for a definitive read."""
    coverage = valid / total if total else 0.0
    if coverage >= 0.80:
        level = "High"
    elif coverage >= 0.50:
        level = "Moderate"
    else:
        level = "Low"
    return level, f"valid population {valid:,}/{total:,} ({coverage:.1%}) - confidence: {level.lower()}"
