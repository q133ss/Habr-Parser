# Habr Parser

## Quick start

1) Install dependencies:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

2) Download HTML and screenshots (artifacts):

```bash
python tools/fetch_pages.py
```

3) Parse the feed and store articles in SQLite:

```bash
python habr_parser.py --limit 10 --db habr.db
```
