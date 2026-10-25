"""sandbox MCP server over stdio: 1 tool, run_python, on sensai/sandbox.py

run: python -m sensai.servers.sandbox
the backend (docker or subprocess) is picked once at start, the instructions say which one ->
the model knows if the network is cut or not
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sensai import sandbox
from sensai.data import data_dir, out_dir

BACKEND = sandbox.pick_backend()

LIMITS = {
    "docker": f"Runs in a Docker container with no network, {sandbox.CPUS} CPU, {sandbox.MEMORY} of memory "
              f"and {sandbox.TIMEOUT} s per run.",
    "subprocess": f"Docker isn't available, so it runs as a local Python process: {sandbox.TIMEOUT} s and "
                  "CPU time per run are capped, network and memory are not.",
}

server = MCPServer(
    name="sensai-sandbox",
    instructions="Runs the Python code you write, for any calculation on market data: returns, "
                 "correlations, regressions, rolling stats, plots. Do the math here instead of in your head. "
                 f"{LIMITS[BACKEND]} Libraries: pandas, numpy, scipy, statsmodels, matplotlib; nothing can "
                 f"be installed and there is no internet. The data folder ({data_dir()}) is read only: read the "
                 "CSV files at the `path` the market tools return. Each run writes in its own folder under "
                 f"{out_dir()}. The user sees every file you save right under your answer, as a link, and "
                 "images are drawn there: refer to the file by name, don't say you can't display it.",
    log_level="WARNING",
)


@server.tool()
def run_python(code: str) -> dict:
    """Run Python code in a sandbox and return its printed output and the files it saved.

    Use it for every calculation on data (returns, correlations, volatility, regressions...):
    read the CSV files at the `path` field of get_prices or get_sentiment results with pandas,
    and print() every number you need, only printed output comes back. Save plots with
    matplotlib under a plain file name (plt.savefig("corr.png")), they land in the run's folder.
    Libraries: pandas, numpy, scipy, statsmodels, matplotlib. No internet, no pip install.
    If the code fails you get the traceback: fix the code and call run_python again.

    Args:
        code: A complete Python script.
    """
    result = sandbox.run(code, backend=BACKEND)
    if not result["ok"]:
        why = f"timed out after {sandbox.TIMEOUT}s" if result["timed_out"] else f"exit code {result['exit_code']}"
        raise ToolError(f"run {result['run_id']} failed ({why}):\n{result['stderr']}\n"
                        + (f"stdout before the error:\n{result['stdout']}" if result["stdout"].strip() else ""))
    return result


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
