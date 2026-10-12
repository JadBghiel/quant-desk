"""prices + fundamentals from yfinance

prices are saved as csv in data/prices/ and only a summary goes back to the model,
250 rows in the context would blow it for nothing. the sandbox (#7) reads the csv
"""

import csv
import logging
from datetime import date, datetime, timedelta

from sensai.data import DataError, sub_dir
from sensai.data.cache import FOREVER, cached

INTERVALS = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]
# how far back yahoo serves each intraday interval, in days
MAX_LOOKBACK = {"1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "90m": 60, "60m": 730, "1h": 730}
FUNDAMENTALS = {
    "name": ("longName", "shortName"),
    "sector": ("sector",),
    "industry": ("industry",),
    "currency": ("currency",),
    "price": ("currentPrice", "regularMarketPrice"),
    "market_cap": ("marketCap",),
    "trailing_pe": ("trailingPE",),
    "forward_pe": ("forwardPE",),
    "beta": ("beta",),
    # yahoo sends it in % already (KO 2.43 = dividendRate 2.12 / price 87.18), unit in the name
    "dividend_yield_pct": ("dividendYield",),
    "fifty_two_week_high": ("fiftyTwoWeekHigh",),
    "fifty_two_week_low": ("fiftyTwoWeekLow",),
}


def _yf():
    # imported lazily, yfinance pulls pandas and takes ~1s to import
    import yfinance
    # it logs "possibly delisted" & co on stderr, would leak into the chat. errors are handled here
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return yfinance


def _day(value, name):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise DataError(f"{name} must be a date like 2026-01-31, got {value!r}") from None


def _norm_ticker(ticker):
    t = (ticker or "").strip().upper()
    if not t:
        raise DataError("ticker is empty")
    return t


def check_range(interval, start, end, today=None):
    """dates + interval checked against yahoo's limits, msg says what to do instead"""
    today = today or date.today()
    if interval not in INTERVALS:
        raise DataError(f"interval {interval!r} not supported, use one of {', '.join(INTERVALS)}")
    if start > end:
        raise DataError(f"start {start} is after end {end}")
    if end > today:
        raise DataError(f"end {end} is in the future")
    limit = MAX_LOOKBACK.get(interval)
    if limit and (today - start).days > limit:
        raise DataError(f"yahoo only serves {interval} bars for the last {limit} days, "
                        f"use a later start or a bigger interval like 1d")


def get_prices(ticker, start=None, end=None, interval="1d", today=None):
    ticker = _norm_ticker(ticker)
    today = today or date.today()
    end_d = _day(end, "end") if end else today
    start_d = _day(start, "start") if start else end_d - timedelta(days=365)
    check_range(interval, start_d, end_d, today)

    def fetch():
        try:
            # yahoo's end is exclusive
            df = _yf().Ticker(ticker).history(start=start_d.isoformat(), end=(end_d + timedelta(days=1)).isoformat(),
                                              interval=interval, auto_adjust=True, raise_errors=False)
        except Exception as e:
            raise DataError(f"yahoo finance failed for {ticker}: {e}") from None
        if df is None or df.empty:
            raise DataError(f"no price data for {ticker} between {start_d} and {end_d}, check the ticker")
        daily = interval in ("1d", "5d", "1wk", "1mo", "3mo")
        return [[(ts.date().isoformat() if daily else ts.isoformat()), round(float(r.Open), 4), round(float(r.High), 4),
                 round(float(r.Low), 4), round(float(r.Close), 4), int(r.Volume)]
                for ts, r in df.iterrows()]

    # past ranges cant change, anything touching today is refreshed hourly
    ttl = FOREVER if end_d < today else 3600
    rows, meta = cached("prices", [ticker, start_d.isoformat(), end_d.isoformat(), interval], ttl, fetch)

    path = sub_dir("prices") / f"{ticker}_{interval}_{start_d}_{end_d}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        w.writerows(rows)

    first, last = rows[0], rows[-1]
    return {
        "ticker": ticker,
        "interval": interval,
        "rows": len(rows),
        "first_date": first[0],
        "last_date": last[0],
        "first_close": first[4],
        "last_close": last[4],
        "return_pct": round((last[4] / first[4] - 1) * 100, 2) if first[4] else None,
        "high": max(r[2] for r in rows),
        "low": min(r[3] for r in rows),
        "avg_volume": int(sum(r[5] for r in rows) / len(rows)),
        "path": str(path),
        "columns": ["date", "open", "high", "low", "close", "volume"],
        "source": "yfinance",
        **meta,
    }


def get_fundamentals(ticker):
    ticker = _norm_ticker(ticker)

    def fetch():
        try:
            info = _yf().Ticker(ticker).info or {}
        except Exception as e:
            raise DataError(f"yahoo finance failed for {ticker}: {e}") from None
        if not info.get("quoteType") or not any(info.get(k) for k in ("longName", "shortName")):
            raise DataError(f"no fundamentals for {ticker}, check the ticker")
        out = {}
        for field, keys in FUNDAMENTALS.items():
            value = next((info[k] for k in keys if info.get(k) is not None), None)
            if value is not None:
                out[field] = round(value, 4) if isinstance(value, float) else value
        ts = info.get("earningsTimestamp")
        if ts:
            # yahoo gives the next one or the last one depending on the day, so no "next" in the name
            out["earnings_date"] = datetime.fromtimestamp(ts).date().isoformat()
        return out

    # bump the version when FUNDAMENTALS changes so old cache entries w/ the old fields are ignored
    value, meta = cached("fundamentals", ["v2", ticker], 24 * 3600, fetch)
    return {"ticker": ticker, **value, "source": "yfinance", **meta}
