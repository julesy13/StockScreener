"""Lesson library for the Learn tab.

Each lesson:
  id, title, track, minutes, summary, formula (optional),
  sections:  [(heading, text), ...]
  pitfalls:  [text, ...]
  example:   live-data spec rendered from the user's watchlist (optional)
             {"cols": [...], "metric": col, "label": str, "high_means": str, "fmt": kind}
  quiz:      [{"q", "options", "answer" (index), "why"}, ...]
"""

LESSONS = [
    # ── Valuation ─────────────────────────────────────────────────────────────
    {
        "id": "pe", "title": "Price-to-Earnings (P/E)", "track": "Valuation", "minutes": 4,
        "summary": "How many dollars investors pay today for one dollar of a company's annual profit.",
        "formula": "P/E = Share price ÷ Earnings per share (EPS)",
        "sections": [
            ("What it measures",
             "P/E tells you how expensive a stock is relative to its profits. A P/E of 20 means "
             "investors pay $20 for every $1 of yearly earnings — or, flipped around, the company "
             "'earns back' its price in about 20 years if profits never grew."),
            ("Trailing vs. forward",
             "Trailing P/E uses the last 12 months of reported EPS — real, audited numbers. Forward "
             "P/E uses analysts' estimates for the next 12 months. For fast-growing companies the "
             "forward P/E is much lower than the trailing one, because earnings are expected to "
             "rise. When forward P/E is higher than trailing, the market expects profits to fall."),
            ("How to read it",
             "There is no universal 'good' P/E. The S&P 500 has historically averaged roughly 15–20×. "
             "Fast growers and high-quality businesses command higher multiples; cyclical or "
             "slow-growing companies trade lower. Compare a company to its own history and to "
             "close peers, not to the whole market."),
        ],
        "pitfalls": [
            "Negative earnings make P/E meaningless — that's why loss-making companies show 'n/m'.",
            "One-off gains or write-downs can distort EPS for a year; check whether earnings are 'clean'.",
            "A low P/E can be a value trap: the market may be right that profits are about to shrink.",
        ],
        "example": {"cols": ["P/E", "Fwd P/E"], "metric": "Fwd P/E", "label": "forward P/E",
                    "high_means": "the market is paying the most per dollar of expected profit",
                    "fmt": "x", "positive_only": True},
        "quiz": [
            {"q": "A stock trades at $50 and earned $2.50 per share over the last year. What is its trailing P/E?",
             "options": ["12.5×", "20×", "25×", "50×"], "answer": 1,
             "why": "$50 ÷ $2.50 = 20. Investors pay $20 for each $1 of annual earnings."},
            {"q": "A company's forward P/E (15×) is far below its trailing P/E (40×). What does that usually imply?",
             "options": ["Earnings are expected to grow strongly", "The stock price is about to fall",
                         "The company lost money last year", "Analysts expect earnings to shrink"],
             "answer": 0,
             "why": "Same price, much lower multiple on next year's EPS means analysts expect EPS to rise substantially."},
            {"q": "Why is P/E not useful for a company that is losing money?",
             "options": ["The ratio becomes negative or meaningless", "Its share price is always zero",
                         "Exchanges don't allow it", "It is always exactly 1"],
             "answer": 0,
             "why": "With negative EPS the ratio is negative and can't be compared — use sales, cash flow or EV multiples instead."},
        ],
    },
    {
        "id": "peg", "title": "PEG Ratio", "track": "Valuation", "minutes": 3,
        "summary": "P/E adjusted for growth — a way to compare expensive-looking fast growers with cheap slow growers.",
        "formula": "PEG = P/E ÷ Expected annual EPS growth rate (%)",
        "sections": [
            ("Why it exists",
             "A P/E of 40 looks expensive next to a P/E of 15 — unless the first company is growing "
             "earnings 40% a year and the second 3%. PEG divides the P/E by the growth rate so you "
             "can compare them on one scale."),
            ("Rule of thumb",
             "Popularised by Peter Lynch: a PEG around 1 suggests the price is roughly in line with "
             "growth; well below 1 may be cheap for its growth; well above 2 means you're paying a "
             "lot for each unit of growth."),
        ],
        "pitfalls": [
            "The growth rate is an estimate — PEG is only as good as the forecast behind it.",
            "Yahoo's PEG uses a 5-year growth estimate; other sources use 1-year, so numbers differ.",
            "Meaningless for negative earnings or negative growth.",
        ],
        "example": {"cols": ["P/E", "PEG"], "metric": "PEG", "label": "PEG ratio",
                    "high_means": "you pay the most for each unit of expected growth",
                    "fmt": "num", "positive_only": True},
        "quiz": [
            {"q": "Company A: P/E 30, growth 30%/yr. Company B: P/E 12, growth 4%/yr. Which has the lower PEG?",
             "options": ["A (PEG 1.0)", "B (PEG 3.0)", "They're equal", "Can't tell"], "answer": 0,
             "why": "A: 30 ÷ 30 = 1.0. B: 12 ÷ 4 = 3.0. Despite the higher P/E, A is cheaper relative to its growth."},
            {"q": "What is the biggest weakness of the PEG ratio?",
             "options": ["It relies on forecast growth that may not happen", "It ignores the share price",
                         "It only works for banks", "It can't be calculated for large companies"],
             "answer": 0, "why": "Growth estimates are often wrong, especially far into the future."},
            {"q": "Roughly what PEG did Peter Lynch consider 'fairly valued'?",
             "options": ["About 1", "About 5", "About 0.1", "About 10"], "answer": 0,
             "why": "A PEG near 1 means the P/E roughly equals the growth rate."},
        ],
    },
    {
        "id": "ev", "title": "Market Cap vs. Enterprise Value", "track": "Valuation", "minutes": 4,
        "summary": "Market cap prices the shares; enterprise value prices the whole business, debts and cash included.",
        "formula": "Enterprise value = Market cap + Total debt − Cash",
        "sections": [
            ("The takeover view",
             "Imagine buying the entire company. You'd pay the market cap for the shares, but you'd "
             "also inherit its debt (which you must repay) and its cash (which you get to keep). "
             "Enterprise value (EV) is that true takeover price."),
            ("Why it matters",
             "Two companies with the same $10B market cap can be very different: one with $5B of net "
             "cash is effectively cheaper ($5B EV) than one with $5B of net debt ($15B EV). EV-based "
             "multiples like EV/EBITDA and EV/Sales let you compare companies with different "
             "balance sheets fairly."),
        ],
        "pitfalls": [
            "Cash held overseas or needed for operations isn't fully 'free' to the buyer.",
            "Leases, pensions and preferred stock are debt-like too; simple EV formulas skip them.",
        ],
        "example": {"cols": ["Market Cap", "EV", "Net Cash"], "metric": "Net Cash",
                    "label": "net cash (cash minus debt)",
                    "high_means": "the most cash cushion relative to debt — its EV is below its market cap",
                    "fmt": "money"},
        "quiz": [
            {"q": "Market cap $20B, debt $6B, cash $2B. What is the enterprise value?",
             "options": ["$24B", "$28B", "$16B", "$20B"], "answer": 0,
             "why": "$20B + $6B − $2B = $24B."},
            {"q": "If a company has more cash than debt, its enterprise value is…",
             "options": ["Lower than its market cap", "Higher than its market cap",
                         "Exactly equal to its market cap", "Always zero"], "answer": 0,
             "why": "Net cash is subtracted, so EV falls below the market cap."},
            {"q": "Why do analysts use EV/EBITDA instead of P/E when comparing companies?",
             "options": ["It neutralises differences in debt and cash", "It's always lower",
                         "It ignores profits", "Regulators require it"], "answer": 0,
             "why": "EV includes the capital structure, so heavily indebted and cash-rich firms compare fairly."},
        ],
    },
    {
        "id": "evebitda", "title": "EV/EBITDA", "track": "Valuation", "minutes": 4,
        "summary": "The go-to multiple on Wall Street for comparing businesses regardless of debt, taxes or accounting choices.",
        "formula": "EV/EBITDA = Enterprise value ÷ EBITDA (earnings before interest, taxes, depreciation & amortization)",
        "sections": [
            ("What EBITDA is",
             "EBITDA approximates the cash profit a business generates from operations before "
             "financing decisions (interest), tax jurisdictions and non-cash charges (depreciation "
             "and amortization). It's a rough, comparable measure of operating earning power."),
            ("How to read it",
             "Lower is cheaper. Mature industrial or utility businesses often trade around 8–12×; "
             "high-growth software can trade well above 25×. Private-equity buyers think in EV/EBITDA "
             "because it shows how many years of operating profit pay back the purchase price."),
        ],
        "pitfalls": [
            "EBITDA ignores capex. For capital-hungry businesses (fabs, power plants, telecoms) that flatters reality — check free cash flow too.",
            "Negative EBITDA makes the ratio meaningless ('n/m').",
            "'Adjusted EBITDA' in company presentations often excludes real costs like stock compensation.",
        ],
        "example": {"cols": ["EV/EBITDA"], "metric": "EV/EBITDA", "label": "EV/EBITDA",
                    "high_means": "the market is paying the most per dollar of operating profit",
                    "fmt": "x", "positive_only": True},
        "quiz": [
            {"q": "EV is $50B and EBITDA is $5B. What is EV/EBITDA?",
             "options": ["10×", "5×", "45×", "55×"], "answer": 0, "why": "$50B ÷ $5B = 10×."},
            {"q": "Which cost does EBITDA leave out that matters most for capital-intensive companies?",
             "options": ["Capital expenditure (and its depreciation)", "Salaries", "Rent", "Marketing"],
             "answer": 0,
             "why": "Depreciation is the accounting echo of capex; for factories or power plants it's a very real cost."},
            {"q": "Why do private-equity firms like EV/EBITDA?",
             "options": ["It shows roughly how many years of operating profit repay the full purchase price",
                         "It's required by the SEC", "It ignores debt entirely", "It's always below 5"],
             "answer": 0, "why": "EV is what you pay for the whole business; EBITDA is what it earns before financing."},
        ],
    },
    {
        "id": "fcfyield", "title": "Free Cash Flow Yield", "track": "Valuation", "minutes": 3,
        "summary": "The cash 'interest rate' the business pays you — free cash flow as a percentage of its market value.",
        "formula": "FCF yield = Free cash flow ÷ Market cap",
        "sections": [
            ("Why investors love it",
             "Earnings can be shaped by accounting choices; cash is harder to fake. FCF yield asks: "
             "if you bought the whole company, what percentage of your purchase price would come "
             "back to you as spare cash each year?"),
            ("How to read it",
             "Compare it with the 10-year Treasury yield. A 6% FCF yield on a stable business beats "
             "a 4% risk-free bond — and the cash flow can grow. Very fast growers often show low or "
             "negative FCF yields because they reinvest heavily; that can be fine if the "
             "reinvestment earns high returns."),
        ],
        "pitfalls": [
            "One year of FCF can be lumpy (big inventory build, tax timing). Look at multi-year trends.",
            "Stock-based compensation isn't deducted from FCF but does dilute shareholders.",
        ],
        "example": {"cols": ["FCF", "Market Cap", "FCF Yield %"], "metric": "FCF Yield %",
                    "label": "FCF yield",
                    "high_means": "the most free cash flow per dollar of market value",
                    "fmt": "pct"},
        "quiz": [
            {"q": "A $40B company generates $2B of free cash flow. What is its FCF yield?",
             "options": ["5%", "2%", "20%", "0.5%"], "answer": 0, "why": "$2B ÷ $40B = 5%."},
            {"q": "Negative FCF yield usually means…",
             "options": ["The company spent more cash than its operations generated",
                         "The stock is guaranteed to fall", "The company pays a dividend",
                         "It has no debt"], "answer": 0,
             "why": "Operating cash flow minus capex was negative — common for young or heavily investing companies."},
            {"q": "A useful benchmark to compare FCF yield against is…",
             "options": ["The 10-year Treasury yield", "The stock's P/E", "The VIX", "The company's age"],
             "answer": 0, "why": "Treasuries are the 'risk-free' return; a stock's cash yield should compensate for extra risk."},
        ],
    },
    {
        "id": "dcf", "title": "Intrinsic Value & DCF Basics", "track": "Valuation", "minutes": 6,
        "summary": "A business is worth the cash it will produce in the future, discounted back to today.",
        "formula": "Value = Σ  FCFₜ ÷ (1 + r)ᵗ  +  Terminal value ÷ (1 + r)ᴺ",
        "sections": [
            ("The core idea",
             "A dollar next year is worth less than a dollar today, because today's dollar could be "
             "invested. A discounted cash flow (DCF) model forecasts a company's free cash flows, "
             "then shrinks each future year's cash by a discount rate (r) to find what it's worth now."),
            ("The two big levers",
             "Growth assumptions and the discount rate dominate the answer. Raise the discount rate "
             "from 8% to 10% and long-duration growth stocks lose a big chunk of value — that's why "
             "rising interest rates hit high-multiple tech and speculative stocks hardest."),
            ("Terminal value",
             "Most of a DCF's value often sits in the 'terminal value' — everything beyond the "
             "explicit forecast years. Small changes to the long-run growth rate swing it a lot."),
        ],
        "pitfalls": [
            "Garbage in, garbage out: a DCF is a structured way to express assumptions, not a fact.",
            "If 80%+ of value comes from the terminal value, you're mostly betting on the distant future.",
        ],
        "example": None,
        "quiz": [
            {"q": "Why are future cash flows 'discounted' in a DCF?",
             "options": ["Money today is worth more than the same money later", "To reduce taxes",
                         "Because companies always shrink", "Regulations require it"], "answer": 0,
             "why": "Time value of money: cash now can be invested to earn a return."},
            {"q": "If interest rates (and so discount rates) rise, DCF values of long-duration growth stocks usually…",
             "options": ["Fall", "Rise", "Don't change", "Double"], "answer": 0,
             "why": "Their cash flows are far in the future, so a higher discount rate shrinks them the most."},
            {"q": "What is 'terminal value' in a DCF?",
             "options": ["The value of all cash flows beyond the explicit forecast period",
                         "The stock's lowest price", "The company's liquidation value", "Year-one revenue"],
             "answer": 0, "why": "It captures the business's value after the years you model in detail."},
        ],
    },
    # ── Cash & profitability ─────────────────────────────────────────────────
    {
        "id": "fcf", "title": "Free Cash Flow", "track": "Cash & profitability", "minutes": 4,
        "summary": "The cash left over after running and investing in the business — the money that can reward shareholders.",
        "formula": "Free cash flow = Operating cash flow − Capital expenditures",
        "sections": [
            ("Why it's the 'real' profit",
             "Net income follows accounting rules (accruals, depreciation, non-cash charges). Free "
             "cash flow is the actual cash generated after the company pays for the equipment, "
             "buildings and data centers it needs. It's what funds buybacks, dividends, "
             "acquisitions and debt repayment."),
            ("Reading the trend",
             "Rising FCF alongside rising revenue is the signature of a business that scales. "
             "Negative FCF isn't automatically bad — Amazon ran thin FCF for years while building "
             "its moat — but it needs a credible path to turning positive, and enough cash on hand "
             "to get there."),
        ],
        "pitfalls": [
            "Companies can boost FCF short-term by delaying capex or stretching supplier payments.",
            "Big AI/data-center build-outs (hyperscalers, utilities) can depress FCF for years even in great businesses.",
        ],
        "example": {"cols": ["FCF", "FCF Yield %"], "metric": "FCF", "label": "free cash flow",
                    "high_means": "the largest cash engine", "fmt": "money"},
        "quiz": [
            {"q": "Operating cash flow is $10B and capex is $3B. What is free cash flow?",
             "options": ["$7B", "$13B", "$3B", "$10B"], "answer": 0, "why": "$10B − $3B = $7B."},
            {"q": "Which is the best description of free cash flow?",
             "options": ["Cash available after funding operations and investment",
                         "Total revenue", "Cash sitting on the balance sheet", "Net income plus debt"],
             "answer": 0, "why": "It's the surplus the business generates after keeping itself running and growing."},
            {"q": "A company reports rising net income but falling free cash flow for several years. A good next step is to…",
             "options": ["Check working capital and capex trends for the cause",
                         "Assume the stock will double", "Ignore it — net income is what matters",
                         "Sell immediately"], "answer": 0,
             "why": "A gap between earnings and cash often hides receivables build-up, inventory or heavy capex."},
        ],
    },
    {
        "id": "margins", "title": "Gross, Operating & Net Margins", "track": "Cash & profitability", "minutes": 5,
        "summary": "How many cents of each sales dollar survive each layer of costs.",
        "formula": "Margin = Profit at that level ÷ Revenue",
        "sections": [
            ("Three layers",
             "Gross margin = (revenue − cost of goods) ÷ revenue: pricing power and production "
             "efficiency. Operating margin subtracts R&D, sales and admin costs: how efficient the "
             "whole operation is. Net margin is what's left after interest and taxes: the bottom line."),
            ("Typical ranges",
             "Software often has 70–85% gross margins; semiconductor designers 50–75%; hardware and "
             "manufacturing 20–40%; grocery retail below 30%. Compare within an industry."),
            ("Operating leverage",
             "When revenue grows faster than operating costs, operating margin expands — profits grow "
             "faster than sales. That's operating leverage, and it's why investors watch margin "
             "trends quarter by quarter."),
        ],
        "pitfalls": [
            "A one-time charge can crush net margin for a quarter without changing the business.",
            "Rising gross margin with falling operating margin means overhead is growing too fast.",
        ],
        "example": {"cols": ["Gross Margin %", "Op Margin %", "Profit Margin %"], "metric": "Op Margin %",
                    "label": "operating margin", "high_means": "the most efficient operation", "fmt": "pct"},
        "quiz": [
            {"q": "Revenue $100M, cost of goods $40M, operating expenses $35M. What is the operating margin?",
             "options": ["25%", "60%", "35%", "40%"], "answer": 0,
             "why": "Operating profit = 100 − 40 − 35 = $25M → 25%. (Gross margin would be 60%.)"},
            {"q": "Which margin best reflects pricing power over the product itself?",
             "options": ["Gross margin", "Net margin", "Dividend yield", "Operating margin"], "answer": 0,
             "why": "Gross margin compares price with the direct cost of making the product."},
            {"q": "Revenue grows 30% while operating costs grow 10%. Operating margin will most likely…",
             "options": ["Expand", "Shrink", "Stay exactly the same", "Turn negative"], "answer": 0,
             "why": "That's operating leverage: fixed-ish costs are spread over more revenue."},
        ],
    },
    {
        "id": "balance", "title": "Net Cash, Net Debt & Leverage", "track": "Cash & profitability", "minutes": 4,
        "summary": "Whether a company has a cushion or a burden — and how long it can survive a bad stretch.",
        "formula": "Net cash = Cash − Total debt   ·   Leverage = Net debt ÷ EBITDA",
        "sections": [
            ("Why it matters",
             "Debt amplifies outcomes. In good times leverage boosts returns; in bad times interest "
             "payments and maturities can force dilution or bankruptcy. Net cash companies can keep "
             "investing through downturns and buy weaker rivals."),
            ("Reading leverage",
             "Net debt ÷ EBITDA under ~2× is usually comfortable for a stable business; above ~4× is "
             "considered highly levered. Utilities and real estate carry more debt by design because "
             "their cash flows are predictable."),
            ("Cash runway",
             "For pre-profit companies (many quantum, nuclear and biotech names), divide cash by "
             "annual cash burn: that's the runway in years before they need to raise money."),
        ],
        "pitfalls": [
            "Debt maturing soon matters more than total debt — check when it's due.",
            "A big cash pile funded by recent share issuance means you were diluted to build it.",
        ],
        "example": {"cols": ["Cash", "Debt", "Net Cash"], "metric": "Net Cash", "label": "net cash",
                    "high_means": "the strongest balance sheet cushion", "fmt": "money"},
        "quiz": [
            {"q": "A pre-revenue company has $1.2B of cash and burns $300M a year. Roughly how long is its runway?",
             "options": ["4 years", "1 year", "12 years", "3 months"], "answer": 0,
             "why": "$1.2B ÷ $0.3B per year ≈ 4 years before it needs new money."},
            {"q": "Net debt of $8B and EBITDA of $2B gives leverage of…",
             "options": ["4× — fairly high", "0.25× — very low", "16×", "2×"], "answer": 0,
             "why": "$8B ÷ $2B = 4×, at the upper end of what most investors are comfortable with."},
            {"q": "Why can net-cash companies be advantaged in a recession?",
             "options": ["They can keep investing and buy weaker rivals", "They pay no taxes",
                         "Their stock can't fall", "They have no employees"], "answer": 0,
             "why": "No lenders to satisfy means freedom to play offense when others retrench."},
        ],
    },
    # ── Earnings & growth ────────────────────────────────────────────────────
    {
        "id": "eps", "title": "Earnings Per Share & Dilution", "track": "Earnings & growth", "minutes": 4,
        "summary": "Profit divided across every share — and how issuing new shares quietly shrinks your slice.",
        "formula": "EPS = Net income ÷ Weighted average shares outstanding",
        "sections": [
            ("Basic vs. diluted",
             "Basic EPS uses shares currently outstanding. Diluted EPS also counts shares that "
             "could be created from stock options, warrants and convertible bonds — the more "
             "conservative number, and the one most analysts quote."),
            ("Dilution",
             "If a company issues 10% more shares, each existing share owns 10% less of future "
             "profits. Fast-growing tech companies often pay employees heavily in stock; watch "
             "share count growth. Buybacks do the opposite and can lift EPS even when net income is flat."),
        ],
        "pitfalls": [
            "EPS can rise purely from buybacks while the underlying business stagnates.",
            "'Adjusted EPS' often excludes stock compensation — a real cost to shareholders.",
        ],
        "example": {"cols": ["EPS", "P/E"], "metric": "EPS", "label": "trailing EPS",
                    "high_means": "the most profit per share (not comparable across companies with different share prices)",
                    "fmt": "price"},
        "quiz": [
            {"q": "Net income $500M, 250M shares outstanding. What is EPS?",
             "options": ["$2.00", "$0.50", "$5.00", "$250"], "answer": 0, "why": "$500M ÷ 250M = $2.00."},
            {"q": "Net income stays flat, but the company buys back 5% of its shares. EPS will…",
             "options": ["Rise about 5%", "Fall about 5%", "Stay the same", "Go to zero"], "answer": 0,
             "why": "Same profit split across fewer shares."},
            {"q": "Why do analysts prefer diluted EPS?",
             "options": ["It includes shares that options and convertibles could create",
                         "It's always higher", "It ignores taxes", "It excludes interest"], "answer": 0,
             "why": "It's the conservative view of how many shares will share the profit."},
        ],
    },
    {
        "id": "surprise", "title": "Earnings Season: Beats, Misses & Guidance", "track": "Earnings & growth", "minutes": 4,
        "summary": "Why a stock can fall on 'great' results — the market trades on expectations, not absolutes.",
        "formula": "Surprise % = (Reported EPS − Consensus estimate) ÷ |Consensus estimate|",
        "sections": [
            ("Expectations are priced in",
             "Before each quarterly report, analysts publish estimates and the average becomes "
             "'consensus'. The stock price already reflects that consensus. What moves the price is "
             "the difference between results and expectations — and especially guidance."),
            ("Guidance matters most",
             "Management's outlook for the next quarter or year often outweighs the quarter just "
             "reported. A beat with lowered guidance frequently sends a stock down; a small miss "
             "with raised guidance can send it up."),
            ("Whisper numbers",
             "For heavily owned momentum stocks, investors often expect a beat of a certain size. "
             "Merely matching consensus can disappoint. Check the Deep Dive EPS chart to see a "
             "company's beat history."),
        ],
        "pitfalls": [
            "Companies often guide conservatively so they can 'beat' — a beat of 1–2% is barely news.",
            "Revenue quality matters: an EPS beat from a lower tax rate is weaker than one from sales growth.",
        ],
        "example": None,
        "quiz": [
            {"q": "Consensus EPS is $2.00 and the company reports $2.10. What is the surprise?",
             "options": ["+5%", "+10%", "+0.1%", "+21%"], "answer": 0, "why": "($2.10 − $2.00) ÷ $2.00 = 5%."},
            {"q": "A company beats estimates but cuts its full-year outlook. The stock most often…",
             "options": ["Falls", "Rises sharply", "Doesn't move", "Is halted permanently"], "answer": 0,
             "why": "Investors value the future; lower guidance resets expectations down."},
            {"q": "What is 'consensus' in earnings season?",
             "options": ["The average of analysts' estimates", "The company's own forecast",
                         "Last year's EPS", "The stock's P/E"], "answer": 0,
             "why": "It's the benchmark results are measured against."},
        ],
    },
    {
        "id": "revgrowth", "title": "Revenue Growth & CAGR", "track": "Earnings & growth", "minutes": 3,
        "summary": "The top line is where every story starts — and compounding is what turns growth into fortunes.",
        "formula": "CAGR = (Ending value ÷ Starting value)^(1 ÷ Years) − 1",
        "sections": [
            ("Why the top line",
             "Revenue is harder to manipulate than earnings and shows whether customers want more "
             "of what a company sells. Sustained double-digit growth is rare; most mature companies "
             "grow in line with the economy (low-to-mid single digits)."),
            ("Compound annual growth rate",
             "CAGR smooths a bumpy multi-year path into one annual rate. Revenue that goes from "
             "$1B to $2B in 5 years grew at about 14.9% per year — not 20% (100% ÷ 5), because "
             "growth compounds."),
            ("The rule of 72",
             "Divide 72 by the growth rate to estimate the years to double. At 24% a year, revenue "
             "doubles in about 3 years; at 8%, about 9 years."),
        ],
        "pitfalls": [
            "Acquisitions can inflate growth — look for 'organic' growth.",
            "Very high growth rates almost always slow; extrapolating them forever is the classic mistake.",
        ],
        "example": {"cols": ["Rev Growth %"], "metric": "Rev Growth %", "label": "year-over-year revenue growth",
                    "high_means": "the fastest-growing top line", "fmt": "pct"},
        "quiz": [
            {"q": "Revenue grows from $1B to $2B over 5 years. The CAGR is approximately…",
             "options": ["14.9%", "20%", "100%", "10%"], "answer": 0,
             "why": "2^(1/5) − 1 ≈ 14.9%. Compounding means you need less than 20% a year."},
            {"q": "Using the rule of 72, something growing 12% a year doubles in about…",
             "options": ["6 years", "12 years", "3 years", "72 years"], "answer": 0, "why": "72 ÷ 12 = 6."},
            {"q": "Why look at 'organic' growth?",
             "options": ["It excludes growth bought through acquisitions", "It's always higher",
                         "It only counts food companies", "It includes currency gains"], "answer": 0,
             "why": "It shows how fast the existing business is growing on its own."},
        ],
    },
    {
        "id": "rule40", "title": "The Rule of 40", "track": "Earnings & growth", "minutes": 3,
        "summary": "A quick health check for growth companies: growth plus profitability should add up to 40 or more.",
        "formula": "Rule of 40 score = Revenue growth % + Profit margin % (often FCF or operating margin)",
        "sections": [
            ("The trade-off",
             "Young companies can grow fast by spending heavily (low margins) or grow slower but "
             "profitably. The rule of 40 says a healthy growth business balances the two: 50% "
             "growth with −10% margins passes; 10% growth with 30% margins also passes."),
            ("Where it's used",
             "It began in software but is now applied to many growth stocks. A score above 40 is "
             "strong; elite companies post 60+. This app uses operating margin, so scores differ "
             "slightly from FCF-margin versions."),
        ],
        "pitfalls": [
            "It's a screen, not a valuation — a company can pass and still be overpriced.",
            "It breaks down for very early-stage or pre-revenue companies.",
        ],
        "example": {"cols": ["Rev Growth %", "Op Margin %", "Rule of 40"], "metric": "Rule of 40",
                    "label": "Rule of 40 score (growth + operating margin)",
                    "high_means": "the best balance of growth and profitability", "fmt": "num"},
        "quiz": [
            {"q": "Revenue growth 35%, operating margin 10%. Rule of 40 score?",
             "options": ["45 — passes", "25 — fails", "350", "3.5"], "answer": 0, "why": "35 + 10 = 45 ≥ 40."},
            {"q": "Which company passes the rule of 40?",
             "options": ["8% growth, 35% margin", "20% growth, 5% margin", "15% growth, 10% margin",
                         "30% growth, −15% margin"], "answer": 0, "why": "8 + 35 = 43. The others score 25, 25 and 15."},
            {"q": "The rule of 40 is best described as…",
             "options": ["A balance check between growth and profitability", "A valuation model",
                         "A tax rule", "A trading signal"], "answer": 0,
             "why": "It tells you whether growth is being bought efficiently, not what the stock is worth."},
        ],
    },
    # ── Risk & market structure ──────────────────────────────────────────────
    {
        "id": "beta", "title": "Beta & Volatility", "track": "Risk & market", "minutes": 3,
        "summary": "How much a stock tends to swing compared with the overall market.",
        "formula": "Beta ≈ how much the stock moves for each 1% move in the S&P 500",
        "sections": [
            ("Reading beta",
             "A beta of 1.0 moves in line with the market. Beta 1.5 tends to move 1.5% for every 1% "
             "market move — up and down. Utilities and staples often have betas below 1; "
             "semiconductors, small caps and speculative tech often sit well above 1."),
            ("Why it matters for a portfolio",
             "A watchlist full of high-beta names (AI semis, quantum, nuclear SMRs) will feel every "
             "market wobble amplified. Mixing in lower-beta holdings smooths the ride without "
             "necessarily sacrificing long-run returns."),
        ],
        "pitfalls": [
            "Beta is backward-looking; a company's risk can change quickly after news.",
            "Low beta doesn't mean low risk — a stock can fall on its own bad news while the market rises.",
        ],
        "example": {"cols": ["Beta"], "metric": "Beta", "label": "beta",
                    "high_means": "the biggest swings relative to the market", "fmt": "num"},
        "quiz": [
            {"q": "A stock with beta 2.0 when the market falls 3% would be expected to fall about…",
             "options": ["6%", "3%", "1.5%", "2%"], "answer": 0, "why": "2.0 × 3% = 6%."},
            {"q": "Which sector usually has the lowest beta?",
             "options": ["Utilities", "Semiconductors", "Quantum computing", "Crypto miners"], "answer": 0,
             "why": "Regulated, steady cash flows make utilities move less than the market."},
            {"q": "Beta measures…",
             "options": ["Sensitivity to overall market moves", "Profitability", "Dividend safety",
                         "Debt levels"], "answer": 0, "why": "It's a measure of market-related volatility."},
        ],
    },
    {
        "id": "short", "title": "Short Interest & Squeezes", "track": "Risk & market", "minutes": 4,
        "summary": "What it means when lots of investors are betting a stock will fall — and why that can backfire on them.",
        "formula": "Short interest % of float = Shares sold short ÷ Shares available to trade",
        "sections": [
            ("How shorting works",
             "A short seller borrows shares, sells them, and hopes to buy them back cheaper later. "
             "Their maximum gain is 100% (stock goes to zero) but their potential loss is unlimited."),
            ("Reading the number",
             "Under ~5% of float is normal. Above 10% signals meaningful skepticism; above 20% is "
             "crowded. Days-to-cover (short interest ÷ average daily volume) shows how long it "
             "would take shorts to exit."),
            ("Squeezes",
             "When a heavily shorted stock rises sharply, shorts rush to buy back shares to limit "
             "losses — and that buying pushes the price higher still. That's a short squeeze."),
        ],
        "pitfalls": [
            "High short interest is often right — short sellers do deep research.",
            "Short data is reported twice a month, so it lags.",
        ],
        "example": {"cols": ["Short %"], "metric": "Short %", "label": "short interest (% of float)",
                    "high_means": "the most bets against it", "fmt": "pct"},
        "quiz": [
            {"q": "What is the maximum loss on a short sale?",
             "options": ["Unlimited", "100%", "50%", "The borrow fee"], "answer": 0,
             "why": "A stock can keep rising indefinitely, so a short's loss has no ceiling."},
            {"q": "Short interest of 25% of float is generally considered…",
             "options": ["Very high / crowded", "Normal", "Low", "Impossible"], "answer": 0,
             "why": "Anything above ~20% means a large share of tradable stock is bet against."},
            {"q": "What fuels a short squeeze?",
             "options": ["Short sellers buying back shares as the price rises", "Dividend cuts",
                         "Index rebalancing only", "Lower trading volume"], "answer": 0,
             "why": "Forced buying from shorts adds fuel to a rally."},
        ],
    },
    {
        "id": "analysts", "title": "Analyst Ratings & Price Targets", "track": "Risk & market", "minutes": 4,
        "summary": "What Wall Street research is actually telling you — and how to read between the lines.",
        "formula": "Implied upside = Average price target ÷ Current price − 1",
        "sections": [
            ("The rating scale",
             "Sell-side analysts rate stocks Buy / Hold / Sell (or Overweight / Equal-weight / "
             "Underweight, Outperform / Market Perform). Ratings skew positive: 'Hold' is often a "
             "polite sell. Yahoo scores the average from 1 (Strong Buy) to 5 (Strong Sell)."),
            ("Price targets",
             "Targets are usually 12-month estimates. The spread between the low and high target "
             "tells you how much analysts disagree. Targets tend to chase the price — they get "
             "raised after rallies and cut after declines."),
            ("Changes matter more than levels",
             "An upgrade or downgrade (especially from a respected analyst) and estimate revisions "
             "move stocks more than the standing rating. The Analysts tab tracks exactly those changes."),
        ],
        "pitfalls": [
            "Analysts at banks may have relationships with the companies they cover.",
            "Very large implied upside often means the price has fallen faster than targets were cut.",
        ],
        "example": {"cols": ["Rating", "Target", "Upside %"], "metric": "Upside %",
                    "label": "implied upside to the average price target",
                    "high_means": "the biggest gap between price and analysts' targets", "fmt": "pct"},
        "quiz": [
            {"q": "Price $80, average target $100. What is the implied upside?",
             "options": ["25%", "20%", "80%", "8%"], "answer": 0, "why": "$100 ÷ $80 − 1 = 25%."},
            {"q": "On Yahoo's 1–5 scale, an average rating of 1.4 means…",
             "options": ["Strong Buy consensus", "Strong Sell consensus", "Hold", "No coverage"],
             "answer": 0, "why": "1 is Strong Buy and 5 is Strong Sell."},
            {"q": "What usually moves a stock more?",
             "options": ["A rating change or estimate revision", "A reiterated rating",
                         "The analyst's firm logo", "The number of analysts"], "answer": 0,
             "why": "New information — upgrades, downgrades, revisions — is what the market reacts to."},
        ],
    },
    {
        "id": "ma", "title": "Moving Averages (50-day & 200-day)", "track": "Risk & market", "minutes": 3,
        "summary": "The simplest trend tools — and the lines traders, funds and algorithms all watch.",
        "formula": "50-day MA = Average closing price over the last 50 trading days",
        "sections": [
            ("What they show",
             "A moving average smooths daily noise into a trend line. The 50-day tracks the "
             "intermediate trend; the 200-day tracks the long-term trend. Price above a rising "
             "200-day is generally considered a healthy uptrend."),
            ("Crosses",
             "When the 50-day crosses above the 200-day it's called a 'golden cross'; crossing "
             "below is a 'death cross'. They're lagging signals, but because so many participants "
             "watch them they can become self-fulfilling support or resistance levels."),
            ("In this app",
             "Select a single stock in any compare panel to see its 50- and 200-day averages drawn "
             "on the price chart."),
        ],
        "pitfalls": [
            "Moving averages lag — by the time a cross happens, much of the move has occurred.",
            "In choppy, sideways markets they produce many false signals.",
        ],
        "example": {"cols": ["vs 50D %", "vs 200D %"], "metric": "vs 200D %",
                    "label": "distance above/below the 200-day moving average",
                    "high_means": "the most extended above its long-term trend", "fmt": "pct"},
        "quiz": [
            {"q": "A 'golden cross' happens when…",
             "options": ["The 50-day MA crosses above the 200-day MA", "Price hits an all-time high",
                         "The 200-day crosses above the 50-day", "Volume doubles"], "answer": 0,
             "why": "Short-term trend overtaking the long-term trend is read as bullish."},
            {"q": "A stock trading 30% below its 200-day moving average is…",
             "options": ["In a strong downtrend", "In a strong uptrend", "Exactly at trend",
                         "Paying a dividend"], "answer": 0,
             "why": "Price far below the long-term average signals sustained weakness."},
            {"q": "The main weakness of moving-average signals is that they…",
             "options": ["Lag price", "Predict the future", "Ignore closing prices", "Only work on bonds"],
             "answer": 0, "why": "They're built from past prices, so they confirm trends late."},
        ],
    },
    {
        "id": "benchmark", "title": "Benchmarks & Relative Performance", "track": "Risk & market", "minutes": 3,
        "summary": "A 20% gain isn't impressive if the market gained 30% — always ask 'compared with what?'",
        "formula": "Relative return = Stock return − Benchmark return",
        "sections": [
            ("Why benchmark",
             "Professional investors are judged against an index: the S&P 500 for large US stocks, "
             "the Nasdaq-100 for tech, the Russell 2000 for small caps. Beating the benchmark "
             "after fees is 'alpha'; matching it is what a cheap index fund gives you for free."),
            ("In this app",
             "The dotted line on every '% change' chart is the S&P 500, and the Themes tab shows "
             "each basket's points ahead of or behind the index. If a stock can't beat the index "
             "over time, the index fund is the simpler holding."),
        ],
        "pitfalls": [
            "Pick a benchmark that matches the risk: comparing a small-cap biotech to the S&P 500 mixes apples and oranges.",
            "Short windows are noisy; judge relative performance over a full cycle.",
        ],
        "example": {"cols": ["1Y %", "vs S&P 1Y"], "metric": "vs S&P 1Y",
                    "label": "1-year return minus the S&P 500's",
                    "high_means": "the biggest outperformance versus the market", "fmt": "pct"},
        "quiz": [
            {"q": "Your stock rose 12% while the S&P 500 rose 18%. Relative performance is…",
             "options": ["−6 percentage points", "+12%", "+30%", "+6 percentage points"], "answer": 0,
             "why": "12 − 18 = −6. You made money but lagged the market."},
            {"q": "'Alpha' refers to…",
             "options": ["Return above the benchmark", "The first stock in an index", "A type of bond",
                         "Total dividends"], "answer": 0, "why": "It's excess return beyond what the benchmark delivered."},
            {"q": "Which benchmark best fits a portfolio of small US companies?",
             "options": ["Russell 2000", "Dow Jones Industrial Average", "Gold", "10-year Treasury"],
             "answer": 0, "why": "The Russell 2000 tracks US small caps."},
        ],
    },
    # ── Business quality ─────────────────────────────────────────────────────
    {
        "id": "moat", "title": "Competitive Moats", "track": "Business quality", "minutes": 5,
        "summary": "Why some companies keep earning high returns for decades while rivals get competed away.",
        "formula": None,
        "sections": [
            ("The idea",
             "Warren Buffett's term: a moat is a durable advantage that protects a business's "
             "profits from competition. High margins attract rivals; a moat keeps them out."),
            ("Five common sources",
             "1) Network effects — the product gets better as more people use it (marketplaces, "
             "social networks, payment networks). 2) Switching costs — it's painful to leave "
             "(enterprise software, chip design ecosystems like CUDA). 3) Cost advantages — scale "
             "or unique assets let them produce cheaper. 4) Intangibles — brands, patents, "
             "regulatory licenses (nuclear permits!). 5) Efficient scale — a market only supports "
             "one or two players."),
            ("Spotting a moat in the numbers",
             "Look for high and stable gross margins, returns on capital well above peers for many "
             "years, and market share that holds up even when competitors cut prices."),
        ],
        "pitfalls": [
            "Technology shifts can drain a moat fast (think film cameras or flip phones).",
            "A great moat at a terrible price can still be a bad investment.",
        ],
        "example": {"cols": ["Gross Margin %", "Op Margin %"], "metric": "Gross Margin %",
                    "label": "gross margin (a common moat footprint)",
                    "high_means": "the strongest pricing power — a possible moat signal", "fmt": "pct"},
        "quiz": [
            {"q": "A payment network that becomes more valuable as more merchants and cardholders join has which moat?",
             "options": ["Network effect", "Cost advantage", "Efficient scale", "No moat"], "answer": 0,
             "why": "Each new user adds value for every other user."},
            {"q": "Developers building on one chip company's software stack and reluctant to rewrite code for a rival is an example of…",
             "options": ["Switching costs", "Brand", "Efficient scale", "Dilution"], "answer": 0,
             "why": "The cost and risk of moving away locks customers in."},
            {"q": "Which financial pattern most suggests a moat?",
             "options": ["High, stable margins and returns sustained for years", "One great quarter",
                         "A falling share count", "High short interest"], "answer": 0,
             "why": "Competition normally erodes excess returns; persistence signals protection."},
        ],
    },
]

TRACKS = ["Valuation", "Cash & profitability", "Earnings & growth", "Risk & market", "Business quality"]
LESSON_BY_ID = {l["id"]: l for l in LESSONS}
