#!/usr/bin/env python3
"""Присылает в Telegram новости о новых моделях ИИ.
Запускается по расписанию (GitHub Actions). Состояние хранит в seen.json."""
import os, json, time, html, pathlib, urllib.parse, urllib.request

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]
AA_KEY    = os.environ.get("AA_API_KEY", "")   # необязательно
STATE     = pathlib.Path("seen.json")
UA        = "Mozilla/5.0 (ai-news-bot)"

# RSS/Atom-ленты с анонсами моделей
FEEDS = [
    "https://huggingface.co/blog/feed.xml",
    "https://www.reddit.com/r/LocalLLaMA/.rss",
    "https://simonwillison.net/atom/everything/",
]
# Поиск по Hacker News (свежие сюжеты)
HN_QUERIES = ["Claude", "GPT", "Gemini", "DeepSeek", "Qwen", "Kimi", "GLM", "Llama", "Mistral", "Grok"]

# Фильтр: в заголовке должно быть имя семейства модели И признак релиза
MODELS  = ["claude","gpt","gemini","glm","kimi","deepseek","qwen","llama",
           "mistral","grok","o3","o4","phi","command r","yi-","minimax"]
RELEASE = ["release","released","launch","introduc","announc","available","open-source",
           "open source","weights","new model","unveil","preview","drops","now live","ships"]

def looks_like_model_news(title: str) -> bool:
    t = title.lower()
    return any(m in t for m in MODELS) and any(r in t for r in RELEASE)

def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read()

def parse_feed(url: str):
    import feedparser
    d = feedparser.parse(get(url))
    for e in d.entries:
        title = getattr(e, "title", "")
        link  = getattr(e, "link", "")
        if title and link:
            yield (link, title)

def parse_hn():
    for q in HN_QUERIES:
        u = ("https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=20&query="
             + urllib.parse.quote(q))
        try:
            data = json.loads(get(u))
        except Exception:
            continue
        for h in data.get("hits", []):
            title = h.get("title") or ""
            link  = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            if title:
                yield (link, title)

def parse_openrouter():
    """Новые модели на OpenRouter (публичный API, ключ не нужен)."""
    data = json.loads(get("https://openrouter.ai/api/v1/models"))["data"]
    done = set()
    for m in data:
        base = m["id"].split(":")[0]          # без :free / :batch вариантов
        if base in done: continue
        done.add(base)
        pr = m.get("pricing", {})
        try:
            price = f"${float(pr.get('prompt',0))*1e6:.2f} / ${float(pr.get('completion',0))*1e6:.2f} за 1M"
        except Exception:
            price = ""
        ctx = m.get("context_length")
        info = " · ".join(x for x in [price, f"контекст {ctx:,}".replace(",", " ") if ctx else ""] if x)
        yield ("or:" + base, f"🆕 <b>OpenRouter: {html.escape(m.get('name', base))}</b>\n{info}\nhttps://openrouter.ai/{base}")

def parse_aa():
    """Новые модели в рейтинге Artificial Analysis (нужен бесплатный ключ)."""
    if not AA_KEY: return
    req = urllib.request.Request("https://artificialanalysis.ai/api/v2/language/models",
                                 headers={"x-api-key": AA_KEY, "User-Agent": UA})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read()).get("data", [])
    for m in data:
        mid  = m.get("id") or m.get("slug") or m.get("name")
        name = m.get("name") or mid
        ev   = m.get("evaluations") or {}
        idx  = m.get("artificial_analysis_intelligence_index") or ev.get("artificial_analysis_intelligence_index")
        slug = m.get("slug")
        link = f"https://artificialanalysis.ai/models/{slug}" if slug else "https://artificialanalysis.ai/"
        extra = f"\nIntelligence Index: {idx}" if idx is not None else ""
        yield ("aa:" + str(mid), f"📊 <b>Artificial Analysis: {html.escape(str(name))}</b>{extra}\n{link}")

def send(text: str):
    u = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": CHAT_ID, "text": text,
        "disable_web_page_preview": "false", "parse_mode": "HTML",
    }).encode()
    urllib.request.urlopen(urllib.request.Request(u, data=body), timeout=30).read()

def main():
    seen = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    first_run = not STATE.exists()
    items = []
    for f in FEEDS:
        try: items += list(parse_feed(f))
        except Exception as ex: print("feed err", f, ex)
    try: items += list(parse_hn())
    except Exception as ex: print("hn err", ex)

    direct = []   # OpenRouter и AA: каждая новая модель = новость, без фильтра
    for src in (parse_openrouter, parse_aa):
        try: direct += list(src() or [])
        except Exception as ex: print("err", src.__name__, ex)

    fresh = []
    # источник подключён впервые -> молча запоминаем его каталог, без спама
    new_src = {p for p in ("or:", "aa:") if not any(k.startswith(p) for k in seen)}
    for key, text in direct:
        if key in seen: continue
        seen.add(key)
        if key[:3] not in new_src:
            fresh.append(("", text))
    for link, title in items:
        if link in seen: continue
        seen.add(link)
        if looks_like_model_news(title):
            fresh.append((link, f"🤖 <b>{html.escape(title)}</b>\n{html.escape(link)}"))

    STATE.write_text(json.dumps(sorted(seen)))
    if first_run:                      # первый прогон не спамит историей
        print("init, saved", len(seen)); return
    for _, text in fresh[:15]:
        send(text)
        time.sleep(1)
    print("sent", len(fresh))

if __name__ == "__main__":
    main()
