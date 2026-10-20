import asyncio
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import certifi

# На macOS у aiohttp/vkbottle иногда нет доступа к системным сертификатам.
# Поэтому подключаем сертификаты из certifi до импорта сетевых библиотек.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import OpenAI
from vkbottle import API

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
AI_AVAILABLE = bool(OPENAI_API_KEY)

VK_ACCESS_TOKEN = os.getenv("VK_ACCESS_TOKEN", "").strip()
try:
    VK_GROUP_ID = abs(int(os.getenv("VK_GROUP_ID", "0").strip() or 0))
except ValueError:
    VK_GROUP_ID = 0
VK_AVAILABLE = bool(VK_ACCESS_TOKEN and VK_GROUP_ID)

# Локальное хранение избранного и отложенных публикаций (без базы данных).
FAVORITES_FILE = BASE_DIR / "favorites.json"
SCHEDULED_FILE = BASE_DIR / "scheduled.json"
DATA_LOCK = threading.Lock()

# Фоновый планировщик отложенных постов (запускается при первом запросе).
SCHEDULER_STARTED = False
SCHEDULER_LOCK = threading.Lock()
SCHEDULER_INTERVAL = 15



# ══════════════════════════════════════════════════════════════════════
#  НАСТРОЙКИ СТИЛЯ ГЕНЕРАТОРА
#  Здесь можно менять тон, длину, эмодзи, CTA и хэштеги.
#  Для режима ИИ эти же настройки лежат в voice.md.
# ══════════════════════════════════════════════════════════════════════

DEFAULT_MOOD = "радостное"

# Тон поста. Меняйте emoji / hook / cta / tags под свой бренд.
MOODS = {
    "радостное": {
        "label": "Радостное",
        "emoji": "✨",
        "cta_emoji": "🎉",
        "hook": "Есть повод порадоваться:",
        "cta": "Посмотрите подробности — товар стоит внимания",
        "tags": ["#находка", "#покупка"],
    },
    "экспертное": {
        "label": "Экспертное",
        "emoji": "🔎",
        "cta_emoji": "📌",
        "hook": "Коротко и по делу:",
        "cta": "Сохраните пост и выбирайте с умом",
        "tags": ["#обзор", "#выбор"],
    },
    "дерзкое": {
        "label": "Дерзкое",
        "emoji": "😎",
        "cta_emoji": "🔥",
        "hook": "Сразу к сути:",
        "cta": "Посмотрите сами — и решите без сомнений",
        "tags": ["#musthave", "#тренд"],
    },
    "заботливое": {
        "label": "Заботливое",
        "emoji": "🤍",
        "cta_emoji": "💚",
        "hook": "Позаботьтесь о главном:",
        "cta": "Побалуйте себя — вы этого достойны",
        "tags": ["#забота", "#комфорт"],
    },
    "минимализм": {
        "label": "Минимализм",
        "emoji": "🖤",
        "cta_emoji": "🔗",
        "hook": "Ничего лишнего:",
        "cta": "Подробности и заказ — по ссылке",
        "tags": ["#минимализм", "#стиль"],
    },
    "вдохновляющее": {
        "label": "Вдохновляющее",
        "emoji": "🌿",
        "cta_emoji": "✨",
        "hook": "Маленькая деталь — большая перемена:",
        "cta": "Сделайте первый шаг к переменам",
        "tags": ["#вдохновение", "#длясебя"],
    },
}

# Длина поста в шаблонном режиме (в символах).
TEMPLATE_TITLE_LIMIT = 60
TEMPLATE_LEAD_LIMIT = 420
TEMPLATE_BENEFIT_LIMIT = 160
TEMPLATE_MAX_BENEFITS = 3

# Количество эмодзи: в шаблоне их два — в заголовке и перед CTA,
# плюс 💰 для строки с ценой, если поле заполнено.
# Хотите меньше — уберите emoji / cta_emoji в настройках настроений.

# Хэштеги: максимум штук и общие хэштеги в конце.
HASHTAG_LIMIT = 5
EXTRA_HASHTAGS = ["#покупка", "#полезно"]

# ══════════════════════════════════════════════════════════════════════

STOP_WORDS = {
    "этот", "эта", "это", "как", "для", "что", "все", "весь", "ваш", "ваша",
    "ваши", "наш", "наши", "или", "при", "над", "под", "без", "если", "так",
    "там", "тут", "уже", "ещё", "еще", "очень", "который", "которая",
    "которые", "можно", "нужно", "будет", "есть", "его", "ее", "её", "их",
    "чем", "тот", "та", "те", "по", "на", "в", "с", "и", "а", "но", "о",
    "об", "от", "до", "из", "за", "не", "ни", "да", "нет",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


def default_mode():
    return "ai" if AI_AVAILABLE else "template"


def clean_text(text):
    return " ".join((text or "").split()).strip()


def format_datetime(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d.%m.%Y, %H:%M")
    except (TypeError, ValueError):
        return value or ""


def load_json_list(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_json_list(path, items):
    # Пишем во временный файл, чтобы не повредить данные при сбое.
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def get_favorites():
    with DATA_LOCK:
        items = load_json_list(FAVORITES_FILE)
    for item in items:
        item["created_at_display"] = format_datetime(item.get("created_at"))
    return items


def add_favorite(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Пост пуст")

    item = {
        "id": uuid.uuid4().hex,
        "text": text,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    with DATA_LOCK:
        items = load_json_list(FAVORITES_FILE)
        items.insert(0, item)
        save_json_list(FAVORITES_FILE, items)

    item["created_at_display"] = format_datetime(item["created_at"])
    return item


def update_favorite(favorite_id, text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Пост пуст")

    with DATA_LOCK:
        items = load_json_list(FAVORITES_FILE)
        updated = None
        for item in items:
            if item.get("id") == favorite_id:
                item["text"] = text
                item["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                updated = dict(item)
                break
        if updated is None:
            return None
        save_json_list(FAVORITES_FILE, items)

    updated["created_at_display"] = format_datetime(updated.get("created_at"))
    return updated


def delete_favorite(favorite_id):
    with DATA_LOCK:
        items = load_json_list(FAVORITES_FILE)
        remaining = [item for item in items if item.get("id") != favorite_id]
        if len(remaining) == len(items):
            return False
        save_json_list(FAVORITES_FILE, remaining)
    return True


def normalize_scheduled(items):
    changed = False
    for item in items:
        if not item.get("status"):
            # Старые записи уже были запланированы средствами ВКонтакте.
            item["status"] = "vk_scheduled" if item.get("post_id") else "pending"
            changed = True
    return changed


def parse_scheduled_datetime(value):
    scheduled_dt = datetime.fromisoformat(value)
    if scheduled_dt.tzinfo is None:
        scheduled_dt = scheduled_dt.astimezone()
    return scheduled_dt



def get_scheduled():
    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
        if normalize_scheduled(items):
            save_json_list(SCHEDULED_FILE, items)
    items.sort(key=lambda item: item.get("scheduled_at", ""))
    for item in items:
        item["scheduled_at_display"] = format_datetime(item.get("scheduled_at"))
    return items


def add_scheduled(text, scheduled_dt):
    item = {
        "id": uuid.uuid4().hex,
        "text": text,
        "scheduled_at": scheduled_dt.isoformat(timespec="seconds"),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "pending",
    }

    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
        items.append(item)
        items.sort(key=lambda entry: entry.get("scheduled_at", ""))
        save_json_list(SCHEDULED_FILE, items)

    item["scheduled_at_display"] = format_datetime(item["scheduled_at"])
    return item


def update_scheduled(scheduled_id, text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Пост пуст")

    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
        updated = None
        for item in items:
            if item.get("id") == scheduled_id:
                item["text"] = text
                item["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                updated = dict(item)
                break
        if updated is None:
            return None
        save_json_list(SCHEDULED_FILE, items)

    updated["scheduled_at_display"] = format_datetime(updated.get("scheduled_at"))
    return updated


def delete_scheduled(scheduled_id):
    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
        remaining = [item for item in items if item.get("id") != scheduled_id]
        if len(remaining) == len(items):
            return False
        save_json_list(SCHEDULED_FILE, remaining)
    return True


def publish_to_vk(text, publish_date=None):
    """Публикует или планирует пост на стене сообщества через vkbottle."""
    if not VK_AVAILABLE:
        raise RuntimeError("ВКонтакте не настроен")

    async def _publish():
        api = API(VK_ACCESS_TOKEN)
        try:
            params = {
                "owner_id": -VK_GROUP_ID,
                "from_group": True,
                "message": text,
            }
            if publish_date is not None:
                params["publish_date"] = publish_date
            return await api.wall.post(**params)
        finally:
            await api.http_client.close()

    return asyncio.run(_publish())


def get_post_id(response):
    post_id = getattr(response, "post_id", None)
    if post_id is None and isinstance(response, dict):
        post_id = response.get("post_id")
    return post_id


def publish_due_scheduled():
    """Публикует локально отложенные посты, у которых наступило время."""
    now = datetime.now().astimezone()
    due = []

    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
        changed = normalize_scheduled(items)
        remaining = []

        for item in items:
            status = item.get("status", "pending")
            try:
                scheduled_dt = parse_scheduled_datetime(item.get("scheduled_at", ""))
            except (TypeError, ValueError):
                remaining.append(item)
                continue

            # Старые записи были запланированы через VK — просто убираем их
            # из локального списка после наступления времени публикации.
            if status == "vk_scheduled":
                if scheduled_dt <= now:
                    changed = True
                    continue

            # Новые записи публикуем сами, когда наступает время.
            elif status == "pending" and scheduled_dt <= now:
                due.append(dict(item))
                changed = True
                continue

            remaining.append(item)

        if changed:
            save_json_list(SCHEDULED_FILE, remaining)

    for item in due:
        try:
            publish_to_vk(item["text"])
            app.logger.info("Отложенный пост %s опубликован", item["id"])
        except Exception as exc:
            app.logger.warning(
                "Не удалось опубликовать отложенный пост %s: %s",
                item["id"],
                exc,
            )
            item["status"] = "error"
            item["last_error"] = str(exc)[:300]
            item["last_attempt_at"] = now.isoformat(timespec="seconds")
            with DATA_LOCK:
                items = load_json_list(SCHEDULED_FILE)
                if not any(entry.get("id") == item["id"] for entry in items):
                    items.append(item)
                    items.sort(key=lambda entry: entry.get("scheduled_at", ""))
                    save_json_list(SCHEDULED_FILE, items)


def scheduler_loop():
    while True:
        try:
            publish_due_scheduled()
        except Exception:
            app.logger.exception("Ошибка планировщика отложенных постов")
        time.sleep(SCHEDULER_INTERVAL)


def ensure_scheduler():
    global SCHEDULER_STARTED

    with SCHEDULER_LOCK:
        if SCHEDULER_STARTED:
            return
        SCHEDULER_STARTED = True

    thread = threading.Thread(
        target=scheduler_loop,
        name="scheduled-posts",
        daemon=True,
    )
    thread.start()


@app.before_request
def start_scheduler_on_request():
    ensure_scheduler()




def trim_text(text, limit):
    text = clean_text(text)
    if len(text) <= limit:
        return text
    short = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return short + "…"


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", clean_text(text))
    return [part.strip(" •-–—") for part in parts if len(part.strip()) > 2]


def build_hashtags(title, description, mood):
    tags = []

    # Берём 1–2 ключевых слова из названия товара.
    for word in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", title or ""):
        word = word.lower()
        if word in STOP_WORDS:
            continue
        tags.append("#" + word)
        if len(tags) == 2:
            break

    tags.extend(mood["tags"])
    tags.extend(EXTRA_HASHTAGS)

    unique_tags = []
    for tag in tags:
        if tag not in unique_tags:
            unique_tags.append(tag)

    return " ".join(unique_tags[:HASHTAG_LIMIT])


def generate_with_template(title, description, price, mood_key, product_url=""):
    mood = MOODS.get(mood_key, MOODS[DEFAULT_MOOD])
    description = clean_text(description)

    headline = clean_text(title)
    if not headline:
        sentences = split_sentences(description)
        headline = sentences[0] if sentences else "Ваш новый фаворит"
    headline = trim_text(headline, TEMPLATE_TITLE_LIMIT)
    headline = headline[:1].upper() + headline[1:]

    sentences = split_sentences(description)
    lead = " ".join(sentences[:2]) if sentences else description
    lead = trim_text(lead, TEMPLATE_LEAD_LIMIT)
    if lead and lead[-1] not in ".!?…":
        lead += "."

    benefits = []
    for sentence in sentences[1:]:
        if len(benefits) >= TEMPLATE_MAX_BENEFITS:
            break
        short = trim_text(sentence, TEMPLATE_BENEFIT_LIMIT)
        if short and short not in benefits:
            benefits.append(short)

    if not benefits:
        benefits.append("Практичное решение, которое приятно использовать каждый день")

    benefits = benefits[:TEMPLATE_MAX_BENEFITS]

    benefits_text = "\n".join("• " + item for item in benefits)
    hashtags = build_hashtags(headline, description, mood)

    blocks = [
        f"{mood['emoji']} {headline}",
        f"{mood['hook']} {lead}",
        "Польза для вас:\n" + benefits_text,
    ]

    # Цена или выгода — отдельной строкой, если поле заполнено.
    if price:
        blocks.append(f"💰 Цена / выгода: {trim_text(price, TEMPLATE_BENEFIT_LIMIT)}")

    blocks.append(f"{mood['cta_emoji']} {mood['cta']}")

    # Ссылка на карточку товара добавляется, если пост собран по URL.
    if product_url:
        blocks.append(f"🔗 Подробнее: {product_url}")

    blocks.append(hashtags)
    return "\n\n".join(blocks)


def normalize_url(url):
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url


def append_product_link(post, product_url):
    """Добавляет ссылку на товар перед строкой хэштегов, если её ещё нет."""
    if not product_url or product_url in post:
        return post

    link_line = f"🔗 Подробнее: {product_url}"
    lines = post.rstrip().splitlines()

    if lines and lines[-1].lstrip().startswith("#"):
        hashtags = lines.pop()
        return "\n".join(lines).rstrip() + "\n\n" + link_line + "\n\n" + hashtags

    return post.rstrip() + "\n\n" + link_line


def fetch_product_page(url):
    url = normalize_url(url)

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Некорректный URL")

    response = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    page_title = ""
    if soup.title and soup.title.string:
        page_title = clean_text(soup.title.string)

    meta_description = ""
    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if meta is None:
        meta = soup.find("meta", attrs={"property": "og:description"})
    if meta and meta.get("content"):
        meta_description = clean_text(meta["content"])

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer"]):
        tag.decompose()

    page_text = clean_text(soup.get_text(" ", strip=True))
    combined = " ".join(part for part in [meta_description, page_text] if part)

    if len(combined) < 50:
        raise ValueError("На странице не найдено описание товара")

    return {
        "title": page_title,
        "text": combined[:8000],
        "url": url,
    }


def load_voice_settings():
    try:
        return (BASE_DIR / "voice.md").read_text(encoding="utf-8")
    except OSError:
        return "Пиши дружелюбно, понятно и без канцелярита."


def generate_with_ai(title, description, page_title, page_text, price, mood_key):
    voice = load_voice_settings()
    mood = MOODS.get(mood_key, MOODS[DEFAULT_MOOD])

    system_prompt = (
        "Ты — опытный редактор и копирайтер. Пишешь посты для товаров на русском языке.\n"
        "Соблюдай настройки стиля ниже.\n\n"
        "НАСТРОЙКИ СТИЛЯ (voice.md):\n"
        f"{voice}\n\n"
        "Структура готового поста:\n"
        "1. Заголовок с одним эмодзи.\n"
        "2. Основной текст: 2–4 коротких предложения.\n"
        "3. Блок «Польза для вас:» с 2–3 пунктами через «•».\n"
        "4. Если указана цена или выгода — отдельная строка «💰 Цена / выгода: …».\n"
        "5. Призыв к действию с одним эмодзи.\n"
        "6. 4–5 хэштегов в одну строку.\n\n"
        "Верни только готовый текст поста. Без markdown-заголовков, пояснений, "
        "кавычек и вступлений. Не выдумывай характеристики товара и не придумывай "
        "цену, если она не указана."
    )

    source_parts = []
    if title:
        source_parts.append("Название товара: " + title)
    if page_title and page_title != title:
        source_parts.append("Название со страницы: " + page_title)

    if page_text:
        source_parts.append(
            "Текст со страницы товара (основной источник, используй только факты из него):\n"
            + page_text
        )
    elif description:
        source_parts.append("Описание товара:\n" + description)

    if price:
        source_parts.append(
            "Цена или выгода (обязательно добавь в пост отдельной строкой «💰 Цена / выгода: …»): "
            + price
        )

    source_parts.append("Настроение поста: " + mood["label"])
    source_parts.append("Сформируй пост по структуре и настройкам стиля.")

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(source_parts)},
        ],
        temperature=0.8,
        max_tokens=900,
    )

    result = (response.choices[0].message.content or "").strip()
    if not result:
        raise ValueError("Пустой ответ от ИИ")
    return result


@app.route("/", methods=["GET", "POST"])
def index():
    form = {
        "mode": default_mode(),
        "url": "",
        "title": "",
        "description": "",
        "price": "",
        "mood": DEFAULT_MOOD,
    }
    result = ""
    result_mode = ""
    result_url = ""
    error = ""
    notice = ""

    if request.method == "POST":
        form = {
            "mode": request.form.get("mode", "").strip(),
            "url": request.form.get("url", "").strip(),
            "title": request.form.get("title", "").strip(),
            "description": request.form.get("description", "").strip(),
            "price": request.form.get("price", "").strip(),
            "mood": request.form.get("mood", "").strip(),
        }

        if form["mode"] not in ("ai", "template"):
            form["mode"] = default_mode()
        if form["mood"] not in MOODS:
            form["mood"] = DEFAULT_MOOD

        mode = form["mode"]

        if mode == "ai" and not AI_AVAILABLE:
            mode = "template"
            notice = "Ключ OpenAI не найден — использовали режим по шаблону."

        page_title = ""
        page_text = ""
        page_url = ""

        if mode == "ai" and form["url"]:
            try:
                page = fetch_product_page(form["url"])
                page_title = page["title"]
                page_text = page["text"]
                page_url = page["url"]
            except Exception as exc:
                app.logger.warning("Не удалось загрузить страницу товара: %s", exc)
                mode = "template"
                notice = "Страница недоступна — автоматически переключились на режим по шаблону."

        if mode == "ai":
            if not page_text and not form["description"]:
                error = "Добавьте описание товара"
            else:
                try:
                    result = generate_with_ai(
                        title=form["title"],
                        description=form["description"],
                        page_title=page_title,
                        page_text=page_text,
                        price=form["price"],
                        mood_key=form["mood"],
                    )
                    result = append_product_link(result, page_url)
                except Exception as exc:
                    app.logger.warning("Ошибка генерации через ИИ: %s", exc)
                    mode = "template"
                    notice = "ИИ не ответил — использовали режим по шаблону. Проверьте ключ и модель в .env."
                    fallback_description = form["description"] or page_text
                    if fallback_description:
                        result = generate_with_template(
                            form["title"],
                            fallback_description,
                            form["price"],
                            form["mood"],
                            product_url=page_url,
                        )
                    else:
                        error = "Добавьте описание товара"
        else:
            # В режиме по шаблону URL не используется.
            if not form["description"]:
                error = "Добавьте описание товара"
            else:
                result = generate_with_template(
                    form["title"], form["description"], form["price"], form["mood"]
                )

        form["mode"] = mode
        if result:
            result_mode = mode
            result_url = page_url

    return render_template(
        "index.html",
        form=form,
        moods=MOODS,
        ai_available=AI_AVAILABLE,
        result=result,
        result_mode=result_mode,
        result_url=result_url,
        error=error,
        notice=notice,
        favorites=get_favorites(),
        scheduled=get_scheduled(),
        vk_available=VK_AVAILABLE,
        vk_group_id=VK_GROUP_ID,
    )


def request_post_text():
    data = request.get_json(silent=True) or {}
    return str(data.get("text", "")).strip()


@app.post("/api/favorites")
def api_add_favorite():
    text = request_post_text()
    if not text:
        return jsonify(ok=False, error="Добавьте текст поста"), 400

    try:
        favorite = add_favorite(text)
    except (OSError, ValueError) as exc:
        app.logger.warning("Не удалось сохранить избранное: %s", exc)
        return jsonify(ok=False, error="Не удалось сохранить избранное"), 500

    return jsonify(ok=True, favorite=favorite, message="Пост добавлен в избранное")


@app.post("/api/favorites/<favorite_id>")
def api_update_favorite(favorite_id):
    text = request_post_text()
    if not text:
        return jsonify(ok=False, error="Добавьте текст поста"), 400

    try:
        favorite = update_favorite(favorite_id, text)
    except (OSError, ValueError) as exc:
        app.logger.warning("Не удалось обновить избранное: %s", exc)
        return jsonify(ok=False, error="Не удалось сохранить изменения"), 500

    if favorite is None:
        return jsonify(ok=False, error="Пост не найден"), 404

    return jsonify(
        ok=True,
        favorite=favorite,
        text=favorite["text"],
        message="Пост в избранном обновлён",
    )


@app.post("/api/favorites/<favorite_id>/publish")
def api_publish_favorite(favorite_id):
    text = request_post_text()
    if not VK_AVAILABLE:
        return jsonify(
            ok=False,
            error="ВКонтакте не настроен: добавьте VK_ACCESS_TOKEN и VK_GROUP_ID в .env",
        ), 400

    with DATA_LOCK:
        items = load_json_list(FAVORITES_FILE)
        favorite = next((item for item in items if item.get("id") == favorite_id), None)

    if favorite is None:
        return jsonify(ok=False, error="Пост не найден"), 404

    if text and text != favorite.get("text"):
        try:
            update_favorite(favorite_id, text)
        except (OSError, ValueError) as exc:
            app.logger.warning("Не удалось сохранить изменения избранного: %s", exc)
            return jsonify(ok=False, error="Не удалось сохранить изменения"), 500
    else:
        text = favorite.get("text", "")

    if not text:
        return jsonify(ok=False, error="Добавьте текст поста"), 400

    try:
        response = publish_to_vk(text)
        post_id = get_post_id(response)
    except Exception as exc:
        app.logger.warning("Не удалось опубликовать пост из избранного: %s", exc)
        return jsonify(
            ok=False,
            error="Не удалось опубликовать пост. Проверьте настройки ВКонтакте.",
        ), 502

    delete_favorite(favorite_id)
    return jsonify(
        ok=True,
        post_id=post_id,
        message="Пост опубликован и удалён из избранного",
    )


@app.post("/api/favorites/<favorite_id>/delete")
def api_delete_favorite(favorite_id):
    try:
        deleted = delete_favorite(favorite_id)
    except OSError as exc:
        app.logger.warning("Не удалось удалить избранное: %s", exc)
        return jsonify(ok=False, error="Не удалось удалить пост"), 500

    if not deleted:
        return jsonify(ok=False, error="Пост не найден"), 404
    return jsonify(ok=True, message="Пост удалён из избранного")


@app.post("/api/publish")
def api_publish():
    text = request_post_text()
    if not text:
        return jsonify(ok=False, error="Добавьте текст поста"), 400
    if not VK_AVAILABLE:
        return jsonify(
            ok=False,
            error="ВКонтакте не настроен: добавьте VK_ACCESS_TOKEN и VK_GROUP_ID в .env",
        ), 400

    try:
        response = publish_to_vk(text)
        post_id = get_post_id(response)
    except Exception as exc:
        app.logger.warning("Не удалось опубликовать пост во ВКонтакте: %s", exc)
        return jsonify(
            ok=False,
            error="Не удалось опубликовать пост. Проверьте VK_ACCESS_TOKEN и VK_GROUP_ID.",
        ), 502

    return jsonify(
        ok=True,
        post_id=post_id,
        message="Пост опубликован во ВКонтакте",
    )


@app.post("/api/schedule")
def api_schedule():
    text = request_post_text()
    if not text:
        return jsonify(ok=False, error="Добавьте текст поста"), 400
    if not VK_AVAILABLE:
        return jsonify(
            ok=False,
            error="ВКонтакте не настроен: добавьте VK_ACCESS_TOKEN и VK_GROUP_ID в .env",
        ), 400

    data = request.get_json(silent=True) or {}
    raw_datetime = str(data.get("scheduled_at", "")).strip()
    try:
        scheduled_dt = parse_scheduled_datetime(raw_datetime)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Укажите корректные дату и время"), 400

    now = datetime.now().astimezone()
    if scheduled_dt < now + timedelta(minutes=10):
        return jsonify(
            ok=False,
            error="Выберите время не раньше чем через 10 минут",
        ), 400

    try:
        item = add_scheduled(text, scheduled_dt)
    except OSError as exc:
        app.logger.warning("Не удалось сохранить отложенный пост: %s", exc)
        return jsonify(
            ok=False,
            error="Не удалось сохранить scheduled.json",
        ), 500

    return jsonify(
        ok=True,
        scheduled=item,
        message=f"Публикация запланирована на {item['scheduled_at_display']}",
    )


@app.get("/api/scheduled")
def api_get_scheduled():
    return jsonify(ok=True, scheduled=get_scheduled())


@app.post("/api/scheduled/<scheduled_id>")
def api_update_scheduled(scheduled_id):
    text = request_post_text()
    if not text:
        return jsonify(ok=False, error="Добавьте текст поста"), 400

    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
        item = next((entry for entry in items if entry.get("id") == scheduled_id), None)

    if item is None:
        return jsonify(ok=False, error="Отложенный пост не найден"), 404
    if item.get("status") == "vk_scheduled":
        return jsonify(
            ok=False,
            error="Этот пост уже запланирован ВКонтакте. Изменение недоступно.",
        ), 400

    try:
        updated = update_scheduled(scheduled_id, text)
    except (OSError, ValueError) as exc:
        app.logger.warning("Не удалось обновить отложенный пост: %s", exc)
        return jsonify(ok=False, error="Не удалось сохранить изменения"), 500

    if updated is None:
        return jsonify(ok=False, error="Отложенный пост не найден"), 404

    return jsonify(
        ok=True,
        scheduled=updated,
        text=updated["text"],
        message="Отложенный пост обновлён",
    )


@app.post("/api/scheduled/<scheduled_id>/publish")
def api_publish_scheduled_now(scheduled_id):
    if not VK_AVAILABLE:
        return jsonify(
            ok=False,
            error="ВКонтакте не настроен: добавьте VK_ACCESS_TOKEN и VK_GROUP_ID в .env",
        ), 400

    text = request_post_text()

    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
        item = next((entry for entry in items if entry.get("id") == scheduled_id), None)
        if item is None:
            return jsonify(ok=False, error="Отложенный пост не найден"), 404
        if item.get("status") == "vk_scheduled":
            return jsonify(
                ok=False,
                error="Этот пост уже запланирован ВКонтакте. Отмените его в управлении сообществом.",
            ), 400

        item = dict(item)
        remaining = [entry for entry in items if entry.get("id") != scheduled_id]
        save_json_list(SCHEDULED_FILE, remaining)

    final_text = text or item.get("text", "")
    if not final_text:
        return jsonify(ok=False, error="Добавьте текст поста"), 400

    try:
        response = publish_to_vk(final_text)
        post_id = get_post_id(response)
    except Exception as exc:
        app.logger.warning("Не удалось опубликовать отложенный пост сейчас: %s", exc)
        item["text"] = final_text
        item["status"] = "error"
        item["last_error"] = str(exc)[:300]
        item["last_attempt_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        with DATA_LOCK:
            items = load_json_list(SCHEDULED_FILE)
            if not any(entry.get("id") == scheduled_id for entry in items):
                items.append(item)
                items.sort(key=lambda entry: entry.get("scheduled_at", ""))
                save_json_list(SCHEDULED_FILE, items)

        return jsonify(
            ok=False,
            error="Не удалось опубликовать пост. Проверьте настройки ВКонтакте.",
        ), 502

    return jsonify(
        ok=True,
        post_id=post_id,
        message="Пост опубликован сейчас и удалён из отложенных",
    )


@app.post("/api/scheduled/<scheduled_id>/delete")
def api_delete_scheduled(scheduled_id):
    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
        item = next((entry for entry in items if entry.get("id") == scheduled_id), None)

    if item is None:
        return jsonify(ok=False, error="Отложенный пост не найден"), 404

    try:
        delete_scheduled(scheduled_id)
    except OSError as exc:
        app.logger.warning("Не удалось удалить отложенный пост: %s", exc)
        return jsonify(ok=False, error="Не удалось удалить запись"), 500

    message = "Запись удалена из отложенных"
    if item.get("status") == "vk_scheduled":
        message += ". Не забудьте отменить публикацию в сообществе ВКонтакте."

    return jsonify(ok=True, message=message)


if __name__ == "__main__":
    app.run(debug=True)
