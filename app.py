import io
import json
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
import plotly.graph_objects as go
import plotly.express as px
from dash import Dash, dcc, html, dash_table, Input, Output, State, callback_context, no_update, ALL
import dash_bootstrap_components as dbc
import yfinance as yf

from screener import fetch_ticker, load_tickers

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
WATCHLISTS_FILE = os.path.join(SCRIPT_DIR, "watchlists.json")

# ── Palette ───────────────────────────────────────────────────────────────────
BG     = "#070b12"
PANEL  = "#0c1220"
BORDER = "#1e3a5a"
CYAN   = "#00e5ff"
GREEN  = "#00ff99"
RED    = "#ff2255"
AMBER  = "#ffb800"
TEXT   = "#eaf4ff"
MUTED  = "#8ec8e8"   # brighter than before
SEL_BG = "#041828"
FONT   = "'Courier New', 'Consolas', monospace"

# ── Market constants ──────────────────────────────────────────────────────────
MARKET_INDICES = [
    {"symbol": "^GSPC", "label": "S&P 500",     "short": "S&P 500"},
    {"symbol": "^IXIC", "label": "NASDAQ",       "short": "NASDAQ"},
    {"symbol": "^DJI",  "label": "DOW JONES",    "short": "DOW"},
    {"symbol": "^RUT",  "label": "RUSSELL 2000", "short": "RUSSELL"},
    {"symbol": "^VIX",  "label": "VOLATILITY",   "short": "VIX"},
    {"symbol": "^TNX",  "label": "10Y YIELD",    "short": "10Y YIELD"},
]
MARKET_SECTORS = [
    {"symbol": "XLK",  "label": "TECHNOLOGY"},
    {"symbol": "XLF",  "label": "FINANCIALS"},
    {"symbol": "XLE",  "label": "ENERGY"},
    {"symbol": "XLV",  "label": "HEALTH CARE"},
    {"symbol": "XLI",  "label": "INDUSTRIALS"},
    {"symbol": "XLC",  "label": "COMM SERVICES"},
    {"symbol": "XLY",  "label": "CONS DISCRET"},
    {"symbol": "XLP",  "label": "CONS STAPLES"},
    {"symbol": "XLRE", "label": "REAL ESTATE"},
    {"symbol": "XLB",  "label": "MATERIALS"},
    {"symbol": "XLU",  "label": "UTILITIES"},
]

SECTOR_DEFINITIONS = [
    {"label": "TECHNOLOGY",     "yahoo": "Technology"},
    {"label": "FINANCIALS",     "yahoo": "Financial Services"},
    {"label": "ENERGY",         "yahoo": "Energy"},
    {"label": "HEALTH CARE",    "yahoo": "Healthcare"},
    {"label": "INDUSTRIALS",    "yahoo": "Industrials"},
    {"label": "COMM SERVICES",  "yahoo": "Communication Services"},
    {"label": "CONS DISCRET",   "yahoo": "Consumer Cyclical"},
    {"label": "CONS STAPLES",   "yahoo": "Consumer Defensive"},
    {"label": "REAL ESTATE",    "yahoo": "Real Estate"},
    {"label": "MATERIALS",      "yahoo": "Basic Materials"},
    {"label": "UTILITIES",      "yahoo": "Utilities"},
]

PERIOD_OPTIONS = [
    {"label": "1D", "value": "1D"}, {"label": "1W", "value": "1W"},
    {"label": "1M", "value": "1M"}, {"label": "3M", "value": "3M"},
    {"label": "6M", "value": "6M"}, {"label": "1Y", "value": "1Y"},
]
PERIOD_DAYS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}
HIST_WINDOW = {"1D": "5d", "1W": "1mo", "1M": "3mo", "3M": "6mo", "6M": "1y", "1Y": "2y"}
CHART_COLORS = [
    CYAN, "#ff6b35", "#a855f7", "#fbbf24", "#00ff99",
    "#f87171", "#60a5fa", "#fb923c", "#4ade80", "#e879f9",
    "#f472b6", "#38bdf8",
]

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
YAHOO_FIELD_MAP = {
    "pe":     ("trailingpe",               1),
    "fpe":    ("forwardpe",                1),
    "peg":    ("pegRatio",                 1),
    "eps":    ("epsTrailingTwelveMonths",  1),
    "revgr":  ("revenueGrowth",            0.01),
    "margin": ("profitMargins",            0.01),
    "mcap":   ("marketcap",                1e9),
    "vol":    ("averageDailyVolume3Month", 1e6),
}

def yahoo_screen(operands: list, max_results: int = 500) -> pd.DataFrame:
    # Yahoo expects uppercase operators; topOperator is not a valid field
    base = [
        {"operator": "EQ", "operands": ["region", "us"]},
        {"operator": "EQ", "operands": ["quoteType", "EQUITY"]},
    ]
    all_quotes = []
    batch = 250
    for offset in range(0, max_results, batch):
        payload = {
            "offset": offset,
            "size": min(batch, max_results - offset),
            "sortField": "marketcap",
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
        "pegRatio": "PEG", "epsTrailingTwelveMonths": "EPS",
        "revenueGrowth": "_revFrac", "profitMargins": "_marginFrac",
        "averageDailyVolume3Month": "Avg Volume", "regularMarketVolume": "Volume",
        "fiftyTwoWeekHigh": "52W High", "fiftyTwoWeekLow": "52W Low",
        "sector": "Sector",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "_revFrac" in df.columns:
        df["Rev Growth %"] = df["_revFrac"] * 100
        df.drop(columns=["_revFrac"], inplace=True)
    if "_marginFrac" in df.columns:
        df["Profit Margin %"] = df["_marginFrac"] * 100
        df.drop(columns=["_marginFrac"], inplace=True)
    return df

def build_yahoo_operands(mins: dict, maxs: dict) -> list:
    ops = []
    for fid, (yfield, scale) in YAHOO_FIELD_MAP.items():
        lo, hi = mins.get(fid), maxs.get(fid)
        if lo is not None:
            ops.append({"operator": "GT", "operands": [yfield, float(lo) * scale]})
        if hi is not None:
            ops.append({"operator": "LT", "operands": [yfield, float(hi) * scale]})
    return ops

# ── Market snapshot (bulk yf.download) ───────────────────────────────────────
def fetch_market_snapshot():
    all_syms = [x["symbol"] for x in MARKET_INDICES + MARKET_SECTORS]
    hist_df  = pd.DataFrame()
    try:
        raw = yf.download(all_syms, period="3mo", progress=False, auto_adjust=True)
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = raw.columns.get_level_values(0).unique()
            key    = "Close" if "Close" in level0 else (level0[0] if len(level0) else None)
            hist_df = raw[key] if key else pd.DataFrame()
        elif "Close" in raw.columns:
            hist_df = raw[["Close"]].rename(columns={"Close": all_syms[0]})
    except Exception as e:
        print(f"Market download error: {e}")

    rows = {}
    for sym in all_syms:
        try:
            ser = (hist_df[sym].dropna()
                   if (not hist_df.empty and sym in hist_df.columns)
                   else pd.Series(dtype=float))
            if len(ser) == 0:
                rows[sym] = {}
                continue
            price = float(ser.iloc[-1])
            pct1d = float((ser.iloc[-1] - ser.iloc[-2]) / ser.iloc[-2] * 100) if len(ser) >= 2 else None
            pct1w = float((ser.iloc[-1] - ser.iloc[-6]) / ser.iloc[-6] * 100) if len(ser) >= 6 else None
            pct1m = float((ser.iloc[-1] - ser.iloc[-22]) / ser.iloc[-22] * 100) if len(ser) >= 22 else None
            rows[sym] = {"price": price, "pct1d": pct1d, "pct1w": pct1w, "pct1m": pct1m}
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
    return [{"label": "── Default (tickers.txt) ──", "value": "__default__"}] + \
           [{"label": n, "value": n} for n in lists]

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

# ── Style helpers ─────────────────────────────────────────────────────────────
def _inp(extra=None):
    s = {"backgroundColor": PANEL, "color": TEXT, "border": f"1px solid {BORDER}",
         "borderRadius": "3px", "fontFamily": FONT, "fontSize": "12px", "outline": "none"}
    if extra:
        s.update(extra)
    return s

def _btn(label, id_, color=CYAN, extra=None):
    return html.Button(label, id=id_, n_clicks=0, style={
        "height": "32px", "padding": "0 14px", "cursor": "pointer",
        "background": "transparent", "border": f"1px solid {color}",
        "color": color, "fontFamily": FONT, "fontSize": "10px",
        "letterSpacing": "1.5px", "borderRadius": "3px", "whiteSpace": "nowrap",
        **(extra or {}),
    })

def _chart_layout(title=""):
    return dict(
        plot_bgcolor=PANEL, paper_bgcolor=BG,
        font=dict(color=TEXT, size=11, family=FONT),
        title=dict(text=title, font=dict(size=11, color=MUTED), x=0.01),
        margin=dict(l=50, r=15, t=32, b=32),
        xaxis=dict(gridcolor=BORDER, linecolor=BORDER, tickfont=dict(color=MUTED, size=10)),
        yaxis=dict(gridcolor=BORDER, linecolor=BORDER, tickfont=dict(color=MUTED, size=10)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11, color=TEXT)),
        hovermode="x unified",
    )

def _empty_chart(msg=""):
    fig = go.Figure()
    fig.update_layout(
        **_chart_layout(),
        annotations=[dict(text=msg, x=0.5, y=0.5, showarrow=False,
                          font=dict(color=MUTED, size=11, family=FONT))],
    )
    return fig

# ── Format helpers ────────────────────────────────────────────────────────────
def _pct(v):
    return f"{v:+.2f}%" if v is not None and not (isinstance(v, float) and v != v) else "—"

def _price(v):
    return f"${v:.2f}" if v is not None and not (isinstance(v, float) and v != v) else "—"

def _large(v):
    if v is None or (isinstance(v, float) and v != v): return "—"
    if v >= 1e12: return f"${v/1e12:.1f}T"
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v >= 1e6:  return f"${v/1e6:.1f}M"
    return f"${v:,.0f}"

def _num(v, d=1):
    return f"{v:.{d}f}" if v is not None and not (isinstance(v, float) and v != v) else "—"

def _accent(pct):
    if pct is None or (isinstance(pct, float) and pct != pct): return MUTED
    return GREEN if pct >= 0 else RED

def _card_bg(pct):
    if pct is None or (isinstance(pct, float) and pct != pct): return PANEL
    return "#041a0c" if pct >= 0 else "#1a0408"

# ── Markets UI builders ───────────────────────────────────────────────────────
def _fmt_idx_price(price, sym):
    if price is None: return "—"
    if sym == "^TNX": return f"{price:.3f}%"
    if price >= 10000: return f"{price:,.0f}"
    if price >= 1000:  return f"{price:,.2f}"
    return f"{price:.2f}"

def _index_card(sym, label, short, mdata):
    info  = mdata.get(sym, {})
    price = info.get("price")
    p1d   = info.get("pct1d")
    p1w   = info.get("pct1w")
    p1m   = info.get("pct1m")
    ac    = _accent(p1d)
    bg    = _card_bg(p1d)
    return html.Div([
        html.Div([
            html.Div(short, style={"color": CYAN, "fontSize": "12px",
                                    "fontWeight": "bold", "letterSpacing": "1px"}),
            html.Div(label, style={"color": MUTED, "fontSize": "9px", "marginTop": "1px"}),
        ], style={"marginBottom": "8px"}),
        html.Div(_fmt_idx_price(price, sym),
                 style={"color": TEXT, "fontSize": "20px", "fontWeight": "bold",
                        "marginBottom": "5px", "letterSpacing": "0.5px"}),
        html.Div([
            html.Span("1D  ", style={"color": MUTED, "fontSize": "9px"}),
            html.Span(_pct(p1d), style={"color": ac, "fontSize": "14px", "fontWeight": "bold"}),
        ], style={"marginBottom": "3px"}),
        html.Div([
            html.Span("1W  ", style={"color": MUTED, "fontSize": "9px"}),
            html.Span(_pct(p1w), style={"color": _accent(p1w), "fontSize": "11px"}),
            html.Span("   1M  ", style={"color": MUTED, "fontSize": "9px"}),
            html.Span(_pct(p1m), style={"color": _accent(p1m), "fontSize": "11px"}),
        ]),
    ], style={
        "backgroundColor": bg, "border": f"1px solid {ac}55",
        "borderRadius": "8px", "padding": "14px 18px",
        "flex": "1", "minWidth": "150px", "boxShadow": f"0 0 12px {ac}22",
    })

def _sector_card(sym, label, mdata):
    info = mdata.get(sym, {})
    p1d  = info.get("pct1d")
    p1m  = info.get("pct1m")
    ac   = _accent(p1d)
    return html.Div([
        html.Div(sym,   style={"color": CYAN, "fontSize": "10px", "fontWeight": "bold",
                                "letterSpacing": "1px"}),
        html.Div(label, style={"color": MUTED, "fontSize": "8px", "marginBottom": "6px",
                                "whiteSpace": "nowrap"}),
        html.Div(_pct(p1d), style={"color": ac, "fontSize": "15px",
                                    "fontWeight": "bold", "marginBottom": "2px"}),
        html.Div([
            html.Span("1M ", style={"color": MUTED, "fontSize": "8px"}),
            html.Span(_pct(p1m), style={"color": _accent(p1m), "fontSize": "10px"}),
        ]),
    ], style={
        "backgroundColor": _card_bg(p1d), "border": f"1px solid {ac}55",
        "borderRadius": "6px", "padding": "10px 14px",
        "flex": "1", "minWidth": "100px", "boxShadow": f"0 0 8px {ac}22",
    })

def _build_markets_chart(hist_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if hist_df.empty:
        return _empty_chart("LOADING...")
    for i, idx in enumerate(MARKET_INDICES):
        sym = idx["symbol"]
        if sym not in hist_df.columns:
            continue
        ser = hist_df[sym].dropna()
        if len(ser) < 2:
            continue
        norm  = (ser / ser.iloc[0] - 1) * 100
        color = CHART_COLORS[i % len(CHART_COLORS)]
        fig.add_trace(go.Scatter(
            x=ser.index, y=norm.values, mode="lines", name=idx["short"],
            line=dict(color=color, width=2),
            hovertemplate=f"<b>{idx['short']}</b>  %{{y:+.2f}}%<extra></extra>",
        ))
    fig.add_hline(y=0, line_dash="dot", line_color=BORDER, line_width=1)
    fig.update_layout(**_chart_layout("MAJOR INDICES  //  3M NORMALIZED %"))
    fig.update_yaxes(ticksuffix="%")
    return fig

# ── Screener bubble ────────────────────────────────────────────────────────────
def _bubble(row, is_sel: bool, period: str, bubble_type="bubble") -> html.Div:
    ticker = row["Ticker"]
    pct    = row.get(f"{period} %")
    pct1d  = row.get("1D %")
    valid  = pct is not None and not (isinstance(pct, float) and pct != pct)
    accent = (GREEN if valid and pct >= 0 else RED) if valid else MUTED
    bg     = ("#041a0c" if valid and pct >= 0 else "#1a0408") if valid else PANEL
    border = f"2px solid {CYAN}" if is_sel else f"1px solid {accent}55"
    shadow = f"0 0 18px {CYAN}55, 0 0 6px {CYAN}33" if is_sel else f"0 0 10px {accent}22"
    p1clr  = (GREEN if pct1d is not None and not (isinstance(pct1d, float) and pct1d != pct1d)
              and pct1d >= 0 else RED)
    return html.Div(
        id={"type": bubble_type, "ticker": ticker},
        n_clicks=0,
        className="ticker-bubble",
        children=[
            html.Div([
                html.Span(ticker, style={
                    "fontSize": "15px", "fontWeight": "bold", "letterSpacing": "1px",
                    "color": CYAN if is_sel else TEXT,
                    "textShadow": f"0 0 10px {CYAN}aa" if is_sel else "none",
                }),
                html.Span("◆" if is_sel else "◇",
                           style={"color": CYAN if is_sel else MUTED, "fontSize": "10px"}),
            ], style={"display": "flex", "justifyContent": "space-between",
                      "alignItems": "center", "marginBottom": "6px"}),
            html.Div(_price(row.get("Price")),
                     style={"color": TEXT, "fontSize": "17px", "fontWeight": "bold",
                            "marginBottom": "4px"}),
            html.Div([
                html.Span(f"{period}  ", style={"color": MUTED, "fontSize": "10px"}),
                html.Span(_pct(pct), style={"color": accent, "fontSize": "16px",
                                             "fontWeight": "bold"}),
            ], style={"marginBottom": "3px"}),
            html.Div([
                html.Span("1D  ", style={"color": MUTED, "fontSize": "10px"}),
                html.Span(_pct(pct1d), style={"color": p1clr, "fontSize": "12px"}),
            ], style={"marginBottom": "6px"}),
            html.Div(_large(row.get("Market Cap")),
                     style={"color": MUTED, "fontSize": "10px",
                            "borderTop": f"1px solid {BORDER}", "paddingTop": "6px"}),
        ],
        style={
            "backgroundColor": bg, "border": border, "borderRadius": "8px",
            "padding": "12px 14px", "width": "164px", "minWidth": "164px",
            "cursor": "pointer", "boxShadow": shadow, "userSelect": "none",
        },
    )

# ── All-stocks bubble ─────────────────────────────────────────────────────────
def _allstocks_bubble(row, is_sel: bool, bubble_type: str = "filter-bubble") -> html.Div:
    ticker  = row.get("Ticker", "")
    pct1d   = row.get("1D %")
    price   = row.get("Price")
    mcap    = row.get("Market Cap")
    pe      = row.get("P/E")
    fpe     = row.get("Fwd P/E")
    company = str(row.get("Company", ""))
    valid   = pct1d is not None and not (isinstance(pct1d, float) and pct1d != pct1d)
    accent  = (GREEN if valid and pct1d >= 0 else RED) if valid else MUTED
    bg      = ("#041a0c" if valid and pct1d >= 0 else "#1a0408") if valid else PANEL
    border  = f"2px solid {CYAN}" if is_sel else f"1px solid {accent}55"
    shadow  = f"0 0 18px {CYAN}55" if is_sel else f"0 0 10px {accent}22"
    return html.Div(
        id={"type": bubble_type, "ticker": ticker},
        n_clicks=0,
        className="ticker-bubble",
        children=[
            html.Div([
                html.Span(ticker, style={
                    "fontSize": "14px", "fontWeight": "bold",
                    "color": CYAN if is_sel else TEXT,
                    "textShadow": f"0 0 10px {CYAN}aa" if is_sel else "none",
                }),
                html.Span("◆" if is_sel else "◇",
                           style={"color": CYAN if is_sel else MUTED, "fontSize": "10px"}),
            ], style={"display": "flex", "justifyContent": "space-between",
                      "alignItems": "center", "marginBottom": "2px"}),
            html.Div(company[:22], style={"color": MUTED, "fontSize": "9px",
                                           "whiteSpace": "nowrap", "overflow": "hidden",
                                           "textOverflow": "ellipsis", "marginBottom": "5px"}),
            html.Div([
                html.Span(_price(price),
                           style={"color": TEXT, "fontSize": "14px", "fontWeight": "bold",
                                  "marginRight": "6px"}),
                html.Span(_pct(pct1d), style={"color": accent, "fontSize": "12px"}),
            ], style={"marginBottom": "5px"}),
            html.Div([
                html.Span("PE ", style={"color": MUTED, "fontSize": "9px"}),
                html.Span(_num(pe), style={"color": TEXT, "fontSize": "12px", "marginRight": "10px"}),
                html.Span("Fwd ", style={"color": MUTED, "fontSize": "9px"}),
                html.Span(_num(fpe), style={"color": TEXT, "fontSize": "12px"}),
            ], style={"marginBottom": "5px"}),
            html.Div(_large(mcap),
                     style={"color": MUTED, "fontSize": "10px",
                            "borderTop": f"1px solid {BORDER}", "paddingTop": "5px"}),
        ],
        style={
            "backgroundColor": bg, "border": border, "borderRadius": "8px",
            "padding": "12px 14px", "width": "172px", "minWidth": "172px",
            "cursor": "pointer", "boxShadow": shadow, "userSelect": "none",
        },
    )

# ── News bubble ───────────────────────────────────────────────────────────────
def _news_bubble(row, is_sel: bool) -> html.Div:
    ticker   = row.get("Ticker", "")
    pct1d    = row.get("1D %")
    pct1m    = row.get("1M %")
    valid    = pct1d is not None and not (isinstance(pct1d, float) and pct1d != pct1d)
    accent   = (GREEN if pct1d >= 0 else RED) if valid else MUTED
    bg       = ("#041a0c" if pct1d >= 0 else "#1a0408") if valid else PANEL
    border   = f"2px solid {CYAN}" if is_sel else f"1px solid {accent}55"
    shadow   = f"0 0 18px {CYAN}55" if is_sel else f"0 0 10px {accent}22"
    heads    = row.get("Headlines") or []
    headline = heads[0]["title"] if heads else ""
    n        = row.get("Mentions", 0)
    return html.Div(
        id={"type": "news-bubble", "ticker": ticker},
        n_clicks=0,
        className="ticker-bubble",
        children=[
            html.Div([
                html.Span(ticker, style={
                    "fontSize": "14px", "fontWeight": "bold",
                    "color": CYAN if is_sel else TEXT,
                    "textShadow": f"0 0 10px {CYAN}aa" if is_sel else "none",
                }),
                html.Span([
                    html.Span("▲ HOT ", style={"color": AMBER, "fontSize": "8px",
                                               "letterSpacing": "1px"}) if row.get("Trending") else None,
                    html.Span("◆" if is_sel else "◇",
                              style={"color": CYAN if is_sel else MUTED, "fontSize": "10px"}),
                ]),
            ], style={"display": "flex", "justifyContent": "space-between",
                      "alignItems": "center", "marginBottom": "2px"}),
            html.Div(str(row.get("Company", ""))[:26],
                     style={"color": MUTED, "fontSize": "9px", "whiteSpace": "nowrap",
                            "overflow": "hidden", "textOverflow": "ellipsis",
                            "marginBottom": "5px"}),
            html.Div([
                html.Span(_price(row.get("Price")),
                          style={"color": TEXT, "fontSize": "14px", "fontWeight": "bold",
                                 "marginRight": "6px"}),
                html.Span(_pct(pct1d), style={"color": accent, "fontSize": "12px"}),
            ], style={"marginBottom": "3px"}),
            html.Div([
                html.Span("1M  ", style={"color": MUTED, "fontSize": "9px"}),
                html.Span(_pct(pct1m), style={"color": _accent(pct1m), "fontSize": "11px"}),
            ], style={"marginBottom": "6px"}),
            html.Div(f"{n} ARTICLE{'S' if n != 1 else ''}",
                     style={"color": AMBER, "fontSize": "9px", "letterSpacing": "1px",
                            "borderTop": f"1px solid {BORDER}", "paddingTop": "5px",
                            "marginBottom": "3px"}),
            html.Div(headline, title=headline,
                     style={"color": TEXT, "fontSize": "9px", "lineHeight": "1.35",
                            "opacity": "0.85", "display": "-webkit-box",
                            "WebkitLineClamp": 2, "WebkitBoxOrient": "vertical",
                            "overflow": "hidden"}),
        ],
        style={
            "backgroundColor": bg, "border": border, "borderRadius": "8px",
            "padding": "12px 14px", "width": "196px", "minWidth": "196px",
            "cursor": "pointer", "boxShadow": shadow, "userSelect": "none",
        },
    )

# ── News charts (1Y data, view defaults to last month) ────────────────────────
NEWS_RANGE_BUTTONS = [
    dict(count=7, label="1W", step="day",   stepmode="backward"),
    dict(count=1, label="1M", step="month", stepmode="backward"),
    dict(count=3, label="3M", step="month", stepmode="backward"),
    dict(count=6, label="6M", step="month", stepmode="backward"),
    dict(count=1, label="YTD", step="year", stepmode="todate"),
    dict(label="1Y", step="all"),
]


def _news_y_range(lo, hi):
    if lo is None:
        return None
    pad = max((hi - lo) * 0.06, abs(hi) * 0.005, 0.5 if hi - lo < 1 else 0)
    return [lo - pad, hi + pad]


def _build_news_charts(selected: list, xrange: list | None = None):
    """Normalized-% and price charts. Full 1Y of data is sent to the browser;
    the visible window starts at the last month (or the user's last zoom)."""
    hists = get_histories_1y(selected)
    series = {t: hists[t] for t in selected if t in hists and len(hists[t])}
    if not series:
        return _empty_chart("NO PRICE HISTORY"), _empty_chart("NO PRICE HISTORY")

    last  = max(s.index[-1] for s in series.values())
    first = min(s.index[0] for s in series.values())
    if xrange:
        x0, x1 = pd.Timestamp(str(xrange[0])), pd.Timestamp(str(xrange[1]))
    else:
        x0, x1 = last - pd.DateOffset(months=1), last
    x0 = max(min(x0, last), first - pd.Timedelta(days=1))

    norm_fig, price_fig = go.Figure(), go.Figure()
    n_lo = n_hi = p_lo = p_hi = None
    for i, t in enumerate(selected):
        ser = series.get(t)
        if ser is None:
            continue
        color = CHART_COLORS[i % len(CHART_COLORS)]
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
            mode="lines", name=t, line=dict(color=color, width=2),
            hovertemplate=f"<b>{t}</b>  %{{y:+.2f}}%  ($%{{customdata:.2f}})<extra></extra>",
        ))
        price_fig.add_trace(go.Scatter(
            x=xs, y=ser.round(4).tolist(), mode="lines", name=t,
            line=dict(color=color, width=2),
            hovertemplate=f"<b>{t}</b>  $%{{y:.2f}}<extra></extra>",
        ))

    xr = [x0.strftime("%Y-%m-%d"), x1.strftime("%Y-%m-%d")]
    for fig, title, yr in (
        (norm_fig,  "% CHANGE FROM START OF VIEW", _news_y_range(n_lo, n_hi)),
        (price_fig, "PRICE  //  1Y DATA",          _news_y_range(p_lo, p_hi)),
    ):
        fig.update_layout(**_chart_layout(title))
        fig.update_layout(margin=dict(l=55, r=15, t=44, b=32))
        fig.update_xaxes(
            type="date", range=xr, autorange=False,
            rangeselector=dict(
                buttons=NEWS_RANGE_BUTTONS, x=1, xanchor="right", y=1.02, yanchor="bottom",
                bgcolor=PANEL, activecolor=SEL_BG, bordercolor=BORDER, borderwidth=1,
                font=dict(color=CYAN, size=10, family=FONT),
            ),
        )
        # x-only zooming; y is refit to the visible window (server + clientside)
        fig.update_yaxes(fixedrange=True, autorange=yr is None, range=yr)
    norm_fig.add_hline(y=0, line_dash="dot", line_color=BORDER, line_width=1)
    norm_fig.update_yaxes(ticksuffix="%")
    price_fig.update_yaxes(tickprefix="$")
    return norm_fig, price_fig


def _news_headlines(rows: list, selected: list) -> list:
    if selected:
        pool, seen = [], set()
        for r in rows:
            if r["Ticker"] in selected:
                for h in r["Headlines"]:
                    if h["link"] not in seen:
                        seen.add(h["link"])
                        pool.append(h)
        title = f"HEADLINES  //  {' · '.join(selected)}"
    else:
        pool, seen = [], set()
        for r in rows:
            for h in r["Headlines"]:
                if h["link"] not in seen:
                    seen.add(h["link"])
                    pool.append(h)
        title = "LATEST HEADLINES  //  click cards to filter"
    pool.sort(key=lambda h: h["time"], reverse=True)
    sel = set(selected or [])
    items = []
    for h in pool[:30]:
        items.append(html.Div([
            html.Span(_time_ago(h["time"]),
                      style={"color": MUTED, "fontSize": "9px", "width": "58px",
                             "flexShrink": "0"}),
            html.Div([
                html.A(h["title"], href=h["link"], target="_blank", rel="noopener noreferrer",
                       style={"color": TEXT, "fontSize": "11px", "textDecoration": "none"}),
                html.Div([
                    html.Span(h["publisher"], style={"color": MUTED, "fontSize": "9px",
                                                     "marginRight": "8px"}),
                    *[html.Span(t, style={"color": CYAN if t in sel else MUTED,
                                          "fontSize": "9px", "marginRight": "6px",
                                          "fontWeight": "bold" if t in sel else "normal"})
                      for t in h["tickers"][:8]],
                ], style={"marginTop": "2px"}),
            ], style={"minWidth": "0"}),
        ], style={"display": "flex", "gap": "10px", "padding": "7px 0",
                  "borderBottom": f"1px solid {BORDER}"}))
    return [
        html.Div(title, style={"color": CYAN, "fontSize": "9px", "letterSpacing": "2px",
                               "marginBottom": "6px"}),
        *(items or [html.Div("NO HEADLINES", style={"color": MUTED, "fontSize": "10px"})]),
    ]

# ── History helper ────────────────────────────────────────────────────────────
def fetch_history(symbol: str, window: str) -> pd.Series | None:
    try:
        hist = yf.Ticker(symbol).history(period=window)
        return hist["Close"] if not hist.empty else None
    except Exception:
        return None

# ── News / trending data ──────────────────────────────────────────────────────
# Broad market queries; each Yahoo news article carries a `relatedTickers` list,
# so counting tickers across recent articles gives "most talked about" stocks.
NEWS_QUERIES = [
    "stock market", "stocks", "Wall Street", "earnings", "shares",
    "analyst rating", "IPO", "guidance", "Nasdaq", "Dow Jones",
]
NEWS_CACHE_TTL = 10 * 60      # seconds
HIST_CACHE_TTL = 30 * 60
NEWS_MAX_TICKERS = 40

_news_cache = {"ts": 0.0, "articles": []}
_hist_cache: dict = {}        # symbol -> (timestamp, pd.Series of 1Y closes)


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
    for s in symbols:
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


def _is_us_stock_symbol(sym: str) -> bool:
    # skip indices (^GSPC), futures/currencies (GC=F, EURUSD=X), foreign listings (WTB.L)
    return bool(sym) and not any(c in sym for c in "^=.")


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

    trending  = fetch_yahoo_trending()
    candidates = sorted(counts, key=lambda s: (-counts[s], -(s in trending)))[:NEWS_MAX_TICKERS * 2]
    quotes    = {q["symbol"]: q for q in _yahoo.get_quotes(candidates)}
    stocks    = [s for s in candidates if quotes.get(s, {}).get("quoteType") == "EQUITY"]
    stocks    = stocks[:NEWS_MAX_TICKERS]
    hists     = get_histories_1y(stocks)

    rows = []
    for s in stocks:
        q   = quotes[s]
        ser = hists.get(s)
        pct1m = (float((ser.iloc[-1] / ser.iloc[-22] - 1) * 100)
                 if ser is not None and len(ser) >= 22 else None)
        rows.append({
            "Ticker":     s,
            "Company":    q.get("shortName") or q.get("longName") or "",
            "Price":      q.get("regularMarketPrice"),
            "1D %":       q.get("regularMarketChangePercent"),
            "1M %":       pct1m,
            "Market Cap": q.get("marketCap"),
            "Mentions":   counts[s],
            "Trending":   s in trending,
            "Headlines":  heads[s],
        })
    rows.sort(key=lambda r: (-r["Mentions"], -r["Trending"], -(r["Market Cap"] or 0)))
    return rows, len(recent)


def _time_ago(ts: float) -> str:
    mins = max(0, int((time.time() - ts) / 60))
    if mins < 60:
        return f"{mins}m ago"
    if mins < 48 * 60:
        return f"{mins // 60}h ago"
    return f"{mins // 1440}d ago"

# ── Sector metrics table ──────────────────────────────────────────────────────
def _make_sector_metrics_table(df: pd.DataFrame):
    COLS = [
        ("Ticker",   "Ticker"),
        ("Company",  "Company"),
        ("Price",    "Price"),
        ("1D %",     "1D %"),
        ("Mkt Cap",  "Market Cap"),
        ("P/E",      "P/E"),
        ("Fwd P/E",  "Fwd P/E"),
        ("PEG",      "PEG"),
        ("EPS",      "EPS"),
        ("Rev Gr%",  "Rev Growth %"),
        ("Margin%",  "Profit Margin %"),
        ("52W Hi",   "52W High"),
        ("52W Lo",   "52W Low"),
        ("Avg Vol",  "Avg Volume"),
        ("Sector",   "Sector"),
    ]
    display = pd.DataFrame()
    for label, col in COLS:
        if col not in df.columns:
            display[label] = "—"
            continue
        if col == "Price":
            display[label] = df[col].apply(lambda v: f"${v:.2f}" if pd.notna(v) else "—")
        elif col == "1D %":
            display[label] = df[col].apply(lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
        elif col == "Market Cap":
            display[label] = df[col].apply(_large)
        elif col == "Avg Volume":
            def _vol(v):
                if pd.isna(v): return "—"
                if v >= 1e6: return f"{v/1e6:.1f}M"
                if v >= 1e3: return f"{v/1e3:.1f}K"
                return str(int(v))
            display[label] = df[col].apply(_vol)
        elif col in ("52W High", "52W Low"):
            display[label] = df[col].apply(lambda v: f"${v:.2f}" if pd.notna(v) else "—")
        elif col == "Company":
            display[label] = df[col].apply(lambda v: str(v)[:30] if pd.notna(v) else "—")
        elif col == "Sector":
            display[label] = df[col].apply(lambda v: str(v) if pd.notna(v) else "—")
        else:
            display[label] = df[col].apply(lambda v: f"{v:.2f}" if pd.notna(v) else "—")

    return dash_table.DataTable(
        data=display.to_dict("records"),
        columns=[{"name": lbl, "id": lbl} for lbl, _ in COLS],
        sort_action="native",
        style_table={"overflowX": "auto", "minWidth": "100%"},
        style_cell={
            "backgroundColor": PANEL, "color": TEXT,
            "fontFamily": FONT, "fontSize": "11px",
            "border": f"1px solid {BORDER}",
            "padding": "6px 10px", "whiteSpace": "nowrap",
            "textAlign": "right",
        },
        style_cell_conditional=[
            {"if": {"column_id": "Ticker"},  "textAlign": "left",
             "color": CYAN, "fontWeight": "bold", "letterSpacing": "1px"},
            {"if": {"column_id": "Company"}, "textAlign": "left", "color": TEXT},
            {"if": {"column_id": "Sector"},  "textAlign": "left", "color": MUTED},
        ],
        style_header={
            "backgroundColor": SEL_BG, "color": MUTED,
            "fontFamily": FONT, "fontSize": "9px",
            "fontWeight": "normal", "letterSpacing": "1.5px",
            "border": f"1px solid {BORDER}", "textAlign": "right",
            "textTransform": "uppercase",
        },
        style_header_conditional=[
            {"if": {"column_id": col}, "textAlign": "left"}
            for col in ["Ticker", "Company", "Sector"]
        ],
        style_data_conditional=[
            {"if": {"filter_query": '{`1D %`} contains "+"', "column_id": "1D %"}, "color": GREEN},
            {"if": {"filter_query": '{`1D %`} contains "-"', "column_id": "1D %"}, "color": RED},
            {"if": {"row_index": "odd"}, "backgroundColor": "#0a1828"},
        ],
        page_action="none",
    )

# ── Sector button styles ───────────────────────────────────────────────────────
_SECTOR_BTN_BASE = {
    "height": "32px", "padding": "0 14px", "cursor": "pointer",
    "background": "transparent", "border": f"1px solid {BORDER}",
    "color": MUTED, "fontFamily": FONT, "fontSize": "10px",
    "letterSpacing": "1.5px", "borderRadius": "3px",
}
_SECTOR_BTN_SEL = {
    **_SECTOR_BTN_BASE,
    "background": f"{CYAN}22", "border": f"1px solid {CYAN}",
    "color": CYAN, "boxShadow": f"0 0 8px {CYAN}55",
}

# ── App init ──────────────────────────────────────────────────────────────────
app = Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
app.title = "STOCK SCREENER"

TAB_STYLE = {
    "backgroundColor": PANEL, "color": MUTED, "border": f"1px solid {BORDER}",
    "fontFamily": FONT, "fontSize": "10px", "letterSpacing": "2px",
    "padding": "8px 20px", "borderRadius": "4px 4px 0 0",
}
TAB_SELECTED = {**TAB_STYLE, "backgroundColor": SEL_BG,
                "color": CYAN, "borderBottom": f"2px solid {CYAN}",
                "textShadow": f"0 0 8px {CYAN}88"}

app.index_string = f"""<!DOCTYPE html>
<html>
<head>
    {{%metas%}}
    <title>{{%title%}}</title>
    {{%favicon%}}
    {{%css%}}
    <style>
        * {{ box-sizing: border-box; }}
        body {{ background-color: {BG} !important; font-family: {FONT} !important; color: {TEXT} !important; }}
        ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
        ::-webkit-scrollbar-track {{ background: {PANEL}; }}
        ::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 3px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: {CYAN}66; }}
        .ticker-bubble {{ transition: transform 0.12s ease, box-shadow 0.12s ease; }}
        .ticker-bubble:hover {{ transform: translateY(-2px); }}
        .Select-control {{ background-color: {PANEL} !important; border: 1px solid {BORDER} !important; border-radius: 3px !important; font-family: {FONT} !important; }}
        .Select-menu-outer {{ background-color: {PANEL} !important; border: 1px solid {BORDER} !important; font-family: {FONT} !important; font-size: 12px !important; }}
        .Select-option {{ background-color: {PANEL} !important; color: {TEXT} !important; }}
        .Select-option.is-focused {{ background-color: {SEL_BG} !important; color: {CYAN} !important; }}
        .Select-option.is-selected {{ background-color: {SEL_BG} !important; color: {CYAN} !important; }}
        .Select-value-label {{ color: {TEXT} !important; font-family: {FONT} !important; }}
        .Select-placeholder {{ color: {MUTED} !important; }}
        .Select-arrow {{ border-top-color: {MUTED} !important; }}
        .cyber-panel {{ background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; box-shadow: 0 4px 24px #00000099; }}
    </style>
</head>
<body>
{{%app_entry%}}
<footer>{{%config%}}{{%scripts%}}{{%renderer%}}</footer>
</body>
</html>"""

# ── Filter helpers ────────────────────────────────────────────────────────────
def _filter_row(label: str, id_prefix: str, unit: str = "", watchlist_only: bool = False):
    lbl = label + (f" ({unit})" if unit else "")
    s   = _inp({"height": "28px", "padding": "2px 6px", "width": "85px", "fontSize": "11px"})
    return html.Div([
        html.Div([
            html.Span(lbl, style={"color": MUTED, "fontSize": "9px", "letterSpacing": "1px",
                                   "textTransform": "uppercase"}),
            html.Span(" ·watchlist only" if watchlist_only else "",
                       style={"color": MUTED, "fontSize": "8px", "marginLeft": "4px",
                               "opacity": "0.6"}),
        ], style={"marginBottom": "4px", "display": "flex", "alignItems": "center"}),
        html.Div([
            dcc.Input(id=f"f-{id_prefix}-min", placeholder="min", type="number",
                      debounce=False, style=s),
            html.Span("—", style={"color": MUTED, "margin": "0 4px", "lineHeight": "28px"}),
            dcc.Input(id=f"f-{id_prefix}-max", placeholder="max", type="number",
                      debounce=False, style=s),
        ], style={"display": "flex", "alignItems": "center"}),
    ], style={"marginBottom": "10px"})

def _filter_card(title: str, children):
    return html.Div([
        html.Div(title, style={"color": CYAN, "fontSize": "9px", "letterSpacing": "2px",
                                "marginBottom": "10px", "paddingBottom": "6px",
                                "borderBottom": f"1px solid {BORDER}"}),
        *children,
    ], style={"backgroundColor": PANEL, "border": f"1px solid {BORDER}",
              "borderRadius": "6px", "padding": "12px 14px"})

# ── Markets tab ───────────────────────────────────────────────────────────────
markets_tab = html.Div([
    dcc.Interval(id="interval-markets", interval=5 * 60 * 1000, n_intervals=0),

    dbc.Row([
        dbc.Col(html.Div("MARKET OVERVIEW", style={
            "color": MUTED, "fontSize": "9px", "letterSpacing": "3px", "lineHeight": "32px",
        })),
        dbc.Col(_btn("↻  REFRESH", "btn-markets-refresh"), width="auto"),
        dbc.Col(html.Div(id="markets-status",
                         style={"color": MUTED, "fontSize": "9px",
                                "letterSpacing": "1px", "lineHeight": "32px"}), width="auto"),
    ], align="center", className="mb-3"),

    html.Div(
        html.Div(id="div-market-indices",
                 style={"display": "flex", "gap": "10px", "flexWrap": "wrap"},
                 children=[html.Div("LOADING MARKET DATA...",
                                     style={"color": MUTED, "fontSize": "10px",
                                            "letterSpacing": "2px", "padding": "20px"})]),
        className="cyber-panel mb-3", style={"padding": "14px"},
    ),

    html.Div(
        dcc.Graph(id="graph-markets-chart", config={"displayModeBar": True},
                  style={"height": "300px"},
                  figure=_empty_chart("LOADING MARKET DATA...")),
        className="cyber-panel mb-3",
    ),

    html.Div([
        html.Div("SECTORS", style={
            "color": MUTED, "fontSize": "9px", "letterSpacing": "3px", "marginBottom": "10px",
        }),
        html.Div(id="div-market-sectors",
                 style={"display": "flex", "gap": "8px", "flexWrap": "wrap"},
                 children=[html.Div("LOADING...",
                                     style={"color": MUTED, "fontSize": "10px", "padding": "10px"})]),
    ], className="cyber-panel", style={"padding": "14px"}),

], style={"paddingTop": "16px"})

# ── Screener tab ──────────────────────────────────────────────────────────────
screener_tab = html.Div([
    dcc.Store(id="store-data"),
    dcc.Store(id="store-selected", data=[]),

    dbc.Row([
        dbc.Col(dcc.Textarea(
            id="input-tickers",
            placeholder="AAPL MSFT NVDA  (blank = tickers.txt)",
            style=_inp({"width": "100%", "height": "32px", "resize": "none", "padding": "5px 8px"}),
        )),
        dbc.Col(dcc.Dropdown(
            id="dd-period", options=PERIOD_OPTIONS, value="1M",
            clearable=False, style=_inp({"minWidth": "80px", "color": "#111"}),
        ), width="auto"),
        dbc.Col(_btn("▶  RUN", "btn-run",
                     extra={"boxShadow": f"0 0 10px {CYAN}55", "fontWeight": "bold"}),
                width="auto"),
        dbc.Col(_btn("CLEAR SEL", "btn-clear"), width="auto"),
    ], align="center", className="mb-2", style={"gap": "6px"}),

    dbc.Row([
        dbc.Col(html.Span("WATCHLISTS:", style={
            "color": MUTED, "fontSize": "9px", "letterSpacing": "2px", "lineHeight": "32px",
        }), width="auto"),
        dbc.Col(dcc.Dropdown(
            id="dd-watchlist", options=watchlist_options(load_watchlists()),
            placeholder="Select a list...", clearable=True,
            style=_inp({"color": "#111"}),
        ), width=3),
        dbc.Col(dcc.Input(
            id="input-list-name", placeholder="New list name...",
            style=_inp({"height": "32px", "padding": "4px 8px", "width": "160px"}),
        ), width="auto"),
        dbc.Col(_btn("SAVE LIST", "btn-save-list"), width="auto"),
        dbc.Col(_btn("DELETE", "btn-delete-list", color=RED), width="auto"),
        dbc.Col(html.Div(id="list-status",
                         style={"color": MUTED, "fontSize": "10px",
                                "lineHeight": "32px", "letterSpacing": "1px"})),
    ], align="center", className="mb-2", style={"gap": "6px"}),

    html.Div(id="status-bar",
             style={"color": MUTED, "fontSize": "9px", "letterSpacing": "2px",
                    "marginBottom": "10px"}),

    html.Div(
        html.Div(id="div-bubbles",
                 style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "padding": "14px"},
                 children=[html.Div("▶  PRESS RUN TO LOAD DATA",
                                     style={"color": MUTED, "fontSize": "10px",
                                            "letterSpacing": "2px", "padding": "10px"})]),
        className="cyber-panel mb-2",
    ),

    dbc.Row([
        dbc.Col(html.Div(
            dcc.Graph(id="graph-normalized", config={"displayModeBar": True},
                      style={"height": "300px"}),
            className="cyber-panel",
        ), width=6),
        dbc.Col(html.Div(
            dcc.Graph(id="graph-price", config={"displayModeBar": True},
                      style={"height": "300px"}),
            className="cyber-panel",
        ), width=6),
    ], className="mb-2"),

    html.Div(id="div-metrics-table", className="cyber-panel mb-2",
             style={"overflowX": "auto", "padding": "4px 0"}),

    html.Div(
        dcc.Graph(id="graph-treemap", config={"displayModeBar": False},
                  style={"height": "360px"}),
        className="cyber-panel",
    ),
], style={"paddingTop": "16px"})

# ── Filter tab ────────────────────────────────────────────────────────────────
filter_tab = html.Div([
    dcc.Store(id="store-filter-data"),
    dcc.Store(id="store-filter-source", data="watchlist"),
    dcc.Store(id="store-filter-selected", data=[]),

    dbc.Row([
        dbc.Col(html.Div([
            html.Div("UNIVERSE", style={"color": MUTED, "fontSize": "9px",
                                         "letterSpacing": "2px", "marginBottom": "4px"}),
            dcc.RadioItems(
                id="filter-universe",
                options=[
                    {"label": "  Watchlist", "value": "watchlist"},
                    {"label": "  All US Stocks (NYSE + NASDAQ)", "value": "all"},
                ],
                value="all", inline=True,
                style={"color": TEXT, "fontSize": "11px", "fontFamily": FONT},
                inputStyle={"marginRight": "4px", "accentColor": CYAN},
                labelStyle={"marginRight": "16px"},
            ),
        ]), width="auto"),
        dbc.Col(dcc.Textarea(
            id="filter-input-tickers",
            placeholder="AAPL MSFT …  (watchlist mode only)",
            style=_inp({"width": "100%", "height": "32px", "resize": "none", "padding": "5px 8px"}),
        )),
        dbc.Col(dcc.Dropdown(
            id="filter-dd-period", options=PERIOD_OPTIONS, value="1M",
            clearable=False, style=_inp({"minWidth": "80px", "color": "#111"}),
        ), width="auto"),
        dbc.Col(_btn("▶  SCREEN", "btn-filter-run",
                     extra={"boxShadow": f"0 0 10px {CYAN}55", "fontWeight": "bold"}),
                width="auto"),
        dbc.Col(_btn("CLEAR SEL", "btn-filter-clear"), width="auto"),
    ], align="center", className="mb-3", style={"gap": "6px"}),

    dbc.Row([
        dbc.Col(_filter_card("VALUATION", [
            _filter_row("P/E",     "pe"),
            _filter_row("Fwd P/E", "fpe"),
            _filter_row("PEG",     "peg"),
            _filter_row("EPS",     "eps"),
        ]), width=3),
        dbc.Col(_filter_card("GROWTH & MARGIN", [
            _filter_row("Rev Growth", "revgr",  "%"),
            _filter_row("Margin",     "margin", "%"),
        ]), width=3),
        dbc.Col(_filter_card("SIZE & VOLUME", [
            _filter_row("Market Cap", "mcap", "$B"),
            _filter_row("Avg Volume", "vol",  "M"),
        ]), width=3),
        dbc.Col(_filter_card("PERFORMANCE  ·watchlist only", [
            _filter_row("52W Pos", "w52", watchlist_only=True),
            _filter_row("1M %",    "p1m", watchlist_only=True),
            _filter_row("3M %",    "p3m", watchlist_only=True),
            _filter_row("6M %",    "p6m", watchlist_only=True),
            _filter_row("1Y %",    "p1y", watchlist_only=True),
        ]), width=3),
    ], className="mb-3"),

    html.Div(id="filter-status",
             style={"color": MUTED, "fontSize": "9px", "letterSpacing": "2px",
                    "marginBottom": "10px"}),

    html.Div(
        html.Div(id="div-filter-bubbles",
                 style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "padding": "14px"},
                 children=[html.Div("▶  SET FILTERS AND PRESS SCREEN",
                                     style={"color": MUTED, "fontSize": "10px",
                                            "letterSpacing": "2px", "padding": "10px"})]),
        className="cyber-panel mb-2",
    ),

    dbc.Row([
        dbc.Col(html.Div(
            dcc.Graph(id="graph-filter-normalized", config={"displayModeBar": True},
                      style={"height": "300px"}),
            className="cyber-panel",
        ), width=6),
        dbc.Col(html.Div(
            dcc.Graph(id="graph-filter-price", config={"displayModeBar": True},
                      style={"height": "300px"}),
            className="cyber-panel",
        ), width=6),
    ]),
], style={"paddingTop": "16px"})

# ── Sectors tab ───────────────────────────────────────────────────────────────
sectors_tab = html.Div([
    dcc.Store(id="store-sector-name",     data=None),
    dcc.Store(id="store-sector-data",     data=None),
    dcc.Store(id="store-sector-selected", data=[]),

    html.Div([
        html.Div("SELECT SECTOR", style={
            "color": MUTED, "fontSize": "9px", "letterSpacing": "3px", "marginBottom": "10px",
        }),
        html.Div(
            [html.Button(
                s["label"],
                id={"type": "sector-btn", "sector": s["yahoo"]},
                n_clicks=0,
                style=_SECTOR_BTN_BASE,
            ) for s in SECTOR_DEFINITIONS],
            style={"display": "flex", "flexWrap": "wrap", "gap": "8px"},
        ),
    ], className="cyber-panel mb-3", style={"padding": "14px"}),

    dbc.Row([
        dbc.Col(html.Div(id="sector-status",
                          style={"color": MUTED, "fontSize": "9px",
                                 "letterSpacing": "2px", "lineHeight": "32px"})),
        dbc.Col(_btn("CLEAR SEL", "btn-sector-clear"), width="auto"),
    ], align="center", className="mb-2"),

    html.Div(
        html.Div(id="div-sector-bubbles",
                 style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "padding": "14px"},
                 children=[html.Div("▶  SELECT A SECTOR ABOVE",
                                     style={"color": MUTED, "fontSize": "10px",
                                            "letterSpacing": "2px", "padding": "10px"})]),
        className="cyber-panel mb-2",
    ),

    dbc.Row([
        dbc.Col(html.Div(
            dcc.Graph(id="graph-sector-normalized", config={"displayModeBar": True},
                      style={"height": "300px"},
                      figure=_empty_chart("CLICK BUBBLES TO COMPARE")),
            className="cyber-panel",
        ), width=6),
        dbc.Col(html.Div(
            dcc.Graph(id="graph-sector-price", config={"displayModeBar": True},
                      style={"height": "300px"},
                      figure=_empty_chart("SELECT A TICKER")),
            className="cyber-panel",
        ), width=6),
    ], className="mb-2"),

    html.Div(id="div-sector-metrics-table", className="cyber-panel",
             style={"overflowX": "auto", "padding": "4px 0"}),

], style={"paddingTop": "16px"})

# ── News tab ──────────────────────────────────────────────────────────────────
news_tab = html.Div([
    dcc.Store(id="store-news-data",     data=None),
    dcc.Store(id="store-news-selected", data=[]),
    dcc.Store(id="store-news-xrange",   data=None),

    dbc.Row([
        dbc.Col(html.Div("TRENDING IN THE NEWS", style={
            "color": MUTED, "fontSize": "9px", "letterSpacing": "3px", "lineHeight": "32px",
        }), width="auto"),
        dbc.Col(dcc.Dropdown(
            id="dd-news-hours",
            options=[{"label": "PAST 24H", "value": 24}, {"label": "PAST 48H", "value": 48}],
            value=48, clearable=False, searchable=False,
            style=_inp({"minWidth": "110px", "color": "#111"}),
        ), width="auto"),
        dbc.Col(_btn("↻  REFRESH", "btn-news-refresh"), width="auto"),
        dbc.Col(_btn("CLEAR SEL", "btn-news-clear"), width="auto"),
        dbc.Col(dcc.Loading(
            html.Div(id="news-status",
                     style={"color": MUTED, "fontSize": "9px",
                            "letterSpacing": "1px", "lineHeight": "32px", "minHeight": "32px"}),
            type="dot", color=CYAN,
        )),
    ], align="center", className="mb-2", style={"gap": "6px"}),

    html.Div(
        html.Div(id="div-news-bubbles",
                 style={"display": "flex", "flexWrap": "wrap", "gap": "10px",
                        "padding": "14px", "minHeight": "80px"},
                 children=[html.Div("LOADING NEWS...",
                                    style={"color": MUTED, "fontSize": "10px",
                                           "letterSpacing": "2px", "padding": "10px"})]),
        className="cyber-panel mb-2",
    ),

    dbc.Row([
        dbc.Col(html.Div(
            dcc.Graph(id="graph-news-normalized", config={"displayModeBar": False},
                      style={"height": "340px"},
                      figure=_empty_chart("CLICK CARDS TO COMPARE")),
            className="cyber-panel",
        ), width=6),
        dbc.Col(html.Div(
            dcc.Graph(id="graph-news-price", config={"displayModeBar": False},
                      style={"height": "340px"},
                      figure=_empty_chart("SELECT A TICKER")),
            className="cyber-panel",
        ), width=6),
    ], className="mb-2"),

    html.Div(id="div-news-headlines", className="cyber-panel",
             style={"padding": "12px 16px", "maxHeight": "420px", "overflowY": "auto"}),

], style={"paddingTop": "16px"})

# ── Root layout ───────────────────────────────────────────────────────────────
app.layout = dbc.Container(
    fluid=True,
    style={"backgroundColor": BG, "minHeight": "100vh", "padding": "12px 16px"},
    children=[
        dcc.Store(id="store-watchlists", data=load_watchlists()),

        html.Div([
            html.Span("▌ ", style={"color": CYAN}),
            html.Span("STOCK SCREENER", style={
                "color": CYAN, "fontSize": "14px", "letterSpacing": "5px",
                "fontWeight": "bold", "textShadow": f"0 0 14px {CYAN}aa",
            }),
            html.Span("  //  terminal v2.0",
                      style={"color": MUTED, "fontSize": "9px", "letterSpacing": "2px"}),
            html.Span(f"  ·  {LOCAL_IP}:8050",
                      style={"color": AMBER, "fontSize": "9px", "letterSpacing": "1px",
                             "marginLeft": "10px"}),
        ], style={"marginBottom": "10px", "paddingBottom": "8px",
                  "borderBottom": f"1px solid {BORDER}"}),

        dcc.Tabs(
            id="main-tabs", value="tab-markets",
            children=[
                dcc.Tab(label="MARKETS",  value="tab-markets",
                        style=TAB_STYLE, selected_style=TAB_SELECTED,
                        children=markets_tab),
                dcc.Tab(label="SCREENER", value="tab-screener",
                        style=TAB_STYLE, selected_style=TAB_SELECTED,
                        children=screener_tab),
                dcc.Tab(label="FILTER",   value="tab-filter",
                        style=TAB_STYLE, selected_style=TAB_SELECTED,
                        children=filter_tab),
                dcc.Tab(label="SECTORS",  value="tab-sectors",
                        style=TAB_STYLE, selected_style=TAB_SELECTED,
                        children=sectors_tab),
                dcc.Tab(label="NEWS",     value="tab-news",
                        style=TAB_STYLE, selected_style=TAB_SELECTED,
                        children=news_tab),
            ],
            style={"border": "none"},
            colors={"border": BORDER, "primary": CYAN, "background": BG},
        ),
    ],
)

# ── MARKETS CALLBACKS ─────────────────────────────────────────────────────────

@app.callback(
    Output("div-market-indices",  "children"),
    Output("graph-markets-chart", "figure"),
    Output("div-market-sectors",  "children"),
    Output("markets-status",      "children"),
    Input("interval-markets",      "n_intervals"),
    Input("btn-markets-refresh",   "n_clicks"),
)
def load_market_data(_ni, _nr):
    mdata, hist_df = fetch_market_snapshot()
    ts = pd.Timestamp.now().strftime("%H:%M:%S")
    idx_cards = [_index_card(x["symbol"], x["label"], x["short"], mdata)
                 for x in MARKET_INDICES]
    sec_cards = [_sector_card(x["symbol"], x["label"], mdata)
                 for x in MARKET_SECTORS]
    chart = _build_markets_chart(hist_df)
    return idx_cards, chart, sec_cards, f"●  UPDATED {ts}"

# ── SCREENER CALLBACKS ─────────────────────────────────────────────────────────

@app.callback(
    Output("store-data",    "data"),
    Output("store-selected","data"),
    Output("status-bar",    "children"),
    Input("btn-run",        "n_clicks"),
    State("input-tickers",  "value"),
    prevent_initial_call=True,
)
def run_screener(_, ticker_input):
    tickers = ([t.strip().upper() for t in ticker_input.replace(",", " ").split() if t.strip()]
               if ticker_input and ticker_input.strip() else load_tickers())
    rows = []
    for i, sym in enumerate(tickers):
        row = fetch_ticker(sym)
        if row:
            rows.append(row)
        if i < len(tickers) - 1:
            time.sleep(0.3)
    if not rows:
        return no_update, no_update, "⚠  NO DATA RETRIEVED"
    df = pd.DataFrame(rows)
    ts = pd.Timestamp.now().strftime("%H:%M:%S")
    return df.to_json(orient="records"), df["Ticker"].tolist(), f"●  LOADED {len(rows)} TICKERS  //  {ts}"


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
    if "btn-save-list" in trigger:
        n = (name or "").strip()
        if not n:
            return no_update, no_update, "⚠  ENTER A LIST NAME", no_update
        tickers = [t.strip().upper() for t in (ticker_input or "").replace(",", " ").split() if t.strip()]
        if not tickers:
            return no_update, no_update, "⚠  NO TICKERS IN INPUT", no_update
        lists[n] = tickers
        save_watchlists(lists)
        return lists, watchlist_options(lists), f"✓  SAVED  '{n}'", no_update
    if "btn-delete-list" in trigger:
        if not sel or sel == "__default__":
            return no_update, no_update, "⚠  SELECT A LIST TO DELETE", no_update
        lists.pop(sel, None)
        save_watchlists(lists)
        return lists, watchlist_options(lists), f"✓  DELETED  '{sel}'", no_update
    if "dd-watchlist" in trigger:
        if not sel or sel == "__default__":
            return no_update, no_update, "●  LOADED tickers.txt", " ".join(load_tickers())
        return no_update, no_update, f"●  LOADED  '{sel}'", " ".join(lists.get(sel, []))
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
    if not ctx.triggered:
        return selected or []
    trigger = ctx.triggered[0]["prop_id"]
    selected = selected or []
    if "btn-clear" in trigger:
        return []
    if "graph-treemap" in trigger and treemap_click:
        pts = treemap_click.get("points", [])
        if pts:
            label = pts[0].get("label", "")
            if label and label != "Market" and not label.startswith("_"):
                return [t for t in selected if t != label] if label in selected else selected + [label]
        return selected
    if '"type":"bubble"' in trigger or '"type": "bubble"' in trigger:
        try:
            info = json.loads(trigger.replace(".n_clicks", ""))
            ticker = info.get("ticker", "")
            if ticker:
                return [t for t in selected if t != ticker] if ticker in selected else selected + [ticker]
        except Exception:
            pass
    return selected


@app.callback(
    Output("div-bubbles", "children"),
    Input("store-data",     "data"),
    Input("store-selected", "data"),
    Input("dd-period",      "value"),
)
def update_bubbles(store_json, selected, period):
    if not store_json:
        return [html.Div("▶  PRESS RUN TO LOAD DATA",
                          style={"color": MUTED, "fontSize": "10px",
                                 "letterSpacing": "2px", "padding": "10px"})]
    df  = pd.read_json(io.StringIO(store_json), orient="records")
    sel = selected or []
    return [_bubble(row, row["Ticker"] in sel, period) for _, row in df.iterrows()]


@app.callback(
    Output("graph-normalized", "figure"),
    Output("graph-price",      "figure"),
    Input("store-selected",    "data"),
    Input("dd-period",         "value"),
    prevent_initial_call=True,
)
def update_charts(selected, period):
    if not selected:
        return _empty_chart("CLICK BUBBLES TO COMPARE"), _empty_chart("SELECT A TICKER")
    return _build_charts(selected, period)


@app.callback(
    Output("graph-treemap", "figure"),
    Input("store-data",     "data"),
    Input("dd-period",      "value"),
)
def update_treemap(store_json, period):
    if not store_json:
        fig = _empty_chart("▶  RUN SCREENER TO LOAD DATA")
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
        return fig
    return _build_treemap(pd.read_json(io.StringIO(store_json), orient="records"), period)


@app.callback(
    Output("div-metrics-table", "children"),
    Input("store-data", "data"),
)
def update_metrics_table(store_json):
    if not store_json:
        return []
    df = pd.read_json(io.StringIO(store_json), orient="records")

    COLS = [
        ("Ticker",         "Ticker"),
        ("Price",          "Price"),
        ("1D %",           "1D %"),
        ("1W %",           "1W %"),
        ("1M %",           "1M %"),
        ("3M %",           "3M %"),
        ("6M %",           "6M %"),
        ("1Y %",           "1Y %"),
        ("Mkt Cap",        "Market Cap"),
        ("P/E",            "P/E"),
        ("Fwd P/E",        "Fwd P/E"),
        ("PEG",            "PEG"),
        ("EPS",            "EPS"),
        ("Rev Gr%",        "Rev Growth %"),
        ("Margin%",        "Profit Margin %"),
        ("52W Hi",         "52W High"),
        ("52W Lo",         "52W Low"),
        ("52W Pos%",       "52W Pos %"),
        ("Avg Vol",        "Avg Volume"),
    ]
    PCT_COLS = {"1D %", "1W %", "1M %", "3M %", "6M %", "1Y %"}

    display = pd.DataFrame()
    for label, col in COLS:
        if col not in df.columns:
            display[label] = "—"
            continue
        if col == "Price":
            display[label] = df[col].apply(lambda v: f"${v:.2f}" if pd.notna(v) else "—")
        elif col in PCT_COLS:
            display[label] = df[col].apply(lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
        elif col == "Market Cap":
            display[label] = df[col].apply(_large)
        elif col in ("Avg Volume",):
            def _vol(v):
                if pd.isna(v): return "—"
                if v >= 1e6: return f"{v/1e6:.1f}M"
                if v >= 1e3: return f"{v/1e3:.1f}K"
                return str(int(v))
            display[label] = df[col].apply(_vol)
        elif col in ("52W High", "52W Low"):
            display[label] = df[col].apply(lambda v: f"${v:.2f}" if pd.notna(v) else "—")
        else:
            display[label] = df[col].apply(lambda v: f"{v:.2f}" if pd.notna(v) else "—")

    pct_cond = []
    for lbl, col in COLS:
        if col not in PCT_COLS:
            continue
        # backtick-escape column IDs that contain spaces or special chars
        pct_cond += [
            {"if": {"filter_query": f'{{`{lbl}`}} contains "+"', "column_id": lbl},
             "color": GREEN},
            {"if": {"filter_query": f'{{`{lbl}`}} contains "-"', "column_id": lbl},
             "color": RED},
        ]

    table = dash_table.DataTable(
        data=display.to_dict("records"),
        columns=[{"name": lbl, "id": lbl} for lbl, _ in COLS],
        sort_action="native",
        style_table={"overflowX": "auto", "minWidth": "100%"},
        style_cell={
            "backgroundColor": PANEL, "color": TEXT,
            "fontFamily": FONT, "fontSize": "11px",
            "border": f"1px solid {BORDER}",
            "padding": "6px 10px", "whiteSpace": "nowrap",
            "textAlign": "right",
        },
        style_cell_conditional=[
            {"if": {"column_id": "Ticker"}, "textAlign": "left",
             "color": CYAN, "fontWeight": "bold", "letterSpacing": "1px"},
        ],
        style_header={
            "backgroundColor": SEL_BG, "color": MUTED,
            "fontFamily": FONT, "fontSize": "9px",
            "fontWeight": "normal", "letterSpacing": "1.5px",
            "border": f"1px solid {BORDER}", "textAlign": "right",
            "textTransform": "uppercase",
        },
        style_header_conditional=[
            {"if": {"column_id": "Ticker"}, "textAlign": "left"},
        ],
        style_data_conditional=pct_cond + [
            {"if": {"row_index": "odd"}, "backgroundColor": "#0a1828"},
        ],
        page_action="none",
    )
    return table

# ── FILTER CALLBACKS ──────────────────────────────────────────────────────────

FILTER_IDS = ["pe", "fpe", "peg", "eps", "revgr", "margin",
               "mcap", "vol", "w52", "p1m", "p3m", "p6m", "p1y"]
WATCHLIST_ONLY = {"w52", "p1m", "p3m", "p6m", "p1y"}
WATCHLIST_COL_MAP = {
    "pe":   "P/E",           "fpe":    "Fwd P/E",       "peg":    "PEG",
    "eps":  "EPS",           "revgr":  "Rev Growth %",  "margin": "Profit Margin %",
    "mcap": "Market Cap",    "vol":    "Avg Volume",
    "w52":  "52W Pos %",     "p1m":    "1M %",          "p3m":    "3M %",
    "p6m":  "6M %",          "p1y":    "1Y %",
}
WATCHLIST_SCALE = {"mcap": 1e9, "vol": 1e6}


@app.callback(
    Output("store-filter-data",   "data"),
    Output("store-filter-source", "data"),
    Output("filter-status",       "children"),
    Input("btn-filter-run",       "n_clicks"),
    State("filter-universe",      "value"),
    State("filter-input-tickers", "value"),
    *[State(f"f-{fid}-min", "value") for fid in FILTER_IDS],
    *[State(f"f-{fid}-max", "value") for fid in FILTER_IDS],
    prevent_initial_call=True,
)
def run_filter(_, universe, ticker_input, *filter_vals):
    mins = dict(zip(FILTER_IDS, filter_vals[:len(FILTER_IDS)]))
    maxs = dict(zip(FILTER_IDS, filter_vals[len(FILTER_IDS):]))

    if universe == "all":
        operands = build_yahoo_operands(mins, maxs)
        df = yahoo_screen(operands, max_results=1000)
        if df.empty:
            return no_update, no_update, "⚠  NO RESULTS FROM YAHOO SCREENER  (check filters or try again)"
        ts = pd.Timestamp.now().strftime("%H:%M:%S")
        return df.to_json(orient="records"), "all", \
               f"●  {len(df)} STOCKS MATCHED  //  NYSE + NASDAQ  //  {ts}  ·  sorted by market cap"

    # Watchlist mode
    tickers = ([t.strip().upper() for t in ticker_input.replace(",", " ").split() if t.strip()]
               if ticker_input and ticker_input.strip() else load_tickers())
    rows = []
    for i, sym in enumerate(tickers):
        row = fetch_ticker(sym)
        if row:
            rows.append(row)
        if i < len(tickers) - 1:
            time.sleep(0.3)
    if not rows:
        return no_update, no_update, "⚠  NO DATA RETRIEVED"
    df = pd.DataFrame(rows)
    before = len(df)
    mask = pd.Series(True, index=df.index)
    for fid, col in WATCHLIST_COL_MAP.items():
        scale = WATCHLIST_SCALE.get(fid, 1)
        lo, hi = mins.get(fid), maxs.get(fid)
        if lo is not None:
            mask &= df[col].fillna(-1e18) >= float(lo) * scale
        if hi is not None:
            mask &= df[col].fillna(1e18)  <= float(hi) * scale
    df = df[mask]
    ts = pd.Timestamp.now().strftime("%H:%M:%S")
    return df.to_json(orient="records"), "watchlist", \
           f"●  {len(df)} / {before} TICKERS PASSED FILTERS  //  {ts}"


@app.callback(
    Output("store-filter-selected", "data"),
    Input("btn-filter-clear", "n_clicks"),
    Input({"type": "filter-bubble", "ticker": ALL}, "n_clicks"),
    State("store-filter-selected", "data"),
    prevent_initial_call=True,
)
def update_filter_selection(_, _b, selected):
    ctx = callback_context
    if not ctx.triggered:
        return selected or []
    trigger  = ctx.triggered[0]["prop_id"]
    selected = selected or []
    if "btn-filter-clear" in trigger:
        return []
    if '"type":"filter-bubble"' in trigger or '"type": "filter-bubble"' in trigger:
        try:
            info   = json.loads(trigger.replace(".n_clicks", ""))
            ticker = info.get("ticker", "")
            if ticker:
                return [t for t in selected if t != ticker] if ticker in selected else selected + [ticker]
        except Exception:
            pass
    return selected


@app.callback(
    Output("div-filter-bubbles",    "children"),
    Input("store-filter-data",      "data"),
    Input("store-filter-source",    "data"),
    Input("store-filter-selected",  "data"),
    Input("filter-dd-period",       "value"),
)
def update_filter_bubbles(store_json, source, selected, period):
    if not store_json:
        return [html.Div("▶  SET FILTERS AND PRESS SCREEN",
                          style={"color": MUTED, "fontSize": "10px",
                                 "letterSpacing": "2px", "padding": "10px"})]
    df  = pd.read_json(io.StringIO(store_json), orient="records")
    sel = selected or []
    if df.empty:
        return [html.Div("NO STOCKS MATCHED THE FILTERS",
                          style={"color": RED, "fontSize": "11px", "padding": "10px"})]
    if source == "all":
        return [_allstocks_bubble(row, row["Ticker"] in sel) for _, row in df.iterrows()]
    return [_bubble(row, row["Ticker"] in sel, period, bubble_type="filter-bubble")
            for _, row in df.iterrows()]


@app.callback(
    Output("graph-filter-normalized", "figure"),
    Output("graph-filter-price",      "figure"),
    Input("store-filter-selected",    "data"),
    Input("filter-dd-period",         "value"),
    prevent_initial_call=True,
)
def update_filter_charts(selected, period):
    if not selected:
        return _empty_chart("CLICK BUBBLES TO COMPARE"), _empty_chart("SELECT A TICKER")
    return _build_charts(selected, period)


# ── Shared chart builders ─────────────────────────────────────────────────────

def _build_charts(selected, period):
    window    = HIST_WINDOW.get(period, "1y")
    days      = PERIOD_DAYS.get(period, 21)
    norm_fig  = go.Figure()
    price_fig = go.Figure()
    for i, ticker in enumerate(selected):
        closes = fetch_history(ticker, window)
        if closes is None or len(closes) < 2:
            continue
        color  = CHART_COLORS[i % len(CHART_COLORS)]
        sliced = closes.iloc[-min(days + 5, len(closes)):]
        norm_vals = (sliced / sliced.iloc[0] - 1) * 100
        norm_fig.add_trace(go.Scatter(
            x=sliced.index, y=norm_vals, mode="lines", name=ticker,
            line=dict(color=color, width=2),
            hovertemplate=f"<b>{ticker}</b>  %{{y:+.2f}}%<extra></extra>",
        ))
        price_fig.add_trace(go.Scatter(
            x=closes.index, y=closes.values, mode="lines", name=ticker,
            line=dict(color=color, width=2),
            hovertemplate=f"<b>{ticker}</b>  $%{{y:.2f}}<extra></extra>",
        ))
    norm_fig.add_hline(y=0, line_dash="dot", line_color=BORDER, line_width=1)
    norm_fig.update_layout(**_chart_layout(f"NORMALIZED %  //  {period}"))
    norm_fig.update_yaxes(ticksuffix="%")
    price_fig.update_layout(**_chart_layout("PRICE HISTORY"))
    price_fig.update_yaxes(tickprefix="$")
    return norm_fig, price_fig


def _build_treemap(df: pd.DataFrame, period: str) -> go.Figure:
    pct_col = f"{period} %"
    tdf = df.copy()
    tdf["_size"]   = tdf["Market Cap"].fillna(1e9).clip(lower=1e8)
    tdf["_pct"]    = tdf[pct_col].fillna(0)
    tdf["_sector"] = tdf["Sector"].fillna("Market") if "Sector" in tdf.columns else "Market"
    max_abs = tdf["_pct"].abs().max() or 1
    fig = px.treemap(
        tdf, path=["_sector", "Ticker"], values="_size", color="_pct",
        color_continuous_scale=[
            [0, "#6b0000"], [0.42, "#2a0000"], [0.5, PANEL],
            [0.58, "#002a10"], [1, "#006b2d"],
        ],
        range_color=[-max_abs, max_abs],
        custom_data=["_pct", "Ticker"],
    )
    fig.update_traces(
        texttemplate="<b>%{customdata[1]}</b><br>%{customdata[0]:+.1f}%",
        hovertemplate="<b>%{customdata[1]}</b>  %{customdata[0]:+.2f}%<extra></extra>",
        textfont=dict(size=13, family=FONT, color=TEXT),
        marker=dict(line=dict(color=BG, width=2)),
    )
    fig.update_layout(
        plot_bgcolor=PANEL, paper_bgcolor=BG, font=dict(color=TEXT, family=FONT),
        title=dict(text=f"MARKET MAP  //  {period} PERFORMANCE",
                   font=dict(size=10, color=MUTED), x=0.01),
        coloraxis_showscale=False,
        margin=dict(l=0, r=0, t=28, b=0),
    )
    return fig


# ── SECTOR CALLBACKS ─────────────────────────────────────────────────────────

@app.callback(
    Output("store-sector-name", "data"),
    Output("store-sector-data", "data"),
    Output("sector-status",     "children"),
    Input({"type": "sector-btn", "sector": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def run_sector_screen(_clicks):
    ctx = callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update
    trigger = ctx.triggered[0]["prop_id"]
    try:
        info   = json.loads(trigger.replace(".n_clicks", ""))
        sector = info.get("sector", "")
    except Exception:
        return no_update, no_update, no_update
    if not sector:
        return no_update, no_update, no_update
    df = yahoo_screen([{"operator": "EQ", "operands": ["sector", sector]}], max_results=20)
    if df.empty:
        return sector, no_update, f"⚠  NO RESULTS FOR {sector.upper()}  (try again)"
    ts = pd.Timestamp.now().strftime("%H:%M:%S")
    return (sector, df.to_json(orient="records"),
            f"●  TOP {len(df)} BY MARKET CAP  //  {sector.upper()}  //  {ts}")


@app.callback(
    Output({"type": "sector-btn", "sector": ALL}, "style"),
    Input("store-sector-name", "data"),
    State({"type": "sector-btn", "sector": ALL}, "id"),
)
def update_sector_btn_styles(selected, ids):
    return [_SECTOR_BTN_SEL if bid["sector"] == selected else _SECTOR_BTN_BASE
            for bid in ids]


@app.callback(
    Output("store-sector-selected", "data"),
    Input("btn-sector-clear", "n_clicks"),
    Input({"type": "sector-bubble", "ticker": ALL}, "n_clicks"),
    State("store-sector-selected", "data"),
    prevent_initial_call=True,
)
def update_sector_selection(_, _b, selected):
    ctx = callback_context
    if not ctx.triggered:
        return selected or []
    trigger  = ctx.triggered[0]["prop_id"]
    selected = selected or []
    if "btn-sector-clear" in trigger:
        return []
    if '"type":"sector-bubble"' in trigger or '"type": "sector-bubble"' in trigger:
        try:
            info   = json.loads(trigger.replace(".n_clicks", ""))
            ticker = info.get("ticker", "")
            if ticker:
                return [t for t in selected if t != ticker] if ticker in selected else selected + [ticker]
        except Exception:
            pass
    return selected


@app.callback(
    Output("div-sector-bubbles",       "children"),
    Output("graph-sector-normalized",  "figure"),
    Output("graph-sector-price",       "figure"),
    Output("div-sector-metrics-table", "children"),
    Input("store-sector-data",         "data"),
    Input("store-sector-selected",     "data"),
)
def update_sector_display(store_json, selected):
    sel = selected or []
    if not store_json:
        placeholder = html.Div("▶  SELECT A SECTOR ABOVE",
                               style={"color": MUTED, "fontSize": "10px",
                                      "letterSpacing": "2px", "padding": "10px"})
        return [placeholder], _empty_chart(""), _empty_chart(""), []

    df  = pd.read_json(io.StringIO(store_json), orient="records")
    valid = set(df["Ticker"].tolist())
    sel   = [t for t in sel if t in valid]

    bubbles = [_allstocks_bubble(row, row["Ticker"] in sel, bubble_type="sector-bubble")
               for _, row in df.iterrows()]

    if sel:
        norm_fig, price_fig = _build_charts(sel, "1M")
    else:
        norm_fig  = _empty_chart("CLICK BUBBLES TO COMPARE")
        price_fig = _empty_chart("SELECT A TICKER")

    return bubbles, norm_fig, price_fig, _make_sector_metrics_table(df)


# ── NEWS CALLBACKS ───────────────────────────────────────────────────────────

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
    ts = pd.Timestamp.now().strftime("%H:%M:%S")
    if not rows:
        return [], f"⚠  NO TICKERS FOUND IN {n_articles} ARTICLES  //  {ts}"
    return rows, (f"●  {len(rows)} STOCKS FROM {n_articles} ARTICLES  //  PAST {hours}H  //  "
                  f"{ts}  ·  ranked by mentions  ·  ▲ HOT = Yahoo trending")


@app.callback(
    Output("store-news-selected", "data"),
    Input("btn-news-clear", "n_clicks"),
    Input({"type": "news-bubble", "ticker": ALL}, "n_clicks"),
    State("store-news-selected", "data"),
    prevent_initial_call=True,
)
def update_news_selection(_, clicks, selected):
    ctx = callback_context
    if not ctx.triggered:
        return no_update
    trigger  = ctx.triggered[0]["prop_id"]
    selected = selected or []
    if trigger.startswith("btn-news-clear"):
        return []
    # bubbles are re-rendered on every selection change; ignore the n_clicks=0 re-mount
    if not ctx.triggered[0].get("value"):
        return no_update
    try:
        ticker = json.loads(trigger.rsplit(".", 1)[0]).get("ticker", "")
    except Exception:
        return no_update
    if not ticker:
        return no_update
    return [t for t in selected if t != ticker] if ticker in selected else selected + [ticker]


@app.callback(
    Output("div-news-bubbles", "children"),
    Input("store-news-data",     "data"),
    Input("store-news-selected", "data"),
)
def update_news_bubbles(rows, selected):
    if rows is None:
        return [html.Div("OPEN THIS TAB OR PRESS REFRESH TO LOAD NEWS",
                         style={"color": MUTED, "fontSize": "10px",
                                "letterSpacing": "2px", "padding": "10px"})]
    if not rows:
        return [html.Div("NO TRENDING STOCKS FOUND", style={"color": RED, "fontSize": "11px",
                                                           "padding": "10px"})]
    sel = set(selected or [])
    return [_news_bubble(r, r["Ticker"] in sel) for r in rows]


@app.callback(
    Output("graph-news-normalized", "figure"),
    Output("graph-news-price",      "figure"),
    Input("store-news-selected",    "data"),
    State("store-news-xrange",      "data"),
    prevent_initial_call=True,
)
def update_news_charts(selected, xrange):
    if not selected:
        return _empty_chart("CLICK CARDS TO COMPARE"), _empty_chart("SELECT A TICKER")
    return _build_news_charts(selected, xrange)


@app.callback(
    Output("div-news-headlines", "children"),
    Input("store-news-data",     "data"),
    Input("store-news-selected", "data"),
)
def update_news_headlines(rows, selected):
    if not rows:
        return []
    return _news_headlines(rows, selected or [])


# Browser-side: when either chart is zoomed / a range button is clicked, apply the same
# x-range to both charts, re-base the % chart to the first visible day, and refit y.
app.clientside_callback(
    """
    function(rdNorm, rdPrice, figNorm, figPrice, cur) {
        const NU = window.dash_clientside.no_update;
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered.length || !figNorm || !figPrice) return [NU, NU, NU];
        const trig = ctx.triggered[0].prop_id;
        const rd = trig.startsWith("graph-news-normalized") ? rdNorm : rdPrice;
        if (!rd || !figPrice.data || !figPrice.data.length) return [NU, NU, NU];

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
            figPrice.data.forEach(t => (t.x || []).forEach(x => {
                if (lo === null || x < lo) lo = x;
                if (hi === null || x > hi) hi = x;
            }));
            x0 = lo; x1 = hi;
        } else { return [NU, NU, NU]; }
        if (x0 == null || x1 == null) return [NU, NU, NU];
        const a = ms(x0), b = ms(x1);
        // Loop guard: nothing to do if both figures already show this window.
        const day = s => String(s).slice(0, 10);
        const same = f => {
            const r = f.layout && f.layout.xaxis && f.layout.xaxis.range;
            return r && day(r[0]) === day(x0) && day(r[1]) === day(x1);
        };
        if (same(figNorm) && same(figPrice)) return [NU, NU, NU];

        const pad = (lo, hi) => {
            if (lo === null) return null;
            const p = Math.max((hi - lo) * 0.06, Math.abs(hi) * 0.005, (hi - lo) < 1 ? 0.5 : 0);
            return [lo - p, hi + p];
        };
        const apply = (fig, isNorm) => {
            const f = JSON.parse(JSON.stringify(fig));
            let lo = null, hi = null;
            f.data.forEach(t => {
                const xs = t.x || [];
                if (isNorm && t.customdata) {
                    let i0 = xs.findIndex(x => ms(x) >= a);
                    if (i0 < 0) i0 = xs.length - 1;
                    const base = t.customdata[i0];
                    if (base) t.y = t.customdata.map(c => (c / base - 1) * 100);
                }
                xs.forEach((x, i) => {
                    const m = ms(x), y = t.y[i];
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
        };
        return [apply(figNorm, true), apply(figPrice, false), [x0, x1]];
    }
    """,
    Output("graph-news-normalized", "figure", allow_duplicate=True),
    Output("graph-news-price",      "figure", allow_duplicate=True),
    Output("store-news-xrange",     "data"),
    Input("graph-news-normalized",  "relayoutData"),
    Input("graph-news-price",       "relayoutData"),
    State("graph-news-normalized",  "figure"),
    State("graph-news-price",       "figure"),
    State("store-news-xrange",      "data"),
    prevent_initial_call=True,
)


if __name__ == "__main__":
    print(f"\n  Open on this machine : http://localhost:8050")
    print(f"  Open on phone/other  : http://{LOCAL_IP}:8050\n")
    app.run(debug=False, host="0.0.0.0", port=8050)
