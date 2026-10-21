# sensai

A research assistant for quantitative developers and researchers, built from scratch in Python on
top of the Ollama HTTP API, without any LLM framework.

The goal is an agent that can take a question like *"Is NVDA moving more on news or on the market
lately?"*, fetch prices, news and sentiment, write and run its own analysis code, and check every
number it reports against the data it fetched. This README describes what works today; the
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

The first time you start sensai, it offers to set up your profile (see [Your profile](#your-profile)).
Every question is optional.

## Running it

```bash
python -m sensai                        # start a new session with the default model
python -m sensai --model gpt-oss:20b    # use another model for this run
python -m sensai --resume               # reopen your last session
python -m sensai --resume 20260928-14   # reopen a specific session (a prefix of its id is enough)
```

| Flag | Description |
|---|---|
| `--model MODEL` | Model to use, overrides `config.yaml` |
| `--host HOST` | Ollama host, overrides `config.yaml` (e.g. `http://localhost:11434` for a local Ollama) |
| `--config CONFIG` | Path to the config file (default: `config.yaml`) |
| `--resume [ID]` | Reopen a saved session: the last one without an id, or the one whose id starts with `ID` |
| `--trace` | Show the details of each reasoning step: tool results and tokens used |
| `--version` | Print the version |
| `-h`, `--help` | Show the help |

## Commands in the chat

| Command | Description |
|---|---|
| `/help` | List the commands |
| `/model` | Show the current model and the available ones |
| `/model <name>` | Switch model; the conversation is kept |
| `/think` | Show or hide the model's thinking (reasoning models only) |
| `/tools` | List the MCP servers and the tools the model can call |
| `/trace` | Show or hide the details of each step (tool results, tokens used) |
| `/steps` | Print the trace of the last answer: the plan, every step with its thought and result, the tokens |
| `/clear` | Start a new session; the current one stays saved |
| `/sessions` | List the 10 most recent sessions |
| `/resume <id>` | Reopen a session (a prefix of the id, or `last`) |
| `/profile` | Show your profile, with numbered notes |
| `/profile setup` | Answer the profile questions again (Enter keeps a value, `-` clears it) |
| `/profile edit` | Open the profile file in your editor (`$VISUAL`, `$EDITOR`, then `nano` or `vi`) |
| `/remember <fact>` | Add a note sensai always keeps in mind |
| `/forget <n>` | Remove note number `n` |
| `/exit` | Quit (Ctrl+D works too) |

**Ctrl+C** during an answer stops it and returns to the prompt. The interrupted question is not
kept in the conversation, so you can simply ask again.

## Usage examples

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

Mistakes end in a one-line message, never a traceback:

```
$ python -m sensai --model gpt-oss:20
sensai: model gpt-oss:20 not available on https://ollama.com, closest: gpt-oss:20b, gpt-oss:120b (/model to list them)

>
empty input, type a question or /help
```

Ctrl+C during an answer prints `[interrupted]` and returns to the prompt; the question is
dropped from the history, so you can simply ask again.

### Profile and saved sessions (M1)

The first start offers to set up your profile. Every question can be skipped with Enter:

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

Every session is saved after each answer. List them, close sensai, and pick up where you left:

```
> /sessions
  20261012-145719  2026-10-12 14:57    3 turns  gemma4:31b     last close of AAPL and what do the news say

$ python -m sensai --resume
resumed 20261012-145719: last close of AAPL and what do the news say (3 turns)
you: open the most relevant AAPL article with the fetch tool and summarize it in 2 lines
sensai: Apple is showing strong relative performance and projected earnings growth ...
```

The profile is given to the model in every session, so you never repeat it:

```
> and for my watchlist?
NVDA, AMD, TSM; Focus: NVDA earnings
```

### Market data and tool calling (T1)

`/tools` lists what the model can call, from our 2 servers and the official `fetch` server:

```
> /tools
quant-data: get_prices, get_fundamentals, get_news, get_sentiment
fetch: fetch
web: web_search
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

(`get_news` took 0.0 s: it reused the Massive call `get_sentiment` had just made.)

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

Company names come from a tool, not from the model's memory:

```
> what company is GFS and how did it do over the last 30 days?
⚙ get_fundamentals(ticker=GFS)  1.7s ✓
⚙ get_prices(start=2026-09-12, ticker=GFS)  0.0s ✓
GFS is GLOBALFOUNDRIES Inc., a company in the Technology sector and Semiconductors industry.
Over the last 30 days (from 2026-09-14 to 2026-10-09), the stock returned +11.07% ...
```

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

`fetch` reads any web page:

```
> read https://en.wikipedia.org/wiki/Nvidia and tell me in 2 lines what Nvidia makes and where it is headquartered
⚙ fetch(url=https://en.wikipedia.org/wiki/Nvidia)  6.0s ✓
Nvidia develops GPUs, SoCs, and APIs for data science, high-performance computing, and artificial intelligence.
It is headquartered in Santa Clara, California.
```

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

### Things to try

| Type this | You should see |
|---|---|
| `last close of AAPL and what do the news say` | 2 `⚙` lines (`get_prices`, `get_news`), then the price and a news summary |
| `what is the news sentiment on NVDA over the last 7 days, and why?` | `get_sentiment` (and maybe `get_news`), a label, a score and the reasons |
| `what is the P/E of ZZZQX?` | a red `✗ no fundamentals for ZZZQX` line, then the model says the ticker is unknown |
| `read https://en.wikipedia.org/wiki/Nvidia and tell me where it is headquartered` | a `fetch` line, then "Santa Clara, California" |
| `what did the fed decide at its last meeting?` | a `web_search` line, then the decision and the source URL |
| `what is the implied volatility of NVDA options expiring next month?` | no tool covers options, so a `web_search` line, then what the sources say |
| `what company is GFS?` | a `get_fundamentals` line, then GLOBALFOUNDRIES, not a guess |
| `how did my watchlist do this month?` | one `get_prices` per ticker of your profile, without naming them |
| `/exit`, then `python -m sensai --resume`, then `and what about AMD?` | the conversation goes on, with the data fetched before |
| `compare NVDA and AMD 30d returns vs sentiment`, then `/steps` | a dim plan, a thought before each of the 4 calls, the answer, then the saved trace |
| `/trace`, then `what is the P/E of NVDA?` | no plan (1 step is enough), a thought, the result preview and the tokens of each round |

### Our MCP server on its own

The market data server works with any MCP client, not only sensai. To try it in the
[MCP inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m sensai.servers.quant_data
```

## Features

### Streaming chat with history (B1)

Answers are streamed as they are generated, and the whole conversation is sent back to the model
on every turn, so follow-up questions work. When a reasoning model thinks before answering, a
spinner with a timer shows it is working, and its thinking streams in dim text (`/think` hides it).

Every failure ends in a one-line message, never a traceback: unreachable host, missing or invalid
API key, unknown model (with the closest names suggested), a model outside the free tier, quota
reached, timeout, or a connection lost in the middle of an answer. The API key and the model name
are checked at startup, before the first question.

### Saved sessions and a user profile (M1)

Every session is saved after each answer, so closing the terminal loses nothing. `--resume` or
`/resume` picks a conversation up where it stopped.

The profile tells sensai who you are and how you work. It is given to the model at the start of
every session, together with today's date, so you never have to repeat it.

### Tool calling over MCP (T1)

The model decides on its own when it needs data: it asks for a tool, sensai runs it through
[MCP](https://modelcontextprotocol.io), sends the result back, and the model carries on with real
numbers. Each call shows as one line, with a ✓ or the error (see [Usage examples](#usage-examples)).

A failed call (unknown ticker, bad argument, API down) is sent back to the model as an error
message, so it can explain it or try something else; the chat never crashes. A question can lead
to several rounds of calls (see [the reasoning loop](#reasoning-loop-a1)). Tool calls and their
results are saved with the session, so after `--resume` the model still has the data it fetched.

sensai starts every server listed under `mcp_servers` in `config.yaml`. Three are set up:

| Server | Tools | What for |
|---|---|---|
| `quant-data` (ours, `sensai/servers/quant_data.py`) | `get_prices`, `get_fundamentals`, `get_news`, `get_sentiment` | Market data, see below |
| [`fetch`](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch) (official) | `fetch` | Reads a web page as Markdown, e.g. the full article behind a headline. It respects `robots.txt`, so some news sites refuse it |
| `web` (ours, `sensai/servers/web.py`) | `web_search` | Live web search, see [Web search](#web-search-t3) |

A server that fails to start is a warning, not a crash: the other tools still work. Servers' own
logs go to `~/.sensai/logs/`, never into the chat.

**The model knows what its tools can't do.** Tool descriptions say what each tool does, not what
it doesn't cover, so a model tends to fill the gaps from memory (it once called GFS "Global
Payments"; GFS is GlobalFoundries). Each server declares its limits in its MCP `instructions`
(for a server we don't control, like `fetch`, in `config.yaml` under `limits:`), and sensai adds
them to the system prompt with a few rules: names and numbers come from tools, a failed tool is
reported, and what no tool covers goes to web search instead of being guessed.

### Web search (T3)

`web_search` runs a live query through [Tavily](https://tavily.com) and returns, for each result,
its title, URL, publish date when known, and a short snippet. The model uses it for what the market
tools don't cover (options, macro data, recent announcements, non-US news) or when a data tool
fails, cites the URLs it used, and can open a result with `fetch` to read the full page.

| Argument | Description |
|---|---|
| `query` | A short search engine query |
| `topic` | `general` (default), `news` (recent articles, with dates) or `finance` |
| `days` | Only results from the last N days |
| `max_results` | 1 to 10, default 5 |

Searches are cached for an hour, and each snippet is capped at 500 characters so a search can't
fill the context. Tavily can also write an answer with its own LLM; sensai never asks for it, since
every model call must go through Ollama: the model reads the sources and writes the answer itself.

### Market data tools (our MCP server)

Our server runs on its own over stdio, so any MCP client can use it, not only sensai.

| Tool | Source | Returns |
|---|---|---|
| `get_prices(ticker, start, end, interval)` | Yahoo Finance | First and last close, return %, high, low, average volume, and a CSV with every bar |
| `get_fundamentals(ticker)` | Yahoo Finance | Name, sector, industry, price, market cap, P/E, beta, dividend yield (%), 52 week range, earnings date |
| `get_news(ticker, days, limit)` | Massive (ex Polygon.io) | Recent articles, each with its sentiment towards the ticker and the reason for it |
| `get_sentiment(ticker, days)` | Massive (ex Polygon.io) | Mean sentiment (positive 1, neutral 0, negative -1) and its label, counts per sentiment, and a CSV of the daily series |

Tools return short summaries rather than full tables, to keep the model's context small; the full
data is saved as CSV or JSON in `data/` (`prices/`, `news/`, `sentiment/`).

Every call is cached on disk in `data/cache/`: past prices forever, prices including today for an
hour, fundamentals for a day, news for 6 hours. If a source fails (rate limit, no connection), the
last cached value is returned, marked `"stale": true`, even if it was fetched on an earlier day.
Massive's free plan allows 5 calls a minute, and one call covers a ticker's last 30 days of news
and is shared by `get_news` and `get_sentiment`. One call returns at most 1000 articles, so for a
heavily covered ticker a long window can be cut short: results then include `"truncated": true`
and `covered_from`, the first day actually covered.

### Reasoning loop (A1)

For a question that needs several steps, the model works in a loop you can follow and audit:

1. **Plan:** it first calls `plan`, a tool sensai handles itself, with the steps it intends to take.
2. **Act:** each tool call carries a one-sentence `thought` saying why it is made. sensai shows the
   thought, removes it from the arguments (the MCP servers never see it), and runs the tool.
3. **Observe and repeat:** the model reads the results, then calls more tools, changes its plan, or
   answers. A simple question skips the plan and goes straight to the tool.

The plan and the thoughts are shown in dim text. Each question has a budget: `max_steps` tool calls
(12) and `token_budget` tokens read and written over all its rounds (60,000). When either is used up,
sensai asks the model one last time, without tools, to answer with what it has. Every question's
trace (plan, steps, thoughts, result previews, rounds, tokens, why it stopped) is saved with the
session: `/steps` shows the last one, and `/trace` or `--trace` adds the details live.

The reasoning goes through structured fields, not free text. When the model was asked to write
"Plan:" and "Thought:" lines before its tool calls, it sometimes wrote the calls as text (nothing
ran) or drafted an answer with invented numbers before it had any data. If a call still comes as
text, sensai asks the model once more for a real call, and the made-up text is not kept.

**Model matters for hard questions.** On "which S&P 500 company has the highest trailing P/E?",
`gemma4:31b` searched twice and gave up, while `gpt-oss:20b` chained 6 steps (searches, a check with
`get_fundamentals`, a `fetch` of a ranking article) and answered Tesla, citing both sources. Use
`--model gpt-oss:20b` for multi-step research; the default stays the faster `gemma4:31b`.

## Your profile

Every field is optional, and empty fields are simply left out.

| Field | Example |
|---|---|
| `name` | Jad |
| `sectors` | semiconductors, AI hardware |
| `watchlist` | NVDA, AMD, TSM |
| `benchmark` | SPY |
| `style` | concise, formula before the number |
| `notes` | *only liquid large caps*, anything sensai should always keep in mind |

Fill it with the first-run setup or `/profile setup`, change it with `/profile edit`, and add
notes on the fly with `/remember`.

## Your data

Everything personal is stored in a folder in your home directory, outside the repository, so it
can never be committed by mistake:

```
~/.sensai/
├── profile.yaml
├── sessions/
│   └── 20260928-143012.json    one file per session, named after its start time
└── logs/                       MCP servers' logs (quant-data.log, fetch.log, web.log, mcp.log)
```

The folder is only readable by your user. Set `SENSAI_HOME` to use another folder, for instance a
separate profile for demos: `SENSAI_HOME=~/.sensai-demo python -m sensai`. To start over, delete
the folder.

## Configuration

`config.yaml` holds the project settings:

| Key | Description |
|---|---|
| `model` | Default model (`gemma4:31b`) |
| `ollama.host` | Ollama API host (`https://ollama.com`) |
| `ollama.timeout` | Seconds to wait for data before giving up (`120`) |
| `system_prompt` | Base instructions; today's date and your profile are added after it |
| `show_thinking` | Whether reasoning models' thinking is shown by default (`true`) |
| `mcp_servers` | MCP servers to start: `name`, `command`, `args`, optional `env`, `cwd`, `limits` (what its tools can't do, for servers that don't declare it), `enabled: false` to skip one. `python` means the Python running sensai |
| `max_steps` | Tool calls per question before the model must answer (`12`) |
| `token_budget` | Tokens read and written per question, over all its rounds, before the model must answer (`60000`) |

`.env` holds the secrets: `OLLAMA_API_KEY` (required), `MASSIVE_API_KEY` (for news and
sentiment) and `TAVILY_API_KEY` (for web search). Set `SENSAI_DATA` to store market data somewhere other than `data/`.

## Models

The default is `gemma4:31b`: it answers without a thinking phase (first word in about 0.3 s) and
supports tool calling. Reasoning models such as `gpt-oss:20b` or `qwen3.5:397b` think before
answering, which is slower but better for harder questions. Switch with `--model` or `/model`.

Ollama's free tier allows one request at a time, with usage limits that reset every 5 hours and
every week. Some models listed by `/model` are paid only.

## Troubleshooting

| Message | What to do |
|---|---|
| `OLLAMA_API_KEY is missing, set it in .env` | Copy `.env.example` to `.env` and add your key |
| `OLLAMA_API_KEY missing or invalid, check .env` | The key was rejected: create a new one on ollama.com |
| `model X not available on ..., closest: ...` | Check the spelling, or run `/model` to list the models |
| `this model isnt in the free tier` | Pick another model; this one needs a paid plan |
| `cloud quota hit, wait for the reset` | The free tier limit is reached; it resets after 5 hours (or weekly) |
| `can't reach ..., check the connection` | Check your internet connection or the `--host` value |
| `connection lost mid answer` | Ask again; the interrupted question was not kept |
| `invalid yaml in .../profile.yaml` | Fix the file with `/profile edit`; sensai keeps running without a profile meanwhile |
| `MASSIVE_API_KEY is missing` | Get a free key at massive.com and add it to `.env` |
| `massive rate limit (5 calls/min on the free plan)` | Wait a minute; cached news keeps working meanwhile |
| `massive refused the key` | Check `MASSIVE_API_KEY` in `.env` |
| `TAVILY_API_KEY is missing` | Get a free key at tavily.com and add it to `.env`; the other tools work without it |
| `tavily monthly limit reached` | The free plan's 1000 searches are used up; it resets on the 1st of the month |
| `[warning] mcp server X didnt start: ...` | Check the server's `command` in `config.yaml` (and that `uv` is installed for `fetch`); the other tools still work. Details in `~/.sensai/logs/X.log` |
| `✗ ...` after a tool call | The tool failed; the model got the error and explains it. Nothing to do unless it keeps happening |
| `no price data for X, check the ticker` | The symbol is unknown to Yahoo Finance (e.g. a typo) |
| `yahoo only serves 1m bars for the last 7 days` | Use a later start date or a larger interval |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests never call a model or a data API, so they use no quota, and they run in temporary
folders instead of your real `~/.sensai` and `data/`.

## Project status

| Issue | Feature | Status |
|---|---|---|
| [#1](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/1) | Repository skeleton | Done |
| [#2](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/2) | B1 streaming CLI chatbot | Done |
| [#3](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/3) | M1 saved sessions and user profile | Done |
| [#4](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/4) | T1 market data MCP server | Done |
| [#5](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/5) | T1 tool calling in the chat | Done |
| [#6](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/6) | A1 multi-step reasoning loop (ReAct) | Done |
| [#7](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/7) | T2 sandboxed code execution | Planned |
| [#8](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/8) | M4 research note | Planned |
| [#9](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/9) | EV1 number checking and evaluation | Planned |
| [#17](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/17) | T3 web search and tool limits | Done |
