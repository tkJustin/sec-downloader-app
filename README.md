# SEC Downloader App

This Streamlit app provides two local/cloud-friendly data download modules:

- SEC Financial Data Downloader
- Stock Price Data Downloader

Use the left sidebar selector to switch between modules.

## Install

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Run locally:

```bash
streamlit run app.py
```

On Windows you can also run:

```bat
run_app.bat
```

## Streamlit Community Cloud

Recommended settings:

- Repository: `tkJustin/sec-downloader-app`
- Branch: `main`
- Main file path: `app.py`
- Python version: `3.12`

Recommended Streamlit secrets:

```toml
SEC_USER_AGENT = "SEC Local Dashboard your_email@example.com"
ALPHA_VANTAGE_API_KEY = "your_api_key_here"
```

Do not commit real API keys or secrets to GitHub.

## SEC Financial Data Downloader

Purpose:

- Convert ticker to CIK using SEC `company_tickers.json`
- Query SEC Submissions API
- Preview 10-K / 10-Q filings
- Download selected primary HTML filings
- Convert HTML to clean text
- Optionally render PDF from HTML
- Fetch SEC Company Facts financial data
- Export selected filing outputs as ZIP

Typical workflow:

1. Select `SEC Financial Data Downloader` from the sidebar.
2. Enter one or more tickers, form type, start year, end year, and download type.
3. Click `Query SEC metadata and build filing preview`.
4. Select filings in the preview table.
5. Choose whether to include clean text.
6. Click `Prepare ZIP package`.
7. Click `Download ZIP to computer`.

SEC access notes:

- Requests use a descriptive SEC User-Agent.
- Configure `SEC_USER_AGENT` in Streamlit secrets or as an environment variable.
- The app uses a conservative request rate limit.

PDF note:

- PDF generation uses Chromium print-to-PDF from the SEC HTML document.
- If PDF rendering fails on Streamlit Cloud, HTML can still be packaged and downloaded.

## Stock Price Data Downloader

Purpose:

The stock price downloader allows users to download historical stock price data by ticker symbol, date range, and data frequency.

Supported inputs:

- One or multiple ticker symbols separated by commas, for example `AAPL, MSFT, NVDA`
- Start date
- End date
- Data frequency: Daily, Weekly, Monthly
- Data provider: Alpha Vantage or yfinance backup

Data providers:

- Default provider: Alpha Vantage
- Backup provider: yfinance backup

Alpha Vantage API key setup:

Preferred Streamlit secrets configuration:

```toml
ALPHA_VANTAGE_API_KEY = "your_api_key_here"
```

If the secret is not configured, the stock price page lets users enter an Alpha Vantage API key manually for the current session. The key is not stored by the app.

yfinance backup notice:

yfinance is available only as a backup option for research and educational use. The app does not silently switch to yfinance when Alpha Vantage fails. Users must explicitly select the yfinance backup provider.

Data source disclaimer:

Stock price data are retrieved from selected public or API-based market data providers. The default provider is Alpha Vantage. yfinance is provided only as a backup option for research and educational use. Users should independently verify data accuracy, data completeness, and data usage rights before using the output for investment, trading, regulatory, or commercial purposes.

Output columns:

- Date
- Ticker
- Open
- High
- Low
- Close
- Adjusted Close, if available
- Volume
- Data Frequency
- Data Provider

The page also shows a data preview, row count, unique ticker count, date range, missing values by column, duplicated Date-Ticker check, line chart of Close price, and CSV download.

## Project Structure

```text
sec_downloader_app/
├── app.py
├── config.py
├── requirements.txt
├── packages.txt
├── README.md
├── modules/
├── utils/
│   └── stock_price.py
├── templates/
├── tests/
└── data/
```
