from __future__ import annotations

import pandas as pd

from config import DEFAULT_FINANCIAL_TAGS, FINANCIALS_DIR
from modules.sec_client import SecClient
from modules.storage import safe_filename


FLOW_METRICS = {"Revenue", "Net Income", "Operating Cash Flow"}
QUARTER_FPS = {"Q1", "Q2", "Q3"}
FY_FPS = {"FY"}


def _current_period_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the latest fact period from each filing to avoid prior-year comparatives."""
    group_cols = ["ticker", "metric", "tag", "unit", "accession_number", "fy", "fp", "form"]
    max_end = df.groupby(group_cols, dropna=False)["end"].transform("max")
    return df.loc[df["end"] == max_end].copy()


def _prepare_rows(df: pd.DataFrame) -> pd.DataFrame:
    df["start"] = pd.to_datetime(df["start"], errors="coerce")
    df["end"] = pd.to_datetime(df["end"], errors="coerce")
    df["filed"] = pd.to_datetime(df["filed"], errors="coerce")
    df["duration_days"] = (df["end"] - df["start"]).dt.days
    df["statement_type"] = df["metric"].where(df["metric"].isin(FLOW_METRICS), "point_in_time")
    df.loc[df["metric"].isin(FLOW_METRICS), "statement_type"] = "flow"
    df["reported_value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["end", "reported_value"])


def _build_quarterly_values(df: pd.DataFrame) -> pd.DataFrame:
    current = _current_period_rows(df)
    point = current.loc[~current["metric"].isin(FLOW_METRICS)].copy()
    point["value"] = point["reported_value"]
    point["value_basis"] = "reported_point_in_time"
    point["is_derived"] = False

    flow_quarters = current.loc[
        current["metric"].isin(FLOW_METRICS)
        & current["fp"].isin(QUARTER_FPS)
        & current["duration_days"].between(60, 120, inclusive="both")
    ].copy()
    flow_quarters["value"] = flow_quarters["reported_value"]
    flow_quarters["value_basis"] = "reported_single_quarter"
    flow_quarters["is_derived"] = False

    q4_rows: list[dict] = []
    fy_rows = current.loc[
        current["metric"].isin(FLOW_METRICS)
        & current["fp"].isin(FY_FPS)
        & current["duration_days"].between(300, 390, inclusive="both")
    ].copy()
    q_lookup = flow_quarters.set_index(["ticker", "cik", "metric", "tag", "unit", "fy", "fp"])

    for _, fy_row in fy_rows.iterrows():
        key_base = (
            fy_row["ticker"],
            fy_row["cik"],
            fy_row["metric"],
            fy_row["tag"],
            fy_row["unit"],
            fy_row["fy"],
        )
        quarter_values: list[float] = []
        quarter_rows: list[pd.Series] = []
        for fp in ["Q1", "Q2", "Q3"]:
            key = (*key_base, fp)
            if key not in q_lookup.index:
                quarter_values = []
                break
            match = q_lookup.loc[key]
            if isinstance(match, pd.DataFrame):
                match = match.sort_values("filed").iloc[-1]
            quarter_values.append(float(match["value"]))
            quarter_rows.append(match)
        if len(quarter_values) != 3:
            continue
        q4 = float(fy_row["reported_value"]) - sum(quarter_values)
        q3_end = max(row["end"] for row in quarter_rows)
        derived = fy_row.to_dict()
        derived.update(
            {
                "fp": "Q4",
                "form": "10-K derived",
                "start": q3_end + pd.Timedelta(days=1) if pd.notna(q3_end) else pd.NaT,
                "value": q4,
                "reported_value": fy_row["reported_value"],
                "value_basis": "derived_q4_from_fy_less_q1_q2_q3",
                "is_derived": True,
                "source_accession_number": fy_row["accession_number"],
            }
        )
        derived["duration_days"] = (derived["end"] - derived["start"]).days if pd.notna(derived["start"]) else pd.NA
        q4_rows.append(derived)

    combined = pd.concat([point, flow_quarters, pd.DataFrame(q4_rows)], ignore_index=True)
    if combined.empty:
        return combined
    if "source_accession_number" not in combined.columns:
        combined["source_accession_number"] = ""
    combined["source_accession_number"] = combined["source_accession_number"].fillna(combined["accession_number"])
    combined = combined.sort_values(["ticker", "metric", "end", "filed", "fp"]).drop_duplicates(
        subset=["ticker", "metric", "unit", "fy", "fp", "end"],
        keep="last",
    )
    return combined


def facts_to_quarterly_dataframe(client: SecClient, ticker: str, cik: int) -> pd.DataFrame:
    facts = client.get_company_facts(cik)
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    rows: list[dict] = []

    for metric, tag_candidates in DEFAULT_FINANCIAL_TAGS.items():
        tag_name = next((tag for tag in tag_candidates if tag in us_gaap), None)
        if tag_name is None:
            continue
        units = us_gaap[tag_name].get("units", {})
        for unit, observations in units.items():
            for obs in observations:
                form = str(obs.get("form", ""))
                fp = str(obs.get("fp", ""))
                if form not in {"10-Q", "10-K"}:
                    continue
                if not obs.get("end") or obs.get("val") is None:
                    continue
                rows.append(
                    {
                        "ticker": ticker.upper(),
                        "cik": int(cik),
                        "metric": metric,
                        "tag": tag_name,
                        "unit": unit,
                        "fy": obs.get("fy"),
                        "fp": fp,
                        "form": form,
                        "frame": obs.get("frame"),
                        "filed": obs.get("filed"),
                        "start": obs.get("start"),
                        "end": obs.get("end"),
                        "value": obs.get("val"),
                        "accession_number": obs.get("accn"),
                    }
                )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = _prepare_rows(df)
    df = _build_quarterly_values(df)
    ordered_cols = [
        "ticker",
        "cik",
        "metric",
        "tag",
        "unit",
        "fy",
        "fp",
        "form",
        "statement_type",
        "value_basis",
        "is_derived",
        "filed",
        "start",
        "end",
        "duration_days",
        "value",
        "reported_value",
        "frame",
        "accession_number",
        "source_accession_number",
    ]
    df = df[[col for col in ordered_cols if col in df.columns]]
    out_path = FINANCIALS_DIR / f"{safe_filename(ticker.upper())}_quarterly_financials.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return df
