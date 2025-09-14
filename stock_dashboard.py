import streamlit as st
import yfinance as yf
import pandas as pd

st.title("Stock Market Dashboard")

# Sidebar for user input
ticker = st.sidebar.text_input("Enter Stock Ticker", value="AAPL")
start_date = st.sidebar.date_input("Start Date", value=pd.to_datetime("2023-01-01"))
end_date = st.sidebar.date_input("End Date", value=pd.to_datetime("today"))

# Fetch data
if ticker:
    data = yf.download(ticker, start=start_date, end=end_date)
    if not data.empty:
        st.subheader(f"{ticker} Stock Price")
        st.line_chart(data['Close'])

        st.subheader(f"Key Metrics for {ticker}")
        st.write(data.describe())

        st.subheader("Raw Data")
        st.write(data)
    else:
        st.warning("No data found for the ticker symbol.")
else:
    st.info("Please enter a stock ticker to begin.")