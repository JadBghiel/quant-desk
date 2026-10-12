"""quant data MCP server over stdio: prices, fundamentals, news, sentiment

standalone, any MCP client can use it (sensai in #5, the MCP inspector, claude desktop...)
run: python -m sensai.servers.quant_data

tools are thin wrappers on sensai.data, the docstrings are what the model reads to pick a tool
"""

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sensai.data import REPO, DataError, market, news

# launched by any client from any dir, so the repo's .env is loaded explicitly
load_dotenv(REPO / ".env", override=False)

server = MCPServer(
    name="sensai-quant-data",
    instructions="Market data for quant research: daily or intraday prices, fundamentals, "
                 "news and news sentiment per ticker. Full data is saved as files, results are summaries.",
    # tool errors already reach the client as is_error results, logging them too is noise on stderr
    log_level="WARNING",
)


def _run(fn, *args, **kwargs):
    # a DataError is anticipated, its msg reaches the model as is. anything else stays a crash
    try:
        return fn(*args, **kwargs)
    except DataError as e:
        raise ToolError(str(e)) from None


@server.tool()
def get_prices(ticker: str, start: str | None = None, end: str | None = None, interval: str = "1d") -> dict:
    """Historical OHLCV prices for a ticker, from Yahoo Finance.

    Returns a summary (first/last close, return %, high, low, average volume) and the path of a
    CSV file with every bar (columns: date, open, high, low, close, volume).

    Args:
        ticker: Stock symbol, e.g. NVDA.
        start: First day, YYYY-MM-DD. Default: 1 year before end.
        end: Last day, YYYY-MM-DD. Default: today.
        interval: Bar size: 1d (default), 1wk, 1mo, or intraday 1h, 30m, 15m, 5m, 1m
            (1m only for the last 7 days, under 1h only for the last 60 days).
    """
    return _run(market.get_prices, ticker, start, end, interval)


@server.tool()
def get_fundamentals(ticker: str) -> dict:
    """Company fundamentals from Yahoo Finance: name, sector, industry, price, market cap,
    trailing and forward P/E, beta, dividend yield in percent, 52 week high and low, earnings date.

    Args:
        ticker: Stock symbol, e.g. NVDA.
    """
    return _run(market.get_fundamentals, ticker)


@server.tool()
def get_news(ticker: str, days: int = 7, limit: int = 10) -> dict:
    """Recent news articles about a ticker, most relevant first, from Alpha Vantage.

    Each article has its time, title, source, url, a short summary, and the sentiment of the
    article towards this ticker (score from -1 bearish to 1 bullish, label, relevance 0 to 1).

    Args:
        ticker: Stock symbol, e.g. NVDA.
        days: How many days back to look, 1 to 365. Default 7.
        limit: How many articles to return, 1 to 50. Default 10.
    """
    return _run(news.get_news, ticker, days, limit)


@server.tool()
def get_sentiment(ticker: str, days: int = 30) -> dict:
    """News sentiment for a ticker over the last days, from Alpha Vantage.

    Returns the number of articles, the relevance-weighted mean sentiment score (-1 bearish to
    1 bullish) and its label, the count of articles per label, and the path of a CSV file with
    the daily series (columns: date, n_articles, mean_score).

    Args:
        ticker: Stock symbol, e.g. NVDA.
        days: How many days back to look, 1 to 365. Default 30.
    """
    return _run(news.get_sentiment, ticker, days)


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
