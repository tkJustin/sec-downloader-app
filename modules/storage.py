from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

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


def build_zip_bytes(files: list[tuple[Path, str]], manifest_csv: bytes | None = None) -> bytes:
    buffer = BytesIO()
    seen: set[str] = set()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        if manifest_csv is not None:
            archive.writestr("manifest.csv", manifest_csv)
        for path, archive_name in files:
            if not path.exists() or not path.is_file():
                continue
            name = archive_name.replace("\\", "/")
            if name in seen:
                stem = Path(name).stem
                suffix = Path(name).suffix
                parent = Path(name).parent
                counter = 2
                while name in seen:
                    name = str(parent / f"{stem}_{counter}{suffix}").replace("\\", "/")
                    counter += 1
            archive.write(path, arcname=name)
            seen.add(name)
    return buffer.getvalue()
