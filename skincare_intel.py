import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from openai import OpenAI

SUBREDDITS = ["IndianSkincareAddicts", "SkincareAddiction", "AsianBeauty"]
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
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
        # Fetch comments for posts with meaningful engagement
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
        f"?subreddit={subreddit}&after={week_ago}&before={now}&limit=50&sort=score"
    )
    r = requests.get(posts_url, timeout=30)
    r.raise_for_status()
    posts_data = r.json().get("data", [])

    comments_url = (
        f"https://arctic-shift.photon-reddit.com/api/comments/search"
        f"?subreddit={subreddit}&after={week_ago}&before={now}&limit=200&sort=score"
    )
    cr = requests.get(comments_url, timeout=30)
    comments_by_post = {}
    if cr.status_code == 200:
        for c in cr.json().get("data", []):
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
        posts = fetch_reddit_json(subreddit)
        if posts:
            print(f"r/{subreddit}: {len(posts)} posts via Reddit .json")
            return posts
    except Exception as e:
        print(f"Reddit .json failed for r/{subreddit}: {e}, trying Arctic Shift...")

    try:
        posts = fetch_arctic_shift(subreddit)
        if posts:
            print(f"r/{subreddit}: {len(posts)} posts via Arctic Shift")
            return posts
    except Exception as e:
        print(f"Arctic Shift failed for r/{subreddit}: {e}")

    return []


def analyze(all_posts):
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GITHUB_TOKEN,
    )

    posts_text = "\n\n".join(
        f"[r/{p['subreddit']}] {p['title']} (score: {p['score']})\n"
        f"Post: {p['body']}\n"
        f"Top comments: {' | '.join(p['comments'][:5]) if p['comments'] else 'none'}"
        for p in all_posts[:120]
    )

    prompt = f"""You are a consumer insights analyst for Foxtale, an Indian D2C skincare brand.

Analyze these Reddit posts AND comments from skincare communities (past week). Your goal is PROBLEM MINING — find underlying consumer problems, not surface complaints. Comments often reveal more honest frustration than post titles.

Look for:
- Repeated questions across posts/comments → unmet information or education need
- Workarounds people describe → product or category gap
- "I've tried everything" / chronic frustration → unresolved persistent problem
- Frustration with ingredient combos → formulation complexity pain
- Indian-specific concerns (humidity, pigmentation, oiliness, tan, monsoon skin) → climate/skin-type gap
- Affordability + efficacy tension → price-performance gap
- Ingredient confusion or misinformation circulating → education opportunity

Also check for any mention of "foxtale" or "fox tale" (case insensitive) in posts or comments.

POSTS + COMMENTS:
{posts_text}

Respond ONLY with valid JSON in this exact format:
{{
  "problems": [
    {{"theme": "Theme name", "summary": "2-sentence explanation of the pattern and why it signals an opportunity", "post_count": 5}}
  ],
  "unmet_needs": ["specific unmet need 1", "specific unmet need 2"],
  "foxtale_mentions": [
    {{"title": "post title", "sentiment": "positive/negative/neutral"}}
  ]
}}

Include 3-5 problems ranked by frequency. 2-3 unmet_needs. foxtale_mentions only if found (empty array if none)."""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1500,
    )
    return json.loads(response.choices[0].message.content)


def format_message(analysis):
    today = datetime.utcnow().strftime("%d %b %Y")
    lines = [f"\U0001f50d *Skincare Reddit Digest \u2014 Week of {today}*\n"]

    lines.append("*TOP CONSUMER PROBLEMS*")
    for i, p in enumerate(analysis["problems"], 1):
        lines.append(f"{i}. *{p['theme']}* \u2014 {p['summary']} ({p['post_count']} posts)")

    lines.append("\n*UNMET NEEDS*")
    for need in analysis["unmet_needs"]:
        lines.append(f"\u2022 {need}")

    if analysis.get("foxtale_mentions"):
        lines.append("\n*FOXTALE MENTIONS*")
        for m in analysis["foxtale_mentions"]:
            lines.append(f"\u2022 _{m['title']}_ \u2014 {m['sentiment']}")

    lines.append("\n_Sources: r/IndianSkincareAddicts \u00b7 r/SkincareAddiction \u00b7 r/AsianBeauty_")
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

    print(f"Analyzing {len(all_posts)} posts...")
    analysis = analyze(all_posts)
    message = format_message(analysis)
    send_to_slack(message)
    print("Digest sent to Slack.")


if __name__ == "__main__":
    main()
