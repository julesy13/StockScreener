import io
import json
import os
import re
import socket
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
import plotly.graph_objects as go
import plotly.express as px
from dash import (Dash, dcc, html, dash_table, Input, Output, State,
                  callback_context, no_update, ALL)
from dash.dash_table.Format import Format, Scheme, Sign, Symbol
import yfinance as yf

from screener import fetch_ticker, load_tickers

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
WATCHLISTS_FILE = os.path.join(SCRIPT_DIR, "watchlists.json")

# ── Design tokens (mirrors assets/style.css) ─────────────────────────────────
BG        = "#0b0e14"
SURFACE   = "#12161f"
SURFACE_2 = "#181d28"
SURFACE_3 = "#1f2532"
BORDER    = "#232a37"
GRID      = "#1b212c"
TEXT      = "#e9edf3"
MUTED     = "#8d96a8"
SUBTLE    = "#5f687a"
ACCENT    = "#4f8cff"
GREEN     = "#21c07a"
RED       = "#f2495c"
AMBER     = "#f5a524"
FONT      = "Inter, -apple-system, 'Segoe UI', Roboto, system-ui, sans-serif"

CHART_COLORS = [
    "#4f8cff", "#f5a524", "#a78bfa", "#21c07a", "#f472b6", "#22d3ee",
    "#fb7185", "#facc15", "#34d399", "#c084fc", "#60a5fa", "#fb923c",
]

# ── Market constants ──────────────────────────────────────────────────────────
MARKET_INDICES = [
    {"symbol": "^GSPC", "name": "S&P 500"},
    {"symbol": "^IXIC", "name": "Nasdaq"},
    {"symbol": "^DJI",  "name": "Dow Jones"},
    {"symbol": "^RUT",  "name": "Russell 2000"},
    {"symbol": "^VIX",  "name": "VIX"},
    {"symbol": "^TNX",  "name": "10-Yr Yield"},
]
CHART_INDICES = ["^GSPC", "^IXIC", "^DJI", "^RUT"]

# label, Yahoo screener sector name, SPDR sector ETF
SECTORS = [
    ("Technology",       "Technology",             "XLK"),
    ("Financials",       "Financial Services",     "XLF"),
    ("Health Care",      "Healthcare",             "XLV"),
    ("Communication",    "Communication Services", "XLC"),
    ("Cons. Discretionary", "Consumer Cyclical",   "XLY"),
    ("Industrials",      "Industrials",            "XLI"),
    ("Cons. Staples",    "Consumer Defensive",     "XLP"),
    ("Energy",           "Energy",                 "XLE"),
    ("Utilities",        "Utilities",              "XLU"),
    ("Real Estate",      "Real Estate",            "XLRE"),
    ("Materials",        "Basic Materials",        "XLB"),
]
SECTOR_ETF = {yahoo: etf for _, yahoo, etf in SECTORS}

PERIOD_OPTIONS = [{"label": p, "value": p} for p in ["1D", "1W", "1M", "3M", "6M", "1Y"]]

# ── Yahoo Finance session with crumb auth ─────────────────────────────────────
class _YahooSession:
    def __init__(self):
        self._s     = None
        self._crumb = None

    def _init(self):
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            s.get("https://finance.yahoo.com/", timeout=10, allow_redirects=True)
        except Exception:
            pass
        try:
            r = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
            self._crumb = r.text.strip() if r.status_code == 200 else None
        except Exception:
            self._crumb = None
        self._s = s

    def post_screener(self, payload: dict) -> requests.Response:
        if self._s is None:
            self._init()
        params = {"crumb": self._crumb, "lang": "en-US", "region": "US"} if self._crumb else {}
        resp = self._s.post(
            "https://query1.finance.yahoo.com/v1/finance/screener",
            json=payload, params=params, timeout=15,
        )
        if resp.status_code == 401:
            self._init()
            params = {"crumb": self._crumb, "lang": "en-US", "region": "US"} if self._crumb else {}
            resp = self._s.post(
                "https://query1.finance.yahoo.com/v1/finance/screener",
                json=payload, params=params, timeout=15,
            )
        return resp

    def get_json(self, url: str, params: dict | None = None) -> dict:
        if self._s is None:
            self._init()
        p = dict(params or {})
        if self._crumb:
            p["crumb"] = self._crumb
        resp = self._s.get(url, params=p, timeout=15)
        if resp.status_code == 401:
            self._init()
            if self._crumb:
                p["crumb"] = self._crumb
            resp = self._s.get(url, params=p, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_quotes(self, symbols: list) -> list:
        out = []
        for i in range(0, len(symbols), 50):
            chunk = symbols[i:i + 50]
            try:
                data = self.get_json("https://query1.finance.yahoo.com/v7/finance/quote",
                                     {"symbols": ",".join(chunk)})
                out.extend(data.get("quoteResponse", {}).get("result", []) or [])
            except Exception as e:
                print(f"Yahoo quote error: {e}")
        return out

_yahoo = _YahooSession()

# ── Yahoo screener ────────────────────────────────────────────────────────────
US_EXCHANGES = ["NMS", "NGM", "NCM", "NYQ"]   # NASDAQ tiers + NYSE


def yahoo_screen(operands: list, max_results: int = 500) -> pd.DataFrame:
    base = [
        {"operator": "EQ", "operands": ["region", "us"]},
        {"operator": "EQ", "operands": ["quoteType", "EQUITY"]},
        {"operator": "OR", "operands": [{"operator": "EQ", "operands": ["exchange", e]}
                                        for e in US_EXCHANGES]},
    ]
    all_quotes = []
    batch = 250
    for offset in range(0, max_results, batch):
        payload = {
            "offset": offset,
            "size": min(batch, max_results - offset),
            "sortField": "intradaymarketcap",
            "sortType": "DESC",
            "quoteType": "EQUITY",
            "query": {"operator": "AND", "operands": base + operands},
            "userId": "",
            "userIdType": "guid",
        }
        try:
            resp = _yahoo.post_screener(payload)
            if not resp.ok:
                print(f"Yahoo screener {resp.status_code}: {resp.text[:300]}")
                resp.raise_for_status()
            result = resp.json().get("finance", {}).get("result") or []
            if not result:
                break
            chunk  = result[0]
            quotes = chunk.get("quotes", [])
            total  = chunk.get("total", 0)
            all_quotes.extend(quotes)
            if offset + batch >= total or not quotes:
                break
        except Exception as e:
            print(f"Yahoo screener: {e}")
            break

    if not all_quotes:
        return pd.DataFrame()

    df = pd.DataFrame(all_quotes)
    rename = {
        "symbol": "Ticker", "shortName": "Company",
        "regularMarketPrice": "Price", "regularMarketChangePercent": "1D %",
        "marketCap": "Market Cap", "trailingPE": "P/E", "forwardPE": "Fwd P/E",
        "epsTrailingTwelveMonths": "EPS",
        "averageDailyVolume3Month": "Avg Volume", "regularMarketVolume": "Volume",
        "fiftyTwoWeekHigh": "52W High", "fiftyTwoWeekLow": "52W Low",
        "fiftyTwoWeekChangePercent": "1Y %",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    # drop preferred shares / depositary preferreds (e.g. JPM-PC); keep class shares like BRK-B
    df = df[~df["Ticker"].astype(str).str.contains(r"-P[A-Z]*$", regex=True)].reset_index(drop=True)
    if {"Price", "52W High", "52W Low"} <= set(df.columns):
        rng = (df["52W High"] - df["52W Low"]).where(lambda r: r > 0)
        df["52W Pos %"] = (df["Price"] - df["52W Low"]) / rng * 100
    keep = ["Ticker", "Company", "Price", "1D %", "1Y %", "Market Cap", "P/E", "Fwd P/E",
            "EPS", "Avg Volume", "Volume", "52W High", "52W Low", "52W Pos %"]
    return df[[c for c in keep if c in df.columns]]


# Filter definitions: id, label, unit, group, Yahoo screener field, scale, local column.
# Fields with a Yahoo field are applied server-side for "All US stocks"; the rest are
# applied locally when the column exists in the results (else watchlist-only).
FILTERS = [
    ("pe",     "P/E (TTM)",       "",   "Valuation",              "peratio.lasttwelvemonths",                      1,   "P/E"),
    ("fpe",    "Forward P/E",     "",   "Valuation",              None,                                            1,   "Fwd P/E"),
    ("peg",    "PEG (5Y)",        "",   "Valuation",              "pegratio_5y",                                   1,   "PEG"),
    ("eps",    "EPS (TTM)",       "$",  "Valuation",              "basicepscontinuingoperations.lasttwelvemonths", 1,   "EPS"),
    ("revgr",  "Revenue growth",  "%",  "Growth & profitability", "totalrevenues1yrgrowth.lasttwelvemonths",       1,   "Rev Growth %"),
    ("margin", "Net margin",      "%",  "Growth & profitability", None,                                            1,   "Profit Margin %"),
    ("mcap",   "Market cap",      "$B", "Size & liquidity",       "intradaymarketcap",                             1e9, "Market Cap"),
    ("vol",    "Avg volume",      "M",  "Size & liquidity",       "avgdailyvol3m",                                 1e6, "Avg Volume"),
    ("w52",    "52-wk range position", "%", "Performance",        None,                                            1,   "52W Pos %"),
    ("p1m",    "1M change",       "%",  "Performance",            None,                                            1,   "1M %"),
    ("p3m",    "3M change",       "%",  "Performance",            None,                                            1,   "3M %"),
    ("p6m",    "6M change",       "%",  "Performance",            None,                                            1,   "6M %"),
    ("p1y",    "1Y change",       "%",  "Performance",            None,                                            1,   "1Y %"),
]
FILTER_IDS = [f[0] for f in FILTERS]
# columns the "All US stocks" universe returns, so local-only filters still work there
ALL_MODE_LOCAL = {"Fwd P/E", "52W Pos %", "1Y %"}

FILTER_PRESETS = {
    "large":    ("Mega caps",  {"mcap": (200, None)}),
    "value":    ("Value",      {"pe": (0, 15), "mcap": (10, None)}),
    "growth":   ("Growth",     {"revgr": (25, None), "mcap": (2, None)}),
    "momentum": ("Momentum",   {"p1y": (40, None), "mcap": (5, None)}),
}


def _apply_local_filters(df: pd.DataFrame, mins: dict, maxs: dict, skip_yahoo: bool):
    mask, ignored = pd.Series(True, index=df.index), []
    for fid, label, _u, _g, yfield, scale, col in FILTERS:
        lo, hi = mins.get(fid), maxs.get(fid)
        if lo is None and hi is None:
            continue
        if skip_yahoo and yfield:
            continue
        if col not in df.columns:
            ignored.append(label)
            continue
        ser = pd.to_numeric(df[col], errors="coerce")
        if lo is not None:
            mask &= ser >= float(lo) * scale
        if hi is not None:
            mask &= ser <= float(hi) * scale
    return df[mask.fillna(False)], ignored


def build_yahoo_operands(mins: dict, maxs: dict) -> list:
    ops = []
    for fid, _l, _u, _g, yfield, scale, _c in FILTERS:
        if not yfield:
            continue
        lo, hi = mins.get(fid), maxs.get(fid)
        if lo is not None:
            ops.append({"operator": "GT", "operands": [yfield, float(lo) * scale]})
        if hi is not None:
            ops.append({"operator": "LT", "operands": [yfield, float(hi) * scale]})
    return ops

# ── Market snapshot (bulk yf.download) ───────────────────────────────────────
def fetch_market_snapshot():
    all_syms = [x["symbol"] for x in MARKET_INDICES] + [etf for *_, etf in SECTORS]
    hist_df  = pd.DataFrame()
    try:
        raw = yf.download(all_syms, period="1y", progress=False, auto_adjust=True)
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = raw.columns.get_level_values(0).unique()
            key    = "Close" if "Close" in level0 else (level0[0] if len(level0) else None)
            hist_df = raw[key] if key else pd.DataFrame()
        elif "Close" in raw.columns:
            hist_df = raw[["Close"]].rename(columns={"Close": all_syms[0]})
    except Exception as e:
        print(f"Market download error: {e}")

    def chg(ser, n):
        return float((ser.iloc[-1] / ser.iloc[-1 - n] - 1) * 100) if len(ser) > n else None

    rows = {}
    for sym in all_syms:
        try:
            ser = (hist_df[sym].dropna()
                   if (not hist_df.empty and sym in hist_df.columns)
                   else pd.Series(dtype=float))
            if len(ser) == 0:
                rows[sym] = {}
                continue
            rows[sym] = {
                "price": float(ser.iloc[-1]),
                "chg":   float(ser.iloc[-1] - ser.iloc[-2]) if len(ser) >= 2 else None,
                "pct1d": chg(ser, 1), "pct1w": chg(ser, 5),
                "pct1m": chg(ser, 21), "pct3m": chg(ser, 63),
                "spark": [round(float(v), 4) for v in ser.iloc[-63:]],
            }
        except Exception:
            rows[sym] = {}
    return rows, hist_df

# ── Watchlist helpers ─────────────────────────────────────────────────────────
def load_watchlists() -> dict:
    if os.path.exists(WATCHLISTS_FILE):
        try:
            with open(WATCHLISTS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_watchlists(lists: dict):
    with open(WATCHLISTS_FILE, "w") as f:
        json.dump(lists, f, indent=2)

def watchlist_options(lists: dict) -> list:
    return [{"label": "Default (tickers.txt)", "value": "__default__"}] + \
           [{"label": n, "value": n} for n in lists]

def _parse_tickers(text) -> list:
    return [t.strip().upper() for t in (text or "").replace(",", " ").split() if t.strip()]

def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

LOCAL_IP = _local_ip()

# ── Price history cache ──────────────────────────────────────────────────────
HIST_CACHE_TTL = 30 * 60
_hist_cache: dict = {}        # symbol -> (timestamp, pd.Series of 1Y closes)


def _clean_series(ser: pd.Series) -> pd.Series:
    ser = ser.dropna()
    idx = pd.to_datetime(ser.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    ser.index = idx.normalize()
    return ser


def get_histories_1y(symbols: list) -> dict:
    """1Y daily closes for each symbol, bulk-downloaded and cached."""
    now = time.time()
    out, missing = {}, []
    for s in dict.fromkeys(symbols):
        hit = _hist_cache.get(s)
        if hit and now - hit[0] < HIST_CACHE_TTL:
            out[s] = hit[1]
        else:
            missing.append(s)
    if missing:
        try:
            raw = yf.download(missing, period="1y", progress=False,
                              auto_adjust=True, threads=True)
            closes = raw["Close"] if "Close" in raw else pd.DataFrame()
            if isinstance(closes, pd.Series):
                closes = closes.to_frame(name=missing[0])
            for s in missing:
                if s in closes.columns:
                    ser = _clean_series(closes[s])
                    if len(ser):
                        _hist_cache[s] = (now, ser)
                        out[s] = ser
        except Exception as e:
            print(f"History download error: {e}")
    return out


def _pct_back(ser, n):
    return float((ser.iloc[-1] / ser.iloc[-1 - n] - 1) * 100) if ser is not None and len(ser) > n else None

# ── News / trending data ──────────────────────────────────────────────────────
# Broad market queries; each Yahoo news article carries a `relatedTickers` list,
# so counting tickers across recent articles gives "most talked about" stocks.
NEWS_QUERIES = [
    "stock market", "stocks", "Wall Street", "earnings", "shares",
    "analyst rating", "IPO", "guidance", "Nasdaq", "Dow Jones",
]
NEWS_CACHE_TTL   = 10 * 60
NEWS_MAX_TICKERS = 40
_news_cache = {"ts": 0.0, "articles": []}


def _search_news(query: str) -> list:
    try:
        return yf.Search(query, news_count=50, max_results=0).news or []
    except Exception as e:
        print(f"News search '{query}': {e}")
        return []


def fetch_news_articles(force: bool = False) -> list:
    """All recent articles from the broad queries, de-duplicated. Cached."""
    if not force and _news_cache["articles"] and time.time() - _news_cache["ts"] < NEWS_CACHE_TTL:
        return _news_cache["articles"]
    seen, articles = set(), []
    with ThreadPoolExecutor(max_workers=5) as pool:
        for batch in pool.map(_search_news, NEWS_QUERIES):
            for a in batch:
                key = a.get("uuid") or a.get("link")
                if key and key not in seen:
                    seen.add(key)
                    articles.append(a)
    articles.sort(key=lambda a: a.get("providerPublishTime") or 0, reverse=True)
    if articles:
        _news_cache.update(ts=time.time(), articles=articles)
    return articles


def fetch_yahoo_trending() -> set:
    try:
        data = _yahoo.get_json("https://query1.finance.yahoo.com/v1/finance/trending/US",
                               {"count": 50})
        res = data.get("finance", {}).get("result") or []
        return {q["symbol"] for q in (res[0].get("quotes", []) if res else [])}
    except Exception as e:
        print(f"Yahoo trending error: {e}")
        return set()


def _is_us_stock_symbol(sym: str) -> bool:
    # skip indices (^GSPC), futures/currencies (GC=F, EURUSD=X), foreign listings (WTB.L),
    # crypto (BTC-USD)
    return bool(sym) and not any(c in sym for c in "^=.") and not sym.endswith("-USD")


def build_news_trending(hours: int, force: bool = False):
    """Return (rows, n_articles_in_window) for stocks mentioned in the last `hours`."""
    articles = fetch_news_articles(force=force)
    cutoff = time.time() - hours * 3600
    recent = [a for a in articles if (a.get("providerPublishTime") or 0) >= cutoff]

    counts, heads = {}, {}
    for a in recent:
        for sym in dict.fromkeys(a.get("relatedTickers") or []):
            if not _is_us_stock_symbol(sym):
                continue
            counts[sym] = counts.get(sym, 0) + 1
            heads.setdefault(sym, []).append({
                "title":     a.get("title", ""),
                "publisher": a.get("publisher", ""),
                "link":      a.get("link", ""),
                "time":      a.get("providerPublishTime") or 0,
                "tickers":   [t for t in (a.get("relatedTickers") or []) if _is_us_stock_symbol(t)],
            })
    if not counts:
        return [], len(recent)

    trending   = fetch_yahoo_trending()
    candidates = sorted(counts, key=lambda s: (-counts[s], -(s in trending)))[:NEWS_MAX_TICKERS * 2]
    quotes     = {q["symbol"]: q for q in _yahoo.get_quotes(candidates)}
    stocks     = [s for s in candidates if quotes.get(s, {}).get("quoteType") == "EQUITY"]
    stocks     = stocks[:NEWS_MAX_TICKERS]
    hists      = get_histories_1y(stocks)

    rows = []
    for s in stocks:
        q   = quotes[s]
        ser = hists.get(s)
        rows.append({
            "Ticker":     s,
            "Company":    q.get("shortName") or q.get("longName") or "",
            "Price":      q.get("regularMarketPrice"),
            "1D %":       q.get("regularMarketChangePercent"),
            "1M %":       _pct_back(ser, 21),
            "Market Cap": q.get("marketCap"),
            "Mentions":   counts[s],
            "Trending":   s in trending,
            "Spark":      [round(float(v), 4) for v in ser.iloc[-22:]] if ser is not None else [],
            "Headlines":  heads[s],
        })
    rows.sort(key=lambda r: (-r["Mentions"], -r["Trending"], -(r["Market Cap"] or 0)))
    return rows, len(recent)


def _article(a) -> dict:
    return {
        "title":     a.get("title", ""),
        "publisher": a.get("publisher", ""),
        "link":      a.get("link", ""),
        "time":      a.get("providerPublishTime") or 0,
        "tickers":   [t for t in (a.get("relatedTickers") or []) if _is_us_stock_symbol(t)],
    }


_ticker_news_cache: dict = {}     # key -> (timestamp, [articles])


def fetch_ticker_news(sym: str) -> list:
    """Recent headlines for one stock (Yahoo search), cached 10 minutes."""
    hit = _ticker_news_cache.get(sym)
    if hit and time.time() - hit[0] < NEWS_CACHE_TTL:
        return hit[1]
    try:
        news = yf.Search(sym, news_count=15, max_results=0).news or []
    except Exception as e:
        print(f"Ticker news '{sym}': {e}")
        news = []
    arts = [_article(a) for a in news]
    if arts:
        _ticker_news_cache[sym] = (time.time(), arts)
    return arts


ANALYST_NEWS_QUERIES = [
    "analyst upgrade", "analyst downgrade", "price target raised", "price target cut",
    "price target", "initiates coverage", "upgrades stock", "downgrades stock",
    "reiterates rating", "analyst rating", "buy rating", "overweight rating", "outperform",
]
_ANALYST_KW = re.compile(
    r"upgrad|downgrad|price target|\bPT\b|rating|initiat|reiterat|overweight|underweight|"
    r"outperform|underperform|analyst", re.I)


def fetch_analyst_headlines() -> list:
    """Recent analyst-action headlines (rating changes, price targets, initiations)."""
    hit = _ticker_news_cache.get("__analyst__")
    if hit and time.time() - hit[0] < NEWS_CACHE_TTL:
        return hit[1]
    seen, arts = set(), []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for batch in pool.map(_search_news, ANALYST_NEWS_QUERIES):
            for a in batch:
                if (a.get("link") and a["link"] not in seen
                        and _ANALYST_KW.search(a.get("title", ""))):
                    seen.add(a["link"])
                    arts.append(_article(a))
    arts.sort(key=lambda h: h["time"], reverse=True)
    if arts:
        _ticker_news_cache["__analyst__"] = (time.time(), arts)
    return arts

# ── Analyst coverage data ─────────────────────────────────────────────────────
# Source: Yahoo Finance quoteSummary (no key) — dated upgrade/downgrade/price-target
# history per stock, current rating distribution and consensus targets.
# (MarketBeat, Benzinga, TipRanks and Seeking Alpha sit behind bot challenges.)
ANALYST_CACHE_FILE = os.path.join(SCRIPT_DIR, "analyst_cache.json")
ANALYST_TTL        = 6 * 3600
ANALYST_UNIVERSE   = 200          # largest US stocks by market cap
ANALYST_MAX_ROWS   = 60
ANALYST_WINDOWS    = {"1W": 7, "1M": 30, "3M": 91, "6M": 182, "1Y": 365}
ANALYST_ACTIONS    = {"up": "Upgrade", "down": "Downgrade", "init": "Initiates",
                      "main": "Maintains", "reit": "Reiterates"}
RATING_LABELS      = {"strong_buy": "Strong Buy", "buy": "Buy", "hold": "Hold",
                      "underperform": "Underperform", "sell": "Sell", "none": ""}

_analyst      = {"ts": 0.0, "records": []}
_analyst_lock = threading.Lock()


def _raw(v):
    return v.get("raw") if isinstance(v, dict) else v


def _fetch_analyst_one(sym: str) -> dict | None:
    try:
        d = _yahoo.get_json(
            f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}",
            {"modules": "upgradeDowngradeHistory,recommendationTrend,financialData"})
        res = (d.get("quoteSummary", {}).get("result") or [None])[0]
    except Exception as e:
        print(f"Analyst data '{sym}': {e}")
        return None
    if not res:
        return None
    cutoff = time.time() - 370 * 86400
    hist = [{
        "t":     h.get("epochGradeDate") or 0,
        "firm":  h.get("firm", ""),
        "to":    h.get("toGrade", ""),
        "from":  h.get("fromGrade", ""),
        "action": h.get("action", ""),
        "ptAct": h.get("priceTargetAction", ""),
        "pt":    _raw(h.get("currentPriceTarget")) or None,
        "ptOld": _raw(h.get("priorPriceTarget")) or None,
    } for h in (res.get("upgradeDowngradeHistory") or {}).get("history", [])
        if (h.get("epochGradeDate") or 0) >= cutoff]
    trend = next((t for t in (res.get("recommendationTrend") or {}).get("trend", [])
                  if t.get("period") == "0m"), {})
    fd = res.get("financialData") or {}
    return {
        "Ticker":   sym,
        "history":  sorted(hist, key=lambda h: h["t"], reverse=True),
        "ratings":  [trend.get(k, 0) or 0 for k in ("strongBuy", "buy", "hold", "sell", "strongSell")],
        "target":   _raw(fd.get("targetMeanPrice")),
        "targetHi": _raw(fd.get("targetHighPrice")),
        "targetLo": _raw(fd.get("targetLowPrice")),
        "recKey":   fd.get("recommendationKey") or "none",
        "recMean":  _raw(fd.get("recommendationMean")),
        "analysts": _raw(fd.get("numberOfAnalystOpinions")),
    }


def load_analyst_data(force: bool = False) -> list:
    """Analyst records for the universe; memory → disk cache → Yahoo (~30-60s)."""
    with _analyst_lock:
        now = time.time()
        if not force and _analyst["records"] and now - _analyst["ts"] < ANALYST_TTL:
            return _analyst["records"]
        if not force and os.path.exists(ANALYST_CACHE_FILE):
            try:
                with open(ANALYST_CACHE_FILE) as f:
                    disk = json.load(f)
                if now - disk.get("ts", 0) < ANALYST_TTL and disk.get("records"):
                    _analyst.update(ts=disk["ts"], records=disk["records"])
                    return _analyst["records"]
            except Exception:
                pass

        universe = yahoo_screen([], max_results=ANALYST_UNIVERSE)
        if universe.empty:
            return _analyst["records"]
        info = {r["Ticker"]: r for r in universe.to_dict("records")}
        # also cover stocks currently trending in the news, if loaded
        extra = [s for s in {t for a in _news_cache["articles"][:300]
                             for t in (a.get("relatedTickers") or [])}
                 if _is_us_stock_symbol(s) and s not in info]
        for q in (_yahoo.get_quotes(extra) if extra else []):
            if q.get("quoteType") == "EQUITY":
                info[q["symbol"]] = {"Ticker": q["symbol"],
                                     "Company": q.get("shortName") or q.get("longName") or "",
                                     "Price": q.get("regularMarketPrice"),
                                     "1D %": q.get("regularMarketChangePercent"),
                                     "Market Cap": q.get("marketCap")}
        if _yahoo._s is None:
            _yahoo._init()
        with ThreadPoolExecutor(max_workers=12) as pool:
            fetched = list(pool.map(_fetch_analyst_one, list(info)))
        records = []
        for rec in fetched:
            if not rec:
                continue
            base = info[rec["Ticker"]]
            rec.update({k: base.get(k) for k in ("Company", "Price", "1D %", "Market Cap")})
            for k, v in list(rec.items()):
                if isinstance(v, float) and v != v:
                    rec[k] = None
            records.append(rec)
        if records:
            _analyst.update(ts=time.time(), records=records)
            try:
                with open(ANALYST_CACHE_FILE, "w") as f:
                    json.dump({"ts": _analyst["ts"], "records": records}, f)
            except Exception as e:
                print(f"Analyst cache write: {e}")
        return _analyst["records"]


def analyst_window(records: list, window: str, sort: str, headlines: list | None = None):
    """Rank stocks by analyst attention within the window: dated rating/price-target
    actions (Yahoo) plus analyst-related headlines. Returns (rows, totals)."""
    cutoff = time.time() - ANALYST_WINDOWS.get(window, 30) * 86400
    heads_by = {}
    for h in headlines or []:
        if h["time"] >= cutoff:
            for t in dict.fromkeys(h["tickers"]):
                heads_by.setdefault(t, []).append(h)
    rows = []
    tot = {"actions": 0, "up": 0, "down": 0, "init": 0, "stocks": 0, "heads": 0}
    for rec in records:
        acts  = [h for h in rec["history"] if h["t"] >= cutoff]
        heads = heads_by.get(rec["Ticker"], [])
        if not acts and not heads:
            continue
        tot["heads"] += len(heads)
        ups   = sum(a["action"] == "up" for a in acts)
        downs = sum(a["action"] == "down" for a in acts)
        inits = sum(a["action"] == "init" for a in acts)
        tot["actions"] += len(acts); tot["up"] += ups; tot["down"] += downs
        tot["init"] += inits; tot["stocks"] += 1
        price, target = rec.get("Price"), rec.get("target")
        rows.append({
            **{k: rec.get(k) for k in ("Ticker", "Company", "Price", "1D %", "Market Cap",
                                       "ratings", "target", "targetHi", "targetLo",
                                       "recKey", "recMean", "analysts")},
            "actions": acts, "n": len(acts), "ups": ups, "downs": downs, "inits": inits,
            "heads": len(heads), "score": len(acts) + len(heads),
            "firms": len({a["firm"] for a in acts}),
            "ptUp":   sum(a["ptAct"] == "Raises" for a in acts),
            "ptDown": sum(a["ptAct"] == "Lowers" for a in acts),
            "upside": (target / price - 1) * 100 if _ok(price) and _ok(target) and price else None,
        })
    keys = {
        "coverage":   lambda r: (-r["score"], -r["firms"]),
        "upgrades":   lambda r: (-r["ups"], -(r["ups"] - r["downs"]), -r["score"]),
        "downgrades": lambda r: (-r["downs"], -(r["downs"] - r["ups"]), -r["score"]),
        "upside":     lambda r: (-(r["upside"] if r["upside"] is not None else -1e9), -r["score"]),
    }
    rows.sort(key=keys.get(sort, keys["coverage"]))
    return rows[:ANALYST_MAX_ROWS], tot

# ── Format helpers ────────────────────────────────────────────────────────────
def _ok(v):
    return v is not None and not (isinstance(v, float) and v != v)

def _pct(v, d=2):
    return f"{v:+.{d}f}%" if _ok(v) else "—"

def _price(v):
    return f"${v:,.2f}" if _ok(v) else "—"

def _num(v, d=1):
    return f"{v:,.{d}f}" if _ok(v) else "—"

def _large(v):
    if not _ok(v): return "—"
    if v >= 1e12: return f"${v/1e12:.2f}T"
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"

def _tone(v):
    if not _ok(v) or v == 0:
        return "flat"
    return "up" if v > 0 else "down"

def _time_ago(ts: float) -> str:
    mins = max(0, int((time.time() - ts) / 60))
    if mins < 60:
        return f"{mins}m ago"
    if mins < 48 * 60:
        return f"{mins // 60}h ago"
    return f"{mins // 1440}d ago"

def _fmt_idx(price, sym):
    if not _ok(price): return "—"
    if sym == "^TNX":  return f"{price:.3f}%"
    return f"{price:,.2f}"

# ── UI primitives ─────────────────────────────────────────────────────────────
def _cx(*parts):
    return " ".join(p for p in parts if p)

def _kids(*items):
    return [i for i in items if i is not None]

def _btn(label, id_, kind=""):
    return html.Button(label, id=id_, n_clicks=0, className=_cx("btn", kind))

def _page_head(title, sub, actions=None):
    return html.Div([
        html.Div([html.H1(title, className="page-title"), html.Div(sub, className="page-sub")]),
        html.Div(actions or [], className="page-actions"),
    ], className="page-head")

def _panel(children, title=None, sub=None, right=None, className="", **kw):
    # note: Dash components with no children are falsy, so test against None
    head = None
    if title is not None or right is not None:
        head = html.Div([
            html.Div(_kids(html.Div(title, className="panel-title") if title is not None else None,
                           html.Div(sub, className="panel-sub") if sub else None)),
            html.Div(right) if right is not None else None,
        ], className="panel-head")
    body = children if isinstance(children, list) else [children]
    return html.Div(_kids(head, *body), className=_cx("panel", className), **kw)

def _field(label, control, hint=None, className="", id=None):
    kw = {"id": id} if id else {}
    return html.Div(_kids(html.Div(label, className="field-label"), control,
                          html.Div(hint, className="field-hint") if hint else None),
                    className=_cx("field", className), **kw)

def _seg(id_, options, value):
    return dcc.RadioItems(id=id_, options=options, value=value, inline=True, className="seg")

def _empty(msg, warn=False):
    return html.Div(msg, className=_cx("empty", "empty-warn" if warn else ""))

def _chip(v):
    return html.Span(_pct(v), className=f"chip chip-{_tone(v)}")

def _spark_src(values, w=76, h=28, stretch=False):
    vals = [float(v) for v in (values or []) if _ok(v)]
    if len(vals) < 2:
        return None
    lo, hi = min(vals), max(vals)
    rng  = (hi - lo) or 1
    step = w / (len(vals) - 1)
    pts  = [(i * step, h - 2 - (v - lo) / rng * (h - 4)) for i, v in enumerate(vals)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,{h} " + line + f" {w},{h}"
    color = GREEN if vals[-1] >= vals[0] else RED
    par = " preserveAspectRatio='none'" if stretch else ""
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
           f"viewBox='0 0 {w} {h}'{par}>"
           f"<polygon points='{area}' fill='{color}' fill-opacity='0.10'/>"
           f"<polyline points='{line}' fill='none' stroke='{color}' stroke-width='1.6' "
           f"stroke-linejoin='round' stroke-linecap='round' vector-effect='non-scaling-stroke'/></svg>")
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)

def _quote_card(ticker, id_type, sel_color=None, *, company="", price=None, change=None,
                spark=None, stats=(), note=None, badge=None, extra=None):
    """Unified clickable stock card used by Screener, Sectors and News."""
    src = _spark_src(spark)
    return html.Div(
        id={"type": id_type, "ticker": ticker},
        n_clicks=0,
        className=_cx("qcard", "is-selected" if sel_color else ""),
        children=_kids(
            html.Div(style={"background": sel_color}, className="qcard-swatch") if sel_color else None,
            html.Div([
                html.Div(html.Span(ticker, className="qcard-sym"), className="qcard-symrow"),
                html.Img(src=src, className="qcard-spark") if src else None,
            ], className="qcard-top"),
            html.Div(company or "\u00a0", className="qcard-name", title=company),
            html.Div([html.Span(_price(price), className="qcard-price"), _chip(change)],
                     className="qcard-pricerow"),
            extra,
            html.Div([html.Span([html.Span(k, className="stat-k"),
                                 html.Span(v, className=_cx("stat-v", cls))])
                      for k, v, cls in stats] +
                     ([html.Span(badge, className="badge badge-hot",
                                 style={"marginLeft": "auto"})] if badge else []),
                     className="qcard-stats") if (stats or badge) else None,
            html.Div(note, className="qcard-note", title=note) if note else None,
        ),
    )

def _sel_color(ticker, selected):
    return CHART_COLORS[selected.index(ticker) % len(CHART_COLORS)] if ticker in selected else None


def _headline_items(pool: list, sel=(), limit=40):
    sel = set(sel or [])
    items = [
        html.A([
            html.Div(h["title"], className="news-title"),
            html.Div([
                html.Span(h["publisher"]), html.Span("·"), html.Span(_time_ago(h["time"])),
                *[html.Span(t, className=_cx("news-tk", "is-sel" if t in sel else ""))
                  for t in sorted(h["tickers"], key=lambda t: t not in sel)[:6]],
            ], className="news-meta"),
        ], href=h["link"], target="_blank", rel="noopener noreferrer", className="news-item")
        for h in pool[:limit]
    ]
    return items or _empty("No headlines")

# ── Analyst UI pieces ─────────────────────────────────────────────────────────
RATING_COLORS = ["#16935a", "#21c07a", "#6b7385", "#f2495c", "#b4232f"]
RATING_NAMES  = ["Strong buy", "Buy", "Hold", "Sell", "Strong sell"]


def _rating_tone(key):
    return {"strong_buy": "up", "buy": "up", "underperform": "down", "sell": "down"}.get(key, "flat")


def _rating_block(r):
    counts = r.get("ratings") or [0] * 5
    total  = sum(counts)
    label  = RATING_LABELS.get(r.get("recKey") or "none", "")
    up     = r.get("upside")
    if not total and not label:
        return None
    bar = html.Div([
        html.Div(style={"width": f"{c / total * 100:.1f}%", "background": col},
                 title=f"{name}: {c}")
        for c, col, name in zip(counts, RATING_COLORS, RATING_NAMES) if c
    ], className="rbar") if total else None
    return html.Div(_kids(
        html.Div([
            html.Span(label or "No consensus", className=_cx("rating-label", _rating_tone(r.get("recKey")))),
            html.Span(f"{total} analysts" if total else "", className="stat-k"),
            html.Span(["PT ", html.B(_price(r.get("target"))), " ",
                       html.Span(_pct(up, 1), className=_tone(up))],
                      className="rating-pt") if _ok(r.get("target")) else None,
        ], className="rating-line"),
        bar,
    ), className="rating")


def _fmt_date(ts):
    return time.strftime("%b %d", time.localtime(ts)).replace(" 0", " ")


def _grade_text(a):
    if a["from"] and a["to"] and a["from"] != a["to"]:
        return f"{a['from']} → {a['to']}"
    return a["to"] or a["from"] or ""


def _pt_text(a):
    pt, old = a.get("pt"), a.get("ptOld")
    if pt and old and abs(pt - old) > 1e-9:
        return f"PT {_price(old)} → {_price(pt)}"
    return f"PT {_price(pt)}" if pt else ""


def _action_note(a):
    parts = [_fmt_date(a["t"]), f"{a['firm']}: {ANALYST_ACTIONS.get(a['action'], a['action'].title())}"]
    g = _grade_text(a)
    if g:
        parts[-1] += f" {g}"
    pt = _pt_text(a)
    return " · ".join(parts + ([pt] if pt else []))


def _action_items(actions: list, show_ticker: bool, limit=50):
    chip = {"up": "chip-up", "down": "chip-down", "init": "chip-blue"}
    items = []
    for a in actions[:limit]:
        kind = a["action"]
        items.append(html.Div([
            html.Div(_kids(
                html.Span(a.get("ticker"), className="news-tk is-sel") if show_ticker else None,
                html.Span(a["firm"], className="act-firm"),
                html.Span(ANALYST_ACTIONS.get(kind, kind.title()),
                          className=_cx("chip", chip.get(kind, "chip-flat"))),
            ), className="act-top"),
            html.Div(_kids(
                html.Span(_grade_text(a)) if _grade_text(a) else None,
                html.Span(_pt_text(a), className=_tone((a.get("pt") or 0) - (a.get("ptOld") or 0))
                          if a.get("ptOld") else "") if _pt_text(a) else None,
                html.Span(_fmt_date(a["t"])),
            ), className="news-meta"),
        ], className="act-item"))
    return items or _empty("No analyst actions in this window")

# ── Charts ────────────────────────────────────────────────────────────────────
RANGE_BUTTONS = [
    dict(count=7, label="1W", step="day",   stepmode="backward"),
    dict(count=1, label="1M", step="month", stepmode="backward"),
    dict(count=3, label="3M", step="month", stepmode="backward"),
    dict(count=6, label="6M", step="month", stepmode="backward"),
    dict(count=1, label="YTD", step="year", stepmode="todate"),
    dict(label="1Y", step="all"),
]


def _style_fig(fig, *, top=34):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=11, color=MUTED),
        margin=dict(l=4, r=4, t=top, b=4),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=SURFACE_2, bordercolor=BORDER,
                        font=dict(family=FONT, size=12, color=TEXT)),
        legend=dict(orientation="h", x=1, xanchor="right", y=1.0, yanchor="bottom",
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11, color=TEXT)),
    )
    fig.update_xaxes(showgrid=False, linecolor=BORDER, ticks="", zeroline=False,
                     tickfont=dict(size=10.5, color=MUTED),
                     showspikes=True, spikecolor=SUBTLE, spikethickness=1,
                     spikedash="dot", spikemode="across")
    fig.update_yaxes(gridcolor=GRID, zeroline=False, side="right", ticks="",
                     tickfont=dict(size=10.5, color=MUTED))
    return fig


def _empty_fig(msg=""):
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        annotations=[dict(text=msg, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
                          font=dict(color=SUBTLE, size=13, family=FONT))],
    )
    return fig


def _y_range(lo, hi):
    if lo is None:
        return None
    pad = max((hi - lo) * 0.08, abs(hi) * 0.005, 0.5 if hi - lo < 1 else 0)
    return [lo - pad, hi + pad]


def _compare_figs(series: dict, order: list, xrange=None, default_months=1,
                  with_price=True, names=None, colors=None):
    """% change (re-based to the first visible day) and price charts.
    The full series is sent to the browser; the visible window defaults to the
    last `default_months` (or the user's last zoom, `xrange`)."""
    order = [t for t in order if t in series and len(series[t])]
    if not order:
        msg = "No price history"
        return _empty_fig(msg), (_empty_fig(msg) if with_price else None)
    names  = names or {}
    colors = colors or {}
    last  = max(series[t].index[-1] for t in order)
    first = min(series[t].index[0] for t in order)
    if xrange:
        x0, x1 = pd.Timestamp(str(xrange[0])), pd.Timestamp(str(xrange[1]))
    else:
        x0, x1 = last - pd.DateOffset(months=default_months), last
    x0 = max(min(x0, last), first - pd.Timedelta(days=1))

    norm_fig, price_fig = go.Figure(), go.Figure()
    n_lo = n_hi = p_lo = p_hi = None
    single = len(order) == 1
    for i, t in enumerate(order):
        ser   = series[t]
        name  = names.get(t, t)
        color = colors.get(t, CHART_COLORS[i % len(CHART_COLORS)])
        xs    = ser.index.strftime("%Y-%m-%d").tolist()
        after = ser[ser.index >= x0]
        base  = after.iloc[0] if len(after) else ser.iloc[-1]
        norm  = (ser / base - 1) * 100
        vis   = (ser.index >= x0) & (ser.index <= x1)
        if vis.any():
            nv, pv = norm[vis], ser[vis]
            n_lo = min(n_lo, nv.min()) if n_lo is not None else nv.min()
            n_hi = max(n_hi, nv.max()) if n_hi is not None else nv.max()
            p_lo = min(p_lo, pv.min()) if p_lo is not None else pv.min()
            p_hi = max(p_hi, pv.max()) if p_hi is not None else pv.max()
        norm_fig.add_trace(go.Scatter(
            x=xs, y=norm.round(3).tolist(), customdata=ser.round(4).tolist(),
            mode="lines", name=name, line=dict(color=color, width=2),
            hovertemplate=f"{name}  <b>%{{y:+.2f}}%</b><extra></extra>",
        ))
        price_fig.add_trace(go.Scatter(
            x=xs, y=ser.round(4).tolist(), mode="lines", name=name,
            line=dict(color=color, width=2),
            fill="tozeroy" if single else None,
            fillcolor="rgba(79,140,255,0.08)" if single else None,
            hovertemplate=f"{name}  <b>$%{{y:,.2f}}</b><extra></extra>",
        ))

    xr = [x0.strftime("%Y-%m-%d"), x1.strftime("%Y-%m-%d")]
    figs = [(norm_fig, _y_range(n_lo, n_hi))]
    if with_price:
        figs.append((price_fig, _y_range(p_lo, p_hi)))
    for fig, yr in figs:
        _style_fig(fig, top=40)
        fig.update_xaxes(
            type="date", range=xr, autorange=False,
            rangeselector=dict(
                buttons=RANGE_BUTTONS, x=0, xanchor="left", y=1.0, yanchor="bottom",
                bgcolor=SURFACE_2, activecolor=SURFACE_3, bordercolor=BORDER, borderwidth=1,
                font=dict(color=TEXT, size=11, family=FONT),
            ),
        )
        # x-only zooming; y is refit to the visible window (server + clientside)
        fig.update_yaxes(fixedrange=True, autorange=yr is None, range=yr)
    norm_fig.add_hline(y=0, line_dash="dot", line_color=SUBTLE, line_width=1)
    norm_fig.update_yaxes(ticksuffix="%")
    price_fig.update_yaxes(tickprefix="$")
    return norm_fig, (price_fig if with_price else None)


def _build_compare_charts(selected: list, xrange=None):
    if not selected:
        return (_empty_fig("Select stocks to compare"),
                _empty_fig("Click any card to chart it"))
    return _compare_figs(get_histories_1y(selected), selected, xrange)


def _sector_bars_fig(mdata: dict, key: str):
    items = [(label, (mdata.get(etf) or {}).get(key)) for label, _y, etf in SECTORS]
    items = sorted([i for i in items if _ok(i[1])], key=lambda i: i[1])
    if not items:
        return _empty_fig("Loading…")
    fig = go.Figure(go.Bar(
        x=[v for _, v in items], y=[l for l, _ in items], orientation="h",
        marker=dict(color=[GREEN if v >= 0 else RED for _, v in items], cornerradius=4),
        text=[f"{v:+.2f}%" for _, v in items], textposition="outside", cliponaxis=False,
        textfont=dict(family=FONT, size=11, color=TEXT),
        hovertemplate="%{y}  <b>%{x:+.2f}%</b><extra></extra>",
    ))
    _style_fig(fig, top=4)
    span = max(abs(v) for _, v in items) or 1
    fig.update_layout(hovermode="closest", bargap=0.38, showlegend=False,
                      margin=dict(l=4, r=48, t=4, b=4))
    fig.update_xaxes(showspikes=False, gridcolor=GRID, showgrid=True, ticksuffix="%",
                     range=[-span * 1.25 if items[0][1] < 0 else 0,
                            span * 1.25 if items[-1][1] > 0 else 0],
                     zeroline=True, zerolinecolor=BORDER)
    fig.update_yaxes(side="left", showgrid=False, tickfont=dict(size=12, color=TEXT),
                     ticksuffix="  ")
    return fig


def _treemap_fig(df: pd.DataFrame, period: str):
    pct_col = f"{period} %"
    tdf = df.copy()
    tdf["_size"]   = pd.to_numeric(tdf.get("Market Cap"), errors="coerce").fillna(1e9).clip(lower=1e8)
    tdf["_pct"]    = pd.to_numeric(tdf.get(pct_col), errors="coerce").fillna(0)
    tdf["_sector"] = tdf["Sector"].fillna("Other") if "Sector" in tdf.columns else "Watchlist"
    span = tdf["_pct"].abs().max() or 1
    fig = px.treemap(
        tdf, path=["_sector", "Ticker"], values="_size", color="_pct",
        color_continuous_scale=[[0, "#b4232f"], [0.5, "#262c38"], [1, "#16935a"]],
        range_color=[-span, span], custom_data=["_pct", "Ticker"],
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{customdata[0]:+.2f}%",
        hovertemplate="<b>%{label}</b>  %{customdata[0]:+.2f}%<extra></extra>",
        textfont=dict(size=13, family=FONT, color="#ffffff"),
        marker=dict(line=dict(color=BG, width=2)),
        root_color=SURFACE, tiling=dict(pad=2),
    )
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, color=TEXT),
                      coloraxis_showscale=False, margin=dict(l=0, r=0, t=0, b=0))
    return fig

# ── Tables ────────────────────────────────────────────────────────────────────
# source column -> (header, kind)
COL_SPECS = {
    "Ticker":          ("Symbol",     "ticker"),
    "Company":         ("Name",       "text"),
    "Sector":          ("Sector",     "text"),
    "Price":           ("Price",      "price"),
    "1D %":            ("1D",         "pct"),
    "1W %":            ("1W",         "pct"),
    "1M %":            ("1M",         "pct"),
    "3M %":            ("3M",         "pct"),
    "6M %":            ("6M",         "pct"),
    "1Y %":            ("1Y",         "pct"),
    "Market Cap":      ("Mkt cap",    "cap"),
    "P/E":             ("P/E",        "num"),
    "Fwd P/E":         ("Fwd P/E",    "num"),
    "PEG":             ("PEG",        "num"),
    "EPS":             ("EPS",        "num"),
    "Rev Growth %":    ("Rev growth", "pct"),
    "Profit Margin %": ("Net margin", "pct"),
    "52W High":        ("52W high",   "price"),
    "52W Low":         ("52W low",    "price"),
    "52W Pos %":       ("52W pos",    "pos"),
    "Avg Volume":      ("Avg vol",    "vol"),
}
SCREENER_COLS = ["Ticker", "Company", "Price", "1D %", "1W %", "1M %", "3M %", "6M %", "1Y %",
                 "Market Cap", "P/E", "Fwd P/E", "PEG", "EPS", "Rev Growth %",
                 "Profit Margin %", "52W Pos %", "Avg Volume"]
SECTOR_COLS   = ["Ticker", "Company", "Price", "1D %", "1M %", "1Y %", "Market Cap", "P/E",
                 "Fwd P/E", "EPS", "52W High", "52W Low", "52W Pos %", "Avg Volume"]
ALL_US_COLS   = ["Ticker", "Company", "Price", "1D %", "1Y %", "Market Cap", "P/E", "Fwd P/E",
                 "EPS", "52W Pos %", "Avg Volume"]

_FMT = {
    "price": Format(precision=2, scheme=Scheme.fixed, group=True).symbol(Symbol.yes).symbol_prefix("$"),
    "pct":   Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive).symbol(Symbol.yes).symbol_suffix("%"),
    "pos":   Format(precision=0, scheme=Scheme.fixed).symbol(Symbol.yes).symbol_suffix("%"),
    "num":   Format(precision=2, scheme=Scheme.fixed, group=True),
    "cap":   Format(precision=1, scheme=Scheme.fixed, group=True).symbol(Symbol.yes)
                 .symbol_prefix("$").symbol_suffix("B"),
    "vol":   Format(precision=1, scheme=Scheme.fixed, group=True).symbol(Symbol.yes).symbol_suffix("M"),
}


def _col_id(src):
    return "c_" + re.sub(r"[^A-Za-z0-9]", "", src)


def _table_columns(srcs):
    cols = []
    for s in srcs:
        name, kind = COL_SPECS[s]
        c = {"name": name, "id": _col_id(s)}
        if kind in _FMT:
            c.update(type="numeric", format=_FMT[kind])
        cols.append(c)
    return cols


def _table_rows(df: pd.DataFrame, srcs) -> list:
    out = []
    for rec in df.to_dict("records"):
        d = {"id": rec.get("Ticker")}
        for s in srcs:
            kind = COL_SPECS[s][1]
            v = rec.get(s)
            if kind in ("ticker", "text"):
                d[_col_id(s)] = str(v) if _ok(v) else ""
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = None
            if v is not None and v == v:
                v = v / 1e9 if kind == "cap" else v / 1e6 if kind == "vol" else v
                d[_col_id(s)] = round(v, 4)
            else:
                d[_col_id(s)] = None
        out.append(d)
    return out


def _table_props(srcs):
    pct_ids = [_col_id(s) for s in srcs if COL_SPECS[s][1] == "pct"]
    cond = []
    for c in pct_ids:
        cond += [{"if": {"filter_query": f"{{{c}}} > 0", "column_id": c}, "color": GREEN},
                 {"if": {"filter_query": f"{{{c}}} < 0", "column_id": c}, "color": RED}]
    return dict(
        sort_action="native",
        style_as_list_view=True,
        style_table={"overflowX": "auto", "minWidth": "100%"},
        style_cell={
            "backgroundColor": SURFACE, "color": TEXT, "fontFamily": FONT,
            "fontSize": "13px", "padding": "10px 12px", "whiteSpace": "nowrap",
            "border": "none", "borderBottom": f"1px solid {GRID}", "textAlign": "right",
        },
        style_header={
            "backgroundColor": SURFACE, "color": MUTED, "fontWeight": "500",
            "fontSize": "12px", "borderBottom": f"1px solid {BORDER}", "borderTop": "none",
        },
        style_cell_conditional=[
            {"if": {"column_id": _col_id("Ticker")}, "textAlign": "left",
             "fontWeight": "700", "color": TEXT},
            {"if": {"column_id": _col_id("Company")}, "textAlign": "left", "color": MUTED,
             "maxWidth": "220px", "overflow": "hidden", "textOverflow": "ellipsis"},
            {"if": {"column_id": _col_id("Sector")}, "textAlign": "left", "color": MUTED},
        ],
        style_header_conditional=[
            {"if": {"column_id": _col_id(s)}, "textAlign": "left"}
            for s in ("Ticker", "Company", "Sector")
        ],
        style_data_conditional=cond + [
            {"if": {"state": "active"}, "backgroundColor": SURFACE_2, "border": "none",
             "borderBottom": f"1px solid {GRID}"},
            {"if": {"state": "selected"}, "backgroundColor": SURFACE_2, "border": "none",
             "borderBottom": f"1px solid {GRID}"},
        ],
    )


def _make_table(df: pd.DataFrame, srcs, id_=None):
    srcs = [s for s in srcs if s in df.columns]
    kw = {"id": id_} if id_ else {}
    return dash_table.DataTable(
        data=_table_rows(df, srcs), columns=_table_columns(srcs),
        page_action="none", **_table_props(srcs), **kw,
    )

# ── App init ──────────────────────────────────────────────────────────────────
app = Dash(
    __name__,
    external_stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap",
    ],
)
app.title = "Screener"

# ── Markets tab ───────────────────────────────────────────────────────────────
markets_tab = html.Div([
    dcc.Store(id="store-market-data"),
    dcc.Store(id="store-mkt-xrange", data=None),
    _page_head("Markets", "US indices, rates and sector performance", [
        html.Div(id="markets-status", className="status"),
        _btn("Refresh", "btn-markets-refresh"),
    ]),
    html.Div(id="div-market-indices", className="grid-indices",
             children=[html.Div(className="idx-card", style={"height": "170px"})
                       for _ in MARKET_INDICES]),
    html.Div([
        _panel([
            dcc.Graph(id="graph-markets-chart", config={"displayModeBar": False},
                      style={"height": "380px"}, figure=_empty_fig("Loading…")),
        ], title="Index performance", sub="% change from start of view · drag to zoom"),
        _panel([
            dcc.Graph(id="graph-sector-bars", config={"displayModeBar": False},
                      style={"height": "380px"}, figure=_empty_fig("Loading…")),
        ], title="Sector performance", sub="SPDR sector ETFs",
           right=_seg("seg-sector-period",
                      [{"label": "1D", "value": "pct1d"}, {"label": "1W", "value": "pct1w"},
                       {"label": "1M", "value": "pct1m"}, {"label": "3M", "value": "pct3m"}],
                      "pct1d")),
    ], className="grid-2"),
])

# ── Compare panel (sticky charts beside the cards) ────────────────────────────
def _compare_panel(prefix, height=250, extra=None):
    return html.Div(_kids(
        _panel([
            html.Div("Change from start of view", className="chart-label"),
            dcc.Graph(id=f"graph-{prefix}normalized", config={"displayModeBar": False},
                      style={"height": f"{height}px"},
                      figure=_empty_fig("Select stocks to compare")),
            html.Div("Price", className="chart-label", style={"marginTop": "8px"}),
            dcc.Graph(id=f"graph-{prefix}price", config={"displayModeBar": False},
                      style={"height": f"{height}px"},
                      figure=_empty_fig("Click any card to chart it")),
        ], title="Compare", sub="Click cards to add or remove · drag a chart to zoom"),
        extra,
    ), className="explore-side")

# ── Screener tab ──────────────────────────────────────────────────────────────
screener_tab = html.Div([
    dcc.Store(id="store-data"),
    dcc.Store(id="store-selected", data=[]),
    dcc.Store(id="store-scr-xrange", data=None),

    _page_head("Screener", "Track a watchlist and compare performance", [
        html.Div(id="status-bar", className="status"),
    ]),

    _panel(html.Div([
        _field("Tickers", dcc.Input(id="input-tickers", type="text", className="inp",
                                    placeholder="AAPL MSFT NVDA — leave blank for tickers.txt",
                                    debounce=False), className="grow"),
        html.Div([html.Div("Watchlist", className="field-label"),
                  dcc.Dropdown(id="dd-watchlist", options=watchlist_options(load_watchlists()),
                               placeholder="Load a list…", clearable=True)],
                 className="field", style={"width": "220px"}),
        html.Div([html.Div("Save as", className="field-label"),
                  html.Div([dcc.Input(id="input-list-name", type="text", className="inp",
                                      placeholder="List name", style={"width": "150px"}),
                            _btn("Save", "btn-save-list"),
                            _btn("Delete", "btn-delete-list", "btn-danger btn-ghost")],
                           style={"display": "flex", "gap": "6px"})],
                 className="field"),
        _field("Period", _seg("dd-period", PERIOD_OPTIONS, "1M")),
        html.Div([_btn("Clear selection", "btn-clear", "btn-ghost"),
                  _btn("Run screener", "btn-run", "btn-primary")],
                 style={"display": "flex", "gap": "8px"}),
    ], className="toolbar"), className="mb"),
    html.Div(id="list-status", className="status", style={"margin": "-6px 0 12px"}),

    html.Div([
        html.Div(id="div-bubbles", className="card-grid",
                 children=[_empty("Press “Run screener” to load your watchlist")]),
        _compare_panel(""),
    ], className="explore"),

    _panel(html.Div(id="div-metrics-table"), title="Fundamentals",
           sub="Click a column header to sort", className="mb"),
    _panel(dcc.Graph(id="graph-treemap", config={"displayModeBar": False},
                     style={"height": "380px"}, figure=_empty_fig("Run the screener to build the map")),
           title="Market map", sub="Sized by market cap · colored by selected period · click to select"),
])

# ── Filter tab ────────────────────────────────────────────────────────────────
def _filter_item(fid, label, unit, yfield, col):
    tag = None
    if not yfield and col not in ALL_MODE_LOCAL:
        tag = html.Span("Watchlist only", className="badge badge-blue")
    return html.Div([
        html.Div(_kids(html.Span(label + (f"  ({unit})" if unit else "")), tag),
                 className="field-label"),
        html.Div([
            dcc.Input(id=f"f-{fid}-min", type="number", placeholder="Min", debounce=False),
            dcc.Input(id=f"f-{fid}-max", type="number", placeholder="Max", debounce=False),
        ], className="range-row"),
    ], className="filter-item field")


def _filter_groups():
    groups = {}
    for fid, label, unit, group, yfield, _s, col in FILTERS:
        groups.setdefault(group, []).append(_filter_item(fid, label, unit, yfield, col))
    return [html.Div([html.Div(g, className="filter-group-title"), *items],
                     className="filter-group") for g, items in groups.items()]


filter_tab = html.Div([
    dcc.Store(id="store-flt-xrange", data=None),
    _page_head("Stock Filter", "Screen NYSE & NASDAQ stocks by fundamentals and performance"),
    html.Div([
        _panel([
            _field("Universe", _seg("filter-universe",
                                    [{"label": "All US stocks", "value": "all"},
                                     {"label": "Watchlist", "value": "watchlist"}], "all")),
            html.Div(_field("Tickers", dcc.Input(id="filter-input-tickers", type="text",
                                                 className="inp",
                                                 placeholder="Blank = tickers.txt")),
                     id="filter-tickers-wrap", className="hidden", style={"marginTop": "12px"}),
            html.Div([html.Div("Presets", className="field-label"),
                      html.Div([html.Button(name, id=f"btn-preset-{k}", n_clicks=0, className="pill")
                                for k, (name, _) in FILTER_PRESETS.items()],
                               className="chip-row")],
                     className="field", style={"margin": "14px 0 6px"}),
            html.Div(className="divider"),
            *_filter_groups(),
            html.Div([_btn("Reset", "btn-filter-reset", "btn-ghost"),
                      _btn("Screen", "btn-filter-run", "btn-primary btn-block")],
                     style={"display": "grid", "gridTemplateColumns": "auto 1fr", "gap": "8px",
                            "marginTop": "8px"}),
        ], title="Filters", className="filter-aside"),

        html.Div([
            _panel([
                html.Div([
                    html.Div([html.Div("Change from start of view", className="chart-label"),
                              dcc.Graph(id="graph-filter-normalized", config={"displayModeBar": False},
                                        style={"height": "280px"},
                                        figure=_empty_fig("Select rows to compare"))]),
                    html.Div([html.Div("Price", className="chart-label"),
                              dcc.Graph(id="graph-filter-price", config={"displayModeBar": False},
                                        style={"height": "280px"},
                                        figure=_empty_fig("Tick a row to chart it"))]),
                ], className="grid-charts"),
            ], title="Compare", sub="Tick rows in the results to chart them",
               right=_btn("Clear selection", "btn-filter-clear", "btn-ghost"), className="mb"),
            _panel([
                dcc.Loading(dash_table.DataTable(
                    id="filter-table", data=[], columns=_table_columns(ALL_US_COLS),
                    row_selectable="multi", selected_rows=[], selected_row_ids=[],
                    page_action="native", page_size=25,
                    **_table_props(SCREENER_COLS),
                ), type="dot", color=ACCENT),
            ], title="Results", right=html.Div(id="filter-status", className="status")),
        ]),
    ], className="filter-layout"),
])

# ── Sectors tab ───────────────────────────────────────────────────────────────
sectors_tab = html.Div([
    dcc.Store(id="store-sector-name",     data=None),
    dcc.Store(id="store-sector-data",     data=None),
    dcc.Store(id="store-sector-selected", data=[]),
    dcc.Store(id="store-sec-xrange",      data=None),

    _page_head("Sectors", "The 20 largest companies in each sector", [
        html.Div(id="sector-status", className="status"),
        _btn("Clear selection", "btn-sector-clear", "btn-ghost"),
    ]),
    html.Div(
        [html.Button([html.Span(label), html.Span("", className="pill-chg")],
                     id={"type": "sector-btn", "sector": yahoo}, n_clicks=0, className="pill")
         for label, yahoo, _ in SECTORS],
        className="chip-row mb",
    ),
    html.Div([
        dcc.Loading(html.Div(id="div-sector-bubbles", className="card-grid",
                             children=[_empty("Pick a sector above")]),
                    type="dot", color=ACCENT, parent_style={"minWidth": 0}),
        _compare_panel("sector-"),
    ], className="explore"),
    _panel(html.Div(id="div-sector-metrics-table"), title="Fundamentals",
           sub="Click a column header to sort"),
])

# ── News tab ──────────────────────────────────────────────────────────────────
news_tab = html.Div([
    dcc.Store(id="store-news-data",     data=None),
    dcc.Store(id="store-news-selected", data=[]),
    dcc.Store(id="store-news-xrange",   data=None),

    _page_head("In the News", "Stocks most mentioned in financial news", [
        dcc.Loading(html.Div(id="news-status", className="status"),
                    type="dot", color=ACCENT),
        _seg("dd-news-hours", [{"label": "24h", "value": 24}, {"label": "48h", "value": 48}], 48),
        _btn("Clear selection", "btn-news-clear", "btn-ghost"),
        _btn("Refresh", "btn-news-refresh"),
    ]),
    html.Div([
        html.Div(id="div-news-bubbles", className="card-grid",
                 children=[_empty("Loading news…")]),
        _compare_panel("news-", height=215,
                       extra=_panel(html.Div(id="div-news-headlines"), title="Headlines",
                                    id="news-headlines-panel", className="panel-grow")),
    ], className="explore"),
])

# ── Analyst tab ───────────────────────────────────────────────────────────────
analyst_tab = html.Div([
    dcc.Store(id="store-an-data",     data=None),
    dcc.Store(id="store-an-selected", data=[]),
    dcc.Store(id="store-an-xrange",   data=None),

    _page_head("Analyst Coverage",
               "Stocks drawing the most Wall Street analyst attention — rating changes, "
               "price targets and analyst headlines", [
        dcc.Loading(html.Div(id="an-status", className="status"), type="dot", color=ACCENT),
        _btn("Refresh", "btn-an-refresh"),
    ]),
    html.Div([
        _field("Time window", _seg("seg-an-window",
                                   [{"label": k, "value": k} for k in ANALYST_WINDOWS], "1M")),
        _field("Rank by", _seg("seg-an-sort", [
            {"label": "Most coverage", "value": "coverage"},
            {"label": "Upgrades",      "value": "upgrades"},
            {"label": "Downgrades",    "value": "downgrades"},
            {"label": "Target upside", "value": "upside"},
        ], "coverage")),
        html.Div(_btn("Clear selection", "btn-an-clear", "btn-ghost"), style={"marginLeft": "auto"}),
    ], className="toolbar mb"),
    html.Div(id="div-an-kpis", className="kpi-row mb"),
    html.Div([
        html.Div(id="div-an-bubbles", className="card-grid",
                 children=[_empty("Loading analyst coverage…")]),
        _compare_panel("an-", height=200, extra=_panel(
            html.Div(id="div-an-detail"),
            right=_seg("seg-an-detail", [{"label": "Headlines", "value": "news"},
                                         {"label": "Analyst actions", "value": "actions"}], "news"),
            title=html.Span(id="an-detail-title"), className="panel-grow")),
    ], className="explore"),
])

# ── Root layout ───────────────────────────────────────────────────────────────
app.layout = html.Div(className="app", children=[
    dcc.Store(id="store-watchlists", data=load_watchlists()),
    dcc.Interval(id="interval-markets", interval=5 * 60 * 1000, n_intervals=0),

    html.Header([
        html.Div([html.Div("S", className="brand-mark"),
                  html.Span("Screener", className="brand-name"),
                  html.Span("Markets terminal", className="brand-sub")], className="brand"),
        html.Div(id="div-ticker-strip", className="ticker-strip"),
        html.Div([html.Span(className="host-dot"), f"{LOCAL_IP}:8050"], className="host"),
    ], className="topbar"),

    dcc.Tabs(
        id="main-tabs", value="tab-markets", mobile_breakpoint=0,
        className="app-tabs", content_className="app-content",
        children=[
            dcc.Tab(label=label, value=value, className="nav-tab",
                    selected_className="nav-tab--selected", children=content)
            for label, value, content in [
                ("Markets",  "tab-markets",  markets_tab),
                ("Screener", "tab-screener", screener_tab),
                ("Filter",   "tab-filter",   filter_tab),
                ("Sectors",  "tab-sectors",  sectors_tab),
                ("News",     "tab-news",     news_tab),
                ("Analysts", "tab-analyst",  analyst_tab),
            ]
        ],
    ),
])

# ── Shared callback helpers ───────────────────────────────────────────────────
def _toggle_from_click(selected, clear_prefix):
    """Selection toggle for pattern-matched card clicks; returns new list or no_update."""
    ctx = callback_context
    if not ctx.triggered:
        return no_update
    trig = ctx.triggered[0]
    selected = list(selected or [])
    if trig["prop_id"].startswith(clear_prefix):
        return []
    if not trig.get("value"):          # cards re-render with n_clicks=0
        return no_update
    try:
        ticker = json.loads(trig["prop_id"].rsplit(".", 1)[0]).get("ticker", "")
    except Exception:
        return no_update
    if not ticker:
        return no_update
    return [t for t in selected if t != ticker] if ticker in selected else selected + [ticker]


# Browser-side: when a chart is zoomed / a range button is clicked, apply the same
# x-range to all charts in the group, re-base % charts to the first visible day,
# and refit the y-axis to the visible window.
_RESCALE_JS = """
function() {
    const IDS = __IDS__, NORM = __NORM__, n = IDS.length;
    const args = Array.from(arguments);
    const NU = window.dash_clientside.no_update;
    const none = Array(n + 1).fill(NU);
    const ctx = window.dash_clientside.callback_context;
    if (!ctx.triggered.length) return none;
    const k = IDS.indexOf(ctx.triggered[0].prop_id.split(".")[0]);
    const rd = args[k], figs = args.slice(n, 2 * n);
    if (k < 0 || !rd || figs.some(f => !f || !f.data || !f.data.length)) return none;

    const ms = s => {
        s = String(s).replace(" ", "T");
        if (s.length <= 10) s += "T00:00:00";
        if (!/(Z|[+-]\\d\\d:\\d\\d)$/.test(s)) s += "Z";
        return Date.parse(s);
    };
    let x0, x1;
    if (rd["xaxis.range[0]"] !== undefined) { x0 = rd["xaxis.range[0]"]; x1 = rd["xaxis.range[1]"]; }
    else if (Array.isArray(rd["xaxis.range"])) { [x0, x1] = rd["xaxis.range"]; }
    else if (rd["xaxis.autorange"]) {
        let lo = null, hi = null;
        figs[0].data.forEach(t => (t.x || []).forEach(x => {
            if (lo === null || x < lo) lo = x;
            if (hi === null || x > hi) hi = x;
        }));
        x0 = lo; x1 = hi;
    } else { return none; }
    if (x0 == null || x1 == null) return none;

    const day = s => String(s).slice(0, 10);
    const same = f => {
        const r = f.layout && f.layout.xaxis && f.layout.xaxis.range;
        return r && day(r[0]) === day(x0) && day(r[1]) === day(x1);
    };
    if (figs.every(same)) return none;      // loop guard

    const a = ms(x0), b = ms(x1);
    const pad = (lo, hi) => {
        if (lo === null) return null;
        const p = Math.max((hi - lo) * 0.08, Math.abs(hi) * 0.005, (hi - lo) < 1 ? 0.5 : 0);
        return [lo - p, hi + p];
    };
    const out = figs.map((fig, i) => {
        const f = JSON.parse(JSON.stringify(fig));
        let lo = null, hi = null;
        f.data.forEach(t => {
            const xs = t.x || [];
            if (NORM[i] && t.customdata) {
                let i0 = xs.findIndex(x => ms(x) >= a);
                if (i0 < 0) i0 = xs.length - 1;
                const base = t.customdata[i0];
                if (base) t.y = t.customdata.map(c => (c / base - 1) * 100);
            }
            xs.forEach((x, j) => {
                const m = ms(x), y = t.y[j];
                if (m >= a && m <= b && y != null) {
                    if (lo === null || y < lo) lo = y;
                    if (hi === null || y > hi) hi = y;
                }
            });
        });
        f.layout.xaxis = Object.assign({}, f.layout.xaxis, {range: [x0, x1], autorange: false});
        const yr = pad(lo, hi);
        if (yr) f.layout.yaxis = Object.assign({}, f.layout.yaxis, {range: yr, autorange: false});
        return f;
    });
    out.push([x0, x1]);
    return out;
}
"""


def _register_rescale(graph_ids, norm_flags, store_id):
    js = (_RESCALE_JS.replace("__IDS__", json.dumps(graph_ids))
                     .replace("__NORM__", json.dumps(norm_flags)))
    app.clientside_callback(
        js,
        *[Output(g, "figure", allow_duplicate=True) for g in graph_ids],
        Output(store_id, "data"),
        *[Input(g, "relayoutData") for g in graph_ids],
        *[State(g, "figure") for g in graph_ids],
        prevent_initial_call=True,
    )


_register_rescale(["graph-markets-chart"], [True], "store-mkt-xrange")
_register_rescale(["graph-normalized", "graph-price"], [True, False], "store-scr-xrange")
_register_rescale(["graph-filter-normalized", "graph-filter-price"], [True, False], "store-flt-xrange")
_register_rescale(["graph-sector-normalized", "graph-sector-price"], [True, False], "store-sec-xrange")
_register_rescale(["graph-news-normalized", "graph-news-price"], [True, False], "store-news-xrange")
_register_rescale(["graph-an-normalized", "graph-an-price"], [True, False], "store-an-xrange")

# ── MARKETS CALLBACKS ─────────────────────────────────────────────────────────
def _index_card(idx, info):
    sym = idx["symbol"]
    p1d, p1w, p1m = info.get("pct1d"), info.get("pct1w"), info.get("pct1m")
    chg = info.get("chg")
    src = _spark_src(info.get("spark"), 220, 44, stretch=True)
    return html.Div(_kids(
        html.Div(idx["name"], className="idx-name"),
        html.Div(_fmt_idx(info.get("price"), sym), className="idx-price"),
        html.Div([html.Span(f"{chg:+,.2f}" if _ok(chg) else "—", className=_tone(chg)),
                  _chip(p1d)], className="idx-chg"),
        html.Img(src=src, className="idx-spark") if src else html.Div(style={"height": "60px"}),
        html.Div([html.Span(["1W", html.B(_pct(p1w), className=_tone(p1w))]),
                  html.Span(["1M", html.B(_pct(p1m), className=_tone(p1m))])],
                 className="idx-foot"),
    ), className="idx-card")


@app.callback(
    Output("div-market-indices",  "children"),
    Output("graph-markets-chart", "figure"),
    Output("store-market-data",   "data"),
    Output("markets-status",      "children"),
    Output("div-ticker-strip",    "children"),
    Input("interval-markets",     "n_intervals"),
    Input("btn-markets-refresh",  "n_clicks"),
    State("store-mkt-xrange",     "data"),
)
def load_market_data(_ni, _nr, xrange):
    mdata, hist_df = fetch_market_snapshot()
    ts = pd.Timestamp.now().strftime("%I:%M %p").lstrip("0")
    cards = [_index_card(x, mdata.get(x["symbol"], {})) for x in MARKET_INDICES]

    names  = {x["symbol"]: x["name"] for x in MARKET_INDICES}
    series = {s: _clean_series(hist_df[s]) for s in CHART_INDICES
              if not hist_df.empty and s in hist_df.columns}
    chart, _ = _compare_figs(series, CHART_INDICES, xrange, default_months=3,
                             with_price=False, names=names)

    strip = []
    for x in MARKET_INDICES:
        info = mdata.get(x["symbol"], {})
        strip.append(html.Div([
            html.Span(x["name"], className="strip-name"),
            html.Span(_fmt_idx(info.get("price"), x["symbol"]), className="strip-val"),
            html.Span(_pct(info.get("pct1d")), className=_cx("strip-chg", _tone(info.get("pct1d")))),
        ], className="strip-item"))
    return cards, chart, mdata, f"Updated {ts}", strip


@app.callback(
    Output("graph-sector-bars", "figure"),
    Input("store-market-data",  "data"),
    Input("seg-sector-period",  "value"),
)
def update_sector_bars(mdata, key):
    if not mdata:
        return _empty_fig("Loading…")
    return _sector_bars_fig(mdata, key or "pct1d")

# ── SCREENER CALLBACKS ────────────────────────────────────────────────────────

@app.callback(
    Output("store-data",     "data"),
    Output("store-selected", "data", allow_duplicate=True),
    Output("status-bar",     "children"),
    Input("btn-run",         "n_clicks"),
    State("input-tickers",   "value"),
    prevent_initial_call=True,
)
def run_screener(_, ticker_input):
    tickers = _parse_tickers(ticker_input) or load_tickers()
    rows = []
    for i, sym in enumerate(tickers):
        row = fetch_ticker(sym)
        if row:
            rows.append(row)
        if i < len(tickers) - 1:
            time.sleep(0.3)
    if not rows:
        return no_update, no_update, html.Span("No data retrieved", className="status-warn")
    df = pd.DataFrame(rows)
    ts = pd.Timestamp.now().strftime("%I:%M %p").lstrip("0")
    return df.to_json(orient="records"), [], f"{len(rows)} stocks · updated {ts}"


@app.callback(
    Output("store-watchlists",  "data"),
    Output("dd-watchlist",      "options"),
    Output("list-status",       "children"),
    Output("input-tickers",     "value"),
    Input("btn-save-list",      "n_clicks"),
    Input("btn-delete-list",    "n_clicks"),
    Input("dd-watchlist",       "value"),
    State("input-list-name",    "value"),
    State("input-tickers",      "value"),
    State("store-watchlists",   "data"),
    prevent_initial_call=True,
)
def manage_watchlists(_, __, sel, name, ticker_input, lists):
    ctx = callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update, no_update
    trigger = ctx.triggered[0]["prop_id"]
    lists = lists or {}
    warn = lambda m: html.Span(m, className="status-warn")
    if "btn-save-list" in trigger:
        n = (name or "").strip()
        if not n:
            return no_update, no_update, warn("Enter a list name to save"), no_update
        tickers = _parse_tickers(ticker_input)
        if not tickers:
            return no_update, no_update, warn("Add some tickers first"), no_update
        lists[n] = tickers
        save_watchlists(lists)
        return lists, watchlist_options(lists), f"Saved “{n}” ({len(tickers)} tickers)", no_update
    if "btn-delete-list" in trigger:
        if not sel or sel == "__default__":
            return no_update, no_update, warn("Select a saved list to delete"), no_update
        lists.pop(sel, None)
        save_watchlists(lists)
        return lists, watchlist_options(lists), f"Deleted “{sel}”", no_update
    if "dd-watchlist" in trigger:
        # a cleared dropdown (user cleared it, or its list was just deleted) loads nothing
        if not sel:
            return no_update, no_update, no_update, no_update
        if sel == "__default__":
            return no_update, no_update, "Loaded tickers.txt", " ".join(load_tickers())
        return no_update, no_update, f"Loaded “{sel}”", " ".join(lists.get(sel, []))
    return no_update, no_update, no_update, no_update


@app.callback(
    Output("store-selected", "data"),
    Input("btn-clear",  "n_clicks"),
    Input({"type": "bubble", "ticker": ALL}, "n_clicks"),
    Input("graph-treemap", "clickData"),
    State("store-selected", "data"),
    prevent_initial_call=True,
)
def update_selection(_, _b, treemap_click, selected):
    ctx = callback_context
    if ctx.triggered and ctx.triggered[0]["prop_id"].startswith("graph-treemap"):
        pts = (treemap_click or {}).get("points", [])
        # sector tiles have an empty parent; only leaf (ticker) tiles toggle selection
        if pts and pts[0].get("parent"):
            label = pts[0].get("label", "")
            selected = list(selected or [])
            return [t for t in selected if t != label] if label in selected else selected + [label]
        return no_update
    return _toggle_from_click(selected, "btn-clear")


@app.callback(
    Output("div-bubbles", "children"),
    Input("store-data",     "data"),
    Input("store-selected", "data"),
    Input("dd-period",      "value"),
)
def update_bubbles(store_json, selected, period):
    if not store_json:
        return [_empty("Press “Run screener” to load your watchlist")]
    df  = pd.read_json(io.StringIO(store_json), orient="records")
    sel = selected or []
    cards = []
    for rec in df.to_dict("records"):
        t = rec["Ticker"]
        pp = rec.get(f"{period} %")
        stats = [] if period == "1D" else [(period, _pct(pp), _tone(pp))]
        stats.append(("Cap", _large(rec.get("Market Cap")), ""))
        cards.append(_quote_card(
            t, "bubble", _sel_color(t, sel), company=rec.get("Company", ""),
            price=rec.get("Price"), change=rec.get("1D %"), spark=rec.get("Spark"),
            stats=stats,
        ))
    return cards


@app.callback(
    Output("graph-normalized", "figure"),
    Output("graph-price",      "figure"),
    Input("store-selected",    "data"),
    State("store-scr-xrange",  "data"),
    prevent_initial_call=True,
)
def update_charts(selected, xrange):
    return _build_compare_charts(selected or [], xrange)


@app.callback(
    Output("graph-treemap", "figure"),
    Input("store-data",     "data"),
    Input("dd-period",      "value"),
)
def update_treemap(store_json, period):
    if not store_json:
        return _empty_fig("Run the screener to build the map")
    return _treemap_fig(pd.read_json(io.StringIO(store_json), orient="records"), period)


@app.callback(
    Output("div-metrics-table", "children"),
    Input("store-data", "data"),
)
def update_metrics_table(store_json):
    if not store_json:
        return _empty("No data yet")
    df = pd.read_json(io.StringIO(store_json), orient="records")
    return _make_table(df, SCREENER_COLS)

# ── FILTER CALLBACKS ──────────────────────────────────────────────────────────

@app.callback(
    Output("filter-tickers-wrap", "className"),
    Input("filter-universe", "value"),
)
def toggle_filter_universe(universe):
    return "hidden" if universe == "all" else ""


@app.callback(
    *[Output(f"f-{fid}-min", "value") for fid in FILTER_IDS],
    *[Output(f"f-{fid}-max", "value") for fid in FILTER_IDS],
    Input("btn-filter-reset", "n_clicks"),
    *[Input(f"btn-preset-{k}", "n_clicks") for k in FILTER_PRESETS],
    prevent_initial_call=True,
)
def apply_filter_preset(*_):
    trig = callback_context.triggered[0]["prop_id"] if callback_context.triggered else ""
    vals = {}
    for k, (_name, preset) in FILTER_PRESETS.items():
        if trig.startswith(f"btn-preset-{k}."):
            vals = preset
    mins = [vals.get(f, (None, None))[0] for f in FILTER_IDS]
    maxs = [vals.get(f, (None, None))[1] for f in FILTER_IDS]
    return (*mins, *maxs)


@app.callback(
    Output("filter-table",  "data"),
    Output("filter-table",  "columns"),
    Output("filter-table",  "selected_rows"),
    Output("filter-table",  "selected_row_ids"),
    Output("filter-status", "children"),
    Input("btn-filter-run", "n_clicks"),
    State("filter-universe",      "value"),
    State("filter-input-tickers", "value"),
    *[State(f"f-{fid}-min", "value") for fid in FILTER_IDS],
    *[State(f"f-{fid}-max", "value") for fid in FILTER_IDS],
    prevent_initial_call=True,
)
def run_filter(_, universe, ticker_input, *filter_vals):
    mins = dict(zip(FILTER_IDS, filter_vals[:len(FILTER_IDS)]))
    maxs = dict(zip(FILTER_IDS, filter_vals[len(FILTER_IDS):]))
    ts   = pd.Timestamp.now().strftime("%I:%M %p").lstrip("0")
    warn = lambda m: html.Span(m, className="status-warn")

    if universe == "all":
        df = yahoo_screen(build_yahoo_operands(mins, maxs), max_results=1000)
        if df.empty:
            return [], no_update, [], [], warn("No results from Yahoo — loosen filters or retry")
        df, ignored = _apply_local_filters(df, mins, maxs, skip_yahoo=True)
        cols = [c for c in ALL_US_COLS if c in df.columns]
        msg = f"{len(df):,} matches · sorted by market cap · {ts}"
    else:
        tickers = _parse_tickers(ticker_input) or load_tickers()
        rows = []
        for i, sym in enumerate(tickers):
            row = fetch_ticker(sym)
            if row:
                rows.append(row)
            if i < len(tickers) - 1:
                time.sleep(0.3)
        if not rows:
            return [], no_update, [], [], warn("No data retrieved")
        df = pd.DataFrame(rows)
        before = len(df)
        df, ignored = _apply_local_filters(df, mins, maxs, skip_yahoo=False)
        cols = [c for c in SCREENER_COLS if c in df.columns]
        msg = f"{len(df)} of {before} passed · {ts}"
    if ignored:
        msg += f" · not available here: {', '.join(ignored)}"
    return _table_rows(df, cols), _table_columns(cols), [], [], msg


@app.callback(
    Output("filter-table", "selected_rows",    allow_duplicate=True),
    Output("filter-table", "selected_row_ids", allow_duplicate=True),
    Input("btn-filter-clear", "n_clicks"),
    prevent_initial_call=True,
)
def clear_filter_selection(_):
    return [], []


@app.callback(
    Output("graph-filter-normalized", "figure"),
    Output("graph-filter-price",      "figure"),
    Input("filter-table",     "selected_row_ids"),
    State("store-flt-xrange", "data"),
    prevent_initial_call=True,
)
def update_filter_charts(selected, xrange):
    if not selected:
        return _empty_fig("Select rows to compare"), _empty_fig("Tick a row to chart it")
    return _build_compare_charts(list(selected), xrange)

# ── SECTOR CALLBACKS ──────────────────────────────────────────────────────────

@app.callback(
    Output("store-sector-name", "data"),
    Output("store-sector-data", "data"),
    Output("store-sector-selected", "data", allow_duplicate=True),
    Output("sector-status",     "children"),
    Input({"type": "sector-btn", "sector": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def run_sector_screen(_clicks):
    ctx = callback_context
    if not ctx.triggered or not ctx.triggered[0].get("value"):
        return no_update, no_update, no_update, no_update
    try:
        sector = json.loads(ctx.triggered[0]["prop_id"].rsplit(".", 1)[0]).get("sector", "")
    except Exception:
        return no_update, no_update, no_update, no_update
    if not sector:
        return no_update, no_update, no_update, no_update
    df = yahoo_screen([{"operator": "EQ", "operands": ["sector", sector]}], max_results=20)
    if df.empty:
        return sector, None, [], html.Span(f"No results for {sector} — try again",
                                           className="status-warn")
    hists = get_histories_1y(df["Ticker"].tolist())
    df["1M %"]  = [_pct_back(hists.get(t), 21) for t in df["Ticker"]]
    df["Spark"] = [[round(float(v), 4) for v in hists[t].iloc[-22:]] if t in hists else []
                   for t in df["Ticker"]]
    ts = pd.Timestamp.now().strftime("%I:%M %p").lstrip("0")
    return sector, df.to_json(orient="records"), [], f"Top {len(df)} by market cap · {ts}"


@app.callback(
    Output({"type": "sector-btn", "sector": ALL}, "className"),
    Output({"type": "sector-btn", "sector": ALL}, "children"),
    Input("store-sector-name", "data"),
    Input("store-market-data", "data"),
    State({"type": "sector-btn", "sector": ALL}, "id"),
)
def update_sector_pills(selected, mdata, ids):
    labels = {yahoo: label for label, yahoo, _ in SECTORS}
    classes, children = [], []
    for bid in ids:
        sec = bid["sector"]
        pct = ((mdata or {}).get(SECTOR_ETF.get(sec)) or {}).get("pct1d")
        classes.append(_cx("pill", "is-active" if sec == selected else ""))
        children.append([html.Span(labels.get(sec, sec)),
                         html.Span(_pct(pct) if _ok(pct) else "",
                                   className=_cx("pill-chg", _tone(pct)))])
    return classes, children


@app.callback(
    Output("store-sector-selected", "data"),
    Input("btn-sector-clear", "n_clicks"),
    Input({"type": "sector-bubble", "ticker": ALL}, "n_clicks"),
    State("store-sector-selected", "data"),
    prevent_initial_call=True,
)
def update_sector_selection(_, _b, selected):
    return _toggle_from_click(selected, "btn-sector-clear")


@app.callback(
    Output("div-sector-bubbles",       "children"),
    Output("div-sector-metrics-table", "children"),
    Input("store-sector-data",         "data"),
    Input("store-sector-selected",     "data"),
)
def update_sector_display(store_json, selected):
    if not store_json:
        return [_empty("Pick a sector above")], _empty("No sector selected")
    df  = pd.read_json(io.StringIO(store_json), orient="records")
    sel = selected or []
    cards = []
    for rec in df.to_dict("records"):
        t = rec["Ticker"]
        m1 = rec.get("1M %")
        cards.append(_quote_card(
            t, "sector-bubble", _sel_color(t, sel), company=rec.get("Company", ""),
            price=rec.get("Price"), change=rec.get("1D %"), spark=rec.get("Spark"),
            stats=[("1M", _pct(m1), _tone(m1)), ("Cap", _large(rec.get("Market Cap")), "")],
        ))
    return cards, _make_table(df, SECTOR_COLS)


@app.callback(
    Output("graph-sector-normalized", "figure"),
    Output("graph-sector-price",      "figure"),
    Input("store-sector-selected",    "data"),
    State("store-sec-xrange",         "data"),
    prevent_initial_call=True,
)
def update_sector_charts(selected, xrange):
    return _build_compare_charts(selected or [], xrange)

# ── NEWS CALLBACKS ────────────────────────────────────────────────────────────

@app.callback(
    Output("store-news-data", "data"),
    Output("news-status",     "children"),
    Input("main-tabs",        "value"),
    Input("btn-news-refresh", "n_clicks"),
    Input("dd-news-hours",    "value"),
    State("store-news-data",  "data"),
    prevent_initial_call=True,
)
def load_news(tab, _refresh, hours, current):
    trigger = callback_context.triggered[0]["prop_id"] if callback_context.triggered else ""
    if trigger.startswith("main-tabs") and (tab != "tab-news" or current):
        return no_update, no_update
    force = trigger.startswith("btn-news-refresh")
    rows, n_articles = build_news_trending(int(hours or 48), force=force)
    ts = pd.Timestamp.now().strftime("%I:%M %p").lstrip("0")
    if not rows:
        return [], html.Span(f"No tickers found in {n_articles} articles", className="status-warn")
    return rows, f"{len(rows)} stocks from {n_articles:,} articles · {ts}"


@app.callback(
    Output("store-news-selected", "data"),
    Input("btn-news-clear", "n_clicks"),
    Input({"type": "news-bubble", "ticker": ALL}, "n_clicks"),
    State("store-news-selected", "data"),
    prevent_initial_call=True,
)
def update_news_selection(_, _clicks, selected):
    return _toggle_from_click(selected, "btn-news-clear")


@app.callback(
    Output("div-news-bubbles", "children"),
    Input("store-news-data",     "data"),
    Input("store-news-selected", "data"),
)
def update_news_bubbles(rows, selected):
    if rows is None:
        return [_empty("Loading news…")]
    if not rows:
        return [_empty("No trending stocks found", warn=True)]
    sel = selected or []
    cards = []
    for r in rows:
        n = r.get("Mentions", 0)
        heads = r.get("Headlines") or []
        cards.append(_quote_card(
            r["Ticker"], "news-bubble", _sel_color(r["Ticker"], sel),
            company=r.get("Company", ""), price=r.get("Price"), change=r.get("1D %"),
            spark=r.get("Spark"), badge="HOT" if r.get("Trending") else None,
            stats=[("1M", _pct(r.get("1M %")), _tone(r.get("1M %"))),
                   ("", f"{n} article{'s' if n != 1 else ''}", "")],
            note=heads[0]["title"] if heads else None,
        ))
    return cards


@app.callback(
    Output("graph-news-normalized", "figure"),
    Output("graph-news-price",      "figure"),
    Input("store-news-selected",    "data"),
    State("store-news-xrange",      "data"),
    prevent_initial_call=True,
)
def update_news_charts(selected, xrange):
    return _build_compare_charts(selected or [], xrange)


@app.callback(
    Output("div-news-headlines", "children"),
    Input("store-news-data",     "data"),
    Input("store-news-selected", "data"),
)
def update_news_headlines(rows, selected):
    if not rows:
        return _empty("No headlines yet")
    sel  = set(selected or [])
    pool, seen = [], set()
    for r in rows:
        if sel and r["Ticker"] not in sel:
            continue
        for h in r["Headlines"]:
            if h["link"] not in seen:
                seen.add(h["link"])
                pool.append(h)
    pool.sort(key=lambda h: h["time"], reverse=True)
    return _headline_items(pool, sel)


# ── ANALYST CALLBACKS ─────────────────────────────────────────────────────────

def _kpi(label, value, tone=""):
    return html.Div([html.Div(label, className="kpi-label"),
                     html.Div(value, className=_cx("kpi-value", tone))], className="kpi")


@app.callback(
    Output("store-an-data", "data"),
    Output("an-status",     "children"),
    Output("div-an-kpis",   "children"),
    Input("main-tabs",      "value"),
    Input("btn-an-refresh", "n_clicks"),
    Input("seg-an-window",  "value"),
    Input("seg-an-sort",    "value"),
    State("store-an-data",  "data"),
    prevent_initial_call=True,
)
def load_analyst(tab, _refresh, window, sort, current):
    trigger = callback_context.triggered[0]["prop_id"] if callback_context.triggered else ""
    if trigger.startswith("main-tabs") and (tab != "tab-analyst" or current is not None):
        return no_update, no_update, no_update
    force   = trigger.startswith("btn-an-refresh")
    records = load_analyst_data(force=force)
    if not records:
        return [], html.Span("Couldn’t load analyst data — try Refresh", className="status-warn"), []
    if force:
        _ticker_news_cache.pop("__analyst__", None)
    heads = fetch_analyst_headlines()
    rows, tot = analyst_window(records, window or "1M", sort or "coverage", heads)

    hists = get_histories_1y([r["Ticker"] for r in rows])
    for r in rows:
        ser = hists.get(r["Ticker"])
        r["Spark"] = [round(float(v), 4) for v in ser.iloc[-22:]] if ser is not None else []
        r["1M %"]  = _pct_back(ser, 21)

    newest = max((h["t"] for rec in records for h in rec["history"]), default=0)
    as_of  = time.strftime("%I:%M %p", time.localtime(_analyst["ts"])).lstrip("0")
    status = (f"{len(records)} stocks tracked · Yahoo rating history through "
              f"{_fmt_date(newest)} · fetched {as_of}" if newest else "")
    kpis = [
        _kpi("Stocks with activity", f"{tot['stocks']:,}"),
        _kpi("Rating actions",       f"{tot['actions']:,}"),
        _kpi("Upgrades",             f"{tot['up']:,}",   "up"),
        _kpi("Downgrades",           f"{tot['down']:,}", "down"),
        _kpi("Initiations",          f"{tot['init']:,}"),
        _kpi("Analyst headlines",    f"{tot['heads']:,}"),
    ]
    return rows, status, kpis


@app.callback(
    Output("store-an-selected", "data"),
    Input("btn-an-clear", "n_clicks"),
    Input({"type": "an-bubble", "ticker": ALL}, "n_clicks"),
    State("store-an-selected", "data"),
    prevent_initial_call=True,
)
def update_an_selection(_, _clicks, selected):
    return _toggle_from_click(selected, "btn-an-clear")


@app.callback(
    Output("div-an-bubbles",   "children"),
    Input("store-an-data",     "data"),
    Input("store-an-selected", "data"),
)
def update_an_bubbles(rows, selected):
    if rows is None:
        return [_empty("Loading analyst coverage…")]
    if not rows:
        return [_empty("No analyst activity in this window — try a longer one", warn=True)]
    sel = selected or []
    cards = []
    for r in rows:
        stats = [("", f"{r['n']} action{'s' if r['n'] != 1 else ''}", "")] if r["n"] else []
        if r["ups"] or r["downs"]:
            stats.append(("", f"▲{r['ups']} ▼{r['downs']}",
                          "up" if r["ups"] > r["downs"] else "down" if r["downs"] > r["ups"] else ""))
        if r["heads"]:
            stats.append(("", f"{r['heads']} news", ""))
        cards.append(_quote_card(
            r["Ticker"], "an-bubble", _sel_color(r["Ticker"], sel),
            company=r.get("Company", ""), price=r.get("Price"), change=r.get("1D %"),
            spark=r.get("Spark"), stats=stats, extra=_rating_block(r),
            note=_action_note(r["actions"][0]) if r["actions"] else None,
        ))
    return cards


@app.callback(
    Output("graph-an-normalized", "figure"),
    Output("graph-an-price",      "figure"),
    Input("store-an-selected",    "data"),
    State("store-an-xrange",      "data"),
    prevent_initial_call=True,
)
def update_an_charts(selected, xrange):
    return _build_compare_charts(selected or [], xrange)


@app.callback(
    Output("div-an-detail",     "children"),
    Output("an-detail-title",   "children"),
    Input("store-an-selected",  "data"),
    Input("seg-an-detail",      "value"),
    Input("store-an-data",      "data"),
)
def update_an_detail(selected, mode, rows):
    sel = selected or []
    if mode == "actions":
        by = {r["Ticker"]: r for r in rows or []}
        tickers = [t for t in sel if t in by] or list(by)
        acts = sorted(({**a, "ticker": t} for t in tickers for a in by[t]["actions"]),
                      key=lambda a: a["t"], reverse=True)
        title = "Analyst actions" + (f" · {', '.join(sel)}" if sel else " · latest")
        return _action_items(acts, show_ticker=len(tickers) > 1), title
    if sel:
        with ThreadPoolExecutor(max_workers=4) as pool:
            batches = list(pool.map(fetch_ticker_news, sel))
        seen, arts = set(), []
        for b in batches:
            for h in b:
                if h["link"] not in seen:
                    seen.add(h["link"])
                    arts.append(h)
        arts.sort(key=lambda h: h["time"], reverse=True)
        return _headline_items(arts, sel), f"Headlines · {', '.join(sel)}"
    return _headline_items(fetch_analyst_headlines()), "Analyst headlines"


def _warm_caches():
    try:
        load_analyst_data()
        fetch_analyst_headlines()
    except Exception as e:
        print(f"Cache warm-up: {e}")


if __name__ == "__main__":
    threading.Thread(target=_warm_caches, daemon=True).start()
    print(f"\n  Open on this machine : http://localhost:8050")
    print(f"  Open on phone/other  : http://{LOCAL_IP}:8050\n")
    app.run(debug=False, host="0.0.0.0", port=8050)
