import os
import re
import json
import time
import requests
from collections import Counter
from datetime import datetime, timedelta, timezone
from openai import OpenAI

SUBREDDITS = [
    "IndianSkincareAddicts",
    "SkincareAddiction",
    "AsianBeauty",
    "tretinoin",
    "IndianMakeupAndBeauty",
    "acne",
    "hyperpigmentation",
    "30PlusSkinCare",
]
YOUTUBE_KEYWORDS = [
    "acne oily skin India",
    "hyperpigmentation dark spots Indian skin",
    "sunscreen India oily skin summer",
    "closed comedones India skincare",
    "hormonal acne India treatment",
    "skin barrier repair India",
    "tan removal Indian skin",
    "large pores Indian skin",
    "niacinamide serum India review",
    "retinol India beginners",
    "vitamin c serum India review",
    "affordable sunscreen India",
    "best moisturizer oily skin India",
    "skincare Indian skin type",
    "monsoon skincare India",
    "summer skincare routine India",
    "dark circles Indian skin",
    "uneven skin tone India",
    "skincare products India honest review",
    "dermatologist India skincare recommendation",
]
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
USER_AGENT = "script:FoxtaleResearchBot:v1.0 (by /u/foxtale_research)"


def fetch_comments_reddit(subreddit, post_id, headers):
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json?limit=20&depth=2&raw_json=1"
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code != 200:
            return []
        comment_listing = r.json()
        if len(comment_listing) < 2:
            return []
        comments = []
        for c in comment_listing[1]["data"]["children"][:10]:
            if c["kind"] == "t1" and c["data"].get("body"):
                comments.append(c["data"]["body"][:300])
        return comments
    except Exception:
        return []


def fetch_reddit_json(subreddit):
    headers = {"User-Agent": USER_AGENT}
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=week&limit=50&raw_json=1"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()

    posts = r.json()["data"]["children"]
    result = []
    for p in posts[:25]:
        d = p["data"]
        if d["score"] < 5:
            continue
        post = {
            "subreddit": subreddit,
            "id": d["id"],
            "title": d["title"],
            "body": d.get("selftext", "")[:600],
            "score": d["score"],
            "num_comments": d["num_comments"],
            "comments": [],
        }
        if d["score"] >= 30 or d["num_comments"] >= 10:
            post["comments"] = fetch_comments_reddit(subreddit, d["id"], headers)
            time.sleep(0.5)
        result.append(post)
    return result


def fetch_arctic_shift(subreddit):
    week_ago = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
    now = int(datetime.now(timezone.utc).timestamp())

    posts_url = (
        f"https://arctic-shift.photon-reddit.com/api/posts/search"
        f"?subreddit={subreddit}&after={week_ago}&before={now}&limit=100"
    )
    r = requests.get(posts_url, timeout=30)
    r.raise_for_status()
    posts_data = r.json().get("data", [])

    comments_url = (
        f"https://arctic-shift.photon-reddit.com/api/comments/search"
        f"?subreddit={subreddit}&after={week_ago}&before={now}&limit=1000"
    )
    cr = requests.get(comments_url, timeout=30)
    comments_by_post = {}
    if cr.status_code == 200:
        for c in cr.json().get("data", []):
            if c.get("body") in ("[removed]", "[deleted]", "", None):
                continue
            pid = c.get("link_id", "").replace("t3_", "")
            comments_by_post.setdefault(pid, []).append(c.get("body", "")[:300])

    result = []
    for p in posts_data:
        pid = p.get("id", "")
        result.append({
            "subreddit": subreddit,
            "id": pid,
            "title": p.get("title", ""),
            "body": p.get("selftext", "")[:600],
            "score": p.get("score", 0),
            "num_comments": p.get("num_comments", 0),
            "comments": comments_by_post.get(pid, [])[:10],
        })
    return result


def fetch_subreddit(subreddit):
    try:
        posts = fetch_arctic_shift(subreddit)
        if posts:
            print(f"r/{subreddit}: {len(posts)} posts via Arctic Shift")
            return posts
    except Exception as e:
        print(f"Arctic Shift failed for r/{subreddit}: {e}, trying Reddit .json...")

    try:
        posts = fetch_reddit_json(subreddit)
        if posts:
            print(f"r/{subreddit}: {len(posts)} posts via Reddit .json")
            return posts
    except Exception as e:
        print(f"Reddit .json failed for r/{subreddit}: {e}")

    return []


def fetch_youtube(api_key):
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen_ids = set()
    results = []

    for keyword in YOUTUBE_KEYWORDS:
        try:
            search_r = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "key": api_key,
                    "q": keyword,
                    "type": "video",
                    "part": "snippet",
                    "regionCode": "IN",
                    "relevanceLanguage": "en",
                    "publishedAfter": week_ago,
                    "maxResults": 5,
                    "order": "relevance",
                    "videoDuration": "medium",
                },
                timeout=20,
            )
            if search_r.status_code != 200:
                continue
            videos = search_r.json().get("items", [])
        except Exception as e:
            print(f"YouTube search failed for '{keyword}': {e}")
            continue

        for item in videos:
            vid_id = item["id"].get("videoId")
            if not vid_id or vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)

            title = item["snippet"]["title"]
            try:
                comments_r = requests.get(
                    "https://www.googleapis.com/youtube/v3/commentThreads",
                    params={
                        "key": api_key,
                        "videoId": vid_id,
                        "part": "snippet",
                        "maxResults": 30,
                        "order": "relevance",
                        "textFormat": "plainText",
                    },
                    timeout=20,
                )
                comments = []
                if comments_r.status_code == 200:
                    for c in comments_r.json().get("items", []):
                        text = c["snippet"]["topLevelComment"]["snippet"]["textDisplay"][:300]
                        if len(text) >= 30:
                            comments.append(text)
            except Exception:
                comments = []

            if comments:
                results.append({
                    "source": "youtube",
                    "id": vid_id,
                    "title": title,
                    "body": "",
                    "score": 0,
                    "subreddit": "",
                    "comments": comments,
                })

    print(f"YouTube: {len(results)} unique videos with comments")
    return results


def find_new_subreddits(all_posts):
    """Extract r/ mentions from posts and comments not already in our list."""
    known = {s.lower() for s in SUBREDDITS}
    mentions = []
    pattern = re.compile(r"r/([A-Za-z0-9_]+)", re.IGNORECASE)

    for p in all_posts:
        text = f"{p['title']} {p['body']} {' '.join(p['comments'])}"
        for match in pattern.findall(text):
            if match.lower() not in known:
                mentions.append(match.lower())

    counts = Counter(mentions)
    # Return subreddits mentioned 3+ times, sorted by frequency
    return [(sub, count) for sub, count in counts.most_common(5) if count >= 3]


def analyze(all_posts):
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
        default_headers={"HTTP-Referer": "https://github.com/riveshutrivedi-ctrl/intel-agent"},
    )

    # Top 150 Reddit by score + all YouTube items
    reddit_posts = sorted(
        [p for p in all_posts if p.get("source", "reddit") == "reddit"],
        key=lambda x: x["score"], reverse=True
    )[:150]
    youtube_items = [p for p in all_posts if p.get("source") == "youtube"]
    selected = reddit_posts + youtube_items

    def format_item(p):
        source = p.get("source", "reddit")
        if source == "youtube":
            comments = " | ".join(p["comments"][:5]) or "none"
            return f"[YouTube: {p['title']}]\nComments: {comments}"
        comments = " | ".join(p["comments"][:5]) or "none"
        return (
            f"[Reddit: r/{p['subreddit']}] {p['title']} (score: {p['score']})\n"
            f"Post: {p['body']}\nTop comments: {comments}"
        )

    posts_text = "\n\n".join(format_item(p) for p in selected)

    prompt = f"""You are a consumer insights analyst for Foxtale, an Indian D2C skincare brand.

Analyze this multi-source data from skincare communities (past week). Sources are labeled:
- [Reddit: r/subreddit] — community discussion posts with upvotes; scores reflect community agreement
- [YouTube: video title] — comments on skincare videos; reflect reactions, questions, and frustrations of viewers

Your goal is PROBLEM MINING — find underlying consumer problems, not surface complaints.

Source weighting rules:
- A problem appearing in BOTH Reddit and YouTube is a stronger signal than one source alone — call this out explicitly
- Reddit scores indicate community resonance; high-score posts signal widespread agreement
- YouTube comments with many likes or replies signal emotionally resonant frustrations

Look for:
- Repeated questions across sources → unmet information or education need
- Workarounds people describe → product or category gap
- "I've tried everything" / chronic frustration → unresolved persistent problem
- Frustration with ingredient combos → formulation complexity pain
- Indian-specific concerns (humidity, pigmentation, oiliness, tan, monsoon skin) → climate/skin-type gap
- Affordability + efficacy tension → price-performance gap
- Ingredient confusion or misinformation circulating → education opportunity

Also check for any mention of "foxtale" or "fox tale" (case insensitive) across all sources.

DATA:
{posts_text}

Respond ONLY with valid JSON in this exact format:
{{
  "problems": [
    {{
      "theme": "Theme name",
      "summary": "2-sentence explanation of the pattern and why it signals an opportunity",
      "post_count": 5,
      "sources": ["reddit", "youtube"]
    }}
  ],
  "unmet_needs": ["specific unmet need 1", "specific unmet need 2"],
  "foxtale_mentions": [
    {{"title": "post or video title", "sentiment": "positive/negative/neutral", "source": "reddit/youtube"}}
  ]
}}

Include 3-5 problems ranked by frequency. Prioritise problems appearing in multiple sources. 2-3 unmet_needs. foxtale_mentions only if found (empty array if none)."""

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct:free",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            raise


def format_message(analysis, new_subreddits, total_posts):
    today = datetime.utcnow().strftime("%d %b %Y")
    lines = [f"\U0001f50d *Skincare Intel Digest \u2014 Week of {today}* ({total_posts} signals analysed)\n"]

    lines.append("*TOP CONSUMER PROBLEMS*")
    for i, p in enumerate(analysis["problems"], 1):
        srcs = p.get("sources", [])
        source_tag = ""
        if "reddit" in srcs and "youtube" in srcs:
            source_tag = " \u26a1 _cross-source_"
        elif "youtube" in srcs:
            source_tag = " _[YT]_"
        lines.append(f"{i}. *{p['theme']}*{source_tag} \u2014 {p['summary']} ({p['post_count']} signals)")

    lines.append("\n*UNMET NEEDS*")
    for need in analysis["unmet_needs"]:
        lines.append(f"\u2022 {need}")

    if analysis.get("foxtale_mentions"):
        lines.append("\n*FOXTALE MENTIONS*")
        for m in analysis["foxtale_mentions"]:
            src = f" [{m.get('source', 'reddit').upper()}]" if m.get("source") else ""
            lines.append(f"\u2022 _{m['title']}_{src} \u2014 {m['sentiment']}")

    if new_subreddits:
        lines.append("\n*NEW SUBREDDITS TO WATCH*")
        for sub, count in new_subreddits:
            lines.append(f"\u2022 r/{sub} \u2014 mentioned {count}x this week")

    reddit_sources = " \u00b7 ".join(f"r/{s}" for s in SUBREDDITS)
    lines.append(f"\n_Sources: {reddit_sources} \u00b7 YouTube_")
    return "\n".join(lines)


def send_to_slack(message):
    r = requests.post(
        SLACK_WEBHOOK,
        json={"text": message},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    r.raise_for_status()


def main():
    all_posts = []
    for sub in SUBREDDITS:
        posts = fetch_subreddit(sub)
        all_posts.extend(posts)

    if not all_posts:
        send_to_slack("\u26a0\ufe0f *Skincare Intel*: Failed to fetch Reddit data this week.")
        return

    if YOUTUBE_API_KEY:
        youtube_items = fetch_youtube(YOUTUBE_API_KEY)
        all_posts.extend(youtube_items)
    else:
        print("YOUTUBE_API_KEY not set — skipping YouTube.")

    print(f"Analyzing {len(all_posts)} total signals...")
    analysis = analyze(all_posts)
    new_subreddits = find_new_subreddits(all_posts)
    message = format_message(analysis, new_subreddits, len(all_posts))
    send_to_slack(message)
    print("Digest sent to Slack.")


if __name__ == "__main__":
    main()
