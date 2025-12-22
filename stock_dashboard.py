import streamlit as st
import yfinance as yf
import pandas as pd
import datetime

st.set_page_config(page_title="Stock Market Dashboard", layout="wide")

st.title("Stock Market Dashboard")

# Sidebar for user input
ticker = st.sidebar.text_input("Enter Stock Ticker", value="AAPL").upper()
start_date = st.sidebar.date_input("Start Date", value=datetime.date(2023, 1, 1))
end_date = st.sidebar.date_input("End Date", value=datetime.date.today())
interval = st.sidebar.selectbox("Interval", options=["1d", "1wk", "1mo"], index=0)

@st.cache_data(ttl=3600)
def load_data(ticker: str, start: datetime.date, end: datetime.date, interval: str) -> pd.DataFrame:
    """
    Load historical market data from yfinance. Cached for 1 hour.
    """
    if not ticker:
        return pd.DataFrame()
    try:
        df = yf.download(ticker, start=start, end=end + datetime.timedelta(days=1), interval=interval, progress=False, threads=True)
        # Ensure datetime index and drop rows with NaN close (sometimes yfinance returns empty rows)
        if not df.empty:
            df = df.dropna(subset=["Close"])
            df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return pd.DataFrame()

# Fetch data
if ticker:
    data = load_data(ticker, start_date, end_date, interval)

    if data.empty:
        st.warning("No data found for the ticker symbol and date range you entered. Check the ticker and try again.")
    else:
        # Compute moving averages
        data["MA20"] = data["Close"].rolling(window=20).mean()
        data["MA50"] = data["Close"].rolling(window=50).mean()

        # Layout: charts on top, metrics and raw data below
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

        # Download CSV
        csv = data.to_csv().encode("utf-8")
        st.download_button(label="Download data as CSV", data=csv, file_name=f"{ticker}_history.csv", mime="text/csv")
else:
    st.info("Please enter a stock ticker in the sidebar to begin.")
