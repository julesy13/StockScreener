import io
import json
import os
import socket
import time

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dash import Dash, dcc, html, Input, Output, State, callback_context, no_update, ALL
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
MUTED  = "#4a6888"
SEL_BG = "#041828"
FONT   = "'Courier New', 'Consolas', monospace"

PERIOD_OPTIONS = [
    {"label": "1D", "value": "1D"}, {"label": "1W", "value": "1W"},
    {"label": "1M", "value": "1M"}, {"label": "3M", "value": "3M"},
    {"label": "6M", "value": "6M"}, {"label": "1Y", "value": "1Y"},
]
PERIOD_DAYS  = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}
HIST_WINDOW  = {"1D": "5d", "1W": "1mo", "1M": "3mo", "3M": "6mo", "6M": "1y", "1Y": "2y"}
CHART_COLORS = [
    CYAN, "#ff6b35", "#a855f7", "#fbbf24", "#00ff99",
    "#f87171", "#60a5fa", "#fb923c", "#4ade80", "#e879f9",
    "#f472b6", "#38bdf8",
]

# ── Local IP ──────────────────────────────────────────────────────────────────
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

# ── Bubble card ───────────────────────────────────────────────────────────────
def _bubble(row, is_sel: bool, period: str, bubble_type="bubble") -> html.Div:
    ticker  = row["Ticker"]
    pct     = row.get(f"{period} %")
    pct1d   = row.get("1D %")
    valid   = pct is not None and not (isinstance(pct, float) and pct != pct)
    accent  = (GREEN if valid and pct >= 0 else RED) if valid else MUTED
    card_bg = ("#041a0c" if valid and pct >= 0 else "#1a0408") if valid else PANEL
    border  = f"2px solid {CYAN}" if is_sel else f"1px solid {accent}55"
    shadow  = (f"0 0 18px {CYAN}55, 0 0 6px {CYAN}33" if is_sel else f"0 0 10px {accent}22")
    p1d_clr = (GREEN if pct1d is not None and not (isinstance(pct1d, float) and pct1d != pct1d)
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
                html.Span(_pct(pct1d), style={"color": p1d_clr, "fontSize": "12px"}),
            ], style={"marginBottom": "6px"}),
            html.Div(_large(row.get("Market Cap")),
                     style={"color": MUTED, "fontSize": "10px",
                            "borderTop": f"1px solid {BORDER}", "paddingTop": "6px"}),
        ],
        style={
            "backgroundColor": card_bg, "border": border, "borderRadius": "8px",
            "padding": "12px 14px", "width": "164px", "minWidth": "164px",
            "cursor": "pointer", "boxShadow": shadow, "userSelect": "none",
        },
    )

# ── Filter number input pair ───────────────────────────────────────────────────
def _filter_row(label: str, id_prefix: str, unit: str = ""):
    lbl = f"{label} {unit}".strip()
    s   = _inp({"height": "28px", "padding": "2px 6px", "width": "90px",
                 "fontSize": "11px"})
    return html.Div([
        html.Div(lbl, style={"color": MUTED, "fontSize": "9px", "letterSpacing": "1px",
                              "marginBottom": "4px", "textTransform": "uppercase"}),
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

# ── Fetch history ─────────────────────────────────────────────────────────────
def fetch_history(symbol: str, window: str) -> pd.Series | None:
    try:
        hist = yf.Ticker(symbol).history(period=window)
        return hist["Close"] if not hist.empty else None
    except Exception:
        return None

# ── App ───────────────────────────────────────────────────────────────────────
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
        /* Tab overrides */
        .tab-content {{ background-color: {BG} !important; }}
        .rc-tabs-tab {{ background: {PANEL} !important; }}
    </style>
</head>
<body>
{{%app_entry%}}
<footer>{{%config%}}{{%scripts%}}{{%renderer%}}</footer>
</body>
</html>"""

# ── Screener tab layout ───────────────────────────────────────────────────────
screener_tab = html.Div([
    dcc.Store(id="store-data"),
    dcc.Store(id="store-selected", data=[]),

    # Controls row 1
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

    # Controls row 2: watchlists
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

    # 1. Bubble grid
    html.Div(
        html.Div(id="div-bubbles",
                 style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "padding": "14px"},
                 children=[html.Div("▶  PRESS RUN TO LOAD DATA",
                                     style={"color": MUTED, "fontSize": "10px",
                                            "letterSpacing": "2px", "padding": "10px"})]),
        className="cyber-panel mb-2",
    ),

    # 2. Charts
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

    # 3. Treemap
    html.Div(
        dcc.Graph(id="graph-treemap", config={"displayModeBar": False},
                  style={"height": "360px"}),
        className="cyber-panel",
    ),
], style={"paddingTop": "16px"})

# ── Filter tab layout ──────────────────────────────────────────────────────────
filter_tab = html.Div([
    dcc.Store(id="store-filter-data"),
    dcc.Store(id="store-filter-selected", data=[]),

    # Filter controls
    dbc.Row([
        dbc.Col(dcc.Textarea(
            id="filter-input-tickers",
            placeholder="AAPL MSFT NVDA …  (blank = tickers.txt)",
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

    # Filter cards grid
    dbc.Row([
        dbc.Col(_filter_card("VALUATION", [
            _filter_row("P/E",    "pe"),
            _filter_row("Fwd P/E","fpe"),
            _filter_row("PEG",    "peg"),
            _filter_row("EPS",    "eps"),
        ]), width=3),
        dbc.Col(_filter_card("GROWTH & MARGIN", [
            _filter_row("Revenue Growth", "revgr", "%"),
            _filter_row("Profit Margin",  "margin", "%"),
        ]), width=3),
        dbc.Col(_filter_card("SIZE & VOLUME", [
            _filter_row("Market Cap", "mcap", "$B"),
            _filter_row("Avg Volume", "vol",  "M"),
            _filter_row("52W Position", "w52", "%"),
        ]), width=3),
        dbc.Col(_filter_card("PERFORMANCE", [
            _filter_row("1D %",  "p1d"),
            _filter_row("1W %",  "p1w"),
            _filter_row("1M %",  "p1m"),
            _filter_row("3M %",  "p3m"),
            _filter_row("6M %",  "p6m"),
            _filter_row("1Y %",  "p1y"),
        ]), width=3),
    ], className="mb-3"),

    html.Div(id="filter-status",
             style={"color": MUTED, "fontSize": "9px", "letterSpacing": "2px",
                    "marginBottom": "10px"}),

    # Filter results
    html.Div(
        html.Div(id="div-filter-bubbles",
                 style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "padding": "14px"},
                 children=[html.Div("▶  SET FILTERS AND PRESS SCREEN",
                                     style={"color": MUTED, "fontSize": "10px",
                                            "letterSpacing": "2px", "padding": "10px"})]),
        className="cyber-panel mb-2",
    ),

    # Filter charts
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

# ── Root layout ───────────────────────────────────────────────────────────────
app.layout = dbc.Container(
    fluid=True,
    style={"backgroundColor": BG, "minHeight": "100vh", "padding": "12px 16px"},
    children=[
        dcc.Store(id="store-watchlists", data=load_watchlists()),

        # Header
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

        # Tabs
        dcc.Tabs(
            id="main-tabs",
            value="tab-screener",
            children=[
                dcc.Tab(label="SCREENER", value="tab-screener",
                        style=TAB_STYLE, selected_style=TAB_SELECTED,
                        children=screener_tab),
                dcc.Tab(label="FILTER", value="tab-filter",
                        style=TAB_STYLE, selected_style=TAB_SELECTED,
                        children=filter_tab),
            ],
            style={"border": "none"},
            colors={"border": BORDER, "primary": CYAN, "background": BG},
        ),
    ],
)


# ── SCREENER CALLBACKS ─────────────────────────────────────────────────────────

@app.callback(
    Output("store-data", "data"),
    Output("store-selected", "data"),
    Output("status-bar", "children"),
    Input("btn-run", "n_clicks"),
    State("input-tickers", "value"),
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
    Output("store-watchlists", "data"),
    Output("dd-watchlist", "options"),
    Output("list-status", "children"),
    Output("input-tickers", "value"),
    Input("btn-save-list", "n_clicks"),
    Input("btn-delete-list", "n_clicks"),
    Input("dd-watchlist", "value"),
    State("input-list-name", "value"),
    State("input-tickers", "value"),
    State("store-watchlists", "data"),
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
    Input("btn-clear", "n_clicks"),
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
    Input("store-data", "data"),
    Input("store-selected", "data"),
    Input("dd-period", "value"),
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
    Output("graph-price", "figure"),
    Input("store-selected", "data"),
    Input("dd-period", "value"),
    prevent_initial_call=True,
)
def update_charts(selected, period):
    if not selected:
        return _empty_chart("CLICK BUBBLES TO COMPARE"), _empty_chart("SELECT A TICKER")
    return _build_charts(selected, period)


@app.callback(
    Output("graph-treemap", "figure"),
    Input("store-data", "data"),
    Input("dd-period", "value"),
)
def update_treemap(store_json, period):
    if not store_json:
        fig = _empty_chart("▶  RUN SCREENER TO LOAD DATA")
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
        return fig
    return _build_treemap(pd.read_json(io.StringIO(store_json), orient="records"), period)


# ── FILTER CALLBACKS ──────────────────────────────────────────────────────────

FILTER_IDS = ["pe", "fpe", "peg", "eps", "revgr", "margin",
               "mcap", "vol", "w52", "p1d", "p1w", "p1m", "p3m", "p6m", "p1y"]

@app.callback(
    Output("store-filter-data", "data"),
    Output("filter-status", "children"),
    Input("btn-filter-run", "n_clicks"),
    State("filter-input-tickers", "value"),
    *[State(f"f-{fid}-min", "value") for fid in FILTER_IDS],
    *[State(f"f-{fid}-max", "value") for fid in FILTER_IDS],
    prevent_initial_call=True,
)
def run_filter(_, ticker_input, *filter_vals):
    # split min/max values
    mins = dict(zip(FILTER_IDS, filter_vals[:len(FILTER_IDS)]))
    maxs = dict(zip(FILTER_IDS, filter_vals[len(FILTER_IDS):]))

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
        return no_update, "⚠  NO DATA RETRIEVED"

    df = pd.DataFrame(rows)
    before = len(df)

    # apply filters
    COL_MAP = {
        "pe":     "P/E",         "fpe":    "Fwd P/E",    "peg":    "PEG",
        "eps":    "EPS",         "revgr":  "Rev Growth %","margin": "Profit Margin %",
        "mcap":   "Market Cap",  "vol":    "Avg Volume",  "w52":    "52W Pos %",
        "p1d":    "1D %",        "p1w":    "1W %",        "p1m":    "1M %",
        "p3m":    "3M %",        "p6m":    "6M %",        "p1y":    "1Y %",
    }
    SCALE = {"mcap": 1e9, "vol": 1e6}  # input units → raw units

    mask = pd.Series(True, index=df.index)
    for fid, col in COL_MAP.items():
        scale = SCALE.get(fid, 1)
        lo = mins.get(fid)
        hi = maxs.get(fid)
        if lo is not None:
            mask &= df[col].fillna(-1e18) >= float(lo) * scale
        if hi is not None:
            mask &= df[col].fillna(1e18) <= float(hi) * scale

    df = df[mask]
    ts = pd.Timestamp.now().strftime("%H:%M:%S")
    status = f"●  {len(df)} / {before} TICKERS PASSED FILTERS  //  {ts}"
    return df.to_json(orient="records"), status


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
    trigger = ctx.triggered[0]["prop_id"]
    selected = selected or []
    if "btn-filter-clear" in trigger:
        return []
    if '"type":"filter-bubble"' in trigger or '"type": "filter-bubble"' in trigger:
        try:
            info = json.loads(trigger.replace(".n_clicks", ""))
            ticker = info.get("ticker", "")
            if ticker:
                return [t for t in selected if t != ticker] if ticker in selected else selected + [ticker]
        except Exception:
            pass
    return selected


@app.callback(
    Output("div-filter-bubbles", "children"),
    Input("store-filter-data", "data"),
    Input("store-filter-selected", "data"),
    Input("filter-dd-period", "value"),
)
def update_filter_bubbles(store_json, selected, period):
    if not store_json:
        return [html.Div("▶  SET FILTERS AND PRESS SCREEN",
                          style={"color": MUTED, "fontSize": "10px",
                                 "letterSpacing": "2px", "padding": "10px"})]
    df  = pd.read_json(io.StringIO(store_json), orient="records")
    sel = selected or []
    if df.empty:
        return [html.Div("NO TICKERS PASSED THE FILTERS",
                          style={"color": RED, "fontSize": "11px", "padding": "10px"})]
    return [_bubble(row, row["Ticker"] in sel, period, bubble_type="filter-bubble")
            for _, row in df.iterrows()]


@app.callback(
    Output("graph-filter-normalized", "figure"),
    Output("graph-filter-price", "figure"),
    Input("store-filter-selected", "data"),
    Input("filter-dd-period", "value"),
    prevent_initial_call=True,
)
def update_filter_charts(selected, period):
    if not selected:
        return _empty_chart("CLICK BUBBLES TO COMPARE"), _empty_chart("SELECT A TICKER")
    return _build_charts(selected, period)


# ── Shared chart / treemap builders ──────────────────────────────────────────

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
        plot_bgcolor=PANEL, paper_bgcolor=BG,
        font=dict(color=TEXT, family=FONT),
        title=dict(text=f"MARKET MAP  //  {period} PERFORMANCE",
                   font=dict(size=10, color=MUTED), x=0.01),
        coloraxis_showscale=False,
        margin=dict(l=0, r=0, t=28, b=0),
    )
    return fig


if __name__ == "__main__":
    print(f"\n  Open on this machine : http://localhost:8050")
    print(f"  Open on phone/other  : http://{LOCAL_IP}:8050\n")
    app.run(debug=False, host="0.0.0.0", port=8050)
