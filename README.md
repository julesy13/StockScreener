# Stock Screener

A personal stock screener and markets dashboard built on free Yahoo Finance data (via [yfinance](https://github.com/ranaroussi/yfinance)). It comes in two parts:

- **Dashboard** (`app.py`): a Dash web app with charts, filters, news, analyst data and lessons. It runs in your browser and works on your phone over the same Wi-Fi.
- **Command-line screener** (`screener.py`): prints a colored table of your watchlist in the terminal and exports it to `results.csv`.

## Setup

Requires Python 3.10+.

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt requests
```

## Running the dashboard

```powershell
.\.venv\Scripts\python.exe app.py
```

Open **http://localhost:8050**. The terminal also prints a `http://<your-ip>:8050` address for other devices on your network. Stop it with `Ctrl+C`.

On startup the app warms its caches in the background (analyst data, analyst headlines and this week's picks), so the first load of those tabs can take 30–60 seconds.

### Tabs

| Tab | What it shows |
|---|---|
| **Markets** | Index and sector-ETF performance, today's movers (US stocks over $2B), and a compare chart |
| **Themes** | Thematic baskets (built around the AI-infrastructure watchlist) compared with the S&P 500 |
| **Screener** | Your watchlist with fundamentals, a market map sized by market cap, and charts |
| **Filter** | Filter a wider universe by fundamentals, then tick results to chart and compare them |
| **Sectors** | Fundamentals and performance by sector |
| **News** | Recent headlines for your tickers |
| **Analysts** | Ratings, price targets and recent analyst actions |
| **Deep Dive** | "This week's 10" picks, each with business summary, drivers, financial trends, leadership and SEC filings |
| **Learn** | Short investing lessons with live examples from your watchlist, plus quizzes and progress tracking |

## Running the command-line screener

```powershell
.\.venv\Scripts\python.exe screener.py
```

Options:

| Flag | Effect |
|---|---|
| `--sort {1D,1W,1M,3M,6M,1Y}` | Sort by % change over that period (default `1M`) |
| `--asc` / `--desc` | Sort direction (default descending) |
| `--filter` | Apply the filters in `config.json` |
| `--tickers AAPL MSFT ...` | Screen these tickers instead of `tickers.txt` for this run |

Example: `.\.venv\Scripts\python.exe screener.py --sort 1Y --filter`

Columns: price, % change (1D–1Y), market cap, P/E, forward P/E, PEG, EPS, revenue growth, profit margin, 52-week high/low and position in that range, average and current volume. A ⚠ marks a ticker whose latest price is more than one trading day old.

## Configuration

- **`tickers.txt`**: your default watchlist, one ticker per line. The dashboard uses it too and stars these tickers.
- **`config.json`**: filters for `screener.py --filter`. Set a value to `null` to turn that filter off.

  ```json
  {
    "min_market_cap": 10000000000,
    "max_market_cap": null,
    "max_pe": 40,
    "min_revenue_growth": 10,
    "min_avg_volume": 1000000
  }
  ```

  `min_revenue_growth` is in percent; market cap is in dollars.

## Generated files

These are created as the app runs and are not committed (see `.gitignore`):

- `results.csv`: the last command-line screener output
- `analyst_cache.json`: cached analyst data
- `weekly_picks.json`: the picks for each week

`watchlists.json` (watchlists saved from the dashboard) is also created at runtime, but it isn't in `.gitignore`.

## Project layout

```
app.py         Dash dashboard
screener.py    Command-line screener
filters.py     Filter logic for config.json
lessons.py     Content for the Learn tab
assets/        Dashboard stylesheet
```

## Disclaimer

For personal research and learning only, not investment advice. Data comes from Yahoo Finance and may be delayed, incomplete or wrong.
