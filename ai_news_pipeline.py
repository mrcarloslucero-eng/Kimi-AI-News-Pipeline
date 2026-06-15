#!/usr/bin/env python3
"""
AI News Automation Pipeline - GitHub Actions Compatible
"""

import feedparser
import requests
import hashlib
import re
import smtplib
import os
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict
from urllib.parse import urlparse
import time

# =============================================================================
# CONFIGURATION
# =============================================================================
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
        print("  Fetching: " + url[:60] + "...")
        feed = feedparser.parse(url)
        return feed.entries
    except Exception as e:
        print("  ERROR fetching feed: " + str(e))
        return []


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def get_story_hash(title, link):
    content = title.lower().strip() + "|" + urlparse(link).netloc
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def is_recent(entry, hours=HOURS_BACK):
    published = entry.get('published_parsed') or entry.get('updated_parsed')
    if not published:
        return True
    pub_time = datetime(*published[:6])
    cutoff_time = datetime.now() - timedelta(hours=hours)
    return pub_time > cutoff_time


def categorize_story(title, summary):
    text = (title + " " + summary).lower()
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
    print("  Deduplication: " + str(len(stories)) + " raw -> " + str(len(unique_stories)) + " unique")
    return unique_stories


def summarize_with_ai(title, content, category):
    content = content[:3500]
    prompt = ("You are a scriptwriter for an AI news YouTube channel aimed at smart everyday people who are NOT tech experts.\n\n"
              "STORY CATEGORY: " + category.upper() + "\n"
              "TITLE: " + title + "\n"
              "SOURCE CONTENT: " + content + "\n\n"
              "Write a 60-90 second script segment with EXACTLY these sections:\n\n"
              "**HOOK:** One punchy sentence that makes a normal person care about this story. No jargon.\n\n"
              "**THE DRAMA:** What happened, in plain English. If there is conflict, explain both sides simply.\n\n"
              "**WHY IT MATTERS:** Real-world impact on money, privacy, jobs, or daily life. Be specific.\n\n"
              "**THE ANGLE:** What makes this story interesting, controversial, or different from the usual hype?\n\n"
              "RULES:\n"
              "- Conversational, punchy, no corporate speak\n"
              "- Write as if you are talking to a friend at a coffee shop\n"
              "- If numbers are mentioned, put them in context\n"
              "- Avoid phrases like 'In the ever-evolving landscape of AI...'\n"
              "- End with a subtle question or forward-looking statement")

    if AI_PROVIDER == "openai":
        return call_openai_api(prompt)
    else:
        return call_anthropic_api(prompt)


def call_openai_api(prompt):
    headers = {
        "Authorization": "Bearer " + OPENAI_API_KEY,
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
        return "[ERROR: API request failed - " + str(e) + "]"
    except (KeyError, IndexError) as e:
        return "[ERROR: Unexpected API response format - " + str(e) + "]"


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
        return "[ERROR: API request failed - " + str(e) + "]"
    except (KeyError, IndexError) as e:
        return "[ERROR: Unexpected API response format - " + str(e) + "]"


def build_html_email(stories_by_category):
    now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    html = ("<!DOCTYPE html>\n<html>\n<head>\n"
            "    <style>\n"
            "        body { font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto; padding: 20px; }\n"
            "        h1 { color: #1a1a1a; border-bottom: 3px solid #6366f1; padding-bottom: 10px; }\n"
            "        h2 { color: #4f46e5; margin-top: 30px; text-transform: uppercase; font-size: 14px; letter-spacing: 1px; }\n"
            "        h3 { margin-bottom: 5px; font-size: 18px; }\n"
            "        h3 a { color: #1a1a1a; text-decoration: none; }\n"
            "        h3 a:hover { color: #6366f1; text-decoration: underline; }\n"
            "        .story { background: #f8fafc; border-left: 4px solid #6366f1; padding: 15px 20px; margin-bottom: 25px; border-radius: 0 8px 8px 0; }\n"
            "        .meta { color: #64748b; font-size: 13px; margin-bottom: 10px; }\n"
            "        .summary { background: white; padding: 15px; border-radius: 6px; border: 1px solid #e2e8f0; white-space: pre-wrap; font-family: Georgia, serif; font-size: 15px; }\n"
            "        .footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 12px; text-align: center; }\n"
            "    </style>\n"
            "</head>\n<body>\n"
            "    <h1>AI News Daily Brief</h1>\n"
            "    <p style=\"color: #64748b;\"><em>" + now + "</em></p>\n")

    emojis = {"datacenter": "DC", "regulation": "REG", "jobs": "JOBS", "general": "NEWS"}
    for category in ["datacenter", "regulation", "jobs", "general"]:
        stories = stories_by_category.get(category, [])
        if not stories:
            continue
        emoji = emojis.get(category, "NEWS")
        html += "    <h2>" + emoji + " " + category.upper() + "</h2>\n"
        for story in stories:
            html += ("    <div class=\"story\">\n"
                     "        <h3><a href=\"" + story['link'] + "\">" + story['title'] + "</a></h3>\n"
                     "        <div class=\"meta\">" + story['source'] + " | " + story['published'] + "</div>\n"
                     "        <div class=\"summary\">" + story['summary'] + "</div>\n"
                     "    </div>\n")

    html += ("    <div class=\"footer\">\n"
             "        Generated by AI News Pipeline | Edit and publish to your CMS\n"
             "    </div>\n"
             "</body>\n"
             "</html>")
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
        print("Email sent successfully to " + EMAIL_TO)
        return True
    except smtplib.SMTPAuthenticationError:
        print("AUTH ERROR: Check your email password. For Gmail, use an App Password.")
        return False
    except Exception as e:
        print("Email failed: " + str(e))
        return False


def main():
    print("=" * 60)
    print("AI NEWS PIPELINE STARTING")
    print("Provider: " + AI_PROVIDER + " | Model: " + AI_MODEL + " | Lookback: " + str(HOURS_BACK) + "h")
    print("=" * 60)

    all_raw_stories = []
    for category, urls in FEEDS.items():
        print("\nCategory: " + category)
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

    print("\nTotal raw stories collected: " + str(len(all_raw_stories)))

    print("\nDeduplicating...")
    unique_stories = deduplicate_stories(all_raw_stories)

    print("\nOrganizing by category...")
    by_category = defaultdict(list)
    for story in unique_stories:
        by_category[story['category']].append(story)

    print("\nGenerating AI summaries...")
    print("Using " + AI_PROVIDER + " - this may take a minute")

    stories_to_summarize = []
    for category in ["datacenter", "regulation", "jobs", "general"]:
        top_stories = by_category[category][:MAX_STORIES_PER_CATEGORY]
        stories_to_summarize.extend(top_stories)

    for i, story in enumerate(stories_to_summarize, 1):
        print("[" + str(i) + "/" + str(len(stories_to_summarize)) + "] Summarizing: " + story['title'][:55] + "...")
        story['summary'] = summarize_with_ai(story['title'], story['raw_summary'], story['category'])
        time.sleep(1)

    print("\nBuilding email...")
    email_groups = defaultdict(list)
    for story in stories_to_summarize:
        email_groups[story['category']].append(story)

    html_body = build_html_email(email_groups)
    subject = "AI News Brief - " + datetime.now().strftime('%A, %B %d')

    print("\nSending email...")
    success = send_email(subject, html_body)

    print("\n" + "=" * 60)
    if success:
        print("PIPELINE COMPLETE")
        print("Stories summarized: " + str(len(stories_to_summarize)))
        print("Categories covered: " + str(list(email_groups.keys())))
    else:
        print("PIPELINE COMPLETE WITH ERRORS")
    print("=" * 60)


if __name__ == "__main__":
    main()
