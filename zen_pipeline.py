import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv
import os

from habr_parser import (
    FEED_URL,
    fetch_html,
    init_db,
    parse_article,
    parse_feed,
    save_articles,
)


@dataclass
class RankedArticle:
    url: str
    title: str
    reason: str


def load_env() -> None:
    load_dotenv()


def get_openai_config() -> tuple[str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    return api_key, model


def get_telegram_config() -> tuple[Optional[str], Optional[str]]:
    token = os.getenv("TG_BOT_TOKEN", "").strip() or None
    chat_id = os.getenv("TG_CHAT_ID", "").strip() or None
    return token, chat_id


def build_rank_prompt(articles: List[dict], top_k: int) -> str:
    return (
        "You are an editor for Yandex Zen. Select the most interesting posts for a broad audience. "
        "Return JSON only: {\"items\": [{\"url\": \"...\", \"title\": \"...\", \"reason\": \"...\"}]} "
        f"Choose exactly {top_k} items. Use the input list, keep urls exact.\n\n"
        "Articles:\n"
        + json.dumps(articles, ensure_ascii=False, indent=2)
    )


def build_zen_prompt(article: dict) -> str:
    return (
        "Write a Yandex Zen post in Russian based on the article data. "
        "Keep it engaging for a broad audience and avoid clickbait. "
        "Return JSON only: {\"title\": \"...\", \"lead\": \"...\", \"body\": \"...\"}.\n\n"
        + json.dumps(article, ensure_ascii=False, indent=2)
    )


def call_openai(api_key: str, model: str, prompt: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful editor."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.6,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def compose_telegram_message(title: str, lead: str, body: str, url: str) -> str:
    parts = [title.strip()]
    if lead:
        parts.append(lead.strip())
    if body:
        parts.append(body.strip())
    parts.append(f"Источник: {url}")
    message = "\n\n".join([p for p in parts if p])
    if len(message) > 3900:
        message = message[:3897] + "..."
    return message


def send_telegram_message(token: str, chat_id: str, text: str) -> str:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    resp = requests.post(url, data=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return str(data["result"]["message_id"])


def parse_json_from_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)


def rank_articles(api_key: str, model: str, articles: List[dict], top_k: int) -> List[RankedArticle]:
    prompt = build_rank_prompt(articles, top_k)
    try:
        response = call_openai(api_key, model, prompt)
        payload = parse_json_from_response(response)
        items = payload.get("items", [])
        ranked: List[RankedArticle] = []
        for item in items:
            ranked.append(
                RankedArticle(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    reason=item.get("reason", ""),
                )
            )
        return ranked
    except Exception as exc:
        print(f"Ranking failed, fallback to first {top_k}: {exc}")
        fallback = []
        for article in articles[:top_k]:
            fallback.append(RankedArticle(url=article["url"], title=article["title"], reason="fallback"))
        return fallback


def generate_zen_post(api_key: str, model: str, article: dict) -> dict:
    prompt = build_zen_prompt(article)
    response = call_openai(api_key, model, prompt)
    return parse_json_from_response(response)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily Habr -> Zen pipeline")
    parser.add_argument("--db", default="habr.db", help="SQLite DB path")
    parser.add_argument("--limit", type=int, default=10, help="Number of feed items to parse")
    parser.add_argument("--top-k", type=int, default=3, help="Number of Zen posts to generate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env()
    api_key, model = get_openai_config()
    tg_token, tg_chat_id = get_telegram_config()

    feed_html = fetch_html(FEED_URL)
    items = parse_feed(feed_html)
    if args.limit:
        items = items[: args.limit]

    articles = []
    for item in items:
        try:
            article = parse_article(item.url)
        except Exception as exc:
            print(f"Failed to parse {item.url}: {exc}")
            continue
        if not article.title:
            article.title = item.title
        if not article.author:
            article.author = item.author
        if not article.published_at:
            article.published_at = item.published_at
        articles.append(article)

    db_path = Path(args.db)
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        save_articles(conn, articles)

        briefs = [
            {
                "url": a.url,
                "title": a.title,
                "author": a.author,
                "published_at": a.published_at,
                "tags": a.tags,
                "summary": a.content_text[:1200],
            }
            for a in articles
        ]

        ranked = rank_articles(api_key, model, briefs, args.top_k)
        article_map = {a.url: a for a in articles}
        for item in ranked:
            if not item.url:
                continue
            source_article = article_map.get(item.url)
            if not source_article:
                continue
            article_brief = {
                "url": source_article.url,
                "title": source_article.title,
                "author": source_article.author,
                "published_at": source_article.published_at,
                "tags": source_article.tags,
                "summary": source_article.content_text[:1200],
            }
            zen_payload = generate_zen_post(api_key, model, article_brief)
            zen_title = zen_payload.get("title", "").strip() or source_article.title
            zen_lead = zen_payload.get("lead", "").strip()
            zen_body = zen_payload.get("body", "").strip()

            if not zen_body:
                continue

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO zen_posts (
                    article_url, zen_title, zen_lead, zen_body, selection_reason, model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_brief["url"],
                    zen_title,
                    zen_lead,
                    zen_body,
                    item.reason,
                    model,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            if tg_token and tg_chat_id:
                should_send = cursor.rowcount > 0
                if not should_send:
                    row = conn.execute(
                        "SELECT telegram_message_id FROM zen_posts WHERE article_url = ?",
                        (article_brief["url"],),
                    ).fetchone()
                    should_send = row is not None and row[0] is None
                if should_send:
                    try:
                        message = compose_telegram_message(zen_title, zen_lead, zen_body, article_brief["url"])
                        message_id = send_telegram_message(tg_token, tg_chat_id, message)
                        conn.execute(
                            """
                            UPDATE zen_posts
                            SET telegram_message_id = ?, telegram_sent_at = ?
                            WHERE article_url = ?
                            """,
                            (message_id, datetime.now(timezone.utc).isoformat(), article_brief["url"]),
                        )
                    except Exception as exc:
                        print(f"Telegram send failed for {article_brief['url']}: {exc}")
        conn.commit()
    finally:
        conn.close()

    print(f"Pipeline complete. DB: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
