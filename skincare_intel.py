import os
import json
import time
import requests
from datetime import datetime
from openai import OpenAI

SUBREDDITS = ["IndianSkincareAddicts", "SkincareAddiction", "AsianBeauty"]
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]


def fetch_subreddit(subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=week&limit=100&raw_json=1"
    headers = {"User-Agent": "FoxtaleResearchBot/1.0"}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(10)
            r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        posts = r.json()["data"]["children"]
        return [
            {
                "subreddit": subreddit,
                "title": p["data"]["title"],
                "body": p["data"].get("selftext", "")[:500],
                "score": p["data"]["score"],
            }
            for p in posts
            if p["data"]["score"] > 10
        ]
    except Exception as e:
        print(f"Error fetching r/{subreddit}: {e}")
        return []


def analyze(all_posts):
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GITHUB_TOKEN,
    )

    posts_text = "\n\n".join(
        f"[r/{p['subreddit']}] {p['title']}\n{p['body']}"
        for p in all_posts[:150]
    )

    prompt = f"""You are a consumer insights analyst for Foxtale, an Indian D2C skincare brand.

Analyze these Reddit posts from skincare communities (past week). Your goal is PROBLEM MINING — find underlying consumer problems, not surface complaints.

Look for:
- Repeated questions → unmet information or education need
- Workarounds people describe → product or category gap
- "I've tried everything" posts → chronic unresolved problem
- Frustration with ingredient combos → formulation complexity pain
- Indian-specific concerns (humidity, pigmentation, oiliness, tan) → climate or skin-type gap
- Affordability + efficacy tension → price-performance gap

Also check for any mention of "foxtale" or "fox tale" (case insensitive).

POSTS:
{posts_text}

Respond ONLY with valid JSON in this exact format:
{{
  "problems": [
    {{"theme": "Theme name", "summary": "2-sentence explanation of pattern and why it signals an opportunity", "post_count": 5}}
  ],
  "unmet_needs": ["specific unmet need 1", "specific unmet need 2"],
  "foxtale_mentions": [
    {{"title": "post title", "sentiment": "positive/negative/neutral"}}
  ]
}}

Include 3-5 problems, 2-3 unmet_needs. foxtale_mentions should be empty array if none found."""

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
        print(f"Fetched {len(posts)} posts from r/{sub}")

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
