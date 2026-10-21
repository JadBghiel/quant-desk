"""web search MCP server over stdio: 1 tool, web_search, on tavily

run: python -m sensai.servers.web
the instructions are its limits, sensai puts them in the system prompt -> the model knows when
to search and what a search cant give
"""

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sensai.data import REPO, DataError, web

load_dotenv(REPO / ".env", override=False)

server = MCPServer(
    name="sensai-web",
    instructions="Live web search (Tavily) for what the market data tools don't cover: recent events "
                 "and announcements, macro data (rates, inflation, central banks), non-US markets, company "
                 "facts, or a second source when a data tool fails. Returns titles, URLs, dates and short "
                 "snippets, not full pages: use fetch on a URL to read it. Limited to 1000 searches a month, "
                 "so don't search for data a market tool already gives.",
    log_level="WARNING",
)


@server.tool()
def web_search(query: str, topic: str = "general", days: int | None = None, max_results: int = 5) -> dict:
    """Search the web and return the top results: title, URL, publish date when known, and a short snippet.

    Use it whenever the other tools don't cover a question (options and implied volatility, macro data,
    recent events, filings, non-US news...): search before ever answering that you don't have the data.
    The snippets are short: when they don't hold the answer (a table, a ranking, a full article), call
    fetch on the most promising URL and read the page before saying you can't find it.
    Cite the URLs of the results you use in your answer.

    Args:
        query: What to search for, as a short search engine query, e.g. "Fed rate decision September 2026".
        topic: general (default), news (recent articles, with dates) or finance.
        days: Only results from the last N days, e.g. 7. Default: no limit.
        max_results: How many results, 1 to 10. Default 5.
    """
    try:
        return web.web_search(query, topic, days, max_results)
    except DataError as e:
        raise ToolError(str(e)) from None


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
