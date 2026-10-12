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
#   ALPHAVANTAGE_API_KEY  https://www.alphavantage.co/support/#api-key (free, for news and sentiment)
```

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
| `--version` | Print the version |
| `-h`, `--help` | Show the help |

## Commands in the chat

| Command | Description |
|---|---|
| `/help` | List the commands |
| `/model` | Show the current model and the available ones |
| `/model <name>` | Switch model; the conversation is kept |
| `/think` | Show or hide the model's thinking (reasoning models only) |
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
every session, together with today's date, so you never have to repeat it:

```
> and for my watchlist?
NVDA, AMD, TSM; Focus: NVDA earnings
```

### Market data tools over MCP (T1, first half)

sensai ships its own [MCP](https://modelcontextprotocol.io) server with 4 market data tools. It
runs on its own over stdio, so any MCP client can use it; wiring it into the chat is the next step
([#5](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/5)).

| Tool | Source | Returns |
|---|---|---|
| `get_prices(ticker, start, end, interval)` | Yahoo Finance | First and last close, return %, high, low, average volume, and a CSV with every bar |
| `get_fundamentals(ticker)` | Yahoo Finance | Name, sector, industry, price, market cap, P/E, beta, dividend yield (%), 52 week range, earnings date |
| `get_news(ticker, days, limit)` | Alpha Vantage | The most relevant recent articles, each with its sentiment towards the ticker |
| `get_sentiment(ticker, days)` | Alpha Vantage | Relevance-weighted mean sentiment and its label, articles per label, and a CSV of the daily series |

Tools return short summaries rather than full tables, to keep the model's context small; the full
data is saved as CSV or JSON in `data/` (`prices/`, `news/`, `sentiment/`).

Every call is cached on disk in `data/cache/`: past prices forever, prices including today for an
hour, fundamentals for a day, news for 6 hours. If a source fails (rate limit, no connection), the
last cached value is returned, marked `"stale": true`. Alpha Vantage's free tier allows 25 calls a
day, but one call covers a ticker's last 30 days of news and is shared by `get_news` and
`get_sentiment`. One call returns at most 1000 articles, so for a heavily covered ticker a long
window can be cut short: results then include `"truncated": true` and `covered_from`, the first
day actually covered.

To try the server on its own in the [MCP inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m sensai.servers.quant_data
```

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
└── sessions/
    └── 20260928-143012.json    one file per session, named after its start time
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

`.env` holds the secrets: `OLLAMA_API_KEY` (required) and `ALPHAVANTAGE_API_KEY` (for news and
sentiment). Set `SENSAI_DATA` to store market data somewhere other than `data/`.

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
| `ALPHAVANTAGE_API_KEY is missing` | Get a free key at alphavantage.co and add it to `.env` |
| `alpha vantage daily limit (25 calls) reached` | Cached news keeps working; new tickers wait until tomorrow |
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
| [#5](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/5) | T1 tool calling in the chat | Planned |
| [#6](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/6) | A1 multi-step reasoning loop (ReAct) | Planned |
| [#7](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/7) | T2 sandboxed code execution | Planned |
| [#8](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/8) | M4 research note | Planned |
| [#9](https://github.com/EpitechPGE3-2026/G-AIA-500-MAD-5-1-sensai-1/issues/9) | EV1 number checking and evaluation | Planned |
