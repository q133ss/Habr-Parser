import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

import requests
from bs4 import BeautifulSoup

FEED_URL = "https://habr.com/ru/feed/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


@dataclass
class FeedItem:
    title: str
    url: str
    author: Optional[str]
    published_at: Optional[str]


@dataclass
class Article:
    title: str
    url: str
    author: Optional[str]
    published_at: Optional[str]
    content_html: str
    content_text: str
    tags: List[str]
    fetched_at: str


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def normalize_url(href: str) -> str:
    href = href.strip()
    if href.startswith("/"):
        return "https://habr.com" + href
    return href


def parse_feed(feed_html: str) -> List[FeedItem]:
    soup = BeautifulSoup(feed_html, "lxml")
    items: List[FeedItem] = []

    for article in soup.select("article.tm-articles-list__item"):
        title_tag = article.select_one("h2")
        link_tag = article.select_one("h2 a[href]")
        if not title_tag or not link_tag:
            continue
        title = title_tag.get_text(strip=True)
        url = normalize_url(link_tag.get("href", ""))
        author_tag = article.select_one("a.tm-user-info__username")
        time_tag = article.select_one("time[datetime]")
        items.append(
            FeedItem(
                title=title,
                url=url,
                author=author_tag.get_text(strip=True) if author_tag else None,
                published_at=time_tag.get("datetime") if time_tag else None,
            )
        )
    return items


def extract_content(soup: BeautifulSoup) -> tuple[str, str]:
    body = soup.select_one("#post-content-body")
    if not body:
        body = soup.select_one("div.article-body")
    if not body:
        body = soup.select_one("article.tm-article-presenter__content")
    if not body:
        return "", ""

    content_html = str(body)
    content_text = body.get_text("\n", strip=True)
    return content_html, content_text


def extract_tags(soup: BeautifulSoup) -> List[str]:
    tags = [t.get_text(strip=True) for t in soup.select("div.tm-separated-list.tag-list a.link span")]
    if not tags:
        tags = [t.get_text(strip=True) for t in soup.select("a.tm-tags-list__link span")]
    return [t for t in tags if t]


def parse_article(url: str) -> Article:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.select_one("h1.tm-title") or soup.select_one("h1")
    author_tag = soup.select_one("a.tm-user-info__username")
    time_tag = soup.select_one("time[datetime]")
    content_html, content_text = extract_content(soup)
    tags = extract_tags(soup)

    return Article(
        title=title_tag.get_text(strip=True) if title_tag else "",
        url=url,
        author=author_tag.get_text(strip=True) if author_tag else None,
        published_at=time_tag.get("datetime") if time_tag else None,
        content_html=content_html,
        content_text=content_text,
        tags=tags,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            author TEXT,
            published_at TEXT,
            content_html TEXT,
            content_text TEXT,
            tags_json TEXT,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def save_articles(conn: sqlite3.Connection, articles: Iterable[Article]) -> int:
    rows = 0
    for article in articles:
        tags_json = json.dumps(article.tags, ensure_ascii=True)
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO articles (
                url, title, author, published_at, content_html, content_text, tags_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.url,
                article.title,
                article.author,
                article.published_at,
                article.content_html,
                article.content_text,
                tags_json,
                article.fetched_at,
            ),
        )
        rows += cursor.rowcount
    conn.commit()
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse Habr feed and store articles in SQLite")
    parser.add_argument("--db", default="habr.db", help="SQLite DB path")
    parser.add_argument("--limit", type=int, default=10, help="Limit number of feed items to parse")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    feed_html = fetch_html(FEED_URL)
    items = parse_feed(feed_html)
    if args.limit:
        items = items[: args.limit]

    articles: List[Article] = []
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
        inserted = save_articles(conn, articles)
    finally:
        conn.close()

    print(f"Parsed: {len(articles)}, inserted: {inserted}, db: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
