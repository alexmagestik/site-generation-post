import asyncio
import json
import os
import re
import threading
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


def delete_favorite(favorite_id):
    with DATA_LOCK:
        items = load_json_list(FAVORITES_FILE)
        remaining = [item for item in items if item.get("id") != favorite_id]
        if len(remaining) == len(items):
            return False
        save_json_list(FAVORITES_FILE, remaining)
    return True


def get_scheduled():
    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
    items.sort(key=lambda item: item.get("scheduled_at", ""))
    for item in items:
        item["scheduled_at_display"] = format_datetime(item.get("scheduled_at"))
    return items


def add_scheduled(text, scheduled_dt, post_id=None):
    item = {
        "id": uuid.uuid4().hex,
        "text": text,
        "scheduled_at": scheduled_dt.isoformat(timespec="seconds"),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "post_id": post_id,
    }

    with DATA_LOCK:
        items = load_json_list(SCHEDULED_FILE)
        items.append(item)
        items.sort(key=lambda entry: entry.get("scheduled_at", ""))
        save_json_list(SCHEDULED_FILE, items)

    item["scheduled_at_display"] = format_datetime(item["scheduled_at"])
    return item


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


def generate_with_template(title, description, price, mood_key):
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

    blocks.extend([
        f"{mood['cta_emoji']} {mood['cta']}",
        hashtags,
    ])
    return "\n\n".join(blocks)


def fetch_product_page(url):
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url

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

        if mode == "ai" and form["url"]:
            try:
                page = fetch_product_page(form["url"])
                page_title = page["title"]
                page_text = page["text"]
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
                except Exception as exc:
                    app.logger.warning("Ошибка генерации через ИИ: %s", exc)
                    mode = "template"
                    notice = "ИИ не ответил — использовали режим по шаблону. Проверьте ключ и модель в .env."
                    fallback_description = form["description"] or page_text
                    if fallback_description:
                        result = generate_with_template(
                            form["title"], fallback_description, form["price"], form["mood"]
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

    return render_template(
        "index.html",
        form=form,
        moods=MOODS,
        ai_available=AI_AVAILABLE,
        result=result,
        result_mode=result_mode,
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
        scheduled_dt = datetime.fromisoformat(raw_datetime).astimezone()
    except ValueError:
        return jsonify(ok=False, error="Укажите корректные дату и время"), 400

    now = datetime.now().astimezone()
    if scheduled_dt < now + timedelta(minutes=10):
        return jsonify(
            ok=False,
            error="Выберите время не раньше чем через 10 минут",
        ), 400

    timestamp = int(scheduled_dt.timestamp())
    try:
        response = publish_to_vk(text, publish_date=timestamp)
        post_id = get_post_id(response)
    except Exception as exc:
        app.logger.warning("Не удалось запланировать пост во ВКонтакте: %s", exc)
        return jsonify(
            ok=False,
            error="Не удалось запланировать пост. Проверьте настройки ВКонтакте.",
        ), 502

    try:
        item = add_scheduled(text, scheduled_dt, post_id)
    except OSError as exc:
        app.logger.warning("Не удалось сохранить отложенный пост: %s", exc)
        return jsonify(
            ok=False,
            error="Пост запланирован во ВКонтакте, но не удалось сохранить scheduled.json",
        ), 500

    return jsonify(
        ok=True,
        scheduled=item,
        message=f"Публикация запланирована на {item['scheduled_at_display']}",
    )



if __name__ == "__main__":
    app.run(debug=True)
