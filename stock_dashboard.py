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
    """Attempt yf.download and return (df, error_message)"""
    try:
        df = yf.download(
            ticker,
            start=start,
            end=end + datetime.timedelta(days=1),  # include end day
            interval=interval,
            progress=False,
            threads=True,
        )
        # Normalize index and drop rows without Close
        if not df.empty:
            df.index = pd.to_datetime(df.index)
            df = df.dropna(subset=["Close"], how="any")
        return df, ""
    except Exception as e:
        return pd.DataFrame(), f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

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
        st.error("yfinance.download raised an exception:")
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
            "- Check the app logs on Streamlit Cloud (App → Logs) for any network or permission errors and paste them here if unsure."
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
            st.bar_chart(data["Volume"])

        with col2:
            latest = data.iloc[-1]
            prev = data["Close"].iloc[-2] if len(data) >= 2 else None
            change = (latest["Close"] - prev) / prev * 100 if prev is not None else 0.0

            st.metric(label="Latest Close", value=f"${latest['Close']:,.2f}", delta=f"{change:.2f} %")
            st.write("Key stats")
            stats = {
                "Open": f"${latest['Open']:,.2f}",
                "High": f"${latest['High']:,.2f}",
                "Low": f"${latest['Low']:,.2f}",
                "Volume": f"{int(latest['Volume']):,}",
                "52w High": f"${data['Close'].max():,.2f}",
                "52w Low": f"${data['Close'].min():,.2f}",
            }
            st.json(stats)

        st.subheader("Summary statistics")
        st.write(data[["Open", "High", "Low", "Close", "Volume"]].describe().transpose())

        st.subheader("Raw Data")
        st.dataframe(data)

        csv = data.to_csv().encode("utf-8")
        st.download_button(label="Download data as CSV", data=csv, file_name=f"{ticker}_history.csv", mime="text/csv")
