"""Plotly figure builders for the TAT distribution / diagnostic / heatmap /
funnel / trend visuals. Kept separate from tat_analysis.py (data prep, no
plotting) and report.py (page layout, no chart internals) so each stays
focused - this module takes already-computed pandas data and returns a
plotly Figure, nothing else.

Every figure uses a compact height and the same muted red/amber/green
palette as the rest of the app (trend_matrix.RED/AMBER/GREEN) so a chart
never disagrees visually with a table cell right next to it. These are
decision-support visuals meant to sit in a dense dashboard, not slides -
small margins, small fonts, minimal legend chrome.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

RED = "#EF4444"
AMBER = "#F59E0B"
GREEN = "#22C55E"
GRAY = "#9CA3AF"
BUCKET_COLORS = ["#166534", "#22C55E", "#86EFAC", "#FDE68A", "#FB923C", "#F87171", "#B91C1C"]

_BASE_LAYOUT = dict(
    margin=dict(l=8, r=8, t=8, b=8),
    font=dict(size=11, family="sans-serif"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
)


def _severity_color(backlog_rate: float) -> str:
    if pd.isna(backlog_rate):
        return GRAY
    if backlog_rate >= 0.30:
        return RED
    if backlog_rate >= 0.15:
        return AMBER
    return GREEN


def stacked_distribution_bar(dist_df: pd.DataFrame, row_label: str) -> go.Figure:
    """One 100%-stacked horizontal bar, one segment per TAT bucket."""
    fig = go.Figure()
    for i, row in dist_df.iterrows():
        fig.add_trace(go.Bar(
            y=[row_label], x=[row["Pct"]], name=row["Bucket"], orientation="h",
            marker_color=BUCKET_COLORS[i % len(BUCKET_COLORS)],
            customdata=[[row["Bucket"], row["Count"], row["Pct"]]],
            hovertemplate="%{customdata[0]}: %{customdata[1]:,} tickets (%{customdata[2]:.1%})<extra></extra>",
            text=f'{row["Pct"]:.0%}' if row["Pct"] >= 0.06 else "",
            textposition="inside", insidetextanchor="middle", textfont=dict(size=9, color="#111827"),
        ))
    fig.update_layout(
        barmode="stack", xaxis=dict(tickformat=".0%", range=[0, 1], showgrid=False),
        yaxis=dict(visible=False), showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.05, font=dict(size=9)),
        height=130, **_BASE_LAYOUT,
    )
    return fig


def diagnostic_scatter(bubble_df: pd.DataFrame, threshold_hours: float) -> go.Figure:
    """Median (x) vs Average (y) TAT per segment - bubble size = valid
    ticket count, color = backlog-rate severity, gray = low sample."""
    max_n = bubble_df["Valid Tickets"].max() or 1
    colors = [GRAY if low else _severity_color(br) for low, br in
              zip(bubble_df["Low Sample"], bubble_df["Backlog Rate"])]
    fig = go.Figure(go.Scatter(
        x=bubble_df["Median TAT"], y=bubble_df["Avg TAT"], mode="markers+text",
        text=bubble_df["Segment"], textposition="top center", textfont=dict(size=9),
        marker=dict(size=(bubble_df["Valid Tickets"] / max_n * 36 + 8), color=colors,
                    line=dict(width=1, color="white")),
        customdata=bubble_df[["Segment", "Median TAT", "Avg TAT", "Valid Tickets", "Backlog Rate"]].values,
        hovertemplate=("%{customdata[0]}<br>Median %{customdata[1]:.1f}h, Avg %{customdata[2]:.1f}h"
                        "<br>%{customdata[3]} valid tickets, %{customdata[4]:.0%} backlog<extra></extra>"),
    ))
    fig.add_vline(x=threshold_hours, line=dict(color="#6B7280", dash="dash", width=1))
    fig.add_hline(y=threshold_hours, line=dict(color="#6B7280", dash="dash", width=1))
    fig.update_layout(xaxis_title="Median TAT (hrs)", yaxis_title="Avg TAT (hrs)",
                       showlegend=False, height=320, **_BASE_LAYOUT)
    return fig


def volume_tat_scatter_chart(scatter_df: pd.DataFrame, threshold_hours: float) -> go.Figure:
    """Volume (x) vs Median TAT (y) per segment - the 4-zone structural-
    priority view. Bubble size = current backlog, color = backlog-rate
    severity."""
    vol_median = scatter_df["Volume"].median()
    max_backlog = scatter_df["Backlog"].max() or 1
    colors = [_severity_color(b) for b in scatter_df["Backlog %"]]
    fig = go.Figure(go.Scatter(
        x=scatter_df["Volume"], y=scatter_df["Median TAT"], mode="markers+text",
        text=scatter_df["Segment"], textposition="top center", textfont=dict(size=9),
        marker=dict(size=(scatter_df["Backlog"] / max_backlog * 32 + 8), color=colors,
                    line=dict(width=1, color="white")),
        customdata=scatter_df[["Segment", "Volume", "Median TAT", "Backlog", "Backlog %"]].values,
        hovertemplate=("%{customdata[0]}<br>%{customdata[1]:,} tickets, median %{customdata[2]:.1f}h"
                        "<br>%{customdata[3]:,} backlog (%{customdata[4]:.0%})<extra></extra>"),
    ))
    fig.add_vline(x=vol_median, line=dict(color="#6B7280", dash="dash", width=1))
    fig.add_hline(y=threshold_hours, line=dict(color="#6B7280", dash="dash", width=1))
    fig.update_layout(xaxis_title="Ticket Volume", yaxis_title="Median TAT (hrs)",
                       showlegend=False, height=320, **_BASE_LAYOUT)
    return fig


def tat_heatmap(med_pivot: pd.DataFrame, count_pivot: pd.DataFrame, low_sample_n: int) -> go.Figure:
    """Group (rows) x Type (columns) median-TAT heatmap - cell label shows
    median hours + valid count, with a low-sample marker (*)."""
    text = pd.DataFrame(index=med_pivot.index, columns=med_pivot.columns, dtype=object)
    for r in med_pivot.index:
        for col in med_pivot.columns:
            v = med_pivot.loc[r, col]
            n = count_pivot.loc[r, col] if col in count_pivot.columns else None
            if pd.isna(v):
                text.loc[r, col] = ""
            else:
                flag = "*" if (n is not None and pd.notna(n) and n < low_sample_n) else ""
                text.loc[r, col] = f"{v:.1f}h{flag}<br>n={int(n) if pd.notna(n) else 0}"
    fig = go.Figure(go.Heatmap(
        z=med_pivot.values, x=med_pivot.columns.tolist(), y=med_pivot.index.tolist(),
        text=text.values, texttemplate="%{text}", textfont=dict(size=8),
        colorscale=[[0, GREEN], [0.5, AMBER], [1, RED]],
        hoverongaps=False, colorbar=dict(title="hrs", thickness=10, len=0.8),
    ))
    fig.update_layout(height=max(220, 26 * len(med_pivot.index) + 60),
                       xaxis=dict(tickfont=dict(size=9)), yaxis=dict(tickfont=dict(size=9)), **_BASE_LAYOUT)
    return fig


def tat_funnel(stages: list[dict]) -> go.Figure:
    fig = go.Figure(go.Funnel(
        y=[s["Stage"] for s in stages], x=[s["Count"] for s in stages],
        textinfo="value+percent initial", textfont=dict(size=10),
        marker=dict(color=["#1F2937", "#374151", "#4B5563", GREEN, "#86EFAC", RED]),
        connector=dict(line=dict(color="#D1D5DB", width=1)),
    ))
    fig.update_layout(height=260, **_BASE_LAYOUT)
    return fig


def monthly_trend_line(trend_df: pd.DataFrame) -> go.Figure:
    """Avg + Median TAT across M-3 -> M-2 -> M-1 -> MTD - lines break
    (don't connect through) any period marked None for insufficient data."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=trend_df["Period"], y=trend_df["Avg"], mode="lines+markers", name="Average",
                              line=dict(color=AMBER), connectgaps=False))
    fig.add_trace(go.Scatter(x=trend_df["Period"], y=trend_df["Median"], mode="lines+markers", name="Median",
                              line=dict(color="#2563EB"), connectgaps=False))
    fig.update_layout(yaxis_title="hrs", height=220,
                       legend=dict(orientation="h", yanchor="bottom", y=1.05, font=dict(size=9)), **_BASE_LAYOUT)
    return fig
