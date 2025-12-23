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

# Refresh interval selection (milliseconds shown here for control below)
refresh_choice = st.sidebar.selectbox(
    "Auto-refresh interval",
    options=["Off", "1s", "5s", "15s", "30s", "60s"],
    index=1,
    help="How often the dashboard should auto-refresh. 'Off' disables automatic refresh."
)

REFRESH_MAP_MS = {
    "Off": 0,
    "1s": 1000,
    "5s": 5000,
    "15s": 15000,
    "30s": 30000,
    "60s": 60000,
}

refresh_ms = REFRESH_MAP_MS[refresh_choice]

# Try to enable automatic refresh using streamlit-autorefresh if requested
if refresh_ms > 0:
    try:
        from streamlit_autorefresh import st_autorefresh
        # Use st_autorefresh to rerun the app every refresh_ms milliseconds
        st_autorefresh(interval=refresh_ms, key=f"autorefresh_{ticker}_{period}_{refresh_ms}")
    except Exception:
        st.warning(
            "Automatic refresh requested but streamlit-autorefresh is not installed. "
            "Install it with `pip install streamlit-autorefresh` to enable auto-refresh."
        )

# Map selected period to yfinance period and interval
PERIOD_INTERVAL_MAP = {
    "1d": {"period": "1d", "interval": "1m"},
    "1w": {"period": "7d", "interval": "5m"},
    "1m": {"period": "1mo", "interval": "15m"},
    "3m": {"period": "3mo", "interval": "60m"},
    "1y": {"period": "1y", "interval": "1d"},
    "5y": {"period": "5y", "interval": "1d"},
}

# Short TTL so repeated refreshes still fetch fresh data (set small to match auto-refresh)
@st.cache_data(ttl=3)
def fetch_history_cached(ticker_symbol: str, period_param: str, interval_param: str, prepost: bool = False):
    """
    Fetch historical data for ticker using yfinance.download.
    Cached with a very short TTL so the autorefresh still sees updates.
    """
    try:
        data = yf.download(
            tickers=ticker_symbol,
            period=period_param,
            interval=interval_param,
            progress=False,
            threads=False,
            prepost=prepost,
            show_errors=False,
        )
        # Flatten columns if needed
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [' '.join(col).strip() for col in data.columns.values]
        return data
    except Exception:
        return pd.DataFrame()

def fetch_latest_quote(ticker_symbol: str):
    """
    Try to fetch the most recent price and a reliable timestamp.
    1) Try intraday history with prepost=True (preferred; gives timestamped prices).
    2) If no intraday rows, fall back to Ticker.fast_info or Ticker.info common price keys.
    Returns (price_or_None, timestamp_or_now, source_string)
    """
    try:
        tk = yf.Ticker(ticker_symbol)

        # 1) Try last minute intraday including pre/post-market
        try:
            hist = tk.history(period="1d", interval="1m", prepost=True)
            if hist is not None and not hist.empty:
                last_price = float(hist['Close'].iloc[-1])
                last_ts = hist.index[-1]
                # If timestamp is pandas Timestamp, convert to python datetime (keep timezone if present)
                if hasattr(last_ts, "to_pydatetime"):
                    last_ts = last_ts.to_pydatetime()
                return last_price, last_ts, "intraday_history"
        except Exception:
            # ignore and fallback
            pass

        # 2) Fast info (if available)
        try:
            fast = getattr(tk, "fast_info", None)
            if isinstance(fast, dict):
                for key in ("last_price", "last_trade_price", "regularMarketPrice", "currentPrice"):
                    if key in fast and fast[key] is not None:
                        return float(fast[key]), datetime.datetime.now(), "fast_info"
        except Exception:
            pass

        # 3) Ticker.info fallback (slower and may be rate-limited)
        try:
            info = tk.info
            if isinstance(info, dict):
                for key in ("regularMarketPrice", "currentPrice", "previousClose", "lastPrice"):
                    if key in info and info[key] is not None:
                        return float(info[key]), datetime.datetime.now(), "info"
        except Exception:
            pass

        # 4) As a last resort try yf.download for very short period
        try:
            dl = yf.download(ticker_symbol, period="1d", interval="1m", prepost=True, progress=False, threads=False)
            if dl is not None and not dl.empty:
                price = float(dl['Close'].iloc[-1])
                ts = dl.index[-1]
                if hasattr(ts, "to_pydatetime"):
                    ts = ts.to_pydatetime()
                return price, ts, "download_fallback"
        except Exception:
            pass

    except Exception:
        pass

    return None, None, "none"

# Only proceed if a ticker is provided
if not ticker:
    st.sidebar.info("Please enter a stock ticker to begin.")
    st.stop()

# Determine the fetch params
params = PERIOD_INTERVAL_MAP.get(period, PERIOD_INTERVAL_MAP["1d"])

# For 1d (intraday) we enable prepost=True so after-hours are included
prepost = True if period == "1d" else False

history = fetch_history_cached(ticker, params["period"], params["interval"], prepost=prepost)

# Get latest quote (not cached to ensure freshest quote)
latest_price, last_timestamp, price_source = fetch_latest_quote(ticker)

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
        # Format timestamp (preserve tz info if present)
        try:
            ts_text = last_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts_text = str(last_timestamp)
        st.write(f"Last updated: {ts_text} (source: {price_source})")
    else:
        st.warning("Could not fetch latest price. Please check the ticker symbol or your internet connection.")

# Main display
if history is not None and not history.empty:
    st.subheader(f"{ticker} Price ({period})")
    # Line chart for Close price if present
    if 'Close' in history.columns:
        st.line_chart(history['Close'])
        st.subheader(f"Key Metrics for {ticker} ({period})")
        st.write(history['Close'].describe())
    else:
        st.warning("Historical data returned but 'Close' column missing.")
    st.subheader("Raw Data (last 100 rows)")
    st.write(history.tail(100))
else:
    st.warning("No historical data found for the ticker symbol with the selected period. Showing latest quote if available.")
    if latest_price is not None:
        try:
            ts_text = last_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts_text = str(last_timestamp)
        st.write(f"Latest price for {ticker}: ${latest_price:,.2f} (as of {ts_text}, source: {price_source})")
    else:
        st.info("Please enter a valid stock ticker to begin or try again later.")
