from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import DOWNLOAD_LOG_PATH, EXPORTS_DIR


def safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in value)


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def append_download_log(row: dict[str, Any]) -> None:
    DOWNLOAD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"logged_at": datetime.now().isoformat(timespec="seconds"), **row}
    df = pd.DataFrame([payload])
    header = not DOWNLOAD_LOG_PATH.exists()
    try:
        df.to_csv(DOWNLOAD_LOG_PATH, mode="a", header=header, index=False, encoding="utf-8-sig")
    except PermissionError:
        fallback = DOWNLOAD_LOG_PATH.with_name(f"download_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        df.to_csv(fallback, index=False, encoding="utf-8-sig")


def export_dataframe(df: pd.DataFrame, stem: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = EXPORTS_DIR / f"{safe_filename(stem)}_{timestamp}.csv"
    return write_csv(df, path)
