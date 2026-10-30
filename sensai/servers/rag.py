"""news search MCP server over stdio: 1 tool, search_news, RAG over the articles of a ticker

run: python -m sensai.servers.rag
apart from quant-data: the normal eval doesnt start it (same tools and system msg as before), and it
needs a local ollama w/ an embedding model. w/o it the tool isnt registered -> the model cant waste a
step on it, the chat warns the user (commands.py)
"""

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sensai.data import REPO, DataError, rag

load_dotenv(REPO / ".env", override=False)

why_off = rag.unavailable()

server = MCPServer(
    name="sensai-rag",
    instructions=f"News search is off this session: {why_off}. Use get_news." if why_off else
                 "Search by meaning in the news of a US listed ticker (Massive): finds the articles that talk about "
                 "what is asked, between 2 dates. It reads titles, summaries and sentiment reasons, not full articles: "
                 "use fetch on a url to read one. An article published near a price move doesn't prove the cause.",
    log_level="WARNING",
)

if not why_off:
    @server.tool()
    def search_news(query: str, ticker: str, start: str | None = None, end: str | None = None, limit: int = 5) -> dict:
        """Search a ticker's news by meaning and return the closest articles, with their url and a score.

        Use it instead of get_news when the question is about a topic or an event: why a stock moved on a
        date, what is said about a product, a deal, a risk. Search understands meaning, not dates: for a
        date, put it in start and end, not in the query. For a move on 1 day, use that day for both.
        Cite the url of each article you use.

        Args:
            query: What to look for, in words, e.g. "reasons for the Nvidia stock falling".
            ticker: Stock symbol, e.g. NVDA.
            start: First day, YYYY-MM-DD. Default: 30 days before end.
            end: Last day, YYYY-MM-DD. Default: today.
            limit: How many articles, 1 to 20. Default 5.
        """
        try:
            return rag.search_news(query, ticker, start, end, limit)
        except DataError as e:
            raise ToolError(str(e)) from None


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
