import re
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from difflib import SequenceMatcher
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
    ANALYZER = SentimentIntensityAnalyzer()

# light normalize → a rough “topic key”
_STOP = set("""
a an the of for & and to in on with from about by at is are was were be been being
""".split())

def normalize_topic(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)         # drop punct
    toks = [w for w in t.split() if w not in _STOP and len(w) > 2]
    return " ".join(toks)[:80].strip()

def similar(a: str, b: str, thresh=0.88) -> bool:
    # cheap fuzzy—good enough for headlines
    return SequenceMatcher(None, a, b).ratio() >= thresh

def sentiment_delta(title: str) -> float:
    # map VADER compound (-1..1) to delta where sign drives color
    s = ANALYZER.polarity_scores(title or "")
    c = s.get("compound", 0.0)
    return float(c)  # positive => green, negative => red

def normalize_01(values):
    if not values: return []
    m = max(values) or 1.0
    return [v / m for v in values]


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

    # 1) pull raw signals
    trends = fetch_trends(limit=15)
    reddit = fetch_reddit(limit=20)
    news   = fetch_reuters(limit=20)

    # seed X from top terms out of trends+news to avoid noisy reddit phrasing
    seed_terms = [it["title"] for it in (trends + news)][:10]
    x_items = fetch_x_counts(seed_terms, granularity="minute")

    raw = trends + reddit + news + x_items

    # 2) group by topic key + light fuzzy merge
    buckets = []   # list of dicts {key, titles, urls, sources, mentions, sum_score, best_title}
    for it in raw:
        title = (it.get("title") or "").strip()
        if not title: 
            continue
        key = normalize_topic(title)
        if not key: 
            continue

        # find existing bucket by exact key or fuzzy
        found = None
        for b in buckets:
            if b["key"] == key or similar(b["key"], key):
                found = b; break
        if not found:
            found = {"key": key, "titles": [], "urls": [], "sources": set(),
                     "mentions": 0, "sum_score": 0.0, "best_title": title}
            buckets.append(found)

        found["titles"].append(title)
        url = it.get("url")
        if url: found["urls"].append(url)
        found["sources"].add(it.get("source") or "")
        found["mentions"] += 1
        found["sum_score"] += float(it.get("score", 1.0))
        # prefer shortest clean title as display
        if len(title) < len(found["best_title"]):
            found["best_title"] = title

    if not buckets:
        demo = [
            {"title": "placeholder topic A", "url": None, "source":"demo", "score":1.0, "d1": 0.25},
            {"title": "placeholder topic B", "url": None, "source":"demo", "score":0.6, "d1": -0.2},
        ]
        return jsonify({"last_updated": int(time.time()), "items": demo})

    # 3) compute popularity score (mentions-weighted)
    #    score drives SIZE/opacity; d1 drives COLOR via sentiment
    max_mentions = max(b["mentions"] for b in buckets) or 1
    items = []
    for b in buckets:
        display = b["best_title"]
        pop_raw = (b["mentions"] * 0.7) + (b["sum_score"] * 0.3)  # weight mentions more than raw votes
        sent    = sentiment_delta(display)  # -1..1
        items.append({
            "title": display,
            "url": b["urls"][0] if b["urls"] else None,
            "source": ",".join(sorted(s for s in b["sources"] if s)),
            "score": pop_raw,   # normalize later
            "d1": sent          # sign => color, magnitude => saturation
        })

    # 4) normalize score to 0..1
    items = normalize_score(items, key="score")

    # 5) apply a minimum-threshold filter if you want (mentions >= X)
    min_mentions = int(request.args.get("min", 1))
    if min_mentions > 1:
        # rebuild mentions map for filtering
        m = {b["best_title"]: b["mentions"] for b in buckets}
        items = [it for it in items if m.get(it["title"], 1) >= min_mentions]

    # sort by popularity descending so biggest appear first
    items.sort(key=lambda x: x["score"], reverse=True)

    return jsonify({"last_updated": int(time.time()), "items": items})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
