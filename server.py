import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from pytrends.request import TrendReq
import praw
import os

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})  # allow cross-site fetches

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

# ---- endpoint ------------------------------------------------
@app.route("/api/attention/heatmap", methods=["GET","OPTIONS"])
def heatmap():
    if request.method == "OPTIONS":
        return ("", 204)
    trends = fetch_trends(limit=10)
    reddit = fetch_reddit(limit=10)
    items = trends + reddit
    if not items:
        items = [
            {"title":"sample item one", "url": None, "source":"demo", "score": 1.0},
            {"title":"sample item two", "url": None, "source":"demo", "score": 0.7},
        ]
    items = normalize_score(items, key="score")
    return jsonify({"last_updated": int(time.time()), "items": items})


@app.get("/")
def root():
    return jsonify({"ok": True, "endpoints": ["/api/attention/heatmap"]})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

