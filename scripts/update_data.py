"""
QQQM · SCHD 대시보드 데이터 갱신 스크립트
GitHub Actions가 1시간마다 실행해 data.json을 새로 만든다.
항목별로 따로 실행되며, 하나가 실패해도 그 항목은 직전 값을 유지한다.
"""
import json
import os
import statistics as st
import traceback
from datetime import date, datetime, timedelta, timezone

import requests
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data.json")
CFG_PATH = os.path.join(ROOT, "config.json")
KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

GROWTH = "QQQM"            # 성장 ETF 종목 코드 (바꾸려면 여기와 config.json, index.html을 함께 수정)
TICKERS = (GROWTH, "SCHD")

out = {}
if os.path.exists(DATA_PATH):
    with open(DATA_PATH, encoding="utf-8") as f:
        out = json.load(f)
cfg = {}
if os.path.exists(CFG_PATH):
    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

snap = out.setdefault("snap", {})
# 예전 QLD 버전에서 넘어온 값 정리
snap.pop("QLD", None)
out.get("div", {}).pop("QLD", None)
out.get("next", {}).pop("QLD", None)

errors = []


def step(name, fn):
    try:
        fn()
        print(f"[ OK ] {name}")
    except Exception as e:  # noqa: BLE001
        errors.append(name)
        print(f"[FAIL] {name}: {e}")
        traceback.print_exc()


def pctl(a, q):
    a = sorted(a)
    k = (len(a) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(a) - 1)
    return a[lo] + (a[hi] - a[lo]) * (k - lo)


# ---------------------------------------------------------------- 시세·일봉
def ohlc(tk):
    h = yf.Ticker(tk).history(period="1y", interval="1d", auto_adjust=False)
    h = h.dropna(subset=["Open", "High", "Low", "Close"])
    if len(h) < 100:
        raise ValueError(f"{tk} 일봉 부족: {len(h)}")
    def rnd(v):
        return round(float(v), 2)
    return [[d.strftime("%Y-%m-%d"), rnd(r.Open), rnd(r.High), rnd(r.Low), rnd(r.Close)]
            for d, r in h.iterrows()]


def update_prices():
    ndx, schd = ohlc("^NDX"), ohlc("SCHD")
    g = yf.Ticker(GROWTH).history(period="5d", interval="1d")
    out["ndx"], out["schd"] = ndx, schd
    snap["ndxClose"] = ndx[-1][4]
    snap["ndx52"] = [min(r[3] for r in ndx), max(r[2] for r in ndx)]
    snap["SCHD"] = schd[-1][4]
    snap[GROWTH] = round(float(g["Close"].dropna().iloc[-1]), 2)
    snap["asOf"] = ndx[-1][0]


def update_fx():
    h = yf.Ticker("KRW=X").history(period="5d", interval="1h")
    v = float(h["Close"].dropna().iloc[-1])
    if not 500 < v < 3000:
        raise ValueError(f"환율 값 이상: {v}")
    snap["fx"] = round(v, 2)
    snap["fxAsOf"] = datetime.now(KST).strftime("%m/%d %H:%M") + " Yahoo"


# ---------------------------------------------------------------- 배당
def dividend_series(tk):
    s = yf.Ticker(tk).dividends
    s = s[s > 0]
    return [(d.date(), float(v)) for d, v in s.items()]


def update_dividends():
    offsets = cfg.get("pay_offset_days", {"SCHD": 5, GROWTH: 4})
    pay_override = cfg.get("pay_dates", {})
    confirmed = cfg.get("confirmed", {})
    out.setdefault("div", {})
    out.setdefault("next", {})
    for tk in TICKERS:
        items = sorted(dividend_series(tk), key=lambda x: x[0], reverse=True)[:16]
        if len(items) < 8:
            raise ValueError(f"{tk} 배당 이력 부족")
        hist = []
        for ex, amt in items:
            exs = ex.isoformat()
            pay = pay_override.get(tk, {}).get(exs) or (ex + timedelta(days=offsets.get(tk, 5))).isoformat()
            hist.append([exs, pay, round(amt, 5)])
        out["div"][tk] = hist

        # 향후 4분기: 최근 4번의 배당을 52주(364일)씩 밀어 오늘 이후로 투영
        nxt = []
        for exs, pay, amt in hist[:4]:
            e, p = date.fromisoformat(exs), date.fromisoformat(pay)
            while e <= TODAY:
                e += timedelta(days=364)
                p += timedelta(days=364)
            nxt.append([e.isoformat(), p.isoformat(), False, amt])
        nxt.sort(key=lambda x: x[0])
        # config.json의 확정 일정으로 교체 (±25일 이내 후보)
        for c in confirmed.get(tk, []):
            ce = date.fromisoformat(c["ex"])
            if ce <= TODAY:
                continue
            best = min(nxt, key=lambda n: abs((date.fromisoformat(n[0]) - ce).days))
            if abs((date.fromisoformat(best[0]) - ce).days) <= 25:
                best[0], best[1], best[2] = c["ex"], c["pay"], True
                if c.get("amount"):
                    best[3] = float(c["amount"])
        out["next"][tk] = nxt


def update_yield_history():
    h = yf.Ticker("SCHD").history(start="2012-01-01", interval="1d", auto_adjust=False)
    by_year = {}
    for d, v in dividend_series("SCHD"):
        by_year[d.year] = by_year.get(d.year, 0) + v
    rows, lows, highs = [], [], []
    for y in range(2013, TODAY.year):
        yr = h[h.index.year == y]
        if yr.empty or y not in by_year:
            continue
        dv, dp = by_year[y], by_year.get(y - 1, by_year[y])
        rows.append([y, round(dv / float(yr["Close"].iloc[-1]) * 100, 2)])
        highs.append(dv / float(yr["High"].max()) * 100)
        lows.append((dv + dp) / 2 / float(yr["Low"].min()) * 100)
    ye = [r[1] for r in rows]
    out["yhist"] = rows
    out["yband"] = {"min": round(min(highs), 2), "p25": round(pctl(ye, .25), 2), "med": round(st.median(ye), 2),
                    "p75": round(pctl(ye, .75), 2), "max": round(max(lows), 2)}
    out["yhistRange"] = f"{rows[0][0]}~{rows[-1][0]}"


# ---------------------------------------------------------------- 나스닥 PER
def update_pe():
    j = requests.get("https://historyofmarket.com/api/ndx/forward-pe.json", headers=UA, timeout=30).json()
    cur = j["current"]
    snap["ttmPE"] = round(float(cur["trailing"]), 2)
    snap["fwdPE"] = round(float(cur.get("forwardOwn") or cur["forward"]), 2)
    weekly = [(d["date"], float(d["value"])) for d in j["forward"] if d["date"] >= "2006-07"]
    weekly += [(d["date"], float(d["value"])) for d in j.get("forwardOwn", [])]
    monthly = {}
    for d, v in sorted(weekly):
        monthly[d[:7]] = v                      # 그 달 마지막 관측값
    this_month = TODAY.strftime("%Y-%m")
    fpe = [[m, round(v, 2)] for m, v in sorted(monthly.items()) if m != this_month]
    out["fpe"] = fpe
    start10 = f"{TODAY.year - 10}-{TODAY.month:02d}"

    def stats(since):
        w = [v for d, v in weekly if d[:7] >= since]
        m = [v for d, v in fpe if d >= since]
        return {"min": round(min(w), 2), "p25": round(pctl(m, .25), 2), "med": round(st.median(m), 2),
                "p75": round(pctl(m, .75), 2), "max": round(max(w), 2)}
    out["fpeStats"] = {"all": stats("2006-07"), "10y": stats(start10)}
    out["fpe10yStart"] = start10


# ---------------------------------------------------------------- 공포탐욕지수
def update_fear_greed():
    r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                     headers={**UA, "Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"},
                     timeout=30)
    r.raise_for_status()
    fg = r.json()["fear_and_greed"]
    snap["fg"] = round(float(fg["score"]))
    snap["fgRows"] = [["현재", round(float(fg["score"]), 1)],
                      ["전일 마감", round(float(fg["previous_close"]), 1)],
                      ["1주 전", round(float(fg["previous_1_week"]), 1)],
                      ["1개월 전", round(float(fg["previous_1_month"]), 1)],
                      ["1년 전", round(float(fg["previous_1_year"]), 1)]]


# ---------------------------------------------------------------- 실행
step("시세·일봉", update_prices)
step("환율", update_fx)
step("배당 이력·일정", update_dividends)
step("SCHD 배당률 이력", update_yield_history)
step("나스닥 PER", update_pe)
step("공포탐욕지수", update_fear_greed)

out["tpeBand"] = cfg.get("tpe_band", out.get("tpeBand", {"min": 19.5, "med": 27.47, "max": 35.44}))
out["updatedAt"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
out["errors"] = errors

with open(DATA_PATH, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"data.json 저장 완료 · 실패 {len(errors)}건")
