# wikiquote-qotd
GitHub Action to create Pages feed for Wikiquote Quote of the Day for use in RSS feeds. 
can be copied. 

# Wikiquote Quote of the Day — RSS Feed

A self-updating RSS feed of [Wikiquote's Quote of the Day](https://en.wikiquote.org/wiki/Wikiquote:Quote_of_the_day), powered by GitHub Actions and hosted on GitHub Pages. One API call to Wikiquote per day. No server required.

---

## Setup 

### 1. Fork this repo

Click **Fork** at the top right of this page.

### 2. Enable GitHub Pages

In your fork: **Settings → Pages**

- Source: **Deploy from a branch**
- Branch: **main**
- Folder: **/ (root)**

Save. Wait 1-2 minutes for the first deploy to finish (status will say "building" then switch to your live URL).

### 3. Run the Action once to seed the feed

In your fork: **Actions → Fetch Quote of the Day → Run workflow**

Wait ~30 seconds, then check that `feed.xml` in your repo shows today's quote.

---

## Your feed URL: https://YOUR-USERNAME.github.io/wikiquote-qotd/feed.xml

Paste that into FreshRSS, Reeder, or any RSS reader.

---

## How it updates

The feed refreshes automatically every day. No action needed on your part once it's set up; it just runs.

---

## How it works

- `.github/workflows/daily.yml` — runs `fetch_qotd.py` daily via GitHub Actions
- `fetch_qotd.py` — fetches today's quote via the Wikiquote API, parses it, appends it to `feed.xml`, keeps the last 90 days
- `feed.xml` — the RSS feed itself, committed to the repo and served by GitHub Pages

No dependencies beyond Python's standard library. No secrets, tokens, or paid services required.















