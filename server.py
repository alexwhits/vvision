import time
from flask import Flask, jsonify
from pytrends.request import TrendReq
import praw
import os

app = Flask(__name__)

@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

# ---- helpers -------------------------------------------------
def normalize_score(items, key="score"):
    vals = [i.get(key, 0) for i in items if i.get(key, 0) > 0]
    maxv = max(vals) if vals else 1
    for it in items:
        it[key] = round((it.get(key, 0) / maxv), 3)
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
            client_id=os.environ.get("REDDIT_CLIENT_ID"),
            client_secret=os.environ.get("REDDIT_CLIENT_SECRET"),
            user_agent="vvision/0.1 by u/yourusername"
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

# ---- endpoint ------------------------------------------------
@app.route("/api/attention/heatmap")
def heatmap():
    trends = fetch_trends(limit=10)
    reddit = fetch_reddit(limit=10)
    items = trends + reddit
    items = normalize_score(items, key="score")
    return jsonify({
        "last_updated": int(time.time()),
        "items": items
    })

@app.get("/")
def root():
    return jsonify({"ok": True, "endpoints": ["/api/attention/heatmap"]})

if __name__ == "__main__":
    # for local testing
    app.run(host="0.0.0.0", port=5000)
