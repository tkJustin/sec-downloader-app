import os
from pathlib import Path


APP_NAME = "SEC HTML Downloader + Quarterly Financial Dashboard V1.5"

def get_sec_user_agent() -> str:
    """Load SEC User-Agent from Streamlit secrets, environment, or a safe default."""
    env_value = os.getenv("SEC_USER_AGENT")
    if env_value:
        return env_value
    try:
        import streamlit as st

        secret_value = st.secrets.get("SEC_USER_AGENT")
        if secret_value:
            return str(secret_value)
    except Exception:
        pass
    return "SEC Local Dashboard contact@example.com"


SEC_USER_AGENT = get_sec_user_agent()

SEC_BASE_URL = "https://www.sec.gov"
SEC_DATA_URL = "https://data.sec.gov"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

# Conservative fair-access setting. SEC guidance caps automated access; this app
# intentionally stays below 3 requests per second for local interactive use.
REQUESTS_PER_SECOND = 2.5
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
METADATA_DIR = DATA_DIR / "metadata"
RAW_HTML_DIR = DATA_DIR / "raw_html"
PDF_DIR = DATA_DIR / "pdf"
CLEAN_TEXT_DIR = DATA_DIR / "clean_text"
FINANCIALS_DIR = DATA_DIR / "financials"
EXPORTS_DIR = DATA_DIR / "exports"
LOGS_DIR = PROJECT_ROOT / "logs"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
DOWNLOAD_LOG_PATH = LOGS_DIR / "download_log.csv"
TEMPLATE_PATH = TEMPLATE_DIR / "sec_download_template.xlsx"

REQUIRED_TASK_COLUMNS = ["ticker", "form_type", "start_year", "end_year", "download_type"]
SUPPORTED_DOWNLOAD_TYPES = ["html", "pdf"]
SUPPORTED_FORMS = ["10-Q", "10-K"]

DEFAULT_FINANCIAL_TAGS = {
    "Revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "Net Income": ["NetIncomeLoss"],
    "Assets": ["Assets"],
    "Liabilities": ["Liabilities"],
    "Operating Cash Flow": ["NetCashProvidedByUsedInOperatingActivities"],
}


def ensure_directories() -> None:
    for path in [
        INPUT_DIR,
        METADATA_DIR,
        RAW_HTML_DIR,
        PDF_DIR,
        CLEAN_TEXT_DIR,
        FINANCIALS_DIR,
        EXPORTS_DIR,
        LOGS_DIR,
        TEMPLATE_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
