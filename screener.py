import argparse
import os
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box

from filters import apply_filters, load_config

SORT_CHOICES = ["1D", "1W", "1M", "3M", "6M", "1Y"]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TICKERS_FILE = os.path.join(SCRIPT_DIR, "tickers.txt")
RESULTS_FILE = os.path.join(SCRIPT_DIR, "results.csv")

console = Console()


def load_tickers() -> list[str]:
    with open(TICKERS_FILE) as f:
        return [line.strip().upper() for line in f if line.strip()]


def is_stale(last_date: date) -> bool:
    today = date.today()
    delta = today - last_date
    # skip weekends: if today is Mon/Tue the last trading day was Fri/Mon
    trading_days_back = 0
    d = today
    while d > last_date:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            trading_days_back += 1
    return trading_days_back > 1


def pct_change(series: pd.Series, periods: int) -> float | None:
    if len(series) < periods + 1:
        return None
    old = series.iloc[-(periods + 1)]
    new = series.iloc[-1]
    if old == 0:
        return None
    return (new - old) / old * 100


def fetch_ticker(symbol: str) -> dict | None:
    try:
        t = yf.Ticker(symbol)
        info = t.info

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            console.print(f"[yellow]WARNING:[/yellow] {symbol} — no price data, skipping")
            return None

        hist = t.history(period="2y")
        if hist.empty:
            console.print(f"[yellow]WARNING:[/yellow] {symbol} — empty history, skipping")
            return None

        closes = hist["Close"]
        last_date = hist.index[-1].date()

        # trading-day business-day approximations
        # 1D=1, 1W=5, 1M=21, 3M=63, 6M=126, 1Y=252
        change_1d = pct_change(closes, 1)
        change_1w = pct_change(closes, 5)
        change_1m = pct_change(closes, 21)
        change_3m = pct_change(closes, 63)
        change_6m = pct_change(closes, 126)
        change_1y = pct_change(closes, 252)

        high52 = info.get("fiftyTwoWeekHigh")
        low52 = info.get("fiftyTwoWeekLow")
        if high52 and low52 and high52 != low52:
            pos52 = (price - low52) / (high52 - low52) * 100
        else:
            pos52 = None

        return {
            "Ticker": symbol,
            "Price": price,
            "1D %": change_1d,
            "1W %": change_1w,
            "1M %": change_1m,
            "3M %": change_3m,
            "6M %": change_6m,
            "1Y %": change_1y,
            "Market Cap": info.get("marketCap"),
            "P/E": info.get("trailingPE"),
            "Fwd P/E": info.get("forwardPE"),
            "PEG": info.get("pegRatio"),
            "EPS": info.get("trailingEps"),
            "Rev Growth %": (info.get("revenueGrowth") or 0) * 100 or None,
            "Profit Margin %": (info.get("profitMargins") or 0) * 100 or None,
            "52W High": high52,
            "52W Low": low52,
            "52W Pos %": pos52,
            "Avg Volume": info.get("averageVolume"),
            "Volume": info.get("volume"),
            "Stale": is_stale(last_date),
        }
    except Exception as e:
        console.print(f"[yellow]WARNING:[/yellow] {symbol} — {e}")
        return None


def fmt_pct(val) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return "N/A"
    return f"{val:+.2f}%"


def fmt_num(val, decimals=2) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return "N/A"
    return f"{val:.{decimals}f}"


def fmt_large(val) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return "N/A"
    if val >= 1e12:
        return f"${val/1e12:.2f}T"
    if val >= 1e9:
        return f"${val/1e9:.2f}B"
    if val >= 1e6:
        return f"${val/1e6:.2f}M"
    return f"${val:,.0f}"


def fmt_vol(val) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return "N/A"
    if val >= 1e6:
        return f"{val/1e6:.1f}M"
    if val >= 1e3:
        return f"{val/1e3:.1f}K"
    return str(int(val))


def pct_color(val) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return "white"
    return "green" if val >= 0 else "red"


def build_table(df: pd.DataFrame) -> Table:
    table = Table(box=box.SIMPLE_HEAVY, show_lines=False, header_style="bold cyan")

    columns = [
        ("Ticker", "left"),
        ("Price", "right"),
        ("1D %", "right"),
        ("1W %", "right"),
        ("1M %", "right"),
        ("3M %", "right"),
        ("6M %", "right"),
        ("1Y %", "right"),
        ("Mkt Cap", "right"),
        ("P/E", "right"),
        ("Fwd P/E", "right"),
        ("PEG", "right"),
        ("EPS", "right"),
        ("Rev Gr%", "right"),
        ("Margin%", "right"),
        ("52W Hi", "right"),
        ("52W Lo", "right"),
        ("52W Pos%", "right"),
        ("Avg Vol", "right"),
        ("Volume", "right"),
        ("Stale?", "center"),
    ]
    for name, justify in columns:
        table.add_column(name, justify=justify)

    pct_cols = {"1D %", "1W %", "1M %", "3M %", "6M %", "1Y %"}

    for _, row in df.iterrows():
        cells = []
        for col, _ in columns:
            if col == "Ticker":
                cells.append(f"[bold]{row['Ticker']}[/bold]")
            elif col == "Price":
                cells.append(f"${fmt_num(row['Price'])}")
            elif col in pct_cols:
                key = col
                val = row.get(key)
                color = pct_color(val)
                cells.append(f"[{color}]{fmt_pct(val)}[/{color}]")
            elif col == "Mkt Cap":
                cells.append(fmt_large(row["Market Cap"]))
            elif col == "P/E":
                cells.append(fmt_num(row["P/E"]))
            elif col == "Fwd P/E":
                cells.append(fmt_num(row["Fwd P/E"]))
            elif col == "PEG":
                cells.append(fmt_num(row["PEG"]))
            elif col == "EPS":
                cells.append(fmt_num(row["EPS"]))
            elif col == "Rev Gr%":
                cells.append(fmt_num(row["Rev Growth %"]))
            elif col == "Margin%":
                cells.append(fmt_num(row["Profit Margin %"]))
            elif col == "52W Hi":
                cells.append(f"${fmt_num(row['52W High'])}")
            elif col == "52W Lo":
                cells.append(f"${fmt_num(row['52W Low'])}")
            elif col == "52W Pos%":
                cells.append(fmt_num(row["52W Pos %"]))
            elif col == "Avg Vol":
                cells.append(fmt_vol(row["Avg Volume"]))
            elif col == "Volume":
                cells.append(fmt_vol(row["Volume"]))
            elif col == "Stale?":
                cells.append("[yellow]⚠[/yellow]" if row.get("Stale") else "")
        table.add_row(*cells)

    return table


def main():
    parser = argparse.ArgumentParser(description="Stock screener using yfinance")
    parser.add_argument("--filter", action="store_true", help="Apply filters from config.json")
    parser.add_argument(
        "--sort",
        default="1M",
        choices=SORT_CHOICES,
        help="Column to sort by (default: 1M)",
    )
    direction = parser.add_mutually_exclusive_group()
    direction.add_argument("--asc", action="store_true", help="Sort ascending")
    direction.add_argument("--desc", action="store_true", help="Sort descending (default)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        metavar="TICKER",
        help="Override tickers.txt with these tickers for this run",
    )
    args = parser.parse_args()

    ascending = args.asc  # False if neither flag set → descending

    tickers = [t.upper() for t in args.tickers] if args.tickers else load_tickers()

    console.print(f"[bold]Fetching data for {len(tickers)} ticker(s)...[/bold]")
    rows = []
    for i, symbol in enumerate(tickers):
        console.print(f"  [{i+1}/{len(tickers)}] {symbol}", end="\r")
        row = fetch_ticker(symbol)
        if row:
            rows.append(row)
        if i < len(tickers) - 1:
            time.sleep(0.5)

    console.print()  # newline after progress

    if not rows:
        console.print("[red]No data retrieved.[/red]")
        return

    df = pd.DataFrame(rows)

    sort_col = f"{args.sort} %"
    df = df.sort_values(sort_col, ascending=ascending, na_position="last")

    if args.filter:
        config = load_config()
        before = len(df)
        df = apply_filters(df, config)
        console.print(
            f"[dim]Filter applied: {before} → {len(df)} ticker(s) passed[/dim]\n"
        )

    df.to_csv(RESULTS_FILE, index=False)
    console.print(f"[dim]Exported to {RESULTS_FILE}[/dim]\n")

    table = build_table(df)
    console.print(table)

    sort_dir = "asc" if ascending else "desc"
    console.print(
        f"[dim]Sorted by [bold]{args.sort}[/bold] ({sort_dir}) · "
        f"{len(df)} ticker(s) shown[/dim]"
    )


if __name__ == "__main__":
    main()
