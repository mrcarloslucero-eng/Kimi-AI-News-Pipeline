#!/usr/bin/env python3
"""
AI News Automation Pipeline - GitHub Actions Compatible
========================================================
Fetches RSS feeds, deduplicates, categorizes, summarizes with AI,
and emails a daily brief.

RUNS BOTH LOCALLY AND IN GITHUB ACTIONS:
- Local: Uses hardcoded fallback values in CONFIG
- GitHub Actions: Reads from environment variables (set via GitHub Secrets)
"""

import feedparser
import requests
import hashlib
import re
import smtplib
import os  # NEW: For reading environment variables
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict
from urllib.parse import urlparse
import time

# =============================================================================
# CONFIGURATION
# =============================================================================
# These are FALLBACK values for local testing.
# In GitHub Actions, these are overridden by environment variables (GitHub Secrets).

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-your-anthropic-key-here")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "anthropic")
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
EMAIL_USERNAME = os.environ.get("EMAIL_USERNAME", "your.email@gmail.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "your-app-password-16-chars")
EMAIL_TO = os.environ.get("EMAIL_TO", "your.email@gmail.com")

HOURS_BACK = int(os.environ.get("HOURS_BACK", "24"))
MAX_STORIES_PER_CATEGORY = int(os.environ.get("MAX_STORIES_PER_CATEGORY", "3"))
REQUEST_TIMEOUT = 30

FEEDS = {
    "datacenter": [
        "https://www.datacenterknowledge.com/feed",
        "https://www.theregister.com/data_centre/headlines.atom",
    ],
    "regulation": [
        "https://www.politico.com/rss/technology.xml",
        "https://www.euractiv.com/section/artificial-intelligence/feed/",
    ],
    "jobs": [
        "https://www.vox.com/recode/rss.xml",
        "https://www.theguardian.com/technology/artificialintelligence/rss",
    ],
    "general": [
        "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
        "https://arstechnica.com/tag/ai/feed/",
        "https://hnrss.org/newest?q=AI",
        "https://www.anthropic.com/news/rss.xml",
        "https://openai.com/news/rss.xml",
    ],
}


def fetch_feed(url):
    try:
        print(f"  Fetching: {url[:60]}...")
        feed = feedparser.parse(url)
        return feed.entries
    except Exception as e:
        print(f"  ERROR fetching feed: {e}")
        return []


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def get_story_hash(title, link):
    content = f"{title.lower().strip()}|{urlparse(link).netloc}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def is_recent(entry, hours=HOURS_BACK):
    published = entry.get('published_parsed') or entry.get('updated_parsed')
    if not published:
        return True
    pub_time = datetime(*published[:6])
    cutoff_time = datetime.now() - timedelta(hours=hours)
    return pub_time > cutoff_time


def categorize_story(title, summary):
    text = f"{title} {summary}".lower()
    keywords = {
        "datacenter": [
            "datacenter", "data center", "gpu", "server", "infrastructure",
            "facility", "power", "cooling", "nvidia", "cluster", "compute"
        ],
        "regulation": [
            "regulation", "regulatory", "law", "policy", "government",
            "eu", "congress", "senate", "bill", "act", "legal", "sue", "lawsuit",
            "fine", "antitrust", "oversight"
        ],
        "jobs": [
            "job", "employment", "layoff", "layoffs", "firing", "hiring",
            "workforce", "labor", "career", "worker", "replace", "unemployment",
            "wage", "union", "strike"
        ],
    }
    for category, words in keywords.items():
        if any(word in text for word in words):
            return category
    return "general"


def deduplicate_stories(stories):
    seen_hashes = set()
    unique_stories = []
    for story in stories:
        story_hash = story['hash']
        if story_hash not in seen_hashes:
            seen_hashes.add(story_hash)
            unique_stories.append(story)
    print(f"  Deduplication: {len(stories)} raw → {len(unique_stories)} unique")
    return unique_stories


def summarize_with_ai(title, content, category):
    content = content[:3500]
    prompt = f"""You are a scriptwriter for an AI news YouTube channel aimed at smart everyday people who are NOT tech experts.

STORY CATEGORY: {category.upper()}
TITLE: {title}
SOURCE CONTENT: {content}

Write a 60-90 second script segment with EXACTLY these sections:

**HOOK:** One punchy sentence that makes a normal person care about this story. No jargon.

**THE DRAMA:** What happened, in plain English. If there's conflict, explain both sides simply.

**WHY IT MATTERS:** Real-world impact on money, privacy, jobs, or daily life. Be specific.

**THE ANGLE:** What makes this story interesting, controversial, or different from the usual hype?

RULES:
- Conversational, punchy, no corporate speak
- Write as if you're talking to a friend at a coffee shop
- If numbers are mentioned, put them in context
- Avoid phrases like "In the ever-evolving landscape of AI..."
- End with a subtle question or forward-looking statement"""

    if AI_PROVIDER == "openai":
        return call_openai_api(prompt)
    else:
        return call_anthropic_api(prompt)


def call_openai_api(prompt):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 600
    }
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        return f"[ERROR: API request failed - {e}]"
    except (KeyError, IndexError) as e:
        return f"[ERROR: Unexpected API response format - {e}]"


def call_anthropic_api(prompt):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01"
    }
    payload = {
        "model": AI_MODEL,
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()['content'][0]['text']
    except requests.exceptions.RequestException as e:
        return f"[ERROR: API request failed - {e}]"
    except (KeyError, IndexError) as e:
        return f"[ERROR: Unexpected API response format - {e}]"


def build_html_email(stories_by_category):
    now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #1a1a1a; border-bottom: 3px solid #6366f1; padding-bottom: 10px; }}
        h2 {{ color: #4f46e5; margin-top: 30px; text-transform: uppercase; font-size: 14px; letter-spacing: 1px; }}
        h3 {{ margin-bottom: 5px; font-size: 18px; }}
        h3 a {{ color: #1a1a1a; text-decoration: none; }}
        h3 a:hover {{ color: #6366f1; text-decoration: underline; }}
        .story {{ background: #f8fafc; border-left: 4px solid #6366f1; padding: 15px 20px; margin-bottom: 25px; border-radius: 0 8px 8px 0; }}
        .meta {{ color: #64748b; font-size: 13px; margin-bottom: 10px; }}
        .summary {{ background: white; padding: 15px; border-radius: 6px; border: 1px solid #e2e8f0; white-space: pre-wrap; font-family: Georgia, serif; font-size: 15px; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 12px; text-align: center; }}
    </style>
</head>
<body>
    <h1>🤖 AI News Daily Brief</h1>
    <p style="color: #64748b;"><em>{now}</em></p>
"""
    emojis = {"datacenter": "🏭", "regulation": "⚖️", "jobs": "💼", "general": "🌐"}
    for category in ["datacenter", "regulation", "jobs", "general"]:
        stories = stories_by_category.get(category, [])
        if not stories:
            continue
        emoji = emojis.get(category, "📰")
        html += f"<h2>{emoji} {category.upper()}</h2>"
        for story in stories:
            html += f"""
    <div class="story">
        <h3><a href="{story['link']}">{story['title']}</a></h3>
        <div class="meta">📰 {story['source']} | ⏰ {story['published']}</div>
        <div class="summary">{story['summary']}</div>
    </div>
"""
    html += """
    <div class="footer">
        Generated by AI News Pipeline | Edit and publish to your CMS
    </div>
</body>
</html>"""
    return html


def send_email(subject, html_body):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = EMAIL_USERNAME
    msg['To'] = EMAIL_TO
    msg.attach(MIMEText(html_body, 'html'))
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"✅ Email sent successfully to {EMAIL_TO}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("❌ AUTH ERROR: Check your email password. For Gmail, use an App Password.")
        return False
    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False


def main():
    print("=" * 60)
    print("🚀 AI NEWS PIPELINE STARTING")
    print(f"   Provider: {AI_PROVIDER} | Model: {AI_MODEL} | Lookback: {HOURS_BACK}h")
    print("=" * 60)

    all_raw_stories = []
    for category, urls in FEEDS.items():
        print(f"
📂 Category: {category}")
        for url in urls:
            entries = fetch_feed(url)
            for entry in entries:
                if not is_recent(entry):
                    continue
                title = entry.get('title', 'Untitled')
                link = entry.get('link', '')
                raw_summary = entry.get('summary', entry.get('description', ''))
                story = {
                    'title': title,
                    'link': link,
                    'raw_summary': clean_text(raw_summary),
                    'source': urlparse(url).netloc.replace('www.', ''),
                    'hash': get_story_hash(title, link),
                    'published': entry.get('published', 'Recent'),
                    'category': category if category != "general" else categorize_story(title, clean_text(raw_summary))
                }
                all_raw_stories.append(story)
            time.sleep(0.5)

    print(f"
📊 Total raw stories collected: {len(all_raw_stories)}")

    print("
🧹 STEP 2: Deduplicating...")
    unique_stories = deduplicate_stories(all_raw_stories)

    print("
🏷️  STEP 3: Organizing by category...")
    by_category = defaultdict(list)
    for story in unique_stories:
        by_category[story['category']].append(story)

    print("
🤖 STEP 4: Generating AI summaries...")
    print(f"   (Using {AI_PROVIDER} - this may take a minute)")

    stories_to_summarize = []
    for category in ["datacenter", "regulation", "jobs", "general"]:
        top_stories = by_category[category][:MAX_STORIES_PER_CATEGORY]
        stories_to_summarize.extend(top_stories)

    for i, story in enumerate(stories_to_summarize, 1):
        print(f"   [{i}/{len(stories_to_summarize)}] Summarizing: {story['title'][:55]}...")
        story['summary'] = summarize_with_ai(story['title'], story['raw_summary'], story['category'])
        time.sleep(1)

    print("
📧 STEP 5: Building email...")
    email_groups = defaultdict(list)
    for story in stories_to_summarize:
        email_groups[story['category']].append(story)

    html_body = build_html_email(email_groups)
    subject = f"🤖 AI News Brief - {datetime.now().strftime('%A, %B %d')}"

    print("
📤 STEP 6: Sending email...")
    success = send_email(subject, html_body)

    print("
" + "=" * 60)
    if success:
        print("✅ PIPELINE COMPLETE")
        print(f"   Stories summarized: {len(stories_to_summarize)}")
        print(f"   Categories covered: {list(email_groups.keys())}")
    else:
        print("⚠️  PIPELINE COMPLETE WITH ERRORS")
    print("=" * 60)


if __name__ == "__main__":
    main()
