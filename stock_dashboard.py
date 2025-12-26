import streamlit as st
import yfinance as yf
import pandas as pd
import datetime

st.set_page_config(page_title="Stock Market Dashboard", layout="wide")
st.title("Stock Market Dashboard")

# Sidebar inputs
ticker = st.sidebar.text_input("Enter Stock Ticker", value="AAPL").upper().strip()

period_key = st.sidebar.selectbox(
    "Select Time Range",
    options=["1d", "1w", "1m", "3m", "1y", "5y"],
    index=0,
    help="Choose how much history to display"
)

shares = st.sidebar.number_input(
    "Number of Shares",
    min_value=0,
    value=1,
    step=1,
    format="%d"
)

# New: moving average toggles
show_sma50 = st.sidebar.checkbox("Show 50-period SMA", value=False, help="Simple moving average using a 50-row window. For daily data this is 50 trading days.")
show_sma200 = st.sidebar.checkbox("Show 200-period SMA", value=False, help="Simple moving average using a 200-row window. For daily data this is 200 trading days.")

# Map selected period to yfinance period and interval
PERIOD_INTERVAL_MAP = {
    "1d": {"period": "1d", "interval": "1m"},
    "1w": {"period": "7d", "interval": "5m"},
    "1m": {"period": "1mo", "interval": "15m"},
    "3m": {"period": "3mo", "interval": "60m"},
    "1y": {"period": "1y", "interval": "1d"},
    "5y": {"period": "5y", "interval": "1d"},
}


def _ensure_close_column(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame that has a 'Close' column if possible."""
    if df is None or df.empty:
        return df
    if "Close" in df.columns:
        return df
    # sometimes only 'Adj Close' is present
    if "Adj Close" in df.columns:
        df = df.rename(columns={"Adj Close": "Close"})
        return df
    # If there is any numeric column, try to pick one (last resort)
    numeric_cols = df.select_dtypes("number").columns
    if len(numeric_cols) > 0:
        df = df.rename(columns={numeric_cols[0]: "Close"})
    return df


def fetch_history(ticker_symbol: str, period_key: str) -> pd.DataFrame:
    """
    Fetch historical data for the given ticker and period.
    Tries a few fallbacks when the primary call returns empty (common for intraday on some symbols).
    """
    params = PERIOD_INTERVAL_MAP.get(period_key, PERIOD_INTERVAL_MAP["1d"])
    period = params["period"]
    interval = params["interval"]

    # Primary attempt: yf.download with prepost True for intraday (1d)
    prepost = period_key == "1d"
    try:
        df = yf.download(
            tickers=ticker_symbol,
            period=period,
            interval=interval,
            progress=False,
            threads=False,
            prepost=prepost,
            show_errors=False,
        )
        df = _ensure_close_column(df)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # Fallbacks:
    tk = yf.Ticker(ticker_symbol)

    # 1) Try ticker.history which sometimes behaves better
    try:
        df = tk.history(period=period, interval=interval, prepost=prepost)
        df = _ensure_close_column(df)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # 2) If user asked for 1d and intraday is empty, try a slightly longer window and downsample
    if period_key == "1d":
        try:
            # Try 5d at 5m intervals then take last 1 day of rows
            df = tk.history(period="5d", interval="5m", prepost=True)
            if df is not None and not df.empty:
                df = _ensure_close_column(df)
                # keep last 24 hours worth of rows (approx)
                cutoff = datetime.datetime.now(tz=df.index.tz) - datetime.timedelta(days=1)
                df = df[df.index >= cutoff]
                if not df.empty:
                    return df
        except Exception:
            pass

    # 3) Last resort: try a single-day download with different parameters
    try:
        df = yf.download(ticker_symbol, period="1d", interval="5m", prepost=True, progress=False, threads=False)
        df = _ensure_close_column(df)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # If everything fails return empty DataFrame
    return pd.DataFrame()


def fetch_latest_price(ticker_symbol: str):
    """
    Best-effort latest price and timestamp.
    Prefer intraday history's last row (timestamped), then fast_info/info fallbacks.
    Returns (price_or_None, timestamp_or_None, source_string)
    """
    tk = yf.Ticker(ticker_symbol)
    # try intraday history (timestamped)
    try:
        hist = tk.history(period="1d", interval="1m", prepost=True)
        if hist is not None and not hist.empty:
            hist = _ensure_close_column(hist)
            price = float(hist["Close"].iloc[-1])
            ts = hist.index[-1]
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            return price, ts, "intraday_history"
    except Exception:
        pass

    # fast_info
    try:
        fast = getattr(tk, "fast_info", None)
        if isinstance(fast, dict):
            for key in ("last_price", "regularMarketPrice", "currentPrice"):
                if key in fast and fast[key] is not None:
                    return float(fast[key]), datetime.datetime.now(), "fast_info"
    except Exception:
        pass

    # ticker.info fallback
    try:
        info = tk.info
        if isinstance(info, dict):
            for key in ("regularMarketPrice", "currentPrice", "previousClose", "lastPrice"):
                if key in info and info[key] is not None:
                    return float(info[key]), datetime.datetime.now(), "info"
    except Exception:
        pass

    # final fallback: tiny download
    try:
        dl = yf.download(ticker_symbol, period="1d", interval="1m", prepost=True, progress=False, threads=False)
        dl = _ensure_close_column(dl)
        if dl is not None and not dl.empty:
            price = float(dl["Close"].iloc[-1])
            ts = dl.index[-1]
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            return price, ts, "download_fallback"
    except Exception:
        pass

    return None, None, "none"


@st.cache_data(ttl=300)
def fetch_fundamentals(ticker_symbol: str):
    """
    Fetch P/E, annual revenue and gross profit for the past years (if available).
    Returns a dict with keys:
      - pe: float or None
      - revenue: list of (year_str, value) ordered ascending by year (oldest first)
      - revenue_change_pct: percent change from first to last (or None)
      - revenue_cagr_pct: annualized growth % (or None)
      - gross: same shape as revenue
    """
    result = {
        "pe": None,
        "revenue": None,
        "revenue_change_pct": None,
        "revenue_cagr_pct": None,
        "gross": None,
        "gross_change_pct": None,
        "gross_cagr_pct": None,
    }

    tk = yf.Ticker(ticker_symbol)

    # P/E from info: prefer trailingPE then forwardPE
    try:
        info = tk.info
        if isinstance(info, dict):
            pe = info.get("trailingPE") or info.get("forwardPE")
            if pe is not None:
                result["pe"] = float(pe)
    except Exception:
        pass

    # Try to obtain annual financials
    try:
        fin = tk.financials  # typically annual income statement
        if isinstance(fin, pd.DataFrame) and not fin.empty:
            # Determine revenue & gross profit rows by searching index labels (case-insensitive)
            def find_row(df: pd.DataFrame, keywords):
                for idx in df.index:
                    lower = str(idx).lower()
                    for kw in keywords:
                        if kw in lower:
                            return df.loc[idx]
                return None

            revenue_row = find_row(fin, ["total revenue", "totalrevenue", "revenue", "net sales"])
            gross_row = find_row(fin, ["gross profit", "grossprofit", "gross"])

            def series_from_row(row):
                # row is a pd.Series with columns representing period end dates (usually Timestamp)
                if row is None:
                    return None
                # Create year labels and numeric values
                cols = list(row.index)
                years = []
                vals = []
                for c in cols:
                    # try to extract year from column label
                    try:
                        y = getattr(c, "year", None)
                        if y is None:
                            y = int(str(c)[:4])
                        years.append(str(y))
                    except Exception:
                        years.append(str(c))
                    try:
                        vals.append(float(row[c]))
                    except Exception:
                        vals.append(float("nan"))
                # Build dataframe and sort by year (ascending) if years look numeric
                df_cols = pd.DataFrame({"year": years, "value": vals})
                # Remove NaNs
                df_cols = df_cols[df_cols["value"].notna()]
                # Try converting year to int for sorting
                try:
                    df_cols["year_int"] = df_cols["year"].astype(int)
                    df_cols = df_cols.sort_values("year_int").drop(columns=["year_int"])
                except Exception:
                    # fallback: keep as-is
                    pass
                # Keep only last 5 entries (most recent 5 years) but return in ascending order (oldest -> newest)
                if len(df_cols) > 5:
                    df_cols = df_cols.iloc[-5:]
                return list(zip(df_cols["year"].tolist(), df_cols["value"].tolist()))

            revenue_series = series_from_row(revenue_row)
            gross_series = series_from_row(gross_row)

            # Compute changes
            def compute_changes(series):
                if not series or len(series) < 2:
                    return None, None
                first_val = series[0][1]
                last_val = series[-1][1]
                years_count = len(series) - 1
                # percent change
                pct = None
                cagr = None
                try:
                    if first_val != 0 and not pd.isna(first_val):
                        pct = (last_val - first_val) / abs(first_val) * 100.0
                    # compute CAGR if positive and non-zero
                    if first_val > 0 and last_val > 0 and years_count > 0:
                        cagr = (last_val / first_val) ** (1.0 / years_count) - 1.0
                        cagr = cagr * 100.0
                except Exception:
                    pct = None
                    cagr = None
                return pct, cagr

            result["revenue"] = revenue_series
            if revenue_series:
                pct, cagr = compute_changes(revenue_series)
                result["revenue_change_pct"] = pct
                result["revenue_cagr_pct"] = cagr

            result["gross"] = gross_series
            if gross_series:
                pct_g, cagr_g = compute_changes(gross_series)
                result["gross_change_pct"] = pct_g
                result["gross_cagr_pct"] = cagr_g

    except Exception:
        # If any error, return what we have (PE maybe)
        pass

    return result


# Only proceed if a ticker is provided
if not ticker:
    st.sidebar.info("Please enter a stock ticker to begin.")
    st.stop()

# Fetch history & latest price
history = fetch_history(ticker, period_key)
latest_price, last_timestamp, price_source = fetch_latest_price(ticker)

# Fetch fundamentals (cached)
funds = fetch_fundamentals(ticker)

# Sidebar display: current price and total value
with st.sidebar:
    st.markdown("## Current Price")
    if latest_price is not None:
        price_str = f"${latest_price:,.2f}"
        st.metric(label=f"{ticker}", value=price_str)
        total_value = latest_price * float(shares)
        st.write(f"Shares: {int(shares)}")
        st.write(f"Total value: ${total_value:,.2f}")
        if last_timestamp is None:
            last_timestamp = datetime.datetime.now()
        try:
            ts_text = last_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts_text = str(last_timestamp)
        st.write(f"Last updated: {ts_text} (source: {price_source})")
    else:
        st.warning("Could not fetch latest price. Please check the ticker symbol or your internet connection.")

# Main display: chart, fundamentals, raw data
if history is not None and not history.empty and "Close" in history.columns:
    st.subheader(f"{ticker} Price ({period_key})")

    # Work on a copy to avoid mutating original
    df = history.copy()

    # Drop rows without Close to avoid NaN issues
    df = df[df["Close"].notna()]

    # Compute moving averages if requested
    # Note: window counts rows. For intraday data (minute, 5m, etc.), "50" means 50 rows, not 50 trading days.
    if show_sma50:
        df["SMA50"] = df["Close"].rolling(window=50, min_periods=1).mean()
    if show_sma200:
        df["SMA200"] = df["Close"].rolling(window=200, min_periods=1).mean()

    # Build chart dataframe including only requested columns
    chart_cols = ["Close"]
    if show_sma50:
        chart_cols.append("SMA50")
    if show_sma200:
        chart_cols.append("SMA200")

    # Plot using st.line_chart which accepts a DataFrame
    try:
        st.line_chart(df[chart_cols])
    except Exception:
        # Fallback: if line_chart fails for any reason, plot Close only
        st.line_chart(df["Close"])
        st.error("Failed to plot SMAs — showing Close only.")

    # Informational note about interpretation for intraday data
    params = PERIOD_INTERVAL_MAP.get(period_key, {})
    interval = params.get("interval", "")
    if interval != "1d" and (show_sma50 or show_sma200):
        st.caption(
            "Note: The SMA windows are measured in rows (intervals). For intraday intervals (1m, 5m, 15m, 60m) "
            "the 50/200 windows count data rows, not calendar trading days. If you want 50/200 trading-day SMAs "
            "on intraday data, I can resample to daily closes and then compute the SMAs."
        )

    # Fundamentals section (P/E, revenue and gross profit history)
    st.subheader("Fundamentals (P/E, Revenue & Gross Profit)")

    # P/E ratio
    pe = funds.get("pe")
    if pe is not None:
        st.write(f"P/E ratio (trailing/forward): {pe:.2f}")
    else:
        st.write("P/E ratio: N/A")

    # Revenue table + increase
    rev = funds.get("revenue")
    if rev:
        rev_df = pd.DataFrame(rev, columns=["Year", "Revenue"])
        # Format revenue for display
        rev_df["Revenue"] = rev_df["Revenue"].apply(lambda v: f"${v:,.0f}")
        st.markdown("#### Revenue (past years)")
        st.table(rev_df)
        # Changes
        rev_pct = funds.get("revenue_change_pct")
        rev_cagr = funds.get("revenue_cagr_pct")
        if rev_pct is not None:
            st.write(f"Revenue change (first -> last): {rev_pct:.2f}%")
        else:
            st.write("Revenue change: N/A")
        if rev_cagr is not None:
            st.write(f"Revenue CAGR (annualized): {rev_cagr:.2f}%")
    else:
        st.write("Revenue data (annual) not available via yfinance for this ticker.")

    # Gross profit table + increase
    gross = funds.get("gross")
    if gross:
        gross_df = pd.DataFrame(gross, columns=["Year", "Gross Profit"])
        gross_df["Gross Profit"] = gross_df["Gross Profit"].apply(lambda v: f"${v:,.0f}")
        st.markdown("#### Gross Profit (past years)")
        st.table(gross_df)
        gross_pct = funds.get("gross_change_pct")
        gross_cagr = funds.get("gross_cagr_pct")
        if gross_pct is not None:
            st.write(f"Gross profit change (first -> last): {gross_pct:.2f}%")
        else:
            st.write("Gross profit change: N/A")
        if gross_cagr is not None:
            st.write(f"Gross profit CAGR (annualized): {gross_cagr:.2f}%")
    else:
        st.write("Gross profit data (annual) not available via yfinance for this ticker.")

    # Show latest SMA values (if present)
    sma_latest = {}
    if show_sma50 and "SMA50" in df.columns:
        sma_latest["SMA50"] = df["SMA50"].iloc[-1]
    if show_sma200 and "SMA200" in df.columns:
        sma_latest["SMA200"] = df["SMA200"].iloc[-1]
    if sma_latest:
        st.write("Latest moving average values:")
        sma_display = {k: f"${v:,.2f}" for k, v in sma_latest.items()}
        st.json(sma_display)

    st.subheader("Raw Data (last 100 rows)")
    # Include SMA columns in raw data if they exist
    display_cols = ["Close"]
    if "SMA50" in df.columns:
        display_cols.append("SMA50")
    if "SMA200" in df.columns:
        display_cols.append("SMA200")
    st.write(df[display_cols].tail(100))
else:
    # If no multi-row history available, but we have a latest_price, show a single-point chart (so UI has a chart)
    st.warning("No historical data found for the selected period. Showing latest quote if available.")
    if latest_price is not None:
        try:
            ts_text = last_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts_text = str(last_timestamp)
        st.write(f"Latest price for {ticker}: ${latest_price:,.2f} (as of {ts_text}, source: {price_source})")

        # Fundaments should still be shown even if no history
        st.subheader("Fundamentals (P/E, Revenue & Gross Profit)")

        pe = funds.get("pe")
        if pe is not None:
            st.write(f"P/E ratio (trailing/forward): {pe:.2f}")
        else:
            st.write("P/E ratio: N/A")

        rev = funds.get("revenue")
        if rev:
            rev_df = pd.DataFrame(rev, columns=["Year", "Revenue"])
            rev_df["Revenue"] = rev_df["Revenue"].apply(lambda v: f"${v:,.0f}")
            st.markdown("#### Revenue (past years)")
            st.table(rev_df)
            rev_pct = funds.get("revenue_change_pct")
            rev_cagr = funds.get("revenue_cagr_pct")
            if rev_pct is not None:
                st.write(f"Revenue change (first -> last): {rev_pct:.2f}%")
            else:
                st.write("Revenue change: N/A")
            if rev_cagr is not None:
                st.write(f"Revenue CAGR (annualized): {rev_cagr:.2f}%")
        else:
            st.write("Revenue data (annual) not available via yfinance for this ticker.")

        gross = funds.get("gross")
        if gross:
            gross_df = pd.DataFrame(gross, columns=["Year", "Gross Profit"])
            gross_df["Gross Profit"] = gross_df["Gross Profit"].apply(lambda v: f"${v:,.0f}")
            st.markdown("#### Gross Profit (past years)")
            st.table(gross_df)
            gross_pct = funds.get("gross_change_pct")
            gross_cagr = funds.get("gross_cagr_pct")
            if gross_pct is not None:
                st.write(f"Gross profit change (first -> last): {gross_pct:.2f}%")
            else:
                st.write("Gross profit change: N/A")
            if gross_cagr is not None:
                st.write(f"Gross profit CAGR (annualized): {gross_cagr:.2f}%")
        else:
            st.write("Gross profit data (annual) not available via yfinance for this ticker.")

        # create a single-row series so the chart area still appears
        try:
            df_point = pd.DataFrame({"Close": [latest_price]}, index=[pd.to_datetime(last_timestamp)])
            st.line_chart(df_point["Close"])
        except Exception:
            # if timestamp conversion fails, show a numeric metric instead
            st.metric(label=f"{ticker}", value=f"${latest_price:,.2f}")
    else:
        st.info("Please enter a valid stock ticker to begin or try again later.")
