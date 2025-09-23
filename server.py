import os
import time
import datetime as dt
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from pytrends.request import TrendReq
import praw

app = Flask(__name__, static_url_path="/static", static_folder="static")
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ---- global helpers -------------------------------------------------

@app.after_request
def add_headers(resp):
    # CORS already handled by Flask-CORS, but keep permissive:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    # no-cache so the browser always fetches fresh JSON
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp

def normalize_score(items, key="score"):
    vals = [float(i.get(key, 0)) for i in items if float(i.get(key, 0)) > 0]
    m = max(vals) if vals else 1.0
    for it in items:
        it[key] = round(float(it.get(key, 0)) / m, 3)
    return items

# ---- data sources ---------------------------------------------------

def fetch_trends(region="united_states", limit=10):
    try:
        pt = TrendReq(hl="en-US", tz=0)
        df = pt.trending_searches(pn=region)
        titles = []
        if df is not None and not df.empty:
            titles = [row[0] for row in df.head(limit).values.tolist()]
        if not titles:
            # fallback to global if region rate-limited
            dfg = pt.trending_searches(pn="global")
            if dfg is not None and not dfg.empty:
                titles = [row[0] for row in dfg.head(limit).values.tolist()]
        return [{"title": t, "url": None, "source": "trends", "score": 1.0} for t in titles]
    except Exception:
        return []

def fetch_reddit(limit=10):
    try:
        cid = os.environ.get("REDDIT_CLIENT_ID")
        csec = os.environ.get("REDDIT_CLIENT_SECRET")
        if not cid or not csec:
            return []
        reddit = praw.Reddit(
            client_id=cid,
            client_secret=csec,
            user_agent="vvision/0.1 (by u/your_username)"
        )
        posts = []
        # oversample, then filter
        for p in reddit.subreddit("all").hot(limit=limit * 2):
            if getattr(p, "stickied", False) or getattr(p, "over_18", False):
                continue
            title = (p.title or "").strip()
            if not title:
                continue
            posts.append({
                "title": title[:200],
                "url": getattr(p, "url", None),
                "source": "reddit",
                "score": int(getattr(p, "score", 0)) or 1
            })
            if len(posts) >= limit:
                break
        return posts
    except Exception:
        return []

# naive in-memory snapshot for momentum
_prev = {"ts": 0, "map": {}}

def fetch_x_counts(terms, granularity="minute"):
    """
    Query X (Twitter) counts for a small set of terms and compute momentum.
    Returns list of {title, source:'x', score, d1}
    """
    token = os.environ.get("X_BEARER_TOKEN")
    if not token or not terms:
        return []

    now = dt.datetime.utcnow()
    start = (now - dt.timedelta(hours=1)).isoformat(timespec="seconds") + "Z"
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://api.twitter.com/2/tweets/counts/recent"

    out = []
    for term in terms[:10]:  # keep within rate limits
        try:
            params = {"query": term, "granularity": granularity, "start_time": start}
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json().get("data", [])
            if not data:
                continue
            last = data[-1]
            count = int(last.get("tweet_count", 0))
            rate = count if granularity == "minute" else count / 60.0

            global _prev
            prev_map = _prev["map"]
            prev = float(prev_map.get(term, 0.0))
            d1 = rate - prev
            prev_map[term] = rate

            out.append({"title": term, "url": None, "source": "x", "score": max(rate, 0.0), "d1": d1})
        except Exception:
            continue

    _prev["ts"] = int(time.time())
    return out

# ---- API ------------------------------------------------------------

@app.route("/api/attention/heatmap", methods=["GET", "OPTIONS"])
def heatmap():
    if request.method == "OPTIONS":
        return ("", 204)

    trends = fetch_trends(limit=12)
    reddit = fetch_reddit(limit=12)

    # seed X from combined titles (or replace with your own watchlist)
    seed_terms = [it["title"] for it in (trends + reddit)][:8]
    x_items = fetch_x_counts(seed_terms, granularity="minute")

    items = trends + reddit + x_items
    if not items:
        items = [
            {"title": "sample one", "source": "demo", "score": 1.0, "d1": 0.1},
            {"title": "sample two", "source": "demo", "score": 0.7, "d1": -0.1},
        ]

    items = normalize_score(items, key="score")
    return jsonify({"last_updated": int(time.time()), "items": items})

@app.get("/")
def root():
    return jsonify({"ok": True, "endpoints": ["/api/attention/heatmap"]})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
