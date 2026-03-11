#!/usr/bin/env python3
"""
PolyEdge — Live Polymarket Mispricing Scanner
=============================================
Requires: Python 3.8+ (no external installs needed)
Uses:     Google Gemini API (FREE — get key at aistudio.google.com)

Usage:
  1. Set your Gemini API key below (or as env var GROQ_API_KEY)
  2. Run:  python polyedge_server.py
  3. Open: http://localhost:8765
"""

import http.server
import json
import urllib.request
import urllib.error
import os
import threading
import time
from datetime import datetime

# ──────────────────────────────────────────────
#  CONFIG — paste your FREE Gemini key here
#  Get one at: aistudio.google.com → Get API Key
# ──────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "YOUR_GROQ_KEY_HERE")
GROQ_MODEL = "llama-3.3-70b-versatile"  # free, fast, powerful
PORT = int(os.environ.get("PORT", 8765))  # Render sets PORT automatically

# ──────────────────────────────────────────────
#  Fetch live markets from Polymarket Gamma API
# ──────────────────────────────────────────────
def fetch_markets():
    url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=40&order=volume&ascending=false"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "PolyEdge/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    markets = []
    for m in data:
        if not m.get("question") or not m.get("outcomePrices"):
            continue
        try:
            prices = json.loads(m["outcomePrices"])
            yes_price = float(prices[0])
            volume = float(m.get("volume", 0) or 0)
            if yes_price < 0.05 or yes_price > 0.97 or volume < 500:
                continue
            markets.append({
                "question": m["question"],
                "yesPrice": yes_price,
                "noPrice": float(prices[1]) if len(prices) > 1 else round(1 - yes_price, 4),
                "volume": volume,
                "liquidity": float(m.get("liquidity", 0) or 0),
                "endDate": m.get("endDate", ""),
                "category": m.get("category", "General") or "General",
                "resolutionSource": m.get("resolutionSource", "") or "",
                "slug": m.get("slug", "") or "",
            })
        except Exception:
            continue

    return markets[:25]

# ──────────────────────────────────────────────
#  Run AI analysis via Groq API (FREE)
# ──────────────────────────────────────────────
def analyze_markets(markets, capital=20, min_edge=10):
    today = datetime.now().strftime("%B %d, %Y")

    market_lines = []
    for i, m in enumerate(markets):
        end_str = m["endDate"][:10] if m["endDate"] else "unknown"
        market_lines.append(
            f'{i+1}. "{m["question"]}" | YES: {round(m["yesPrice"]*100)}¢ '
            f'| Vol: ${int(m["volume"]):,} | Ends: {end_str} '
            f'| Category: {m["category"]} | Resolution: {m["resolutionSource"] or "not specified"}'
        )

    prompt = f"""You are an expert prediction market analyst specializing in finding mispriced markets on Polymarket.

Today's date: {today}

Analyze these live Polymarket markets and identify the BEST mispricing opportunities. Focus on:
- Markets where crowd price seems wrong based on current world knowledge
- Resolution criteria misreads (e.g. "any day" vs "end of period")
- Recent news/events that changed probability but price has not updated
- Low volume markets where casual bettors misprice

Capital: ${capital} | Minimum edge to flag: {min_edge}%

Markets:
{chr(10).join(market_lines)}

Return ONLY a JSON array of opportunities worth flagging (skip fairly priced markets).
Only include markets with {min_edge}%+ estimated edge.

Respond with a raw JSON array ONLY. No backticks, no markdown, no explanation, no preamble. Start your response with [ and end with ].

Schema:
[
  {{
    "question": "exact market question text",
    "currentPrice": 0.72,
    "estimatedTrueProb": 0.88,
    "edgeLevel": "HIGH",
    "recommendation": "BUY YES",
    "expectedProfit": 8.50,
    "reasoning": "2 sentences max: why mispriced",
    "resolutionInsight": "specific resolution or news insight, or null",
    "riskNote": "key risk in 1 sentence",
    "category": "Sports"
  }}
]

edgeLevel: HIGH (15%+ edge) | MEDIUM (10-15%) | LOW (<10%)
recommendation: BUY YES | BUY NO | WATCH | AVOID"""

    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2048,
    }).encode()

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    raw = result["choices"][0]["message"]["content"]
    raw = raw.strip().replace("```json", "").replace("```", "").strip()

    # Extract JSON array robustly
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start == -1 or end == 0:
        return []
    return json.loads(raw[start:end])

# ──────────────────────────────────────────────
#  HTTP Handler
# ──────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress default request logging

    def send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_html(HTML)
        elif self.path == "/api/status":
            self.send_json(200, {"status": "ok", "apiKeySet": GROQ_API_KEY != "YOUR_GROQ_KEY_HERE"})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/api/scan":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                capital = float(body.get("capital", 20))
                min_edge = int(body.get("minEdge", 10))

                if GROQ_API_KEY == "YOUR_GROQ_KEY_HERE":
                    self.send_json(400, {"error": "Groq API key not set. Edit polyedge_server.py and set GROQ_API_KEY."})
                    return

                print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching markets...")
                markets = fetch_markets()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetched {len(markets)} markets. Running AI analysis...")

                opportunities = analyze_markets(markets, capital, min_edge)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(opportunities)} opportunities.")

                self.send_json(200, {
                    "opportunities": opportunities,
                    "marketsScanned": len(markets),
                    "timestamp": datetime.now().isoformat()
                })

            except urllib.error.HTTPError as e:
                err_body = e.read().decode()
                print(f"API error: {e.code} {err_body}")
                self.send_json(500, {"error": f"API error {e.code}: {err_body[:200]}"})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json(500, {"error": str(e)})
        else:
            self.send_json(404, {"error": "Not found"})

# ──────────────────────────────────────────────
#  Frontend HTML (served at /)
# ──────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PolyEdge — Live Scanner</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#060608;--surface:#0d0d12;--card:#0f0f18;--border:#1a1a28;--border2:#242436;
  --green:#00e676;--yellow:#ffd600;--red:#ff1744;--blue:#448aff;--purple:#e040fb;
  --text:#e0e0f0;--muted:#44445a;--muted2:#666680;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh;}
body::after{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.025) 2px,rgba(0,0,0,0.025) 4px);pointer-events:none;z-index:9999;}

.topbar{display:flex;align-items:center;justify-content:space-between;padding:0.7rem 1.5rem;border-bottom:1px solid var(--border);background:var(--surface);position:sticky;top:0;z-index:100;}
.logo{font-family:'Bebas Neue',sans-serif;font-size:1.6rem;letter-spacing:3px;color:var(--green);text-shadow:0 0 20px rgba(0,230,118,0.5);}
.logo span{color:var(--text);}
.status-row{display:flex;align-items:center;gap:0.8rem;}
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:blink 1.2s ease-in-out infinite;}
.live-dot.off{background:var(--muted);box-shadow:none;animation:none;}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.3}}
.status-text{font-family:'IBM Plex Mono',monospace;font-size:0.65rem;color:var(--muted2);letter-spacing:1px;}
.next-scan{font-family:'IBM Plex Mono',monospace;font-size:0.65rem;color:var(--green);}

.controls{display:flex;align-items:center;gap:0.75rem;padding:0.7rem 1.5rem;border-bottom:1px solid var(--border);background:var(--surface);flex-wrap:wrap;}
.ctrl-label{font-family:'IBM Plex Mono',monospace;font-size:0.6rem;color:var(--muted2);letter-spacing:1px;text-transform:uppercase;}
select,input[type=number]{background:var(--card);border:1px solid var(--border2);color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:0.75rem;padding:0.35rem 0.6rem;border-radius:5px;outline:none;}
input[type=number]{width:65px;}
select:focus,input[type=number]:focus{border-color:var(--green);}
.btn{font-family:'DM Sans',sans-serif;font-weight:600;font-size:0.78rem;padding:0.4rem 1rem;border-radius:5px;border:none;cursor:pointer;transition:all 0.15s;}
.btn-primary{background:var(--green);color:#000;}
.btn-primary:hover{background:#33ff8a;box-shadow:0 0 15px rgba(0,230,118,0.4);}
.btn-primary:disabled{opacity:0.4;cursor:not-allowed;}
.btn-ghost{background:transparent;color:var(--muted2);border:1px solid var(--border2);}
.btn-ghost:hover{color:var(--text);border-color:var(--muted2);}
.filter-tabs{display:flex;gap:0.3rem;margin-left:auto;}
.tab{font-family:'IBM Plex Mono',monospace;font-size:0.62rem;padding:0.3rem 0.7rem;border-radius:4px;border:1px solid var(--border2);background:transparent;color:var(--muted2);cursor:pointer;transition:all 0.15s;}
.tab.active{background:var(--green);color:#000;border-color:var(--green);font-weight:700;}
.tab:hover:not(.active){color:var(--text);}

.main{display:grid;grid-template-columns:240px 1fr;min-height:calc(100vh - 100px);}
.sidebar{border-right:1px solid var(--border);padding:1rem;background:var(--surface);}
.sidebar-title{font-family:'IBM Plex Mono',monospace;font-size:0.58rem;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:0.6rem;padding-bottom:0.4rem;border-bottom:1px solid var(--border);}
.sidebar-section{margin-bottom:1.5rem;}
.stat-row{display:flex;justify-content:space-between;align-items:baseline;padding:0.3rem 0;}
.stat-name{font-size:0.75rem;color:var(--muted2);}
.stat-val{font-family:'IBM Plex Mono',monospace;font-size:0.82rem;font-weight:700;}
.green{color:var(--green);}.yellow{color:var(--yellow);}.red{color:var(--red);}.muted{color:var(--muted2);}
.cat-item{display:flex;justify-content:space-between;padding:0.3rem 0.5rem;border-radius:4px;cursor:pointer;transition:background 0.1s;}
.cat-item:hover{background:var(--card);}
.cat-item.active{background:rgba(0,230,118,0.08);}
.cat-name{font-size:0.75rem;color:var(--muted2);}
.cat-item.active .cat-name{color:var(--green);}
.cat-count{font-family:'IBM Plex Mono',monospace;font-size:0.65rem;color:var(--muted);background:var(--border);padding:0.1rem 0.4rem;border-radius:3px;}

.content{padding:1rem 1.25rem;overflow-y:auto;}
.cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:0.75rem;}

.state-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:320px;gap:1rem;color:var(--muted2);}
.spinner{width:40px;height:40px;border:2px solid var(--border2);border-top-color:var(--green);border-radius:50%;animation:spin 0.7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
.state-label{font-family:'IBM Plex Mono',monospace;font-size:0.7rem;letter-spacing:2px;color:var(--green);animation:blink 1.5s infinite;}
.state-sub{font-size:0.8rem;color:var(--muted);text-align:center;max-width:300px;line-height:1.6;}
.progress-bar{width:200px;height:2px;background:var(--border2);border-radius:2px;overflow:hidden;}
.progress-fill{height:100%;background:var(--green);border-radius:2px;transition:width 0.4s ease;box-shadow:0 0 8px var(--green);}

.opp-card{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;transition:border-color 0.2s,transform 0.15s;animation:fadeUp 0.3s ease forwards;opacity:0;cursor:pointer;position:relative;}
.opp-card:hover{border-color:var(--border2);transform:translateY(-2px);}
.opp-card.high{border-left:3px solid var(--green);}
.opp-card.medium{border-left:3px solid var(--yellow);}
.opp-card.low{border-left:3px solid var(--muted);}
.opp-card.avoid{border-left:3px solid var(--red);}
@keyframes fadeUp{to{opacity:1;transform:translateY(0)}}

.card-top{padding:0.85rem 1rem 0.6rem;display:flex;justify-content:space-between;align-items:flex-start;gap:0.75rem;}
.card-question{font-size:0.82rem;font-weight:500;line-height:1.45;flex:1;}
.edge-badge{font-family:'IBM Plex Mono',monospace;font-size:0.58rem;font-weight:700;padding:0.2rem 0.5rem;border-radius:3px;white-space:nowrap;letter-spacing:1px;flex-shrink:0;}
.badge-high{background:rgba(0,230,118,0.12);color:var(--green);border:1px solid rgba(0,230,118,0.25);}
.badge-medium{background:rgba(255,214,0,0.1);color:var(--yellow);border:1px solid rgba(255,214,0,0.25);}
.badge-low{background:rgba(68,68,90,0.3);color:var(--muted2);border:1px solid var(--border2);}
.badge-avoid{background:rgba(255,23,68,0.1);color:var(--red);border:1px solid rgba(255,23,68,0.25);}

.card-metrics{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--border);border-bottom:1px solid var(--border);}
.metric-cell{padding:0.55rem 0.6rem;border-right:1px solid var(--border);}
.metric-cell:last-child{border-right:none;}
.metric-label{font-family:'IBM Plex Mono',monospace;font-size:0.5rem;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:0.2rem;}
.metric-value{font-family:'IBM Plex Mono',monospace;font-size:0.82rem;font-weight:700;}

.card-bottom{padding:0.65rem 1rem;}
.card-reasoning{font-size:0.75rem;color:var(--muted2);line-height:1.55;margin-bottom:0.45rem;}
.card-insight{font-size:0.72rem;color:var(--yellow);line-height:1.5;margin-bottom:0.45rem;}
.card-risk{font-size:0.7rem;color:var(--red);margin-bottom:0.4rem;}
.card-meta{display:flex;justify-content:space-between;align-items:center;margin-top:0.35rem;}
.card-category{font-family:'IBM Plex Mono',monospace;font-size:0.58rem;color:var(--muted);background:var(--border);padding:0.15rem 0.4rem;border-radius:3px;text-transform:uppercase;}
.card-age{font-family:'IBM Plex Mono',monospace;font-size:0.58rem;color:var(--muted);}
.action-pill{font-family:'IBM Plex Mono',monospace;font-size:0.6rem;font-weight:700;padding:0.2rem 0.6rem;border-radius:20px;}
.action-buy{background:rgba(0,230,118,0.15);color:var(--green);}
.action-watch{background:rgba(68,138,255,0.15);color:var(--blue);}
.action-avoid{background:rgba(255,23,68,0.12);color:var(--red);}
.new-flash{position:absolute;top:0.5rem;right:0.5rem;font-family:'IBM Plex Mono',monospace;font-size:0.5rem;letter-spacing:1px;color:var(--purple);animation:blink 1s infinite;}

.error-banner{background:rgba(255,23,68,0.08);border:1px solid rgba(255,23,68,0.3);border-radius:8px;padding:0.75rem 1rem;font-family:'IBM Plex Mono',monospace;font-size:0.75rem;color:var(--red);margin-bottom:1rem;}

.toast{position:fixed;bottom:1.5rem;right:1.5rem;background:var(--card);border:1px solid var(--border2);border-left:3px solid var(--green);padding:0.75rem 1.25rem;border-radius:8px;font-size:0.8rem;z-index:1000;transform:translateX(200%);transition:transform 0.3s ease;max-width:280px;}
.toast.show{transform:translateX(0);}
.toast-title{font-weight:600;color:var(--green);margin-bottom:0.2rem;}
.toast-body{color:var(--muted2);font-size:0.72rem;}

.disclaimer{padding:0.6rem 1.5rem;border-top:1px solid var(--border);font-family:'IBM Plex Mono',monospace;font-size:0.58rem;color:var(--muted);background:var(--surface);}

.api-warning{background:rgba(255,214,0,0.06);border:1px solid rgba(255,214,0,0.3);border-radius:8px;padding:1rem 1.25rem;font-size:0.82rem;color:var(--yellow);margin-bottom:1rem;}
.api-warning code{background:var(--border);padding:0.15rem 0.4rem;border-radius:3px;font-family:'IBM Plex Mono',monospace;font-size:0.75rem;color:var(--text);}

@media(max-width:768px){.main{grid-template-columns:1fr;}.sidebar{display:none;}.cards-grid{grid-template-columns:1fr;}}
</style>
</head>
<body>
<div class="topbar">
  <div class="logo">Poly<span>Edge</span></div>
  <div class="status-row">
    <div class="live-dot off" id="liveDot"></div>
    <div class="status-text" id="statusText">IDLE</div>
    <div class="next-scan" id="nextScan" style="display:none"></div>
  </div>
</div>

<div class="controls">
  <span class="ctrl-label">Capital $</span>
  <input type="number" id="capitalInput" value="20" min="1">
  <span class="ctrl-label" style="margin-left:0.5rem">Min Edge</span>
  <select id="minEdge">
    <option value="5">5%+</option>
    <option value="10" selected>10%+</option>
    <option value="15">15%+</option>
    <option value="20">20%+</option>
  </select>
  <span class="ctrl-label" style="margin-left:0.5rem">Refresh</span>
  <select id="refreshInterval">
    <option value="1800" selected>30 min</option>
    <option value="900">15 min</option>
    <option value="3600">1 hour</option>
  </select>
  <button class="btn btn-primary" id="startBtn" onclick="toggleScanning()">▶ Start Scanner</button>
  <button class="btn btn-ghost" onclick="runScan()">⟳ Scan Now</button>
  <div class="filter-tabs">
    <button class="tab active" onclick="setFilter('all')">ALL</button>
    <button class="tab" onclick="setFilter('HIGH')">HIGH EDGE</button>
    <button class="tab" onclick="setFilter('MEDIUM')">MEDIUM</button>
    <button class="tab" onclick="setFilter('BUY')">BUY ONLY</button>
  </div>
</div>

<div class="main">
  <div class="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-title">Session Stats</div>
      <div class="stat-row"><span class="stat-name">Markets scanned</span><span class="stat-val green" id="sScanned">0</span></div>
      <div class="stat-row"><span class="stat-name">Opportunities</span><span class="stat-val green" id="sOpps">0</span></div>
      <div class="stat-row"><span class="stat-name">High edge</span><span class="stat-val green" id="sHigh">0</span></div>
      <div class="stat-row"><span class="stat-name">Avg edge</span><span class="stat-val yellow" id="sAvg">—</span></div>
      <div class="stat-row"><span class="stat-name">Best profit</span><span class="stat-val green" id="sBest">—</span></div>
      <div class="stat-row"><span class="stat-name">Scans run</span><span class="stat-val muted" id="sRuns">0</span></div>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-title">Categories</div>
      <div id="categoryList">
        <div class="cat-item active" onclick="setCategory('all')">
          <span class="cat-name">All categories</span>
          <span class="cat-count" id="catAll">0</span>
        </div>
      </div>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-title">Edge Distribution</div>
      <div class="stat-row"><span class="stat-name">🟢 High 15%+</span><span class="stat-val green" id="dHigh">0</span></div>
      <div class="stat-row"><span class="stat-name">🟡 Med 10-15%</span><span class="stat-val yellow" id="dMed">0</span></div>
      <div class="stat-row"><span class="stat-name">⚪ Low &lt;10%</span><span class="stat-val muted" id="dLow">0</span></div>
      <div class="stat-row"><span class="stat-name">🔴 Avoid</span><span class="stat-val red" id="dAvoid">0</span></div>
    </div>
  </div>

  <div class="content" id="content">
    <div class="state-screen" id="idleScreen">
      <div style="font-size:2.5rem">📡</div>
      <div class="state-label">SCANNER READY</div>
      <div class="state-sub">Click <strong style="color:var(--green)">Start Scanner</strong> or <strong style="color:var(--green)">Scan Now</strong> to fetch live Polymarket data and run AI edge detection.</div>
    </div>
  </div>
</div>

<div class="disclaimer">⚠ NOT FINANCIAL ADVICE · Educational purposes only · Verify all markets on polymarket.com before placing positions</div>
<div class="toast" id="toast"><div class="toast-title" id="toastTitle"></div><div class="toast-body" id="toastBody"></div></div>

<script>
let opportunities = [], scanning = false;
let refreshTimer = null, countdownTimer = null, nextScanAt = null;
let activeFilter = 'all', activeCategory = 'all';
let totalScanned = 0, totalRuns = 0;

async function checkApiStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    if (!d.apiKeySet) {
      document.getElementById('content').innerHTML = `
        <div class="api-warning">
          ⚠ <strong>Groq API key not configured.</strong><br><br>
          Open <code>polyedge_server.py</code> and replace <code>YOUR_GROQ_KEY_HERE</code> with your free Groq API key.<br><br>
          Get your FREE key at <strong>console.groq.com</strong> → API Keys (takes 30 seconds)
        </div>
        <div class="state-screen"><div style="font-size:2rem">🔑</div><div class="state-sub">Set your API key in server.py to get started.</div></div>`;
    }
  } catch(e) {}
}

function toggleScanning() {
  scanning = !scanning;
  const btn = document.getElementById('startBtn');
  const dot = document.getElementById('liveDot');
  if (scanning) {
    btn.textContent = '⏹ Stop Scanner';
    btn.style.background = 'var(--red)';
    dot.classList.remove('off');
    runScan();
    scheduleNext();
  } else {
    btn.textContent = '▶ Start Scanner';
    btn.style.background = 'var(--green)';
    dot.classList.add('off');
    clearTimeout(refreshTimer);
    clearInterval(countdownTimer);
    document.getElementById('nextScan').style.display = 'none';
    setStatus('STOPPED');
  }
}

function scheduleNext() {
  clearTimeout(refreshTimer); clearInterval(countdownTimer);
  const ms = parseInt(document.getElementById('refreshInterval').value) * 1000;
  nextScanAt = Date.now() + ms;
  document.getElementById('nextScan').style.display = 'block';
  countdownTimer = setInterval(() => {
    const rem = Math.max(0, nextScanAt - Date.now());
    const m = Math.floor(rem/60000), s = Math.floor((rem%60000)/1000);
    document.getElementById('nextScan').textContent = `next: ${m}:${s.toString().padStart(2,'0')}`;
  }, 1000);
  refreshTimer = setTimeout(() => { if(scanning){ runScan(); scheduleNext(); } }, ms);
}

async function runScan() {
  setStatus('SCANNING...');
  showLoading('Fetching live Polymarket data...', 15);
  const capital = parseFloat(document.getElementById('capitalInput').value)||20;
  const minEdge = parseInt(document.getElementById('minEdge').value)||10;

  try {
    updateProgress(40); updateLoadingText('Running AI edge analysis...');
    const r = await fetch('/api/scan', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({capital, minEdge})
    });
    const d = await r.json();
    if(!r.ok) throw new Error(d.error||'Scan failed');

    updateProgress(90);
    totalScanned += d.marketsScanned||0;
    totalRuns++;

    // Remove stale (35 min)
    const cutoff = Date.now() - 35*60*1000;
    const before = opportunities.length;
    opportunities = opportunities.filter(o => o.foundAt > cutoff);
    const removed = before - opportunities.length;

    // Merge new
    const existing = new Set(opportunities.map(o=>o.question));
    let added = 0;
    for(const opp of (d.opportunities||[])) {
      if(!existing.has(opp.question)) {
        opp.foundAt = Date.now(); opp.isNew = true;
        opportunities.push(opp); added++;
      }
    }
    setTimeout(()=>{ opportunities.forEach(o=>o.isNew=false); renderCards(); }, 60000);

    updateProgress(100);
    setStatus('LIVE');
    updateStats(); renderCards(); buildCategories();
    showToast('Scan complete', `+${added} new · ${removed} stale removed · ${d.marketsScanned} scanned`);

  } catch(e) {
    setStatus('ERROR');
    showToast('Scan failed', e.message);
    if(opportunities.length===0) showIdle('Error: ' + e.message);
    else renderCards();
  }
}

function renderCards() {
  const content = document.getElementById('content');
  let filtered = opportunities.filter(o => {
    if(activeCategory!=='all' && o.category!==activeCategory) return false;
    if(activeFilter==='HIGH') return o.edgeLevel==='HIGH';
    if(activeFilter==='MEDIUM') return o.edgeLevel==='MEDIUM';
    if(activeFilter==='BUY') return o.recommendation?.startsWith('BUY');
    return o.recommendation!=='AVOID';
  });
  filtered.sort((a,b)=>{
    const ord={HIGH:0,MEDIUM:1,LOW:2};
    const d=(ord[a.edgeLevel]||2)-(ord[b.edgeLevel]||2);
    return d||((b.expectedProfit||0)-(a.expectedProfit||0));
  });
  if(!filtered.length){
    content.innerHTML=`<div class="state-screen"><div style="font-size:2rem">🔍</div><div class="state-sub">${opportunities.length?'No results match this filter.':'No opportunities yet. Run a scan.'}</div></div>`;
    return;
  }
  const grid = document.createElement('div'); grid.className='cards-grid';
  filtered.forEach((o,i)=>{
    const ec = o.edgeLevel==='HIGH'?'high':o.edgeLevel==='MEDIUM'?'medium':o.recommendation==='AVOID'?'avoid':'low';
    const edge = Math.round(((o.estimatedTrueProb||0)-(o.currentPrice||0))*100);
    const ec2 = edge>15?'green':edge>5?'yellow':'muted';
    const pc = (o.expectedProfit||0)>0?'green':'red';
    const rc = o.recommendation?.startsWith('BUY')?'action-buy':o.recommendation==='WATCH'?'action-watch':'action-avoid';
    const age = o.foundAt ? Math.round((Date.now()-o.foundAt)/60000) : 0;
    const card = document.createElement('div');
    card.className=`opp-card ${ec}`; card.style.animationDelay=`${i*0.05}s`;
    card.innerHTML=`
      ${o.isNew?'<div class="new-flash">● NEW</div>':''}
      <div class="card-top">
        <div class="card-question">${o.question}</div>
        <div class="edge-badge badge-${ec}">${o.edgeLevel}</div>
      </div>
      <div class="card-metrics">
        <div class="metric-cell"><div class="metric-label">MKT</div><div class="metric-value">${Math.round((o.currentPrice||0)*100)}¢</div></div>
        <div class="metric-cell"><div class="metric-label">TRUE EST</div><div class="metric-value ${ec2}">${Math.round((o.estimatedTrueProb||0)*100)}¢</div></div>
        <div class="metric-cell"><div class="metric-label">EDGE</div><div class="metric-value ${ec2}">${edge>0?'+':''}${edge}%</div></div>
        <div class="metric-cell"><div class="metric-label">PROFIT</div><div class="metric-value ${pc}">$${(o.expectedProfit||0).toFixed(2)}</div></div>
      </div>
      <div class="card-bottom">
        <div class="card-reasoning">${o.reasoning||''}</div>
        ${o.resolutionInsight?`<div class="card-insight">💡 ${o.resolutionInsight}</div>`:''}
        ${o.riskNote?`<div class="card-risk">⚠ ${o.riskNote}</div>`:''}
        <div class="card-meta">
          <span class="card-category">${o.category||'General'}</span>
          <span class="action-pill ${rc}">${o.recommendation}</span>
          <span class="card-age">${age<1?'just now':age+'m ago'}</span>
        </div>
      </div>`;
    card.onclick=()=>{ if(o.slug) window.open(`https://polymarket.com/market/${o.slug}`,'_blank'); };
    grid.appendChild(card);
  });
  content.innerHTML=''; content.appendChild(grid);
}

function updateStats() {
  const valid = opportunities.filter(o=>o.recommendation!=='AVOID');
  document.getElementById('sScanned').textContent=totalScanned;
  document.getElementById('sOpps').textContent=valid.length;
  document.getElementById('sHigh').textContent=valid.filter(o=>o.edgeLevel==='HIGH').length;
  document.getElementById('sRuns').textContent=totalRuns;
  const edges=valid.map(o=>Math.round(((o.estimatedTrueProb||0)-(o.currentPrice||0))*100));
  document.getElementById('sAvg').textContent=edges.length?`+${Math.round(edges.reduce((a,b)=>a+b,0)/edges.length)}%`:'—';
  const profits=valid.map(o=>o.expectedProfit||0);
  document.getElementById('sBest').textContent=profits.length?`$${Math.max(...profits).toFixed(2)}`:'—';
  document.getElementById('dHigh').textContent=opportunities.filter(o=>{const e=((o.estimatedTrueProb||0)-(o.currentPrice||0))*100;return e>=15;}).length;
  document.getElementById('dMed').textContent=opportunities.filter(o=>{const e=((o.estimatedTrueProb||0)-(o.currentPrice||0))*100;return e>=10&&e<15;}).length;
  document.getElementById('dLow').textContent=opportunities.filter(o=>{const e=((o.estimatedTrueProb||0)-(o.currentPrice||0))*100;return e>0&&e<10;}).length;
  document.getElementById('dAvoid').textContent=opportunities.filter(o=>o.recommendation==='AVOID').length;
}

function buildCategories() {
  const cats={};
  opportunities.forEach(o=>{ const c=o.category||'Other'; cats[c]=(cats[c]||0)+1; });
  document.getElementById('catAll').textContent=opportunities.length;
  const list=document.getElementById('categoryList');
  while(list.children.length>1) list.removeChild(list.lastChild);
  Object.entries(cats).sort((a,b)=>b[1]-a[1]).forEach(([cat,count])=>{
    const el=document.createElement('div');
    el.className='cat-item'+(activeCategory===cat?' active':'');
    el.innerHTML=`<span class="cat-name">${cat}</span><span class="cat-count">${count}</span>`;
    el.onclick=()=>setCategory(cat);
    list.appendChild(el);
  });
}

function setFilter(f) {
  activeFilter=f;
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',['all','HIGH','MEDIUM','BUY'][i]===f));
  renderCards();
}
function setCategory(cat) {
  activeCategory=cat;
  document.querySelectorAll('.cat-item').forEach(el=>{
    const name=el.querySelector('.cat-name').textContent;
    el.classList.toggle('active',cat==='all'?name==='All categories':name===cat);
  });
  renderCards();
}
function setStatus(s){document.getElementById('statusText').textContent=s;}
function showToast(title,body){
  const t=document.getElementById('toast');
  document.getElementById('toastTitle').textContent=title;
  document.getElementById('toastBody').textContent=body;
  t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),4000);
}
function showLoading(msg,p){
  document.getElementById('content').innerHTML=`<div class="state-screen"><div class="spinner"></div><div class="state-label">SCANNING...</div><div class="state-sub" id="loadTxt">${msg}</div><div class="progress-bar"><div class="progress-fill" id="progFill" style="width:${p}%"></div></div></div>`;
}
function updateLoadingText(m){const el=document.getElementById('loadTxt');if(el)el.textContent=m;}
function updateProgress(p){const el=document.getElementById('progFill');if(el)el.style.width=p+'%';}
function showIdle(msg){
  document.getElementById('content').innerHTML=`<div class="state-screen"><div style="font-size:2rem">📡</div><div class="state-label">READY</div><div class="state-sub">${msg}</div></div>`;
}

checkApiStatus();
</script>
</body>
</html>"""

# ──────────────────────────────────────────────
#  Start server
# ──────────────────────────────────────────────
if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"""
╔══════════════════════════════════════════════╗
║        PolyEdge — Live Polymarket Scanner    ║
║        Powered by Groq AI (FREE)       ║
╠══════════════════════════════════════════════╣
║  Server: http://localhost:{PORT}               ║
║                                              ║
║  1. Get FREE key: console.groq.com           ║
║  2. Set GROQ_API_KEY in this file            ║
║     OR run:                                  ║
║     GROQ_API_KEY=gsk_... python \\            ║
║       polyedge_server.py                     ║
║                                              ║
║  3. Open http://localhost:{PORT}               ║
╚══════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
