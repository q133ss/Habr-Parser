# Habr Parser

## Quick start

1) Install dependencies:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

2) Configure OpenAI + Telegram credentials in `.env`:

```
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4o-mini
TG_BOT_TOKEN=your_telegram_bot_token
TG_CHAT_ID=your_telegram_chat_id
```

3) Download HTML and screenshots (artifacts):

```bash
python tools/fetch_pages.py
```

4) Parse the feed and store articles in SQLite:

```bash
python habr_parser.py --limit 10 --db habr.db
```

5) Daily pipeline: select top posts and generate Zen drafts:

```bash
python zen_pipeline.py --limit 10 --top-k 3 --db habr.db
```

6) Schedule (Windows Task Scheduler example for 09:00 daily):

```bash
schtasks /Create /SC DAILY /TN "HabrZenDaily" /TR "python c:\\Users\\lexa3\\Desktop\\itParser\\zen_pipeline.py --limit 10 --top-k 3 --db c:\\Users\\lexa3\\Desktop\\itParser\\habr.db" /ST 09:00
```
