import os
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

FEED_URL = "https://habr.com/ru/feed/"
ARTIFACTS_DIR = Path("artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def save_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def find_first_article_url(feed_html: str) -> str:
    soup = BeautifulSoup(feed_html, "lxml")
    # Habr feed items contain a title link inside article.
    link = soup.select_one("article h2 a[href]")
    if not link:
        raise RuntimeError("Could not find article link in feed HTML")
    href = link.get("href", "").strip()
    if href.startswith("/"):
        href = "https://habr.com" + href
    return href


def try_screenshot(url: str, out_path: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - best effort
        print(f"Playwright not available, skipping screenshot for {url}: {exc}")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        time.sleep(2)
        page.screenshot(path=str(out_path), full_page=True)
        browser.close()


def main() -> int:
    feed_html = fetch_html(FEED_URL)
    feed_path = ARTIFACTS_DIR / "feed.html"
    save_text(feed_path, feed_html)

    try_screenshot(FEED_URL, ARTIFACTS_DIR / "feed.png")

    detail_url = find_first_article_url(feed_html)
    detail_html = fetch_html(detail_url)
    detail_path = ARTIFACTS_DIR / "detail.html"
    save_text(detail_path, detail_html)

    try_screenshot(detail_url, ARTIFACTS_DIR / "detail.png")

    print(f"Saved feed html: {feed_path}")
    print(f"Saved detail html: {detail_path}")
    print(f"Detail URL: {detail_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
