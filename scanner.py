#!/usr/bin/env python3
"""Aurora Signal Desk - READ-ONLY scanner. Never places real orders."""
import os, sys, re, json, math, datetime as dt
from zoneinfo import ZoneInfo
import requests, feedparser

SYD = ZoneInfo("Australia/Sydney")
CFG = dict(capital_aud=500, risk_pct=0.02, min_score=70, min_rr=1.5, max_age_min=30,
           fee_per_side={"USD": 1.0, "AUD": 6.0},  # ESTIMATES - check IBKR's real fees and edit
           slip=0.001, max_day_move=0.06, paper_max_days=2, cooldown_h=24, expire_min=90)
# theme -> (keywords, tickers to check). The PRICE decides; news only nominates candidates.
THEMES = {
 "defence": (["defence", "defense", "pentagon", "military spending", "missile"], ["LMT", "RTX", "NOC", "ITA"]),
 "energy": (["oil", "opec", "drilling", "lng", "energy policy"], ["XOM", "CVX", "XLE", "WDS.AX", "STO.AX"]),
 "semiconductors": (["chip", "chips", "semiconductor", "export controls", "nvidia"], ["NVDA", "AMD", "SOXX", "TSM"]),
 "crypto": (["bitcoin", "crypto", "stablecoin"], ["COIN", "MSTR"]),
 "mining": (["gold", "copper", "lithium", "iron ore", "uranium"], ["BHP.AX", "RIO.AX", "FMG.AX", "PLS.AX", "GDX"]),
 "rates": (["rate cut", "rate hike", "interest rates", "inflation", "fed", "rba"], ["SPY", "QQQ", "IVV.AX"]),
 "pharma": (["fda", "approval", "clinical trial"], ["XBI", "LLY", "PFE"]),
 "geopolitics": (["war", "sanctions", "ceasefire", "tariff", "tariffs"], ["GLD", "ITA", "XLE", "FXI"]),
}
TRUSTED = ["reuters", "associated press", "bloomberg", "wall street journal", "financial times", "cnbc", "abc news", "financial review", "white house", "bbc"]
QUERIES = ["Trump tariffs", "Trump executive order", "Trump Truth Social", "White House announcement", "defence contract",
           "OPEC oil", "FDA approval", "central bank rates", "China export controls", "ASX mining"]
UA = {"User-Agent": "Mozilla/5.0"}

def now(): return dt.datetime.now(dt.timezone.utc)
def syd(t): return t.astimezone(SYD).strftime("%a %d %b %Y %I:%M %p %Z")
def load(p, d):
    try: return json.load(open(p))
    except Exception: return d
def save(p, o): json.dump(o, open(p, "w"), indent=1)

def bars(sym):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "5d", "interval": "5m"}, headers=UA, timeout=15).json()["chart"]["result"][0]
    q, out = r["indicators"]["quote"][0], []
    for i, t in enumerate(r["timestamp"]):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]): continue
        out.append(dict(t=t, o=q["open"][i], h=q["high"][i], l=q["low"][i], c=q["close"][i], v=q["volume"][i]))
    return out, r["meta"]

def rsi(c, n=14):
    if len(c) < n + 1: return 50
    g = sum(max(c[i] - c[i-1], 0) for i in range(-n, 0)) / n
    l = sum(max(c[i-1] - c[i], 0) for i in range(-n, 0)) / n
    return 100 if l == 0 else 100 - 100 / (1 + g / l)

def analyse(sym):
    b, meta = bars(sym)
    if len(b) < 30: return None
    sess = [x for x in b if x["t"] > b[-1]["t"] - 8 * 3600]
    tv = sum(x["v"] for x in sess)
    c = [x["c"] for x in b]
    return dict(c=c[-1], t=b[-1]["t"], age=(now().timestamp() - b[-1]["t"]) / 60, open=sess[0]["o"],
                vwap=sum((x["h"] + x["l"] + x["c"]) / 3 * x["v"] for x in sess) / tv if tv else c[-1],
                sma=sum(c[-20:]) / 20, rsi=rsi(c), atr=sum(x["h"] - x["l"] for x in b[-14:]) / 14,
                vr=(sum(x["v"] for x in b[-3:]) / 3) / max(sum(x["v"] for x in b[-63:-3]) / 60, 1),
                dv=sum(x["c"] * x["v"] for x in b[-12:]) / 12, ccy=meta.get("currency", "USD"),
                exch=meta.get("fullExchangeName") or meta.get("exchangeName", ""), name=meta.get("longName") or meta.get("shortName") or "")

def score(pts, a):
    s = pts
    s += 20 if a["c"] > a["vwap"] and a["c"] > a["sma"] else 0
    s += min(20, a["vr"] * 6.7)
    s += 15 if 50 <= a["rsi"] <= 68 else 7 if 45 <= a["rsi"] < 50 or 68 < a["rsi"] <= 75 else 0
    s += min(15, a["dv"] / 20000 * 15)
    return round(min(s, 100))

def events():
    seen, out, err = set(), [], 0
    for q in QUERIES:
        try:
            f = feedparser.parse(requests.get("https://news.google.com/rss/search", params={"q": q + " when:1d", "hl": "en-AU", "gl": "AU", "ceid": "AU:en"}, headers=UA, timeout=15).content)
        except Exception: err += 1; continue
        for e in f.entries[:15]:
            key = re.sub(r"[^a-z0-9]", "", e.title.lower())[:60]
            if key in seen: continue
            seen.add(key)
            tl, src = e.title.lower(), (e.get("source") or {}).get("title", "")
            th = [k for k, (kw, _) in THEMES.items() if any(re.search(r"\b" + re.escape(w) + r"\b", tl) for w in kw)]
            trump = "trump" in tl or "white house" in tl
            trusted = any(t in src.lower() for t in TRUSTED)
            if th: out.append(dict(key=key, title=e.title, source=src, link=e.link, themes=th, trump=trump, trusted=trusted,
                                   pts=12 + (10 if trump else 0) + (8 if trusted else 0)))
    return sorted(out, key=lambda x: -x["pts"]), err

def settle(st):
    keep = []
    for t in st["open"]:
        try: b, _ = bars(t["sym"])
        except Exception: keep.append(t); continue
        res = None
        for x in b:
            if x["t"] <= t["entry_t"]: continue
            if x["l"] <= t["stop"]: res = ("stop", min(t["stop"], x["o"]) * (1 - CFG["slip"])); break  # same-bar tie => stop (conservative)
            if x["h"] >= t["target"]: res = ("target", t["target"] * (1 - CFG["slip"])); break
        if not res and b and b[-1]["t"] - t["entry_t"] > CFG["paper_max_days"] * 86400: res = ("expired", b[-1]["c"])
        if res: st["closed"].append({**t, "exit": round(res[1], 4), "result": res[0], "pnl": round((res[1] - t["entry"]) * t["qty"] - t["fees"], 2)})
        else: keep.append(t)
    st["open"] = keep

def stats(closed):
    out = {}
    for ccy in {t["ccy"] for t in closed}:
        p = [t["pnl"] for t in closed if t["ccy"] == ccy]; w = [x for x in p if x > 0]; l = [x for x in p if x <= 0]
        cum = peak = dd = 0
        for x in p: cum += x; peak = max(peak, cum); dd = max(dd, peak - cum)
        out[ccy] = dict(trades=len(p), win_rate=round(100 * len(w) / len(p), 1), pnl=round(sum(p), 2), avg_win=round(sum(w) / len(w), 2) if w else 0,
                        avg_loss=round(sum(l) / len(l), 2) if l else 0, profit_factor=round(sum(w) / -sum(l), 2) if l and sum(l) < 0 else None, max_drawdown=round(dd, 2))
    by = {}
    for k in ("strategy", "theme", "exchange"):
        d = {}
        for t in closed:
            g = d.setdefault(f'{t[k]} ({t["ccy"]})', [0, 0]); g[0] += 1; g[1] = round(g[1] + t["pnl"], 2)
        by[k] = d
    return out, by

def msg(s, demo=False):
    c = "A$" if s["ccy"] == "AUD" else "US$"
    return (("🧪 DEMO - SAMPLE DATA, NOT A REAL SIGNAL\n" if demo else "") +
            f"🟢 AURORA SIGNAL DESK - CONFIRMED BUY (long only)\n\n{s['name']} ({s['sym']}) · {s['exchange']}\nEvent: {s['event']}\n"
            f"Setup quality: {s['score']}/100 (a rule-based score, NOT a probability)\nStrategy: {s['strategy']}\n"
            f"Entry ≈ {c}{s['entry']} | Stop {c}{s['stop']} | Target {c}{s['target']}\nReward/risk after costs: {s['rr']}:1\n"
            f"Shares: {s['qty']} | Est. costs {c}{s['costs']}\nNet profit at target: {c}{s['net_profit']} | Net loss at stop: {c}{s['net_loss']}\n"
            f"Why: {s['reason']}\nChart: {s['link']}\nNews: {s['news']}\nSignal: {s['time']}\nInvalid after: {s['expires']}\nPaper trade only - no real orders are placed.")

def tg(text):
    tok, cid = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and cid): return "not configured"
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json=dict(chat_id=cid, text=text, disable_web_page_preview=True), timeout=15)
        return "ok" if r.ok else f"error {r.status_code}"
    except Exception as x: return f"error {type(x).__name__}"

def demo():
    n = now()
    s = dict(sym="DEMO", name="Sample Defence Co", exchange="NASDAQ", ccy="USD", event="SAMPLE: new government defence contract", theme="defence",
             strategy="Aggressive momentum", score=85, entry=25.40, stop=24.60, target=26.80, rr=1.62, costs=2.0, qty=15, net_profit=19.0, net_loss=14.0,
             reason="SAMPLE: volume expansion and momentum after a verified announcement", link="https://finance.yahoo.com/quote/DEMO", news="https://example.com/sample",
             time=syd(n), expires=syd(n + dt.timedelta(minutes=CFG["expire_min"])))
    ev = [dict(title="SAMPLE: Trump announces new tariffs on imported chips", source="Sample Wire", link="#", themes=["semiconductors"], trump=True, trusted=True, pts=30)]
    closed = [dict(sym="DEMO", pnl=19.0, ccy="USD", strategy="Aggressive momentum", theme="defence", exchange="NASDAQ", result="target"),
              dict(sym="DEMO2", pnl=-14.0, ccy="USD", strategy="Conservative confirmation", theme="energy", exchange="NYSE", result="stop")]
    stt, by = stats(closed)
    save("docs/data.json", dict(mode="DEMO", generated=syd(n), signals=[s], events=ev, rejected=[dict(sym="SAMPLE", why="SAMPLE: costs would consume most of the reward")],
         paper=dict(stats=stt, by=by, open=[], closed=closed), health=dict(last_scan=syd(n), news="sample", telegram=tg(msg(s, True)), quote_errors=0)))
    if not os.path.exists("state.json"): save("state.json", dict(sent={}, open=[], closed=[]))

def scan():
    st = load("state.json", dict(sent={}, open=[], closed=[]))
    n = now(); settle(st)
    evs, nerr = events()
    try: fx = bars("AUDUSD=X")[0][-1]["c"]
    except Exception: fx = 0.65
    cand = {}
    for e in evs[:25]:
        for th in e["themes"]:
            for s in THEMES[th][1]:
                if s not in cand or e["pts"] > cand[s][0]["pts"]: cand[s] = (e, th)
    sigs, rej, qerr, tstat = [], [], 0, "no new signal"
    for sym, (e, th) in cand.items():
        try: a = analyse(sym)
        except Exception: qerr += 1; rej.append(dict(sym=sym, why="no quote data")); continue
        if not a: rej.append(dict(sym=sym, why="not enough price history")); continue
        sc = score(e["pts"], a); why = None
        if a["age"] > CFG["max_age_min"]: why = f"stale quote / market closed (last price {a['age']:.0f} min old)"
        elif a["c"] / a["open"] - 1 > CFG["max_day_move"]: why = "already moved too far today (chasing)"
        elif a["vr"] < 1.5: why = f"volume not confirmed ({a['vr']:.1f}x normal)"
        elif a["c"] < a["vwap"] or a["c"] < a["sma"]: why = "price not above VWAP and 20-bar average"
        elif sc < CFG["min_score"]: why = f"score {sc} below {CFG['min_score']}"
        if why: rej.append(dict(sym=sym, why=why, score=sc)); continue
        ccy = a["ccy"]; fee = 2 * CFG["fee_per_side"].get(ccy, 1.0)
        entry = a["c"] * (1 + CFG["slip"]); stop = entry - 1.5 * a["atr"]; target = entry + 4.0 * a["atr"]
        cap = CFG["capital_aud"] * (fx if ccy == "USD" else 1)
        qty = math.floor(min(cap * CFG["risk_pct"] / (entry - stop), cap / entry)) if entry > stop else 0
        if qty < 1: rej.append(dict(sym=sym, why="position size under 1 share", score=sc)); continue
        np_, nl = qty * (target - entry) - fee, qty * (entry - stop) + fee
        rr = np_ / nl if nl > 0 else 0
        if rr < CFG["min_rr"]: rej.append(dict(sym=sym, why=f"reward/risk after costs only {rr:.2f}", score=sc)); continue
        k = f"{sym}:{e['key']}"
        if n.timestamp() - st["sent"].get(k, 0) < CFG["cooldown_h"] * 3600: rej.append(dict(sym=sym, why="duplicate alert suppressed")); continue
        strat = "Aggressive momentum" if a["vr"] >= 2.5 else "Conservative confirmation"
        s = dict(sym=sym, name=a["name"], exchange=a["exch"], ccy=ccy, event=e["title"], theme=th, strategy=strat, score=sc, entry=round(entry, 3), stop=round(stop, 3),
                 target=round(target, 3), rr=round(rr, 2), costs=round(fee, 2), qty=qty, net_profit=round(np_, 2), net_loss=round(nl, 2),
                 reason=f"volume {a['vr']:.1f}x normal, above VWAP and 20-bar average, RSI {a['rsi']:.0f}" + (" (Trump-related)" if e["trump"] else ""),
                 link=f"https://finance.yahoo.com/quote/{sym}", news=e["link"], time=syd(n), expires=syd(n + dt.timedelta(minutes=CFG["expire_min"])),
                 aud_est=round(qty * entry / fx, 2) if ccy == "USD" else None)
        sigs.append(s); st["sent"][k] = n.timestamp(); tstat = tg(msg(s))
        st["open"].append(dict(sym=sym, ccy=ccy, entry=round(entry, 4), entry_t=a["t"], stop=s["stop"], target=s["target"], qty=qty, fees=round(fee, 2),
                               strategy=strat, theme=th, exchange=a["exch"], signal_time=s["time"]))
    st["closed"] = st["closed"][-500:]; stt, by = stats(st["closed"])
    save("state.json", st)
    save("docs/data.json", dict(mode="LIVE", generated=syd(n), fx_audusd=round(fx, 4), signals=sigs, events=evs[:20], rejected=rej[:40],
         paper=dict(stats=stt, by=by, open=st["open"], closed=st["closed"][-30:]),
         health=dict(last_scan=syd(n), news="ok" if nerr == 0 else f"{nerr} feeds failed", telegram=tstat, quote_errors=qerr)))

if __name__ == "__main__":
    demo() if "--demo" in sys.argv else scan()
