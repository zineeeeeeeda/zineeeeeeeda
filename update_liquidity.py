from pathlib import Path
from datetime import datetime, timezone
import json
import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

# -----------------------------
# Data loaders
# -----------------------------
def fred_csv(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    df = pd.read_csv(url)
    df.columns = ["date", series_id]
    df["date"] = pd.to_datetime(df["date"])
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    return df.dropna().set_index("date")[series_id].sort_index()

def yahoo_close(ticker, period="3y"):
    df = yf.download(ticker, period=period, auto_adjust=False, progress=False)
    if df.empty:
        raise RuntimeError(f"No Yahoo data for {ticker}")
    c = df["Close"]
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    c.index = pd.to_datetime(c.index).tz_localize(None)
    return c.dropna().sort_index()

def defillama_stablecoin_history():
    # Public DefiLlama stablecoin history endpoint.
    url = "https://stablecoins.llama.fi/stablecoincharts/all"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    rows = r.json()
    out = []
    for row in rows:
        ts = row.get("date")
        total = row.get("totalCirculatingUSD", {})
        usd = total.get("peggedUSD")
        if ts is not None and usd is not None:
            out.append((pd.to_datetime(int(ts), unit="s"), float(usd)))
    if not out:
        raise RuntimeError("No DefiLlama stablecoin history returned")
    s = pd.Series(dict(out), name="stablecoin_mc").sort_index()
    return s

# -----------------------------
# Scoring
# -----------------------------
def percentile_last(s, lookback_days=730):
    s = s.dropna().sort_index()
    if s.empty:
        return np.nan
    cutoff = s.index.max() - pd.Timedelta(days=lookback_days)
    w = s[s.index >= cutoff]
    cur = float(w.iloc[-1])
    return float((w <= cur).mean() * 100)

def percentile_of_change(s, periods, lookback_days=730):
    d = s.diff(periods).dropna()
    return percentile_last(d, lookback_days)

def latest(s):
    s = s.dropna().sort_index()
    return float(s.iloc[-1]), s.index[-1].strftime("%Y-%m-%d")

def clamp(x):
    return float(max(0, min(100, x)))

# -----------------------------
# Fetch series
# -----------------------------
us10y = fred_csv("DGS10")           # %
tga_m = fred_csv("WTREGEN")         # $ millions, weekly average
rrp_b = fred_csv("RRPONTSYD")       # $ billions
sofr = fred_csv("SOFR")             # %
reserves_m = fred_csv("WRESBAL")     # $ millions, weekly

dxy = yahoo_close("DX-Y.NYB", "3y")
btc = yahoo_close("BTC-USD", "3y")
stable = defillama_stablecoin_history()

# -----------------------------
# Individual stress scores
# Higher score = tighter liquidity
# -----------------------------
s10 = percentile_last(us10y)
sdxy = percentile_last(dxy)
stga = percentile_last(tga_m)
ssofr = percentile_last(sofr)

# RRP has two effects:
# 1) FLOW: rising RRP is a liquidity drain; falling RRP is a release.
# 2) BUFFER: very low RRP means little remaining shock absorber.
srrp_flow = percentile_of_change(rrp_b, periods=20)
srrp_buffer = 100 - percentile_last(rrp_b)

# Risk-on / liquidity-positive variables are inverted.
sbtc = 100 - percentile_last(btc)
sstable = 100 - percentile_last(stable)

# Reserve balances: rising reserves are positive, so lower reserves = more stress.
sreserves = 100 - percentile_last(reserves_m)

weights = {
    "US10Y": 0.18,
    "DXY": 0.12,
    "TGA": 0.18,
    "RRP_FLOW": 0.10,
    "RRP_BUFFER": 0.10,
    "SOFR": 0.10,
    "STABLECOIN": 0.08,
    "BTC": 0.04,
    "RESERVES": 0.10,
}
scores = {
    "US10Y": s10,
    "DXY": sdxy,
    "TGA": stga,
    "RRP_FLOW": srrp_flow,
    "RRP_BUFFER": srrp_buffer,
    "SOFR": ssofr,
    "STABLECOIN": sstable,
    "BTC": sbtc,
    "RESERVES": sreserves,
}
valid_weight = sum(weights[k] for k,v in scores.items() if np.isfinite(v))
stress = sum(weights[k]*scores[k] for k in scores if np.isfinite(scores[k])) / valid_weight
stress = clamp(stress)

# Flow and buffer sub-indexes
flow_stress = clamp(np.nanmean([stga, srrp_flow, sreserves]))
buffer_stress = clamp(np.nanmean([srrp_buffer, sreserves, ssofr]))

def regime(score):
    if score >= 75: return "TIGHT LIQUIDITY"
    if score >= 60: return "RISK-OFF BIAS"
    if score >= 40: return "NEUTRAL"
    if score >= 25: return "RISK-ON BIAS"
    return "EASY LIQUIDITY"

# Latest values
v10, d10 = latest(us10y)
vdxy, ddxy = latest(dxy)
vtga, dtga = latest(tga_m)
vrrp, drrp = latest(rrp_b)
vsofr, dsofr = latest(sofr)
vstable, dstable = latest(stable)
vbtc, dbtc = latest(btc)
vres, dres = latest(reserves_m)

payload = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "stress": round(stress, 1),
    "flow_stress": round(flow_stress, 1),
    "buffer_stress": round(buffer_stress, 1),
    "regime": regime(stress),
    "metrics": {
        "US10Y": {"value": v10, "unit": "%", "asof": d10, "stress": round(s10,1)},
        "DXY": {"value": vdxy, "unit": "", "asof": ddxy, "stress": round(sdxy,1)},
        "TGA": {"value": vtga/1000, "unit": "$B", "asof": dtga, "stress": round(stga,1)},
        "ON_RRP": {"value": vrrp, "unit": "$B", "asof": drrp, "stress": round(srrp_buffer,1)},
        "SOFR": {"value": vsofr, "unit": "%", "asof": dsofr, "stress": round(ssofr,1)},
        "STABLECOIN": {"value": vstable/1e9, "unit": "$B", "asof": dstable, "stress": round(sstable,1)},
        "BTC": {"value": vbtc, "unit": "$", "asof": dbtc, "stress": round(sbtc,1)},
        "RESERVES": {"value": vres/1000, "unit": "$B", "asof": dres, "stress": round(sreserves,1)},
    },
    "scores": {k: round(float(v),1) for k,v in scores.items() if np.isfinite(v)},
    "weights": weights,
}

(DATA / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

# Append/update history for charting
hist_path = DATA / "history.csv"
row = pd.DataFrame([{
    "timestamp_utc": payload["generated_at_utc"],
    "stress": payload["stress"],
    "flow_stress": payload["flow_stress"],
    "buffer_stress": payload["buffer_stress"],
}])
if hist_path.exists():
    old = pd.read_csv(hist_path)
    out = pd.concat([old, row], ignore_index=True).tail(5000)
else:
    out = row
out.to_csv(hist_path, index=False)

print(json.dumps(payload, indent=2))
