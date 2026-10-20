const form = document.getElementById("postForm");
const aiRadio = document.getElementById("mode-ai");
const templateRadio = document.getElementById("mode-template");
const urlInput = document.getElementById("url");
const urlField = document.getElementById("urlField");
const urlHint = document.getElementById("urlHint");
const descriptionNote = document.getElementById("descriptionNote");
const generateBtn = document.getElementById("generateBtn");
const generateLabel = generateBtn ? generateBtn.querySelector(".btn-label") : null;
const copyBtn = document.getElementById("copyBtn");
const copyStatus = document.getElementById("copyStatus");
const postText = document.getElementById("postText");
const charCount = document.getElementById("charCount");
const favoriteBtn = document.getElementById("favoriteBtn");
const publishBtn = document.getElementById("publishBtn");
const scheduleToggleBtn = document.getElementById("scheduleToggleBtn");
const schedulePanel = document.getElementById("schedulePanel");
const scheduleAt = document.getElementById("scheduleAt");
const scheduleBtn = document.getElementById("scheduleBtn");
const scheduleCancelBtn = document.getElementById("scheduleCancelBtn");
const actionStatus = document.getElementById("actionStatus");
const favoritesList = document.getElementById("favoritesList");
const favoritesCount = document.getElementById("favoritesCount");
const favoritesEmpty = document.getElementById("favoritesEmpty");
const scheduledList = document.getElementById("scheduledList");
const scheduledCount = document.getElementById("scheduledCount");
const scheduledEmpty = document.getElementById("scheduledEmpty");

function syncMode() {
  const isTemplate = templateRadio.checked;

  urlInput.disabled = isTemplate;
  urlField.classList.toggle("is-disabled", isTemplate);

  if (isTemplate) {
    urlHint.textContent = "В режиме по шаблону URL не используется — заполните описание товара.";
    descriptionNote.textContent = "обязательно";
  } else if (urlInput.value.trim()) {
    urlHint.textContent = "Описание возьмём со страницы товара и обработаем через ИИ.";
    descriptionNote.textContent = "можно не заполнять";
  } else {
    urlHint.textContent = "В режиме ИИ описание автоматически возьмём со страницы товара.";
    descriptionNote.textContent = "обязательно, если нет URL";
  }
}

[aiRadio, templateRadio].forEach((radio) => {
  if (radio) {
    radio.addEventListener("change", syncMode);
  }
});

if (urlInput) {
  urlInput.addEventListener("input", syncMode);
  urlInput.addEventListener("paste", () => setTimeout(syncMode, 0));
}

if (form) {
  form.addEventListener("submit", () => {
    if (generateBtn) {
      generateBtn.classList.add("is-loading");
      generateBtn.disabled = true;
      if (generateLabel) {
        generateLabel.textContent = "Формируем пост…";
      }
    }
  });
}

function fallbackCopy(text) {
  const helper = document.createElement("textarea");
  helper.value = text;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.opacity = "0";
  document.body.appendChild(helper);
  helper.select();
  document.execCommand("copy");
  document.body.removeChild(helper);
}

function getCurrentText() {
  return postText ? postText.value.trim() : "";
}

function pluralizeSigns(number) {
  const mod10 = number % 10;
  const mod100 = number % 100;
  if (mod10 === 1 && mod100 !== 11) return "знак";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return "знака";
  return "знаков";
}

function updateCharCount() {
  if (!postText || !charCount) return;
  const length = postText.value.length;
  charCount.textContent = length + " " + pluralizeSigns(length);
}

function setActionStatus(message, isError = false) {
  if (!actionStatus) return;

  actionStatus.textContent = message;
  actionStatus.classList.toggle("is-error", isError);

  clearTimeout(actionStatus.dataset.timerId);
  actionStatus.dataset.timerId = setTimeout(() => {
    actionStatus.textContent = "";
    actionStatus.classList.remove("is-error");
  }, 6000);
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }

  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Не удалось выполнить действие");
  }
  return data;
}

if (copyBtn && postText) {
  copyBtn.addEventListener("click", async () => {
    const text = postText.value;

    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        fallbackCopy(text);
      }

      copyStatus.textContent = "Пост скопирован";
      copyBtn.classList.add("is-copied");

      clearTimeout(copyBtn.dataset.timerId);
      copyBtn.dataset.timerId = setTimeout(() => {
        copyStatus.textContent = "";
        copyBtn.classList.remove("is-copied");
      }, 2600);
    } catch (error) {
      copyStatus.textContent = "Не удалось скопировать";
    }
  });
}

if (postText) {
  postText.addEventListener("input", updateCharCount);
}

/* ── Избранное ─────────────────────────────────────────────────── */

function buildFavoriteCard(favorite) {
  const article = document.createElement("article");
  article.className = "saved-item";
  article.dataset.favoriteId = favorite.id;

  const text = document.createElement("p");
  text.className = "saved-text";
  text.textContent = favorite.text;

  const footer = document.createElement("div");
  footer.className = "saved-footer";

  const date = document.createElement("span");
  date.textContent = favorite.created_at_display || "";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "link-btn";
  button.dataset.deleteFavorite = favorite.id;
  button.textContent = "Удалить";

  footer.append(date, button);
  article.append(text, footer);
  return article;
}

function updateFavoritesState() {
  if (!favoritesList) return;
  const count = favoritesList.querySelectorAll("[data-favorite-id]").length;
  if (favoritesCount) favoritesCount.textContent = count;
  if (favoritesEmpty) favoritesEmpty.hidden = count > 0;
}

if (favoriteBtn) {
  favoriteBtn.addEventListener("click", async () => {
    const text = getCurrentText();
    if (!text) {
      setActionStatus("Добавьте текст поста", true);
      return;
    }

    favoriteBtn.disabled = true;
    try {
      const data = await postJson("/api/favorites", { text });
      if (favoritesList && data.favorite) {
        favoritesList.prepend(buildFavoriteCard(data.favorite));
      }
      updateFavoritesState();
      setActionStatus(data.message || "Пост добавлен в избранное");
    } catch (error) {
      setActionStatus(error.message, true);
    } finally {
      favoriteBtn.disabled = false;
    }
  });
}

if (favoritesList) {
  favoritesList.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-delete-favorite]");
    if (!button) return;

    const favoriteId = button.dataset.deleteFavorite;
    const card = button.closest(".saved-item");
    button.disabled = true;

    try {
      await postJson(
        "/api/favorites/" + encodeURIComponent(favoriteId) + "/delete",
        {}
      );
      if (card) card.remove();
      updateFavoritesState();
      setActionStatus("Пост удалён из избранного");
    } catch (error) {
      button.disabled = false;
      setActionStatus(error.message, true);
    }
  });
}

/* ── Публикация и отложенные посты ─────────────────────────────── */

if (publishBtn) {
  publishBtn.addEventListener("click", async () => {
    const text = getCurrentText();
    if (!text) {
      setActionStatus("Добавьте текст поста", true);
      return;
    }

    publishBtn.disabled = true;
    try {
      const data = await postJson("/api/publish", { text });
      setActionStatus(data.message || "Пост опубликован во ВКонтакте");
    } catch (error) {
      setActionStatus(error.message, true);
    } finally {
      publishBtn.disabled = false;
    }
  });
}

function toLocalInputValue(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return (
    date.getFullYear() +
    "-" +
    pad(date.getMonth() + 1) +
    "-" +
    pad(date.getDate()) +
    "T" +
    pad(date.getHours()) +
    ":" +
    pad(date.getMinutes())
  );
}

function setDefaultScheduleTime() {
  if (!scheduleAt) return;

  const now = new Date();
  const minimum = new Date(now.getTime() + 10 * 60 * 1000);
  const defaultTime = new Date(now.getTime() + 60 * 60 * 1000);

  scheduleAt.min = toLocalInputValue(minimum);
  if (!scheduleAt.value) {
    scheduleAt.value = toLocalInputValue(defaultTime);
  }
}

if (scheduleToggleBtn && schedulePanel) {
  scheduleToggleBtn.addEventListener("click", () => {
    const willOpen = schedulePanel.hidden;
    schedulePanel.hidden = !willOpen;

    if (willOpen) {
      setDefaultScheduleTime();
      if (scheduleAt) {
        scheduleAt.focus();
      }
    }
  });
}

if (scheduleCancelBtn && schedulePanel) {
  scheduleCancelBtn.addEventListener("click", () => {
    schedulePanel.hidden = true;
  });
}

function buildScheduledCard(item) {
  const article = document.createElement("article");
  article.className = "saved-item saved-item--scheduled";
  article.dataset.scheduledId = item.id;
  article.dataset.scheduledAt = item.scheduled_at || "";

  const time = document.createElement("div");
  time.className = "saved-schedule-time";
  time.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.7"/>' +
    '<path d="M12 7.5V12l3 2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>' +
    "</svg>";
  time.append(document.createTextNode(item.scheduled_at_display || ""));

  const text = document.createElement("p");
  text.className = "saved-text";
  text.textContent = item.text;

  article.append(time, text);
  return article;
}

function sortScheduledList() {
  if (!scheduledList) return;
  const cards = Array.from(scheduledList.querySelectorAll("[data-scheduled-id]"));
  cards.sort((a, b) =>
    (a.dataset.scheduledAt || "").localeCompare(b.dataset.scheduledAt || "")
  );
  cards.forEach((card) => scheduledList.append(card));
}

function updateScheduledState() {
  if (!scheduledList) return;
  const count = scheduledList.querySelectorAll("[data-scheduled-id]").length;
  if (scheduledCount) scheduledCount.textContent = count;
  if (scheduledEmpty) scheduledEmpty.hidden = count > 0;
}

if (scheduleBtn) {
  scheduleBtn.addEventListener("click", async () => {
    const text = getCurrentText();
    if (!text) {
      setActionStatus("Добавьте текст поста", true);
      return;
    }
    if (!scheduleAt || !scheduleAt.value) {
      setActionStatus("Выберите дату и время публикации", true);
      return;
    }

    scheduleBtn.disabled = true;
    try {
      const data = await postJson("/api/schedule", {
        text: text,
        scheduled_at: scheduleAt.value,
      });

      if (scheduledList && data.scheduled) {
        scheduledList.append(buildScheduledCard(data.scheduled));
        sortScheduledList();
      }
      updateScheduledState();
      if (schedulePanel) schedulePanel.hidden = true;
      setActionStatus(data.message || "Публикация запланирована");
    } catch (error) {
      setActionStatus(error.message, true);
    } finally {
      scheduleBtn.disabled = false;
    }
  });
}

syncMode();
updateCharCount();
updateFavoritesState();
updateScheduledState();
