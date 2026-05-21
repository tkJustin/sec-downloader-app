from __future__ import annotations

import pandas as pd
import plotly.express as px


def build_trend_chart(financials: pd.DataFrame, metric: str):
    if financials.empty or metric not in financials["metric"].unique():
        return None
    chart_df = financials.loc[financials["metric"] == metric].copy()
    chart_df = chart_df.sort_values(["ticker", "end"])
    fig = px.line(
        chart_df,
        x="end",
        y="value",
        color="ticker",
        markers=True,
        title=f"{metric} Trend",
        hover_data=["fy", "fp", "form", "unit"],
    )
    fig.update_layout(xaxis_title="Period End", yaxis_title=metric, legend_title="Ticker")
    return fig
