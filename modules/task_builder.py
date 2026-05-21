from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from config import REQUIRED_TASK_COLUMNS, SUPPORTED_DOWNLOAD_TYPES, SUPPORTED_FORMS


@dataclass
class TaskValidationResult:
    tasks: pd.DataFrame
    errors: list[str]


def normalize_tasks(df: pd.DataFrame) -> TaskValidationResult:
    errors: list[str] = []
    normalized = df.copy()
    normalized.columns = [str(col).strip().lower() for col in normalized.columns]

    missing = [col for col in REQUIRED_TASK_COLUMNS if col not in normalized.columns]
    if missing:
        return TaskValidationResult(pd.DataFrame(columns=REQUIRED_TASK_COLUMNS), [f"Missing required columns: {', '.join(missing)}"])

    normalized = normalized[REQUIRED_TASK_COLUMNS].copy()
    normalized["ticker"] = normalized["ticker"].astype(str).str.strip().str.upper()
    normalized["form_type"] = normalized["form_type"].astype(str).str.strip().str.upper()
    normalized["download_type"] = normalized["download_type"].astype(str).str.strip().str.lower()
    normalized["start_year"] = pd.to_numeric(normalized["start_year"], errors="coerce").astype("Int64")
    normalized["end_year"] = pd.to_numeric(normalized["end_year"], errors="coerce").astype("Int64")
    normalized = normalized.dropna(subset=["ticker", "form_type", "start_year", "end_year"])

    for idx, row in normalized.iterrows():
        if not row["ticker"] or row["ticker"] == "NAN":
            errors.append(f"Row {idx + 2}: ticker is required.")
        if row["form_type"] not in SUPPORTED_FORMS:
            errors.append(f"Row {idx + 2}: unsupported form_type {row['form_type']}.")
        if int(row["start_year"]) > int(row["end_year"]):
            errors.append(f"Row {idx + 2}: start_year must be <= end_year.")
        if row["download_type"] not in SUPPORTED_DOWNLOAD_TYPES:
            errors.append(f"Row {idx + 2}: download_type must be one of: {', '.join(SUPPORTED_DOWNLOAD_TYPES)}.")

    normalized = normalized.drop_duplicates().reset_index(drop=True)
    return TaskValidationResult(normalized, errors)


def parse_ticker_input(ticker_input: str) -> list[str]:
    tickers = [ticker.strip().upper() for ticker in str(ticker_input).split(",")]
    return [ticker for ticker in tickers if ticker]


def build_manual_task(ticker: str, form_type: str, start_year: int, end_year: int, download_type: str = "html") -> pd.DataFrame:
    tickers = parse_ticker_input(ticker)
    return pd.DataFrame(
        [
            {
                "ticker": symbol,
                "form_type": form_type,
                "start_year": start_year,
                "end_year": end_year,
                "download_type": download_type,
            }
            for symbol in tickers
        ],
        columns=REQUIRED_TASK_COLUMNS,
    )


def tasks_to_preview_rows(tasks: Iterable[dict]) -> pd.DataFrame:
    return pd.DataFrame(list(tasks))
