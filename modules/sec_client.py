from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    REQUESTS_PER_SECOND,
    RETRY_BACKOFF_SECONDS,
    SEC_BASE_URL,
    SEC_DATA_URL,
    SEC_USER_AGENT,
)


class SecClientError(Exception):
    """Raised when SEC data cannot be fetched or interpreted."""


@dataclass
class FilingDocument:
    url: str
    content: str


class SecClient:
    def __init__(self, user_agent: str = SEC_USER_AGENT, requests_per_second: float = REQUESTS_PER_SECOND):
        self.user_agent = user_agent
        self.min_interval = 1.0 / max(requests_per_second, 0.1)
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": "www.sec.gov",
            }
        )
        retry = Retry(
            total=MAX_RETRIES,
            read=MAX_RETRIES,
            connect=MAX_RETRIES,
            status=MAX_RETRIES,
            backoff_factor=RETRY_BACKOFF_SECONDS,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def get_json(self, url: str) -> dict[str, Any]:
        response = self.get(url)
        try:
            return response.json()
        except ValueError as exc:
            raise SecClientError(f"SEC response was not valid JSON: {url}") from exc

    def get_text(self, url: str) -> str:
        response = self.get(url)
        response.encoding = response.encoding or "utf-8"
        return response.text

    def get(self, url: str) -> requests.Response:
        self._wait_for_rate_limit()
        headers = {"User-Agent": self.user_agent}
        if "data.sec.gov" in url:
            headers["Host"] = "data.sec.gov"
        response = self.session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code >= 400:
            raise SecClientError(f"SEC request failed ({response.status_code}): {url}")
        return response

    def get_company_tickers(self) -> pd.DataFrame:
        data = self.get_json(f"{SEC_BASE_URL}/files/company_tickers.json")
        rows = list(data.values())
        df = pd.DataFrame(rows)
        df["ticker"] = df["ticker"].astype(str).str.upper()
        df["cik_str"] = df["cik_str"].astype(int)
        return df

    def ticker_to_cik(self, ticker: str) -> int:
        ticker = ticker.strip().upper()
        tickers = self.get_company_tickers()
        match = tickers.loc[tickers["ticker"] == ticker]
        if match.empty:
            raise SecClientError(f"Ticker not found in SEC company_tickers.json: {ticker}")
        return int(match.iloc[0]["cik_str"])

    def get_submissions(self, cik: int) -> dict[str, Any]:
        cik_padded = f"{cik:010d}"
        return self.get_json(f"{SEC_DATA_URL}/submissions/CIK{cik_padded}.json")

    def get_company_facts(self, cik: int) -> dict[str, Any]:
        cik_padded = f"{cik:010d}"
        return self.get_json(f"{SEC_DATA_URL}/api/xbrl/companyfacts/CIK{cik_padded}.json")

    def download_primary_document(self, cik: int, accession_number: str, primary_document: str) -> FilingDocument:
        accession_compact = accession_number.replace("-", "")
        url = f"{SEC_BASE_URL}/Archives/edgar/data/{int(cik)}/{accession_compact}/{primary_document}"
        return FilingDocument(url=url, content=self.get_text(url))
