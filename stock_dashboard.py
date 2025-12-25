import streamlit as st
import yfinance as yf
import pandas as pd
import datetime

st.set_page_config(page_title="Stock Market Dashboard", layout="wide")
st.title("Stock Market Dashboard")

# Sidebar inputs
ticker = st.sidebar.text_input("Enter Stock Ticker", value="AAPL").upper().strip()

period = st.sidebar.selectbox(
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


# Only proceed if a ticker is provided
if not ticker:
    st.sidebar.info("Please enter a stock ticker to begin.")
    st.stop()

# Fetch history & latest price
history = fetch_history(ticker, period)
latest_price, last_timestamp, price_source = fetch_latest_price(ticker)

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

# Main display: chart, metrics, raw data
if history is not None and not history.empty and "Close" in history.columns:
    st.subheader(f"{ticker} Price ({period})")

    # Work on a copy to avoid mutating original
    df = history.copy()

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
    params = PERIOD_INTERVAL_MAP.get(period, {})
    interval = params.get("interval", "")
    if interval != "1d" and (show_sma50 or show_sma200):
        st.caption(
            "Note: The SMA windows are measured in rows (intervals). For intraday intervals (1m, 5m, 15m, 60m) "
            "the 50/200 windows count data rows, not calendar trading days. If you want 50/200 trading-day SMAs "
            "on intraday data, I can resample to daily closes and then compute the SMAs."
        )

    # Key metrics (Close.describe) and last values of SMAs
    st.subheader(f"Key Metrics for {ticker} ({period})")
    st.write(df["Close"].describe())

    # Show latest SMA values (if present)
    sma_latest = {}
    if show_sma50 and "SMA50" in df.columns:
        sma_latest["SMA50"] = df["SMA50"].iloc[-1]
    if show_sma200 and "SMA200" in df.columns:
        sma_latest["SMA200"] = df["SMA200"].iloc[-1]
    if sma_latest:
        st.write("Latest moving average values:")
        # Format nicely
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

        # create a single-row series so the chart area still appears
        try:
            df_point = pd.DataFrame({"Close": [latest_price]}, index=[pd.to_datetime(last_timestamp)])
            st.line_chart(df_point["Close"])
        except Exception:
            # if timestamp conversion fails, show a numeric metric instead
            st.metric(label=f"{ticker}", value=f"${latest_price:,.2f}")
    else:
        st.info("Please enter a valid stock ticker to begin or try again later.")
