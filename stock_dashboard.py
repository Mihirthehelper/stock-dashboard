import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import time

st.set_page_config(page_title="Stock Market Dashboard", layout="wide")
st.title("Stock Market Dashboard")

# Sidebar inputs
ticker = st.sidebar.text_input("Enter Stock Ticker", value="AAPL").upper()

period = st.sidebar.selectbox(
    "Select Time Range",
    options=["1d", "1w", "1m", "3m", "1y", "5y"],
    index=0,
    help="Choose how much history to display"
)

shares = st.sidebar.number_input(
    "Number of Shares",
    min_value=0.0,
    value=1.0,
    step=1.0,
    format="%.0f"
)

# Optional: automatic refresh (requires streamlit-autorefresh package).
# If you install streamlit-autorefresh, the page will auto-refresh at the interval below.
# pip install streamlit-autorefresh
try:
    from streamlit_autorefresh import st_autorefresh
    # Refresh every 5 seconds (5000 ms). Change interval to 1000 for 1s refresh, but be mindful of rate limits.
    st_autorefresh(interval=5000, key="stock_autorefresh")
except Exception:
    # If streamlit-autorefresh is not installed, we still fetch fresh data every time the app reruns.
    # A manual page reload will fetch new data.
    pass

# Map selected period to yfinance period and interval
PERIOD_INTERVAL_MAP = {
    "1d": {"period": "1d", "interval": "1m"},
    "1w": {"period": "7d", "interval": "5m"},
    "1m": {"period": "1mo", "interval": "15m"},
    "3m": {"period": "3mo", "interval": "60m"},
    "1y": {"period": "1y", "interval": "1d"},
    "5y": {"period": "5y", "interval": "1d"},
}

@st.cache_data(ttl=3)
def fetch_history(ticker_symbol: str, period_param: str, interval_param: str):
    """
    Fetch historical data for ticker using yfinance.
    Cached for a short TTL to avoid overloading the data provider while still giving near-real-time updates.
    """
    try:
        data = yf.download(
            tickers=ticker_symbol,
            period=period_param,
            interval=interval_param,
            progress=False,
            threads=False,
            show_errors=False,
        )
        # If yfinance returns a DataFrame with MultiIndex columns (for single ticker), flatten them
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [' '.join(col).strip() for col in data.columns.values]
        return data
    except Exception:
        return pd.DataFrame()

def get_latest_price_and_timestamp(ticker_symbol: str, history_df: pd.DataFrame):
    """
    Determine the most recent price and timestamp:
    - Prefer the last 'Close' from history if available.
    - Fallback to yfinance Ticker info fields (regularMarketPrice).
    """
    latest_price = None
    last_ts = None

    try:
        if history_df is not None and not history_df.empty:
            # Use the last available close price in the history
            # For intraday data, this will be the most recent minute/interval close
            latest_price = float(history_df['Close'].iloc[-1])
            # If index is a DatetimeIndex, use it
            if isinstance(history_df.index, pd.DatetimeIndex):
                last_ts = history_df.index[-1].to_pydatetime()
        # Fallback to ticker info for near-real-time price
        if latest_price is None:
            tk = yf.Ticker(ticker_symbol)
            info = tk.fast_info if hasattr(tk, "fast_info") else tk.info
            # Try a few common keys
            for key in ("last_price", "regularMarketPrice", "previousClose", "currentPrice"):
                if isinstance(info, dict) and key in info and info[key] is not None:
                    latest_price = float(info[key])
                    break
            # If still None, try history short fetch
            if latest_price is None:
                hist = tk.history(period="1d", interval="1m")
                if hist is not None and not hist.empty:
                    latest_price = float(hist['Close'].iloc[-1])
                    if isinstance(hist.index, pd.DatetimeIndex):
                        last_ts = hist.index[-1].to_pydatetime()
    except Exception:
        latest_price = None

    # If we don't have a timestamp from data, use now
    if last_ts is None:
        last_ts = datetime.datetime.now()

    return latest_price, last_ts

# Only proceed if a ticker is provided
if not ticker:
    st.sidebar.info("Please enter a stock ticker to begin.")
    st.stop()

# Determine the fetch params
params = PERIOD_INTERVAL_MAP.get(period, PERIOD_INTERVAL_MAP["1d"])
history = fetch_history(ticker, params["period"], params["interval"])

latest_price, last_timestamp = get_latest_price_and_timestamp(ticker, history)

# Sidebar display: current price and total value
with st.sidebar:
    st.markdown("## Current Price")
    if latest_price is not None:
        price_str = f"${latest_price:,.2f}"
        st.metric(label=f"{ticker}", value=price_str)
        total_value = latest_price * float(shares)
        st.write(f"Shares: {int(shares)}")
        st.write(f"Total value: ${total_value:,.2f}")
        st.write(f"Last updated: {last_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        st.warning("Could not fetch latest price. Please check the ticker symbol or your internet connection.")

# Main display
if history is not None and not history.empty:
    st.subheader(f"{ticker} Price ({period})")
    # Line chart for Close price
    st.line_chart(history['Close'])

    st.subheader(f"Key Metrics for {ticker} ({period})")
    # Describe last N rows depending on period
    st.write(history['Close'].describe())

    st.subheader("Raw Data (last 100 rows)")
    st.write(history.tail(100))
else:
    st.warning("No historical data found for the ticker symbol with the selected period. Showing latest quote if available.")
    if latest_price is not None:
        st.write(f"Latest price for {ticker}: ${latest_price:,.2f} (as of {last_timestamp.strftime('%Y-%m-%d %H:%M:%S')})")
    else:
        st.info("Please enter a valid stock ticker to begin or try again later.")
