import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import traceback

st.set_page_config(page_title="Stock Market Dashboard (diagnostic)", layout="wide")

st.title("Stock Market Dashboard — Diagnostic Mode")

# Sidebar for user input
ticker = st.sidebar.text_input("Enter Stock Ticker", value="AAPL").upper()
start_date = st.sidebar.date_input("Start Date", value=datetime.date(2020, 1, 1))
end_date = st.sidebar.date_input("End Date", value=datetime.date.today())
interval = st.sidebar.selectbox("Interval", options=["1d", "1wk", "1mo"], index=0)

def try_download(ticker: str, start: datetime.date, end: datetime.date, interval: str):
    """
    Attempt yf.download and return (df, error_message).
    Robustly handles MultiIndex columns and missing 'Close' by falling back to 'Adj Close'.
    """
    try:
        df = yf.download(
            ticker,
            start=start,
            end=end + datetime.timedelta(days=1),  # include end day
            interval=interval,
            progress=False,
            threads=True,
        )
    except Exception as e:
        return pd.DataFrame(), f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    # If empty, return immediately
    if df.empty:
        return df, ""

    # If columns are a MultiIndex (e.g. when multiple tickers were returned),
    # try to select the ticker subframe or collapse to single-level names.
    try:
        if isinstance(df.columns, pd.MultiIndex):
            # If top-level contains the ticker, select that sub-DataFrame
            top_levels = list(df.columns.get_level_values(0))
            if ticker in top_levels:
                df = df[ticker].copy()
            else:
                # Collapse to last level (Open, High, Low, Close, ...)
                df.columns = df.columns.get_level_values(-1)
    except Exception:
        # If something goes wrong here, continue — we'll inspect columns below
        pass

    # Now ensure we have a Close column; if not, try to use Adj Close or any 'close' column
    cols = list(df.columns)
    if "Close" not in cols:
        if "Adj Close" in cols:
            df["Close"] = df["Adj Close"]
        else:
            # find any column name containing "close" (case-insensitive)
            close_like = [c for c in cols if "close" in str(c).lower()]
            if close_like:
                df["Close"] = df[close_like[0]]
            else:
                # No usable close column — return a helpful error message with columns shown
                cols_str = ", ".join(map(str, cols)) if cols else "<no columns>"
                err = f"No Close/Adj Close column in downloaded DataFrame. Columns returned: {cols_str}"
                return pd.DataFrame(), err

    # Normalize index and drop rows missing Close
    try:
        df.index = pd.to_datetime(df.index)
    except Exception:
        pass

    try:
        df = df.dropna(subset=["Close"], how="any")
    except Exception as e:
        return pd.DataFrame(), f"Error while dropping NaNs from 'Close': {type(e).__name__}: {e}\n{traceback.format_exc()}"

    return df, ""

if not ticker:
    st.info("Please enter a stock ticker in the sidebar to begin.")
else:
    st.sidebar.markdown("### Diagnostic info")
    st.sidebar.write(f"Ticker: `{ticker}`")
    st.sidebar.write(f"Start: `{start_date}`")
    st.sidebar.write(f"End: `{end_date}`")
    st.sidebar.write(f"Interval: `{interval}`")

    st.subheader("Attempting to download data from yfinance...")
    df, err = try_download(ticker, start_date, end_date, interval)

    if err:
        st.error("yfinance.download reported a problem:")
        st.code(err)
        st.stop()

    st.write("Download result summary:")
    st.write(f"- DataFrame empty: {df.empty}")
    st.write(f"- Shape: {df.shape}")
    if not df.empty:
        st.write("Columns:", list(df.columns))
        st.dataframe(df.head())

    if df.empty:
        st.warning("Primary download returned no rows. Trying yf.Ticker(...).history as a fallback...")

        try:
            t = yf.Ticker(ticker)
            hist = t.history(start=start_date, end=end_date + datetime.timedelta(days=1), interval=interval)
            if not hist.empty:
                # Try the same normalization / fallbacks as above
                if isinstance(hist.columns, pd.MultiIndex):
                    try:
                        top_levels = list(hist.columns.get_level_values(0))
                        if ticker in top_levels:
                            hist = hist[ticker].copy()
                        else:
                            hist.columns = hist.columns.get_level_values(-1)
                    except Exception:
                        pass

                if "Close" not in list(hist.columns):
                    if "Adj Close" in hist.columns:
                        hist["Close"] = hist["Adj Close"]
                    else:
                        close_like = [c for c in hist.columns if "close" in str(c).lower()]
                        if close_like:
                            hist["Close"] = hist[close_like[0]]

                if not hist.empty:
                    hist.index = pd.to_datetime(hist.index)
                    hist = hist.dropna(subset=["Close"], how="any")

            st.write("yf.Ticker.history result summary:")
            st.write(f"- DataFrame empty: {hist.empty}")
            st.write(f"- Shape: {hist.shape}")
            if not hist.empty:
                st.dataframe(hist.head())
        except Exception as e:
            st.error("yf.Ticker(...).history also raised an exception:")
            st.code(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

        st.info(
            "If both methods return empty DataFrames:\n"
            "- Confirm the ticker is correct (try `AAPL`, `MSFT`, `GOOG`).\n"
            "- Confirm date range includes actual trading days and start <= end. Avoid future end dates.\n"
            "- Check the app logs on Streamlit Cloud (App → Logs) for any network or SSL errors and paste them here if unsure."
        )
    else:
        # Normal display if data present
        data = df.copy()
        data["MA20"] = data["Close"].rolling(window=20).mean()
        data["MA50"] = data["Close"].rolling(window=50).mean()

        col1, col2 = st.columns((3, 1))

        with col1:
            st.subheader(f"{ticker} — Close Price")
            st.line_chart(data[["Close", "MA20", "MA50"]])

            st.subheader(f"{ticker} — Volume")
            if "Volume" in data.columns:
                st.bar_chart(data["Volume"])
            else:
                st.write("No Volume column available.")

        with col2:
            latest = data.iloc[-1]
            prev = data["Close"].iloc[-2] if len(data) >= 2 else None
            change = (latest["Close"] - prev) / prev * 100 if prev is not None else 0.0

            st.metric(label="Latest Close", value=f"${latest['Close']:,.2f}", delta=f"{change:.2f} %")
            st.write("Key stats")
            stats = {
                "Open": f"${latest['Open']:,.2f}" if "Open" in data.columns else "N/A",
                "High": f"${latest['High']:,.2f}" if "High" in data.columns else "N/A",
                "Low": f"${latest['Low']:,.2f}" if "Low" in data.columns else "N/A",
                "Volume": f"{int(latest['Volume']):,}" if "Volume" in data.columns else "N/A",
                "52w High": f"${data['Close'].max():,.2f}",
                "52w Low": f"${data['Close'].min():,.2f}",
            }
            st.json(stats)

        st.subheader("Summary statistics")
        st.write(data[[c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]].describe().transpose())

        st.subheader("Raw Data")
        st.dataframe(data)

        csv = data.to_csv().encode("utf-8")
        st.download_button(label="Download data as CSV", data=csv, file_name=f"{ticker}_history.csv", mime="text/csv")
