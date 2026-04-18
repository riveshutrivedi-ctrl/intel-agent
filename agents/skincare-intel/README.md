# Skincare Intelligence Agent

Automatically fetches weekly skincare discussions from Reddit, analyses them with Google Gemini, and delivers a structured brief to Slack every **Monday at 10 AM IST**.

**Subreddits monitored:**
- `r/IndianSkincareAddicts` — India-specific, highest signal
- `r/SkincareAddiction` — Global, large community
- `r/AsianBeauty` — Ingredient-focused
- `r/30PlusSkinCare` — Age-conscious routines
- `r/IndianBeautyDeals` — Price sensitivity, Indian market
- `r/Tretinoin` — Active ingredient discussions

---

## One-time Setup

You need **4 credentials**. Set them up once; the agent runs automatically after that.

---

### 1. Reddit API credentials (free)

1. Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Scroll down, click **"create another app"**
3. Name: `SkincareIntelAgent`, Type: **script**, Redirect URI: `http://localhost`
4. Click Create
5. You'll see:
   - `REDDIT_CLIENT_ID` = the short string under your app name
   - `REDDIT_CLIENT_SECRET` = the "secret" field

---

### 2. Google Gemini API key (free)

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Click **Get API key** → **Create API key**
3. No billing setup required — it's genuinely free
4. This is your `GEMINI_API_KEY`

The free tier allows 15 requests/minute and 1 million tokens/day. This weekly job uses ~1 request total, so you'll never hit the limit.

---

### 3. Slack Incoming Webhook

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Name it `Skincare Intel`, pick your Foxtale workspace
4. In the left sidebar: **Incoming Webhooks** → toggle ON
5. Click **Add New Webhook to Workspace**, pick the channel you want (e.g. `#product-intel`)
6. Copy the webhook URL — this is your `SLACK_WEBHOOK_URL`

---

### 4. Deploy to GitHub

This agent runs on **GitHub Actions** (free), so it works even when your laptop is off.

1. Create a new private GitHub repo (e.g. `foxtale-product`)
2. Push the `foxtale/` folder to it:
   ```bash
   cd C:/Users/riveshu.trivedi
   git init foxtale
   cd foxtale
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/foxtale-product.git
   git push -u origin main
   ```
3. In GitHub: go to **Settings → Secrets and variables → Actions**
4. Add these 4 secrets (one at a time, click "New repository secret"):
   - `REDDIT_CLIENT_ID`
   - `REDDIT_CLIENT_SECRET`
   - `GEMINI_API_KEY`
   - `SLACK_WEBHOOK_URL`

---

## Test it manually

Once secrets are added, go to your GitHub repo → **Actions** tab → **Weekly Skincare Intelligence Brief** → **Run workflow**.

It will run immediately and post to Slack. Takes about 2–3 minutes.

---

## What the Slack brief includes

Each Monday morning you'll receive:

1. **What They're Talking About** — top 5 themes with examples
2. **Emerging Trends** — new ingredients, rituals, or products gaining traction
3. **Recurring Pain Points** — specific frustrations (not generic)
4. **Psychology & Behaviour Shifts** — how mindsets and attitudes are changing (most valuable section)
5. **India-Specific Insights** — from Indian subreddits
6. **Opportunity Signals for Foxtale** — unmet needs we could address
7. **Foxtale Mentions** — any direct brand mentions

---

## Adding more sources (future)

The agent can be extended to also pull from:
- YouTube comments (popular skincare channels)
- Nykaa/Amazon product reviews
- Google Trends data
- Blog posts via search API
