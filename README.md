# sensai

A research assistant for quantitative developers and researchers, built from scratch in Python on
top of the Ollama HTTP API, without any LLM framework.

The goal is an agent that can take a question like *"Is NVDA moving more on news or on the market
lately?"*, fetch prices, news and sentiment, write and run its own analysis code, and compare each
number it reports with the data it fetched. This README describes what works today; the
[project status](#project-status) section lists what comes next.

## Setup

Requirements: Python 3.10+ and an [Ollama](https://ollama.com) account. Models run on Ollama Cloud,
so nothing heavy runs on your machine.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then set in .env:
#   OLLAMA_API_KEY        https://ollama.com/settings/keys
#   MASSIVE_API_KEY       https://massive.com (free, for news and sentiment)
#   TAVILY_API_KEY        https://tavily.com (free, 1000 web searches a month)
```

`requirements.txt` includes [uv](https://docs.astral.sh/uv/), which sensai uses to launch the
`fetch` MCP server in its own isolated environment (it is downloaded on the first run).

Optional, for the code sandbox (see [Analysis code in a sandbox](#analysis-code-in-a-sandbox-t2)):
with [Docker](https://docs.docker.com/get-docker/) running, build its image once (about 800 MB):

```bash
docker build -t sensai-sandbox sandbox/
```

Without Docker, the code runs as a local Python process with fewer limits.

The first time you start sensai, it offers to set up your profile (see [Your profile](#your-profile)),
and all its questions are optional.

## Running it

```bash
python -m sensai                        # start a new session with the default model
python -m sensai --model gpt-oss:20b    # use another model for this run
python -m sensai --resume               # reopen your last session
python -m sensai --resume 20260928-14   # reopen a specific session (a prefix of its id is enough)
```

| Flag                | Description                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------------- |
| `--model MODEL`   | Model to use, overrides `config.yaml`                                                     |
| `--host HOST`     | Ollama host, overrides `config.yaml` (e.g. `http://localhost:11434` for a local Ollama) |
| `--config CONFIG` | Path to the config file (default: `config.yaml`)                                          |
| `--resume [ID]`   | Reopen a saved session: the last one without an id, or the one whose id starts with `ID`  |
| `--trace`         | Show the details of each reasoning step: tool results and tokens used                       |
| `--version`       | Print the version                                                                           |
| `-h`, `--help`  | Show the help                                                                               |

## Commands in the chat

| Command              | Description                                                                                      |
| -------------------- | ------------------------------------------------------------------------------------------------ |
| `/help`            | List the commands                                                                                |
| `/model`           | Show the current model and the available ones                                                    |
| `/model <name>`    | Switch model; the conversation is kept                                                           |
| `/think`           | Show or hide the model's thinking (reasoning models only)                                        |
| `/tools`           | List the MCP servers and the tools the model can call                                            |
| `/trace`           | Show or hide the details of each step (tool results, tokens used)                                |
| `/steps`           | Print the trace of the last answer: the plan, every step with its thought and result, the tokens |
| `/check`           | List each number of the last answer, with the tool result it was found in, or why it was flagged |
| `/judge`           | Have a second model grade the last answer on the data it was given (one model call)              |
| `/note`            | Print the research note of the session and the path of its file                                  |
| `/system`          | Print the exact system message the model is given                                                |
| `/retry`           | Ask the last question again; the new answer replaces the old one once it completes               |
| `/undo`            | Remove the last question and answer, from the saved session too                                  |
| `/clear`           | Start a new session; the current one stays saved                                                 |
| `/sessions`        | List the 10 most recent sessions                                                                 |
| `/resume <id>`     | Reopen a session (a prefix of the id, or `last`)                                               |
| `/profile`         | Show your profile, with numbered notes                                                           |
| `/profile setup`   | Answer the profile questions again (Enter keeps a value, `-` clears it)                        |
| `/profile edit`    | Open the profile file in your editor (`$VISUAL`, `$EDITOR`, then `nano` or `vi`)         |
| `/remember <fact>` | Add a note sensai always keeps in mind                                                           |
| `/forget <n>`      | Remove note number `n`                                                                         |
| `/exit`            | Quit (Ctrl+D works too)                                                                          |

**Ctrl+C** during an answer stops it and returns to the prompt. The interrupted question is
dropped from the conversation, and `/retry` sends it again.

### Typing in the chat

| Key or input | What it does |
| --- | --- |
| ← → | Move in the line to fix a typo |
| ↑ ↓ | Go through your past inputs, including the ones of earlier runs |
| Tab | Complete a command: `/ste` becomes `/steps`. When several match (`/re`), a second Tab lists them (`/remember /resume /retry`). It also completes `/profile setup` and `/profile edit`, and the session ids after `/resume` |
| `"""` on its own line | Start a multi-line question: the prompt turns into `...`, and the next `"""` line sends everything as one question. Ctrl+C or Ctrl+D inside the block cancels it |

To paste a block of text (a table, a list of tickers, an error message), type `"""`, paste, then
type `"""`. Without the markers, each pasted line would be sent as a separate question.

Your past inputs are saved in `~/.sensai/history` (the last 1,000, readable by your user only).
A multi-line question is saved as one line. Line editing, the history and Tab need Python's
`readline` module, which macOS and Linux include; without it, the chat still works with plain input
and the `"""` blocks.

# Usage examples

Real sessions on the default model `gemma4:31b`. Long answers are shortened with `...`.

### Chat with history (B1)

The answer streams as it is generated, and earlier turns stay in context:

```
> my favourite ticker is NVDA
...
> what is my favourite ticker?
NVDA
```

With a reasoning model, a spinner (`⠹ thinking 2.4s`) shows while it thinks, then its thinking
streams in dim text before the answer. `/think` hides the thinking and keeps only the spinner:

```bash
python -m sensai --model gpt-oss:20b
```

Switch model in the middle of a conversation, the history stays:

```
> /model gpt-oss:20b
switched to gpt-oss:20b, history kept
```

Mistakes end in a one-line message instead of a traceback:

```
$ python -m sensai --model gpt-oss:20
sensai: model gpt-oss:20 not available on https://ollama.com, closest: gpt-oss:20b, gpt-oss:120b (/model to list them)

>
empty input, type a question or /help
```

Ctrl+C during an answer prints `[interrupted]` and returns to the prompt; the question is
dropped from the history, and `/retry` sends it again.

### Profile and saved sessions (M1)

The first start offers to set up your profile. Enter skips any question:

```
first time here. set up your profile now? every question is optional [Y/n] y
your name: Jad
sectors / industries you follow, comma separated: semiconductors, AI hardware
main tickers you follow, comma separated: NVDA, AMD, TSM
benchmark (e.g. SPY): SPY
research style (e.g. concise, formula before the number): concise, formula before the number
anything sensai should always know, 1 per line, empty line to finish
  -
```

See it, and add a note on the fly:

```
> /profile
name: Jad
sectors: semiconductors, AI hardware
watchlist: NVDA, AMD, TSM
benchmark: SPY
style: concise, formula before the number

> /remember my focus this week is NVDA earnings
noted (1 note(s)), /profile to see them
```

Sessions are saved after each answer. List them, close sensai, and pick up where you left off:

```
> /sessions
  20261012-145719  2026-10-12 14:57    3 turns  gemma4:31b     last close of AAPL and what do the news say

$ python -m sensai --resume
resumed 20261012-145719: last close of AAPL and what do the news say (3 turns)
you: open the most relevant AAPL article with the fetch tool and summarize it in 2 lines
sensai: Apple is showing strong relative performance and projected earnings growth ...
```

The profile goes to the model at the start of each session, so there is no need to repeat it:

```
> and for my watchlist?
NVDA, AMD, TSM; Focus: NVDA earnings
```

`/clear` starts a fresh session and keeps the previous one on disk:

```
> /clear
new session 20261027-143843, 20261027-143840 stays saved (/resume 20261027-143840)
```

### Market data and tool calling (T1)

`/tools` lists what the model can call, from our 2 servers and the official `fetch` server:

```
> /tools
quant-data: get_prices, get_fundamentals, get_news, get_sentiment
fetch: fetch
web: web_search
sandbox: run_python
```

The model decides which tools it needs, and each call shows as one line:

```
> last close of AAPL and what do the news say
⚙ get_prices(end=2026-10-12, start=2026-10-05, ticker=AAPL)  1.1s ✓
⚙ get_news(ticker=AAPL)  1.1s ✓
The last closing price for AAPL was $336.64 (as of October 9, 2026). ...

> what is the news sentiment on NVDA over the last 7 days, and why?
⚙ get_sentiment(days=7, ticker=NVDA)  1.0s ✓
⚙ get_news(days=7, ticker=NVDA)  0.0s ✓
... Bullish, mean score 0.539. Out of 154 scored articles, 88 positive, 61 neutral, 5 negative ...

> open the most relevant AAPL article with the fetch tool and summarize it in 2 lines
⚙ fetch(url=https://www.zacks.com/stock/news/3003233/apple-aapl-advances-wh...)  1.9s ✓
Apple is showing strong relative performance ... Zacks Rank #3 (Hold) due to a high valuation ...
```

(`get_news` took 0.0 s: it reused the Massive call `get_sentiment` had made.)

Without naming a ticker, it uses your profile's watchlist and benchmark:

```
> how did my watchlist do over the past 30 days vs my benchmark? give a table
⚙ get_prices(end=2026-10-12, start=2026-09-12, ticker=NVDA)  0.0s ✓
⚙ get_prices(end=2026-10-12, start=2026-09-12, ticker=AMD)  0.0s ✓
⚙ get_prices(end=2026-10-12, start=2026-09-12, ticker=TSM)  0.9s ✓
⚙ get_prices(end=2026-10-12, start=2026-09-12, ticker=SPY)  0.0s ✓
Performance over the last 30 days (2026-09-12 to 2026-10-12):

Ticker | Return % | vs SPY
--- | --- | ---
AMD | +23.24% | +20.66%
TSM | +8.74% | +6.16%
NVDA | +8.68% | +6.10%
SPY | +2.58% | 0.00%
```

A failed call is shown in red and handed back to the model, which explains it:

```
> what is the P/E of ZZZQX?
⚙ get_fundamentals(ticker=ZZZQX)  0.8s ✗ no fundamentals for ZZZQX, check the ticker
I cannot find the P/E ratio for ZZZQX as there are no fundamental data available for this ticker. ...
```

Company names come from a tool call:

```
> what company is GFS and how did it do over the last 30 days?
⚙ get_fundamentals(ticker=GFS)  1.7s ✓
⚙ get_prices(start=2026-09-12, ticker=GFS)  0.0s ✓
GFS is GLOBALFOUNDRIES Inc., a company in the Technology sector and Semiconductors industry.
Over the last 30 days (from 2026-09-14 to 2026-10-09), the stock returned +11.07% ...
```

### Web search and web pages (T3)

What no tool covers goes to web search, with the sources cited:

```
> what did the fed decide at its last meeting?
⚙ web_search(query=FOMC meeting decision October 2026, topic=finance)  1.7s ✓
At its last meeting in September 2026, the Federal Open Market Committee (FOMC) unanimously decided to raise
interest rates to respond to persistent inflation. ...
Source: https://www.wsj.com/economy/central-banking/fed-minutes-signal-further-rate-increase-this-year-but-no-urgency-for-october-hike-54ec759f

> what is the implied volatility of NVDA options expiring next month?
⚙ web_search(query=NVDA options implied volatility November 2026, topic=finance)  2.7s ✓
I cannot provide a single implied volatility (IV) for all NVDA options expiring next month because IV varies
by strike price and option type (calls vs puts).
However, based on a Yahoo Finance snapshot for the November 13, 2026, 150.00 call option, the implied
volatility was 80.37% as of the close on October 9, 2026. ...
```

`fetch` reads a web page in full:

```
> read https://en.wikipedia.org/wiki/Nvidia and tell me in 2 lines what Nvidia makes and where it is headquartered
⚙ fetch(url=https://en.wikipedia.org/wiki/Nvidia)  6.0s ✓
Nvidia develops GPUs, SoCs, and APIs for data science, high-performance computing, and artificial intelligence.
It is headquartered in Santa Clara, California.
```

### Multi-step reasoning (A1)

A multi-step question shows the plan, a thought before each call, then the answer from the results:

```
> compare NVDA and AMD 30d returns vs sentiment
Plan:
  1. Get 30-day price returns for NVDA and AMD
  2. Get 30-day sentiment analysis for NVDA and AMD
  3. Compare the returns and sentiment for both tickers
Thought: Retrieve 30-day price returns for NVDA
⚙ get_prices(start=2026-09-23, ticker=NVDA)  0.9s ✓
Thought: Retrieve 30-day price returns for AMD
⚙ get_prices(start=2026-09-23, ticker=AMD)  0.1s ✓
Thought: Retrieve 30-day sentiment for NVDA
⚙ get_sentiment(days=30, ticker=NVDA)  1.4s ✓
Thought: Retrieve 30-day sentiment for AMD
⚙ get_sentiment(days=30, ticker=AMD)  0.9s ✓
NVDA:
- 30d Return: -5.76%
- Sentiment: Bullish (Mean score: 0.4465)
AMD:
- 30d Return: -16.44%
- Sentiment: Bullish (Mean score: 0.4395)
...

> /steps
question: compare NVDA and AMD 30d returns vs sentiment
plan:
  1. Get 30-day price returns for NVDA and AMD
  ...
step 1  get_prices(start=2026-09-23, ticker=NVDA)  0.93s ok
        thought: Retrieve 30-day price returns for NVDA
        result: {"ticker": "NVDA", "interval": "1d", "rows": 23, ..., "return_pct": -5.76, ...
...
2 round(s) · 4 step(s) · 6.1k tokens · answered
```

`/trace` (or `--trace` at startup) adds the details live: the tokens of each round and a preview of
each result. A 1-step question skips the plan:

```
> /trace
step details shown

> what is the P/E of NVDA?
  round 1 · 2.3k in · 32 out · 2.3k of 60.0k used
Thought: Retrieving the P/E ratio for NVDA.
⚙ get_fundamentals(ticker=NVDA)  1.7s ✓
    → {"ticker": "NVDA", "name": "NVIDIA Corporation", "sector": "Technology", ...
The trailing P/E of NVDA is 27.574 and the forward P/E is 13.705.
  round 2 · 2.5k in · 36 out · 4.9k of 60.0k used
```

When a question uses up its budget, a dim line says so (`[budget reached: 12 steps, answering w/ what it has]`) and the model answers with the data it already has.

### Analysis code in a sandbox (T2)

The model writes Python on the CSV files the market tools saved and runs it with `run_python`. The
number comes from the code's output, and plots are saved under `out/`. With `--trace`, the code shows
under the thought:

```
> compute the rolling 30 day correlation between NVDA daily returns and its daily news sentiment
  over the last 6 months, give me the latest value and plot it
Plan:
  1. Get daily prices for NVDA for the last 6 months.
  2. Get daily news sentiment for NVDA for the last 6 months.
  3. Use run_python to calculate daily returns from prices, merge with sentiment data, compute the
     rolling 30-day correlation, and plot the result.
Thought: Getting NVDA daily prices for the last 6 months to calculate returns.
⚙ get_prices(start=2026-04-28, ticker=NVDA)  2.3s ✓
Thought: Getting NVDA daily news sentiment for the last 6 months.
⚙ get_sentiment(days=180, ticker=NVDA)  3.5s ✓
Thought: Computing the rolling 30-day correlation between NVDA returns and sentiment and saving the plot.
    import pandas as pd
    import matplotlib.pyplot as plt
    prices = pd.read_csv('.../data/prices/NVDA_1d_2026-04-28_2026-10-28.csv')
    sentiment = pd.read_csv('.../data/sentiment/NVDA_2026-05-01_2026-10-28.csv')
    ...
    rolling_corr = df['returns'].rolling(window=30).corr(df['mean_score'])
    print(f"Latest rolling 30-day correlation: {rolling_corr.iloc[-1]:.4f}")
    ...
    plt.savefig('nvda_sentiment_corr.png')
⚙ run_python(code=import pandas as pd import matplotlib.pyplot as plt # Load dat...)  0.7s ✓
    ↳ .../out/20261028-181324-11d7/nvda_sentiment_corr.png
The latest rolling 30-day correlation between NVDA daily returns and its daily news sentiment is 0.2601.

saved:
  /Users/.../out/20261028-181324-11d7/nvda_sentiment_corr.png
  [the chart, drawn in the terminal]
```

Since the model writes matplotlib code, it can chart anything the data allows, with no chart feature
written in sensai: a price since January, two stocks on one axis, a correlation heatmap, an RSI under
a price. Two real requests:

```
> can u make a chart about HOOD YTD stock price
Plan:
  1. Get historical daily prices for HOOD from 2026-01-01 to today.
  2. Use Python to plot the closing prices for the YTD period and save the chart.
⚙ get_prices(start=2026-01-01, ticker=HOOD)  0.8s ✓
⚙ run_python(code=import pandas as pd import matplotlib.pyplot as plt # Load the...)  1.9s ✓
The stock has seen a YTD return of -21.39%, moving from a first close of 115.21 on 2026-01-02 to
90.57 on 2026-10-28. During this period, it reached a high of 126.74 and a low of 63.515. ...

saved:
  /Users/.../out/20261028-182926-0b5f/hood_ytd_price.png

> (on SIVE.ST, a Swedish stock) ok do 1 and 2   [1 = volatility, 2 = trend and momentum]
⚙ run_python(code=import pandas as pd import numpy as np import matplotlib.pyplo...)  0.8s ✓
**1. Volatility Analysis**
*   **Annualized Volatility: 186.00%** ...
**2. Trend & Momentum**
*   The price is trading below both its 20-day SMA (**26.92 SEK**) and its 50-day SMA (**29.18 SEK**).
*   The 14-day Relative Strength Index (RSI) is **21.35** ...

saved:
  /Users/.../out/20261028-182156-62a2/sive_analysis.png      price with both moving averages, RSI below
```

The second one did 2 analyses and a 2-panel chart in a single run. The 186% volatility is right: the
stock moved +60% on June 2 and +47% on May 4.

If the code fails, the model gets the traceback and fixes its code. After 3 failed tool calls in a
row, sensai stops the tools and the model says what went wrong.

This example also shows a limit. Massive returns at most 1000 articles per call, so the sentiment
covered September 4 to October 28, a shorter window than the 6 months asked (the tool result says so, with
`truncated` and `covered_from`), and the model did not mention it.

### Number checking and the judge (EV1)

Under each answer, sensai lists how many of its numbers it found in the data the tools returned.
When all of them are there, it's one line:

```
> how did NVDA do vs SPY over the last year?
⚙ get_prices(ticker=NVDA)  0.8s ✓
⚙ get_prices(ticker=SPY)  0.1s ✓
Over the last year (2025-10-28 to 2026-10-28), NVDA underperformed SPY:

- NVDA: +7.39% (from 200.55 to 215.38)
- SPY: +13.62% (from 679.73 to 772.31)

checked: 6 numbers, all found in the tool results

> /check
6 numbers · 6 found · 0 derived · 0 not found in the tool results
  ✓ +7.39%   get_prices, step 1         - NVDA: +7.39% (from 200.55 to 215.38)
  ✓ 200.55   get_prices, step 1         - NVDA: +7.39% (from 200.55 to 215.38)
  ...
  ✓ 772.31   get_prices, step 2         - SPY: +13.62% (from 679.73 to 772.31)
```

A number that no tool returned is flagged with the words around it. In an earlier session, a
question on PLTR and HOOD's 30-day returns got 1 year of prices; the model then wrote the closes of
September 27 and the returns from memory:

```
checked: 17 numbers · 13 found · 0 derived · 4 not found in the tool results
  ✗ +5.14%  * **PLTR**: +5.14% (Close 2026-10-27: 198.42 / Close 2026-09-27: 188.68)
  ✗ 188.68  * **PLTR**: +5.14% (Close 2026-10-27: 198.42 / Close 2026-09-27: 188.68)
  ✗ -12.45%  * **HOOD**: -12.45% (Close 2026-10-27: 95.36 / Close 2026-09-27: 108.85)
  ✗ 108.85  e 2026-10-27: 95.36 / Close 2026-09-27: 108.85)
```

Numbers typed into the analysis code count too. Asked for a pie chart of the chip makers' market
shares, the model found no table in its web searches and wrote approximate revenues into its
`run_python` code. The answer itself held no number, but the chart did:

```
> make a pie chart of the market share of the biggest chip makers worldwide, w/ their tickers
⚙ web_search(query=biggest semiconductor companies worldwide by revenue 2024 202...)  2.1s ✓
...
⚙ run_python(code=import matplotlib.pyplot as plt # Based on general 2023/2024 i...)  1.7s ✓
... the following chart is based on industry-standard revenue approximations ...

  ✗ run_python (step 6) types in 8 numbers not found in the tool results [69, 60, 50, 54, ...]
saved:
  /Users/.../out/20261028-214023-9aea/chip_market_share.png

> /judge
asking gpt-oss:20b...
judge (gpt-oss:20b): relevance 2/5 · coherence 3/5 · faithfulness 1/5
  ✓ supported    Since precise real-time revenue figures for all top chip makers in a single table
                 were not available in the most recent search results  (web_search results 1-5)
  ? unverifiable the following chart is based on industry-standard revenue approximations for the
                 2023/2024 period
  ? unverifiable Estimated Market Share by Revenue (Approx. 2023/24): TSMC, NVIDIA, Intel, ...
  ...
The answer is partially relevant but lacks concrete market share data and percentages, making it
incomplete and not fully faithful to the requested information.
```

(The flag on the code came after this session: the line shown is that same answer run through the
current check.)

### Research note (M4)

While it answers a research question, the model writes what it found into the session's note,
one section at a time. Three follow-up questions in one session:

```
> how did NVDA do vs SPY over the last year?
⚙ get_prices(ticker=NVDA)  0.0s ✓
⚙ get_prices(ticker=SPY)  0.0s ✓
⚙ run_python(code=import pandas as pd nvda = pd.read_csv('/Users/jadbghiel/EPITE...)  0.2s ✓
✎ note: data (replace)
✗ note: method refused, 100 not found in the tool results. Copy numbers from the results or compute them with run_python, ...
✎ note: results (replace)
Over the last year (from 2025-10-29 to 2026-10-28), NVDA underperformed the SPY.
...
checked: 3 numbers, all found in the tool results
note: data, results updated · /Users/.../.sensai/notes/20261029-131213.md

> what is its beta to SPY on daily returns?
⚙ run_python(code=import pandas as pd import numpy as np nvda = pd.read_csv('/Us...)  0.2s ✓
✎ note: method (replace)
✎ note: results (append)
The beta of NVDA relative to SPY on daily returns over the last year is 1.9246.

> and its max drawdown?
⚙ run_python(code=import pandas as pd nvda = pd.read_csv('/Users/jadbghiel/EPITE...)  0.2s ✓
✎ note: method (append)
✎ note: results (append)
The maximum drawdown for NVDA over the last year was -20.21%.
```

The refused edit had `* 100` in a return formula, and 100 is in no tool result. The check refuses
any number it can't find, even a constant. The note after the third question, as `/note` prints it:

```
# how did NVDA do vs SPY over the last year?

session 20261029-131213 · gemma4:31b

## Question

(empty)

## Data

NVDA vs SPY Performance Analysis
Period: 2025-10-29 to 2026-10-28
Source: Yahoo Finance via get_prices

## Method

Calculated beta using daily returns for the period 2025-10-29 to 2026-10-28.
Beta = Covariance(NVDA_returns, SPY_returns) / Variance(SPY_returns).
Max drawdown calculated as the minimum of (Price / Cumulative_Max_Price - 1) over the period 2025-10-29 to 2026-10-28.

## Results

NVDA Return: +4.28% [q1 get_prices step 1]
SPY Return: +13.57% [q1 get_prices step 2]
Underperformance: -9.29% [q1 run_python step 3]
NVDA Beta to SPY: 1.9246 [q2 run_python step 1]
NVDA Max Drawdown: -20.21% [q3 run_python step 1]

## Caveats

(empty)
file: /Users/.../.sensai/notes/20261029-131213.md
```

Between two questions, a `diff` of the file shows only the sections that question edited:

```
$ diff note_q2.md note_q3.md
18a19
> Max drawdown calculated as the minimum of (Price / Cumulative_Max_Price - 1) over the period 2025-10-29 to 2026-10-28.
25a27
> NVDA Max Drawdown: -20.21% [q3 run_python step 1]
```

`python -m sensai --resume` brings the session back with its note, and `/note` prints it again.

### Retry, undo and the system message

After an error or Ctrl+C, the question is still in memory and `/retry` sends it again:

```
> How did NVDA do over the last 30 days, and what was its last close?

[interrupted]

> /sessions
no saved session yet

> /retry
retrying: How did NVDA do over the last 30 days, and what was its last
Plan:
  1. Get NVDA prices for the last 30 days.
Thought: Fetch NVDA prices for the last 30 days to determine performance and last close.
⚙ get_prices(start=2026-10-02, ticker=NVDA)  0.0s ✓
NVDA declined -12.53% over the last 30 days, with a last close of 204.64.

checked: 2 numbers, all found in the tool results
```

`/retry` after a normal answer replaces that answer, once the new one has completed. If the new
attempt fails, the old answer stays. To try the same question on another model, run `/model <name>`
and then `/retry`.

`/undo` removes the last question with all that came with it: the tool calls and their results,
the answer and its trace. The saved session follows, and so does `--resume`:

```
> And SPY over the same 30 days?
Thought: Fetch SPY prices for the same 30-day period to compare with NVDA.
⚙ get_prices(start=2026-10-02, ticker=SPY)  0.2s ✓
SPY declined -1.81% over the same 30 days, with a last close of 755.72.

checked: 2 numbers, all found in the tool results

> /sessions
* 20261101-171008  2026-11-01 17:10    2 turns  gemma4:31b     How did NVDA do over the last 30 days, and what was its last

> /undo
undone: And SPY over the same 30 days? (1 turn left)

> /sessions
* 20261101-171008  2026-11-01 17:10    1 turns  gemma4:31b     How did NVDA do over the last 30 days, and what was its last
```

If the question edited the research note, `/undo` also prints `note back to before that question`,
and the note and its file return to their earlier state. Undoing the only question of a session
deletes its saved file, and `--resume` then opens the session before it.

`/system` prints the exact message sent at the start of each request: the prompt from `config.yaml`,
today's date, the tools and their limits, the working rules and your profile. Shortened here:

```
> /remember my focus this week is NVDA earnings
noted (1 note(s)), /profile to see them

> /system
You are sensai, a research assistant for quantitative developers and researchers. ...

Today is Sunday 2026-11-01.

Your tools come from these MCP servers:
- quant-data (get_prices, get_fundamentals, get_news, get_sentiment): Market data for quant research: ...
...

About the user:
- Name: Jad
- Sectors followed: semiconductors, AI hardware
- Main tickers: NVDA, AMD, TSM
- Benchmark: SPY
- Research style: concise, formula before the number
- Always keep in mind:
  - my focus this week is NVDA earnings
```

The limits of these commands:

- `/undo` can't be reversed. The question stays in your input history, so ↑ brings it back.
- `/retry` calls the model and the tools again, which uses quota, and the new answer can differ.
- A failed question is kept in memory only. After you quit, ↑ still recalls it, `/retry` doesn't.
- Files the tools wrote (charts and scripts in `out/`) and cached data stay on disk after `/undo`.
- `/system` shows the system message. The tool definitions travel in another field of the request;
  `/tools` lists the tools.

### Things to try

| Type this                                                                           | You should see                                                                         |
| ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `last close of AAPL and what do the news say`                                     | 2 `⚙` lines (`get_prices`, `get_news`), then the price and a news summary       |
| `what is the news sentiment on NVDA over the last 7 days, and why?`               | `get_sentiment` (and maybe `get_news`), a label, a score and the reasons           |
| `what is the P/E of ZZZQX?`                                                       | a red `✗ no fundamentals for ZZZQX` line, then the model says the ticker is unknown |
| `read https://en.wikipedia.org/wiki/Nvidia and tell me where it is headquartered` | a `fetch` line, then "Santa Clara, California"                                       |
| `what did the fed decide at its last meeting?`                                    | a `web_search` line, then the decision and the source URL                            |
| `what is the implied volatility of NVDA options expiring next month?`             | no tool covers options, so a `web_search` line, then what the sources say            |
| `what company is GFS?`                                                            | a `get_fundamentals` line, then GLOBALFOUNDRIES from the tool result                 |
| `how did my watchlist do this month?`                                             | one `get_prices` per ticker of your profile, without naming them                     |
| `/exit`, then `python -m sensai --resume`, then `and what about AMD?`         | the conversation goes on, with the data fetched before                                 |
| `compare NVDA and AMD 30d returns vs sentiment`, then `/steps`                  | a dim plan, a thought before each of the 4 calls, the answer, then the saved trace     |
| `/trace`, then `what is the P/E of NVDA?`                                       | no plan (1 step is enough), a thought, the result preview and the tokens of each round |
| `annualized volatility of AMD over the last year, with a plot of the daily returns` | `get_prices`, a `run_python` line, the number from the code, then the plot under the answer |
| `can u make a chart about HOOD YTD stock price` | `get_prices` from January 1, a `run_python` line, the return, high and low, then the chart under the answer |
| `how did NVDA do vs SPY over the last year?`, then `/check` | `checked: ... all found in the tool results` under the answer, then each number with the step it comes from |
| `make a pie chart of the market share of the biggest chip makers`, then `/judge` | web searches, a chart, a ✗ line if the code types in its own numbers, then the judge's scores |
| `how did NVDA do vs SPY over the last year?`, `what is its beta to SPY on daily returns?`, then `/note` | `✎ note: ...` lines before each answer, then the note with a source next to each number |
| `/remember my focus is NVDA earnings`, then `/system` | the note you just added, at the end of the message the model is given |
| a question, then Ctrl+C during the answer, then `/retry` | `[interrupted]`, then the full answer to the same question |
| 2 questions, then `/undo`, then `/sessions` | the last question removed, 1 turn less in the list |

### Our MCP server on its own

The market data server works with any MCP client. To try it in the
[MCP inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m sensai.servers.quant_data
npx @modelcontextprotocol/inspector .venv/bin/python -m sensai.servers.sandbox
```

## Features

### Streaming chat with history (B1)

Answers are streamed as they are generated, and the whole conversation is sent back to the model
on every turn, so follow-up questions work. When a reasoning model thinks before answering, a
spinner with a timer shows it is working, and its thinking streams in dim text (`/think` hides it).

Failures end in a one-line message instead of a traceback: unreachable host, missing or invalid
API key, unknown model (with the closest names suggested), a model outside the free tier, quota
reached, timeout, or a connection lost in the middle of an answer. The API key and the model name
are checked at startup, before the first question.

### Saved sessions and a user profile (M1)

Sessions are saved after each answer, so closing the terminal loses nothing. `--resume` or
`/resume` picks a conversation up where it stopped.

The profile tells sensai who you are and how you work. It goes to the model at the start of each
session, together with today's date, so there is no need to repeat it.

### Tool calling over MCP (T1)

The model decides on its own when it needs data: it asks for a tool, sensai runs it through
[MCP](https://modelcontextprotocol.io), sends the result back, and the model carries on with real
numbers. Each call shows as one line, with a ✓ or the error (see [Usage examples](#usage-examples)).

A failed call (unknown ticker, bad argument, API down) is sent back to the model as an error
message, so it can explain it or try something else, and the chat keeps going. A question can lead
to several rounds of calls (see [the reasoning loop](#reasoning-loop-a1)). Tool calls and their
results are saved with the session, so after `--resume` the model still has the data it fetched.

sensai starts every server listed under `mcp_servers` in `config.yaml`. Four are set up:

| Server                                                                                     | Tools                                                                 | What for                                                                                                                        |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `quant-data` (ours, `sensai/servers/quant_data.py`)                                    | `get_prices`, `get_fundamentals`, `get_news`, `get_sentiment` | Market data, see below                                                                                                          |
| [`fetch`](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch) (official) | `fetch`                                                             | Reads a web page as Markdown, e.g. the full article behind a headline. It respects `robots.txt`, so some news sites refuse it |
| `web` (ours, `sensai/servers/web.py`)                                                  | `web_search`                                                        | Live web search, see [Web search](#web-search-t3)                                                                                |
| `sandbox` (ours, `sensai/servers/sandbox.py`) | `run_python` | Runs the model's analysis code, see [Code sandbox](#code-sandbox-t2) |

A server that fails to start shows a warning, and the other tools keep working. Servers' own logs
go to `~/.sensai/logs/`, out of the chat.

The model also knows what its tools can't do. Tool descriptions say what each tool does and leave
out what it doesn't cover, and a model tends to fill those gaps from memory (it once called GFS
"Global Payments"; GFS is GlobalFoundries). Each server declares its limits in its MCP
`instructions` (for a server we don't control, like `fetch`, in `config.yaml` under `limits:`),
and sensai adds them to the system prompt with a few rules: names and numbers come from tools, a
failed tool is reported, and what no tool covers goes to web search.

### Web search (T3)

`web_search` sends a live query to [Tavily](https://tavily.com) and returns, for each result,
its title, URL, publish date when known, and a short snippet. The model uses it for what the market
tools don't cover (options, macro data, recent announcements, non-US news) or when a data tool
fails, cites the URLs it used, and can open a result with `fetch` to read the full page.

| Argument        | Description                                                                  |
| --------------- | ---------------------------------------------------------------------------- |
| `query`       | A short search engine query                                                  |
| `topic`       | `general` (default), `news` (recent articles, with dates) or `finance` |
| `days`        | Only results from the last N days                                            |
| `max_results` | 1 to 10, default 5                                                           |

Searches are cached for an hour, and each snippet is capped at 500 characters so a search can't
fill the context. Tavily can also write an answer with its own LLM. sensai leaves that option off,
since all model calls must go through Ollama: the model reads the sources and writes the answer
itself.

### Market data tools (our MCP server)

Our server runs on its own over stdio, so any MCP client can use it.

| Tool                                         | Source                  | Returns                                                                                                                |
| -------------------------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `get_prices(ticker, start, end, interval)` | Yahoo Finance           | First and last close, return %, high, low, average volume, and a CSV with every bar                                    |
| `get_fundamentals(ticker)`                 | Yahoo Finance           | Name, sector, industry, price, market cap, P/E, beta, dividend yield (%), 52 week range, earnings date                 |
| `get_news(ticker, days, limit)`            | Massive (ex Polygon.io) | Recent articles, each with its sentiment towards the ticker and the reason for it                                      |
| `get_sentiment(ticker, days)`              | Massive (ex Polygon.io) | Mean sentiment (positive 1, neutral 0, negative -1) and its label, counts per sentiment, and a CSV of the daily series |

Tools return short summaries to keep the model's context small; the full data is saved as CSV or
JSON in `data/` (`prices/`, `news/`, `sentiment/`).

Calls are cached on disk in `data/cache/`: past prices forever, prices including today for an
hour, fundamentals for a day, news for 6 hours. If a source fails (rate limit, no connection), the
last cached value is returned, marked `"stale": true`, even if it was fetched on an earlier day.
Massive's free plan allows 5 calls a minute, and one call covers a ticker's last 30 days of news
and is shared by `get_news` and `get_sentiment`. One call returns at most 1000 articles, so for a
heavily covered ticker a long window can be cut short: results then include `"truncated": true`
and `covered_from`, the first day covered.

### Reasoning loop (A1)

For a question that needs several steps, the model works in a loop you can follow and audit:

1. **Plan:** it first calls `plan`, a tool sensai handles itself, with the steps it intends to take.
2. **Act:** each tool call carries a one-sentence `thought` saying why it is made. sensai shows the
   thought, removes it from the arguments (the MCP servers don't see it), and calls the tool.
3. **Observe and repeat:** the model reads the results, then calls more tools, changes its plan, or
   answers. A simple question skips the plan and goes straight to the tool.

The plan and the thoughts are shown in dim text. Each question has a budget: `max_steps` tool calls
(12) and `token_budget` tokens read and written over all its rounds (60,000). When either is used up,
sensai asks the model one last time, without tools, to answer with what it has. The same happens
after 3 failed tool calls in a row, and the model is asked to say what failed. The trace of each
question (plan, steps, thoughts, result previews, rounds, tokens, why it stopped) is saved with the
session: `/steps` shows the last one, and `/trace` or `--trace` adds the details live.

The plan and the thoughts are structured fields: a tool and an argument. An earlier version asked
the model to write "Plan:" and "Thought:" lines before its tool calls; it sometimes wrote the calls
as text (no call went out) or drafted an answer with invented numbers before it had any data. If a
call still comes as text, sensai asks the model once more for a real call and drops the made-up
text.

The model matters for hard questions. On "which S&P 500 company has the highest trailing P/E?",
`gemma4:31b` searched twice and gave up, while `gpt-oss:20b` chained 6 steps (searches, a check with
`get_fundamentals`, a `fetch` of a ranking article) and answered Tesla, citing both sources. Use
`--model gpt-oss:20b` for multi-step research; the default stays the faster `gemma4:31b`.

### Code sandbox (T2)

Language models are unreliable at arithmetic over hundreds of rows. `run_python` lets the model
write the calculation instead: it reads the CSV files at the `path` the market tools return, prints
the numbers it needs, and saves plots. It gets back the printed output, the files it saved, or the
traceback when the code fails. Charts come with it: any plot matplotlib can draw, with no chart code
in sensai itself.

| | Docker (when the `sensai-sandbox` image is built) | Local process (fallback) |
|---|---|---|
| Network | none | not blocked |
| Limits | 1 CPU, 512 MB of memory, 30 s per run | 30 s and 30 s of CPU per run; memory isn't capped |
| `data/` | read only | readable and writable |
| Libraries | pandas, numpy, scipy, statsmodels, matplotlib | the same, from `requirements.txt` |

Both run without the API keys from `.env`. sensai picks Docker when the image exists; set
`SENSAI_SANDBOX` to `docker` or `subprocess` to force one. The server tells the model which one is
running, with its limits.

Each run gets its own folder in `out/` (named after its start time, e.g. `out/20261028-181324-11d7/`)
with the code saved as `script.py` next to what it produced. The data folder is mounted at the same
path inside the container, so the file paths the market tools return work in both modes.

The model's code shows with `/trace` or `--trace`, and in `/steps`. Without them, the chat shows one
line per run.

The files a question produced are listed under its answer, with or without `/trace`:

```
The stock has seen a YTD return of -21.39% ...

saved:
  /Users/.../out/20261028-182926-0b5f/hood_ytd_price.png
  [the chart, drawn here]
```

Each path is a terminal link: Cmd+click (Ctrl+click on Linux and Windows) opens the file, in VS
Code's image preview when sensai runs in its terminal. Images are also drawn right under their link
in iTerm2, WezTerm and VS Code. If VS Code shows the link but no image, turn on "Terminal ›
Integrated: Enable Images" in its settings (`Cmd+,`, search "enable images"). It's a setting, not
a shell command.

Terminals without link or image support, like macOS Terminal.app, show the plain path.

### Number checking and evaluation (EV1)

In finance, a made-up number is worse than no answer. sensai looks up each number of an answer in
the data its tools returned, with no extra model call:

| Status | Meaning |
|---|---|
| found | The number is in a tool result, the output of a `run_python` run, a tool call's arguments or the question, at the precision it's written with: `217.15` matches `217.1499`, `26%` matches `0.2601`, `$5.24 trillion` matches `5243038334976` |
| derived | The difference, ratio or % change of two numbers found in the same answer (NVDA +8.68% vs SPY +2.58% → `+6.10` points) |
| not found | None of the above: flagged under the answer with the words around it |

Dates, times, list numbers, durations ("30-day"), index names ("S&P 500") and tickers like
`000660.KS` are skipped. News and web pages hold hundreds of numbers, and a round number would
always find one by chance (a "25.0%" market share matched "25 robots" in a news summary). To avoid
that, a percentage needs a percentage or a fraction in the source. A number with 2 significant
digits or fewer found in news, web results or an older turn must also share a word with the text
around it in the source (a ticker, a field name, a nearby word). Sums don't count as derived,
since that is how a made-up pie chart adds up.

The check also reads the `run_python` code of the question: a list or dict of 4 or more numbers
(3 with decimals) that aren't in any tool result means the model typed data in, and it is flagged
even when the answer itself holds no number.

A match shows that a number exists in the data. Whether it was used for the right thing is another
question (a 1-year return presented as year-to-date passes the check), and `/judge` covers it: a second model
(`judge_model`, `gpt-oss:20b` by default, a different model from the one it grades) reads the question,
the tool results, the check and the answer. It scores relevance, coherence and faithfulness from 1
to 5, and marks each claim as supported, contradicted or unverifiable. Its reply is requested as
JSON with a schema, then validated, with one retry.

**The evaluation** runs a fixed set of 20 questions (`eval/questions.yaml`) on frozen data. Two
models or two prompts can then be compared on the same inputs:

```bash
python -m sensai.eval --record          # once: run live and save the data in eval/data/
python -m sensai.eval                   # every question, offline on the snapshot, with the judge
python -m sensai.eval --limit 5         # the first 5 only (saves the cloud quota)
python -m sensai.eval --model gpt-oss:20b --no-judge
python -m sensai.eval --only nvda-beta,nvda-drawdown
```

Each question gets a new session with the market data and sandbox tools (web search and web pages
can't be frozen), a fixed profile (benchmark SPY) and the snapshot's date. The tools serve from
the snapshot alone (`SENSAI_OFFLINE=1`), and a wider cached window is cut to the dates the model
asks for. The report gives, for each question and in total:

- **correct**: the expected values found in the answer, within a tolerance. They were computed by
  hand with pandas from the snapshot.
- **faithfulness**: the share of the answer's numbers that were found or derived.
- **planted**: one number found in each answer is multiplied by 1.37, and the check must flag it.
- **traps**: 3 questions no tool can answer (options implied volatility, an unknown ticker, a price
  in 2027). The answer passes if it holds no number from nowhere.
- the judge's 3 scores, then the time, rounds and tokens per question.

On the snapshot of October 28, 2026, `gemma4:31b` with `gpt-oss:20b` as judge (5 questions):

```
question               correct  numbers flagged  planted judge r/c/f steps   secs
nvda-vs-spy            3/3            3       0  caught  5/5/5           3    2.5
mu-market-cap          1/1            1       0  caught  5/5/5           1    1.0
nvda-beta              1/1            1       0  caught  5/5/5           3    5.1
nvda-sentiment         1/1            1       0  caught  5/5/5           1    1.3
trap-implied-vol       trap ok        0       0  -       2/5/5           0    0.6

model gemma4:31b · judge gpt-oss:20b · data 2026-10-28 (frozen)
correct 100.0% (6/6 expected values) · faithfulness 100.0% (6/6 numbers found or derived) · planted caught 4/4 · traps 1/1
judge on 5: relevance 4.4 · coherence 5.0 · faithfulness 5.0 (out of 5)
per question: 2.1s, 2.6 rounds, 6134.8 tokens
```

The live recording of all 20 questions did not flag any number, caught 17 of 17 planted numbers and
passed the 3 traps. The judge gives a low relevance to a correct refusal ("I don't have options
data"): for those rows, read the trap column. Results are saved in `eval/results/`. The snapshot
and the results stay out of git (they hold Yahoo Finance and Massive content). A fresh clone
records its own snapshot first.

### Research note (M4)

Each session has a research note, a Markdown file with 5 fixed sections: question, data, method,
results and caveats. The model edits it with `update_note(section, mode, content)`, a tool that
sensai handles itself (no MCP server, no extra model call). `mode` is `replace` (rewrite the
section) or `append` (add lines to it). The tool's description tells the model to use it for
research questions, before its final answer, with numbers copied from the tool results.

Before an edit is applied:

1. its arguments are validated: a known section, `replace` or `append`, a content that isn't empty
   and is at most 4,000 characters. An invalid edit gets the reason back as a tool error.
2. each number in the content goes through the number check of EV1. A number that isn't in the
   data of the session refuses the whole edit, with a tool error naming it; the model can fix it
   and call again. 3 refused edits in a row stop the tools, like 3 failed tool calls.
3. each number found gets its source written next to it, with the question number since a note
   covers several questions: `+4.28% [q1 get_prices step 1]`, `1.9246 [q2 run_python step 1]`,
   or the formula for a derived number, `-5.16 [q1 derived +8.28% - +13.44%]`.

Only the target section changes. The file doesn't have a timestamp, and its header (the first question,
the session id and the model of the first edit) is written once, and two versions differ only in
the sections that were edited. The file is written atomically (a temporary file, then a rename).
The model gets the section back as written, with its sources, and a later `replace` knows what
was there.

The note is saved with the session and comes back with `--resume`. `/clear` starts a new session
with an empty note. If a question fails or is interrupted with Ctrl+C, or you remove it with `/undo`,
the note goes back to its state before the question, like the conversation. The evaluation runs without the note tool to keep
its scores comparable with earlier runs.

### Structured output (T5)

In two places sensai has the model answer in JSON that follows a schema, and code parses the
reply:

- **The judge** (`/judge` and the evaluation) sends a JSON schema in Ollama's `format` field: 3
  scores from 1 to 5 (relevance, coherence, faithfulness), a list of claims each marked
  `supported`, `contradicted` or `unverifiable`, and a comment. The reply is parsed and validated;
  close variants are accepted (a score written `"4"`, `status` instead of `verdict`), and an
  invalid reply gets one retry with the reason before `/judge` reports an error.
- **The research note** is edited through `update_note`, whose arguments follow a declared schema
  (one of the 5 sections, `replace` or `append`, a content of at most 4,000 characters). An edit
  that doesn't fit is refused with the reason, and the model can send it again.

The schema alone isn't enough on Ollama Cloud: `gpt-oss:20b` sometimes replied without a required
key even with `format` set. The validation in code is what makes the replies safe to use.

## Your profile

All fields are optional, and empty ones are left out.

| Field         | Example                                                                |
| ------------- | ---------------------------------------------------------------------- |
| `name`      | Jad                                                                    |
| `sectors`   | semiconductors, AI hardware                                            |
| `watchlist` | NVDA, AMD, TSM                                                         |
| `benchmark` | SPY                                                                    |
| `style`     | concise, formula before the number                                     |
| `notes`     | *only liquid large caps*, anything sensai should always keep in mind |

Fill it with the first-run setup or `/profile setup`, change it with `/profile edit`, and add
notes on the fly with `/remember`.

## Your data

Everything personal is stored in a folder in your home directory, outside the repository, so it
can't be committed by mistake:

```
~/.sensai/
├── profile.yaml
├── history                     your past inputs, for ↑ ↓ (the last 1,000)
├── sessions/
│   └── 20260928-143012.json    one file per session, named after its start time
├── notes/
│   └── 20260928-143012.md      the research note of that session
└── logs/                       MCP servers' logs (quant-data.log, fetch.log, web.log, sandbox.log, mcp.log)
```

The folder is only readable by your user. Set `SENSAI_HOME` to use another folder, for instance a
separate profile for demos: `SENSAI_HOME=~/.sensai-demo python -m sensai`. To start over, delete
the folder.

## Configuration

`config.yaml` holds the project settings:

| Key                | Description                                                                                                                                                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model`          | Default model (`gemma4:31b`)                                                                                                                                                                                                        |
| `ollama.host`    | Ollama API host (`https://ollama.com`)                                                                                                                                                                                              |
| `ollama.timeout` | Seconds to wait for data before giving up (`120`)                                                                                                                                                                                   |
| `system_prompt`  | Base instructions; today's date and your profile are added after it                                                                                                                                                                   |
| `show_thinking`  | Whether reasoning models' thinking is shown by default (`true`)                                                                                                                                                                     |
| `mcp_servers`    | MCP servers to start: `name`, `command`, `args`, optional `env`, `cwd`, `limits` (what its tools can't do, for servers that don't declare it), `enabled: false` to skip one. `python` means the Python running sensai |
| `max_steps`      | Tool calls per question before the model must answer (`12`)                                                                                                                                                                         |
| `token_budget`   | Tokens read and written per question, over all its rounds, before the model must answer (`60000`)                                                                                                                                   |
| `judge_model`    | Model that grades answers for `/judge` and the evaluation (`gpt-oss:20b`); the chat model is used when it's missing                                                                                                                |

`.env` holds the secrets: `OLLAMA_API_KEY` (required), `MASSIVE_API_KEY` (for news and
sentiment) and `TAVILY_API_KEY` (for web search).

| Environment variable | Description |
|---|---|
| `SENSAI_HOME` | Folder for your profile, sessions, notes and logs (default `~/.sensai`) |
| `SENSAI_DATA` | Folder for market data and its cache (default `data/`) |
| `SENSAI_OUT` | Folder for what the sandbox runs produce (default `out/`) |
| `SENSAI_SANDBOX` | `auto` (default: Docker when its image is built), `docker` or `subprocess` |
| `SENSAI_TODAY` | A fixed date (`2026-10-28`) used instead of the clock by the data tools and the system prompt. The evaluation sets it |
| `SENSAI_OFFLINE` | `1`: the data tools answer from their cache and make no API call. The evaluation sets it |

## Models

The default is `gemma4:31b`: it answers without a thinking phase (first word in about 0.3 s) and
supports tool calling. Reasoning models such as `gpt-oss:20b` or `qwen3.5:397b` think before
answering, which is slower but better for harder questions. Switch with `--model` or `/model`.

Ollama's free tier allows one request at a time, with usage limits that reset every 5 hours and
every week. Some models listed by `/model` are paid only.

## Troubleshooting

| Message                                               | What to do                                                                                                                                                      |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `^[[A` or `^[[C` when you press an arrow key | Python was built without `readline`: line editing, the input history and Tab aren't available. The `"""` blocks still work |
| `OLLAMA_API_KEY is missing, set it in .env`         | Copy `.env.example` to `.env` and add your key                                                                                                              |
| `OLLAMA_API_KEY missing or invalid, check .env`     | The key was rejected: create a new one on ollama.com                                                                                                            |
| `model X not available on ..., closest: ...`        | Check the spelling, or run `/model` to list the models                                                                                                        |
| `this model isnt in the free tier`                  | Pick another model; this one needs a paid plan                                                                                                                  |
| `cloud quota hit, wait for the reset`               | The free tier limit is reached; it resets after 5 hours (or weekly)                                                                                             |
| `can't reach ..., check the connection`             | Check your internet connection or the `--host` value                                                                                                          |
| `connection lost mid answer`                        | `/retry` sends the question again; the interrupted one was not kept in the conversation                                                                                                                |
| `invalid yaml in .../profile.yaml`                  | Fix the file with `/profile edit`; sensai keeps running without a profile meanwhile                                                                           |
| `MASSIVE_API_KEY is missing`                        | Get a free key at massive.com and add it to `.env`                                                                                                            |
| `massive rate limit (5 calls/min on the free plan)` | Wait a minute; cached news keeps working meanwhile                                                                                                              |
| `massive refused the key`                           | Check `MASSIVE_API_KEY` in `.env`                                                                                                                           |
| `TAVILY_API_KEY is missing`                         | Get a free key at tavily.com and add it to `.env`; the other tools work without it                                                                            |
| `tavily monthly limit reached`                      | The free plan's 1000 searches are used up; it resets on the 1st of the month                                                                                    |
| `[warning] mcp server X didnt start: ...`           | Check the server's `command` in `config.yaml` (and that `uv` is installed for `fetch`); the other tools still work. Details in `~/.sensai/logs/X.log` |
| `✗ ...` after a tool call                          | The tool failed; the model got the error and explains it. Nothing to do unless it keeps happening                                                               |
| `no price data for X, check the ticker`             | The symbol is unknown to Yahoo Finance (e.g. a typo)                                                                                                            |
| `yahoo only serves 1m bars for the last 7 days`     | Use a later start date or a larger interval                                                                                                                     |
| `run ... failed (exit code 1)` after `run_python` | The model's code crashed; it got the traceback and usually fixes it. Nothing to do |
| `run ... failed (timed out after 30s)` | The code ran too long (a loop that never ends, too much data); ask for a smaller window |
| `"backend": "subprocess"` in a `run_python` result (`/trace`) when you expected Docker | Docker isn't running or the `sensai-sandbox` image isn't built: start Docker, run `docker build -t sensai-sandbox sandbox/`, restart sensai |
| `✗ 25.0%  ...` under an answer | That number isn't in any tool result of the conversation. Ask where it comes from, or ask the model to compute it with `run_python`. `/check` lists every number |
| `✗ note: results refused, 11.34% not found ...` | The model tried to write a number into the note that no tool returned. It got the reason and usually fixes the edit. A constant in a formula (`* 100`) is refused too: ask it to write the formula without the number |
| `the judge (...) didnt reply w/ valid JSON twice` | The judge model answered in the wrong shape. Run `/judge` again, or set another `judge_model` |
| `not in the frozen eval data` (evaluation only) | The model asked for data the snapshot doesn't hold. Record a new one with `python -m sensai.eval --record` |
| `no snapshot in eval/data/` | Record one first: `python -m sensai.eval --record` (live, uses the data APIs once) |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests call no model and no data API, so they use no quota, and they run in temporary
folders instead of your real `~/.sensai` and `data/`.

## Project status

| Issue                                                                          | Feature                              | Status  |
| ------------------------------------------------------------------------------ | ------------------------------------ | ------- |
| [#1](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/1)   | Repository skeleton                  | Done    |
| [#2](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/2)   | B1 streaming CLI chatbot             | Done    |
| [#3](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/3)   | M1 saved sessions and user profile   | Done    |
| [#4](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/4)   | T1 market data MCP server            | Done    |
| [#5](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/5)   | T1 tool calling in the chat          | Done    |
| [#6](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/6)   | A1 multi-step reasoning loop (ReAct) | Done    |
| [#7](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/7)   | T2 sandboxed code execution          | Done    |
| [#8](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/8)   | M4 research note                     | Done    |
| [#9](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/9)   | EV1 number checking and evaluation   | Done    |
| [#17](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/17) | T3 web search and tool limits        | Done    |
| [#14](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/14) | Line editing, input history and multi-line questions | Done |
| [#20](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/20) | T5 structured output (the judge and the note edits) | Done |
| [#15](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/15) | `/retry`, `/undo` and `/system` commands | Done |
