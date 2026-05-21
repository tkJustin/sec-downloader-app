from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
import requests


ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_FUNCTIONS = {
    "Daily": ("TIME_SERIES_DAILY_ADJUSTED", "Time Series (Daily)"),
    "Weekly": ("TIME_SERIES_WEEKLY_ADJUSTED", "Weekly Adjusted Time Series"),
    "Monthly": ("TIME_SERIES_MONTHLY_ADJUSTED", "Monthly Adjusted Time Series"),
}
YFINANCE_INTERVALS = {"Daily": "1d", "Weekly": "1wk", "Monthly": "1mo"}
PRICE_COLUMNS = [
    "Date",
    "Ticker",
    "Open",
    "High",
    "Low",
    "Close",
    "Adjusted Close",
    "Volume",
    "Data Frequency",
    "Data Provider",
]


class StockPriceError(Exception):
    """Raised for stock price input or provider failures."""


@dataclass
class StockPriceResult:
    data: pd.DataFrame
    warnings: list[str]
    failed_tickers: dict[str, str]
    provider_used: str


def parse_tickers(ticker_input: str) -> list[str]:
    tickers = [ticker.strip().upper() for ticker in str(ticker_input).split(",")]
    return [ticker for ticker in tickers if ticker]


def validate_stock_price_inputs(
    ticker_input: str,
    start_date: date,
    end_date: date,
    provider: str,
    alpha_vantage_api_key: str | None = None,
) -> list[str]:
    errors: list[str] = []
    tickers = parse_tickers(ticker_input)
    if not tickers:
        errors.append("Please enter at least one ticker symbol.")
    invalid = [ticker for ticker in tickers if not re.fullmatch(r"[A-Z0-9.\-]+", ticker)]
    if invalid:
        errors.append(f"Invalid ticker format: {', '.join(invalid)}.")
    if start_date > end_date:
        errors.append("Start date cannot be later than end date.")
    if end_date > date.today():
        errors.append("End date cannot be in the future.")
    if provider == "Alpha Vantage" and not alpha_vantage_api_key:
        errors.append("Alpha Vantage API key is missing. Please configure it in Streamlit secrets or enter it manually.")
    return errors


def fetch_stock_prices(
    tickers: list[str],
    start_date: date,
    end_date: date,
    frequency: str,
    provider: str,
    alpha_vantage_api_key: str | None = None,
) -> StockPriceResult:
    frames: list[pd.DataFrame] = []
    failed: dict[str, str] = {}
    warnings: list[str] = []

    for ticker in tickers:
        try:
            if provider == "Alpha Vantage":
                frame = fetch_alpha_vantage_prices(ticker, start_date, end_date, frequency, alpha_vantage_api_key or "")
            elif provider == "yfinance backup":
                frame = fetch_yfinance_prices(ticker, start_date, end_date, frequency)
            else:
                raise StockPriceError(f"Unsupported data provider: {provider}")
            if frame.empty:
                raise StockPriceError("No price data returned for the selected date range.")
            frames.append(frame)
        except Exception as exc:  # noqa: BLE001 - surfaced to UI per ticker.
            failed[ticker] = str(exc)

    if not frames:
        if provider == "Alpha Vantage":
            warnings.append(
                "Alpha Vantage did not return valid data. You may try again later, check your API key, "
                "or use the yfinance backup source for research and educational use only."
            )
        return StockPriceResult(pd.DataFrame(columns=PRICE_COLUMNS), warnings, failed, provider)

    data = pd.concat(frames, ignore_index=True)
    data, quality_warnings = standardize_stock_price_data(data)
    warnings.extend(quality_warnings)
    if failed:
        warnings.append("Some tickers failed: " + "; ".join(f"{ticker}: {reason}" for ticker, reason in failed.items()))
    return StockPriceResult(data, warnings, failed, provider)


def fetch_alpha_vantage_prices(
    ticker: str,
    start_date: date,
    end_date: date,
    frequency: str,
    api_key: str,
) -> pd.DataFrame:
    function, series_key = ALPHA_VANTAGE_FUNCTIONS[frequency]
    params = {"function": function, "symbol": ticker, "apikey": api_key, "outputsize": "full"}
    try:
        response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise StockPriceError(f"Alpha Vantage request failed: {exc}") from exc
    except ValueError as exc:
        raise StockPriceError("Alpha Vantage returned an invalid JSON response.") from exc

    for key in ["Error Message", "Note", "Information"]:
        if key in payload:
            raise StockPriceError(str(payload[key]))
    if series_key not in payload or not isinstance(payload[series_key], dict):
        raise StockPriceError("Unexpected Alpha Vantage response format or empty time series.")

    rows: list[dict[str, Any]] = []
    for date_text, values in payload[series_key].items():
        period = pd.to_datetime(date_text, errors="coerce")
        if pd.isna(period) or period.date() < start_date or period.date() > end_date:
            continue
        rows.append(
            {
                "Date": period.date().isoformat(),
                "Ticker": ticker,
                "Open": values.get("1. open"),
                "High": values.get("2. high"),
                "Low": values.get("3. low"),
                "Close": values.get("4. close"),
                "Adjusted Close": values.get("5. adjusted close"),
                "Volume": values.get("6. volume"),
                "Data Frequency": frequency,
                "Data Provider": "Alpha Vantage",
            }
        )
    return pd.DataFrame(rows, columns=PRICE_COLUMNS)


def fetch_yfinance_prices(ticker: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise StockPriceError("yfinance is not installed. Please install the yfinance package.") from exc

    interval = YFINANCE_INTERVALS[frequency]
    end_exclusive = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    try:
        frame = yf.download(
            ticker,
            start=pd.Timestamp(start_date).strftime("%Y-%m-%d"),
            end=end_exclusive.strftime("%Y-%m-%d"),
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise StockPriceError(f"yfinance request failed: {exc}") from exc
    if frame.empty:
        raise StockPriceError("No data returned from yfinance.")

    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [col[0] if isinstance(col, tuple) else col for col in frame.columns]
    frame = frame.reset_index()
    date_col = "Date" if "Date" in frame.columns else frame.columns[0]
    output = pd.DataFrame(
        {
            "Date": pd.to_datetime(frame[date_col], errors="coerce").dt.date.astype(str),
            "Ticker": ticker,
            "Open": frame.get("Open"),
            "High": frame.get("High"),
            "Low": frame.get("Low"),
            "Close": frame.get("Close"),
            "Adjusted Close": frame.get("Adj Close"),
            "Volume": frame.get("Volume"),
            "Data Frequency": frequency,
            "Data Provider": "yfinance backup",
        }
    )
    return output[PRICE_COLUMNS]


def standardize_stock_price_data(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS), warnings

    data = df.copy()
    for column in PRICE_COLUMNS:
        if column not in data.columns:
            data[column] = pd.NA
    data = data[PRICE_COLUMNS]
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])
    for column in ["Open", "High", "Low", "Close", "Adjusted Close", "Volume"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    duplicate_mask = data.duplicated(subset=["Date", "Ticker"], keep="first")
    if duplicate_mask.any():
        warnings.append(f"Dropped {int(duplicate_mask.sum())} duplicated Date-Ticker row(s).")
        data = data.loc[~duplicate_mask].copy()

    data = data.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    data["Date"] = data["Date"].dt.strftime("%Y-%m-%d")
    return data, warnings
