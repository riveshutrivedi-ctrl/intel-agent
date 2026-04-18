#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skincare Intelligence Agent
Fetches weekly skincare discussions from Reddit, synthesizes insights with Gemini,
and delivers a structured brief to Slack every Monday at 10 AM IST.
"""

import os
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Fix SSL certificate verification on Windows embedded Python
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass  # On GitHub Actions (Linux), system certs work fine without truststore

load_dotenv()

# ─── Configuration ─────────────────────────────────────────────────────────────

SUBREDDITS = [
    "IndianSkincareAddicts",  # India-specific, highest signal for us
    "SkincareAddiction",      # Global, very large community
    "AsianBeauty",            # Ingredient-focused, K-beauty overlap
    "30PlusSkinCare",         # Age-conscious routines
    "IndianBeautyDeals",      # Price sensitivity, Indian market
    "Tretinoin",              # Active ingredient discussions
]

POSTS_PER_SUB = 20
MIN_POST_SCORE = 15
MIN_COMMENT_SCORE = 5
MAX_COMMENTS_PER_POST = 5
MAX_BODY_CHARS = 400
MAX_COMMENT_CHARS = 250


# ─── Reddit Data Fetching (no API key required) ────────────────────────────────

REDDIT_BASE = "https://www.reddit.com"
REQUEST_DELAY = 2.0  # seconds between calls


def _get(session, url, params=None):
    """GET with retry on rate limit."""
    for attempt in range(3):
        resp = session.get(url, params=params, timeout=20)
        if resp.status_code == 429:
            wait = 60 * (attempt + 1)
            print(f"    Rate limited - waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Failed after 3 attempts: {url}")


def fetch_posts():
    """Fetch this week's top posts and comments via Reddit's public JSON API (no credentials)."""
    import requests as req

    session = req.Session()
    session.headers.update({"User-Agent": "SkincareIntelAgent/1.0 (research bot)"})

    data = []

    for sub_name in SUBREDDITS:
        print(f"  Fetching r/{sub_name}...")
        try:
            result = _get(session, f"{REDDIT_BASE}/r/{sub_name}/top.json", {
                "t": "week",
                "limit": POSTS_PER_SUB,
            })
            time.sleep(REQUEST_DELAY)

            posts = []
            for child in result.get("data", {}).get("children", []):
                post = child.get("data", {})
                if post.get("score", 0) < MIN_POST_SCORE:
                    continue

                body = post.get("selftext") or ""
                if body in ("[removed]", "[deleted]"):
                    body = ""

                # Fetch top comments for this post
                top_comments = []
                post_id = post.get("id", "")
                if post_id:
                    try:
                        c_result = _get(session, f"{REDDIT_BASE}/r/{sub_name}/comments/{post_id}.json", {
                            "sort": "top",
                            "limit": MAX_COMMENTS_PER_POST,
                            "depth": 1,
                        })
                        time.sleep(REQUEST_DELAY)
                        # c_result is [post_listing, comments_listing]
                        if len(c_result) >= 2:
                            for child_c in c_result[1].get("data", {}).get("children", []):
                                c = child_c.get("data", {})
                                if (c.get("score", 0) >= MIN_COMMENT_SCORE
                                        and c.get("body") not in ("[deleted]", "[removed]", None)):
                                    top_comments.append(c["body"][:MAX_COMMENT_CHARS])
                    except Exception as e:
                        print(f"    Warning: Comments unavailable for post {post_id}: {e}")

                posts.append({
                    "title": post.get("title", ""),
                    "body": body[:MAX_BODY_CHARS],
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "top_comments": top_comments,
                })

        except Exception as e:
            print(f"  Warning: Could not fetch r/{sub_name}: {e}")
            continue

        data.append({"subreddit": sub_name, "posts": posts})
        print(f"    -> {len(posts)} posts")

    return data


# ─── Gemini Analysis ───────────────────────────────────────────────────────────

def analyze(data):
    """Synthesize insights from skincare community data using Gemini REST API."""
    import requests as req

    api_key = os.environ["GEMINI_API_KEY"]
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models"
        f"/gemini-2.5-flash:generateContent?key={api_key}"
    )

    week_end = datetime.now().strftime("%B %d, %Y")
    week_start = (datetime.now() - timedelta(days=7)).strftime("%B %d")
    total_posts = sum(len(d["posts"]) for d in data)

    system_prompt = (
        "You are a consumer insights analyst for Foxtale, an Indian D2C skincare brand "
        "(science-backed, formulated for Indian skin and climate, ~Rs 350 Cr revenue). "
        "You synthesize social listening data into product and marketing intelligence. "
        "You write in Slack-compatible formatting: *bold* for headers, no markdown ##."
    )

    user_prompt = f"""Analyse the following Reddit discussions from skincare communities (week of {week_start}-{week_end}).
Total posts: {total_posts} across {len(data)} subreddits.

DATA:
{json.dumps(data, ensure_ascii=False)}

Produce a weekly intelligence brief. Be specific - use real examples and quotes. Avoid generic observations.

Format each section exactly as shown below (use Slack bold: *SECTION NAME*):

*WHAT THEY'RE TALKING ABOUT*
The 5 biggest themes this week. Each: one-line summary + one specific example or quote from the data. Flag if India-specific.

*EMERGING TRENDS*
New ingredients, rituals, or product types gaining traction. What are people newly excited about? 2-4 trends max.

*RECURRING PAIN POINTS*
Top 3-4 specific frustrations. Be precise - not "dryness" but "moisturiser pilling under sunscreen in humid weather."

*PSYCHOLOGY & BEHAVIOUR SHIFTS*
This is the most important section. Deeper patterns in how people think or talk about skincare:
- Mindset shifts (e.g. minimalism vs. layering, DIY vs. clinical)
- New anxieties or aspirations emerging
- How the relationship with products/brands/ingredients is changing
- Any demographic signals (age groups, first-timers vs. enthusiasts)

*INDIA-SPECIFIC INSIGHTS*
From r/IndianSkincareAddicts and r/IndianBeautyDeals - climate, skin type, price sensitivity, local brands, seasonal mentions.

*OPPORTUNITY SIGNALS FOR FOXTALE*
2-3 specific unmet needs that Foxtale could address in product, communication, or experience.

*FOXTALE MENTIONS*
Any direct mentions of Foxtale. If none: "None this week."

Keep each section tight and scannable. No filler phrases."""

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.7},
    }

    resp = req.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


# ─── Slack Delivery ─────────────────────────────────────────────────────────────

def build_slack_blocks(brief, total_posts):
    """Format the brief as Slack Block Kit blocks."""
    week_end = datetime.now().strftime("%d %b %Y")
    week_start = (datetime.now() - timedelta(days=7)).strftime("%d %b")
    sources = " · ".join(f"r/{s}" for s in SUBREDDITS)

    # Slack section blocks have a 3000 char limit - split if needed
    MAX_CHARS = 2800
    chunks = [brief[i: i + MAX_CHARS] for i in range(0, len(brief), MAX_CHARS)]

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Skincare Intelligence Brief - {week_start}-{week_end}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Analysed *{total_posts} posts* · {sources}",
                }
            ],
        },
        {"type": "divider"},
    ]

    for chunk in chunks:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": chunk},
        })

    blocks += [
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Foxtale Skincare Intelligence Agent · runs every Monday 10 AM IST_",
                }
            ],
        },
    ]

    return blocks


def send_to_slack(brief, total_posts):
    """Post the brief to Slack via incoming webhook."""
    import requests

    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    blocks = build_slack_blocks(brief, total_posts)

    response = requests.post(
        webhook_url,
        json={"blocks": blocks},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Slack delivery failed: {response.status_code} - {response.text}"
        )

    print("Brief delivered to Slack.")


def send_error_to_slack(error_msg):
    """Send a failure alert to Slack."""
    import requests

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    requests.post(
        webhook_url,
        json={
            "text": f":warning: *Skincare Intelligence Agent failed*\n```{error_msg[:500]}```"
        },
        timeout=10,
    )


# ─── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"Skincare Intelligence Agent - {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")

    try:
        print("\n1. Fetching Reddit data...")
        data = fetch_posts()
        total_posts = sum(len(d["posts"]) for d in data)
        print(f"   Total: {total_posts} posts")

        if total_posts == 0:
            raise RuntimeError("No posts fetched. Check Reddit connectivity.")

        print("\n2. Analysing with Gemini...")
        brief = analyze(data)
        print(f"   Brief generated ({len(brief)} chars)")

        print("\n3. Sending to Slack...")
        send_to_slack(brief, total_posts)

        print("\nDone.")

    except Exception as e:
        error_str = str(e)
        print(f"\nERROR: {error_str}", file=sys.stderr)
        send_error_to_slack(error_str)
        sys.exit(1)


if __name__ == "__main__":
    main()
