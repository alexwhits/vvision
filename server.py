import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from pytrends.request import TrendReq
import praw
import os
import requests, datetime as dt, os, time


app = Flask(__name__,static_url_path='/static', static_folder='static')
CORS(app, resources={r"/api/*": {"origins": "*"}})  # allow cross-site fetches

@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type" 
def nocache(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp

# ---- helpers -------------------------------------------------
def normalize_score(items, key="score"):
    vals = [i.get(key, 0) for i in items if i.get(key, 0) > 0]
    m = max(vals) if vals else 1
    for it in items:
        it[key] = round((it.get(key, 0) / m), 3)
    return items

# ---- data sources --------------------------------------------
def fetch_trends(region="united_states", limit=10):
    try:
        pt = TrendReq(hl='en-US', tz=360)
        df = pt.trending_searches(pn=region)  # returns top trending queries
        titles = [row[0] for row in df.head(limit).values.tolist()]
        return [{"title": t, "url": None, "source": "trends", "score": 1.0} for t in titles]
    except Exception:
        return []

def fetch_reddit(limit=10):
    try:
        reddit = praw.Reddit(
            client_id=os.environ.get("aEIquN5Wu3UNbXmiZCaBGg"),
            client_secret=os.environ.get("CKuhDTcGVEUJrILD8KTZb0CYEgUzgA"),
            user_agent="vvision/0.1 by u/nonlethaljazz"
        )
        posts = []
        for p in reddit.subreddit("all").hot(limit=limit):
            # filter obvious junk: stickies, NSFW
            if getattr(p, "stickied", False) or getattr(p, "over_18", False):
                continue
            posts.append({
                "title": p.title[:200],
                "url": getattr(p, "url", None),
                "source": "reddit",
                "score": int(getattr(p, "score", 0))
            })
        return posts
    except Exception:
        return []
# naive in-memory cache for previous counts (for momentum)
_prev = {"ts": 0, "map": {}}

def fetch_x_counts(terms, granularity="minute"):
    """
    terms: list[str] like ["drake", "bitcoin", "openai"]
    returns: [{"title": "bitcoin", "source":"x", "score": rate_per_min, "d1": momentum}, ...]
    """
    token = os.environ.get("X_BEARER_TOKEN")
    if not token or not terms:
        return []

    # time window: last 60 minutes
    now = dt.datetime.utcnow()
    start = (now - dt.timedelta(hours=1)).isoformat(timespec="seconds") + "Z"

    headers = {"Authorization": f"Bearer {token}"}
    url = "https://api.twitter.com/2/tweets/counts/recent"  # X's v2 counts endpoint

    out = []
    for term in terms[:10]:  # keep it small for rate limits
        try:
            params = {"query": term, "granularity": granularity, "start_time": start}
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json().get("data", [])
            if not data:
                continue
            # use last bucket as the freshest minute/hour
            last = data[-1]
            count = int(last.get("tweet_count", 0))
            # convert to "rate per minute" roughness (if hourly granularity, divide)
            if granularity == "minute":
                rate = count
            else:
                rate = count / 60.0

            # momentum vs previous snapshot
            global _prev
            prev_map = _prev["map"]
            prev = prev_map.get(term, 0)
            d1 = rate - prev
            prev_map[term] = rate

            out.append({"title": term, "url": None, "source": "x", "score": max(rate, 0), "d1": d1})
        except Exception:
            continue

    # update cache timestamp
    _prev["ts"] = int(time.time())
    return out

# ---- endpoint ------------------------------------------------
@app.route("/api/attention/heatmap", methods=["GET","OPTIONS"])
def heatmap():
    if request.method == "OPTIONS":
        return ("", 204)

    trends = fetch_trends(limit=8)     # existing
    reddit = fetch_reddit(limit=8)     # existing
    seed_terms = [it["title"] for it in (trends + reddit)][:8]

    x_items = fetch_x_counts(seed_terms, granularity="minute")

    items = trends + reddit + x_items
    if not items:
        items = [
            {"title":"sample one", "source":"demo", "score":1.0, "d1":0.1},
            {"title":"sample two", "source":"demo", "score":0.7, "d1":-0.1},
        ]

    # normalize intensity (score) across the mixed set
    items = normalize_score(items, key="score")
    return jsonify({"last_updated": int(time.time()), "items": items})


@app.get("/")
def root():
    return jsonify({"ok": True, "endpoints": ["/api/attention/heatmap"]})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

