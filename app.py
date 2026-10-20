import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, render_template, request
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
AI_AVAILABLE = bool(OPENAI_API_KEY)

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
    )


if __name__ == "__main__":
    app.run(debug=True)
