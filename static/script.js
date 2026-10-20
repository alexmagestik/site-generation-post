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

/* ── Избранное и отложенные: общие помощники ───────────────────── */

function createActionButton(label, action, className, disabled = false, title = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className || "mini-btn";
  button.dataset.itemAction = action;
  button.textContent = label;
  button.disabled = disabled;
  if (title) button.title = title;
  return button;
}

function buildStatusPill(item) {
  const pill = document.createElement("span");
  pill.className = "status-pill";

  if (item.status === "error") {
    pill.classList.add("status-pill--error");
    pill.textContent = "Ошибка";
  } else if (item.status === "vk_scheduled") {
    pill.textContent = "ВКонтакте";
  } else {
    pill.classList.add("status-pill--pending");
    pill.textContent = "Ожидает";
  }
  return pill;
}

function buildScheduledTime(item) {
  const time = document.createElement("div");
  time.className = "saved-schedule-time";
  time.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.7"/>' +
    '<path d="M12 7.5V12l3 2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>' +
    "</svg>";
  time.append(document.createTextNode(item.scheduled_at_display || ""));
  return time;
}

function buildFavoriteCard(favorite) {
  const article = document.createElement("article");
  article.className = "saved-item";
  article.dataset.itemKind = "favorite";
  article.dataset.itemId = favorite.id;

  const text = document.createElement("p");
  text.className = "saved-text";
  text.textContent = favorite.text;

  const actions = document.createElement("div");
  actions.className = "saved-actions";
  actions.append(
    createActionButton("Редактировать", "edit", "mini-btn"),
    createActionButton("Опубликовать", "publish", "mini-btn mini-btn--vk"),
    createActionButton("Удалить", "delete", "link-btn")
  );

  const footer = document.createElement("div");
  footer.className = "saved-footer";
  const date = document.createElement("span");
  date.textContent = favorite.created_at_display || "";
  footer.append(date);

  article.append(text, actions, footer);
  return article;
}

function buildScheduledCard(item) {
  const article = document.createElement("article");
  article.className = "saved-item saved-item--scheduled";
  article.dataset.itemKind = "scheduled";
  article.dataset.itemId = item.id;
  article.dataset.scheduledAt = item.scheduled_at || "";
  article.dataset.status = item.status || "pending";

  const topline = document.createElement("div");
  topline.className = "saved-topline";
  topline.append(buildScheduledTime(item), buildStatusPill(item));

  const isLegacy = item.status === "vk_scheduled";
  const disabledTitle = isLegacy ? "Пост уже запланирован ВКонтакте" : "";

  const actions = document.createElement("div");
  actions.className = "saved-actions";
  actions.append(
    createActionButton("Редактировать", "edit", "mini-btn", isLegacy, disabledTitle),
    createActionButton("Опубликовать сейчас", "publish", "mini-btn mini-btn--vk", isLegacy, disabledTitle),
    createActionButton("Удалить", "delete", "link-btn")
  );

  article.append(topline);

  if (item.status === "error") {
    const note = document.createElement("p");
    note.className = "saved-note saved-note--error";
    note.textContent = "Не удалось опубликовать. Попробуйте «Опубликовать сейчас».";
    article.append(note);
  } else if (isLegacy) {
    const note = document.createElement("p");
    note.className = "saved-note";
    note.textContent = "Пост запланирован на стороне ВКонтакте.";
    article.append(note);
  }

  const text = document.createElement("p");
  text.className = "saved-text";
  text.textContent = item.text;

  article.append(text, actions);
  return article;
}

function updateFavoritesState() {
  if (!favoritesList) return;
  const count = favoritesList.querySelectorAll('[data-item-kind="favorite"]').length;
  if (favoritesCount) favoritesCount.textContent = count;
  if (favoritesEmpty) favoritesEmpty.hidden = count > 0;
}

function updateScheduledState() {
  if (!scheduledList) return;
  const count = scheduledList.querySelectorAll('[data-item-kind="scheduled"]').length;
  if (scheduledCount) scheduledCount.textContent = count;
  if (scheduledEmpty) scheduledEmpty.hidden = count > 0;
}

function sortScheduledList() {
  if (!scheduledList) return;
  const cards = Array.from(scheduledList.querySelectorAll('[data-item-kind="scheduled"]'));
  cards.sort((a, b) =>
    (a.dataset.scheduledAt || "").localeCompare(b.dataset.scheduledAt || "")
  );
  cards.forEach((card) => scheduledList.append(card));
}

function renderScheduledList(items) {
  if (!scheduledList) return;
  scheduledList.innerHTML = "";
  items.forEach((item) => scheduledList.append(buildScheduledCard(item)));
  updateScheduledState();
}

/* ── Избранное: добавление ─────────────────────────────────────── */

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

/* ── Редактирование сохранённых постов ─────────────────────────── */

function getCardText(card) {
  const editArea = card.querySelector(".saved-edit-area");
  if (editArea) return editArea.value.trim();

  const textElement = card.querySelector(".saved-text");
  return textElement ? textElement.textContent.trim() : "";
}

function startItemEdit(card) {
  if (!card || card.dataset.editing === "true") return;

  const textElement = card.querySelector(".saved-text");
  const actions = card.querySelector(".saved-actions");
  if (!textElement || !actions) return;

  const textarea = document.createElement("textarea");
  textarea.className = "saved-edit-area";
  textarea.value = textElement.textContent;
  textElement.hidden = true;
  actions.hidden = true;

  const editActions = document.createElement("div");
  editActions.className = "saved-edit-actions";
  editActions.append(
    createActionButton("Сохранить", "save", "mini-btn mini-btn--save"),
    createActionButton("Отмена", "cancel", "mini-btn")
  );

  card.insertBefore(textarea, actions);
  card.insertBefore(editActions, actions);
  card.dataset.editing = "true";
  textarea.focus();
}

function stopItemEdit(card) {
  if (!card) return;

  const textarea = card.querySelector(".saved-edit-area");
  if (textarea) textarea.remove();

  const editActions = card.querySelector(".saved-edit-actions");
  if (editActions) editActions.remove();

  const textElement = card.querySelector(".saved-text");
  if (textElement) textElement.hidden = false;

  const actions = card.querySelector(".saved-actions");
  if (actions) actions.hidden = false;

  delete card.dataset.editing;
}

async function saveItemEdit(card) {
  const kind = card.dataset.itemKind;
  const itemId = card.dataset.itemId;
  const text = getCardText(card);

  if (!text) {
    setActionStatus("Добавьте текст поста", true);
    return;
  }

  const saveButton = card.querySelector('[data-item-action="save"]');
  if (saveButton) saveButton.disabled = true;

  const endpoint =
    kind === "favorite"
      ? "/api/favorites/" + encodeURIComponent(itemId)
      : "/api/scheduled/" + encodeURIComponent(itemId);

  try {
    const data = await postJson(endpoint, { text });
    const textElement = card.querySelector(".saved-text");
    if (textElement) textElement.textContent = data.text || text;
    stopItemEdit(card);
    setActionStatus(data.message || "Изменения сохранены");
  } catch (error) {
    if (saveButton) saveButton.disabled = false;
    setActionStatus(error.message, true);
  }
}

/* ── Публикация и удаление сохранённых постов ──────────────────── */

async function publishSavedItem(card) {
  const kind = card.dataset.itemKind;
  const itemId = card.dataset.itemId;
  const text = getCardText(card);

  if (!text) {
    setActionStatus("Добавьте текст поста", true);
    return;
  }

  const button = card.querySelector('[data-item-action="publish"]');
  if (button) button.disabled = true;

  const endpoint =
    kind === "favorite"
      ? "/api/favorites/" + encodeURIComponent(itemId) + "/publish"
      : "/api/scheduled/" + encodeURIComponent(itemId) + "/publish";

  try {
    const data = await postJson(endpoint, { text });
    card.remove();
    if (kind === "favorite") {
      updateFavoritesState();
    } else {
      updateScheduledState();
    }
    setActionStatus(data.message || "Пост опубликован");
  } catch (error) {
    if (button) button.disabled = false;
    setActionStatus(error.message, true);
  }
}

async function deleteSavedItem(card) {
  const kind = card.dataset.itemKind;
  const itemId = card.dataset.itemId;
  const button = card.querySelector('[data-item-action="delete"]');
  if (button) button.disabled = true;

  const endpoint =
    kind === "favorite"
      ? "/api/favorites/" + encodeURIComponent(itemId) + "/delete"
      : "/api/scheduled/" + encodeURIComponent(itemId) + "/delete";

  try {
    const data = await postJson(endpoint, {});
    card.remove();
    if (kind === "favorite") {
      updateFavoritesState();
    } else {
      updateScheduledState();
    }
    setActionStatus(data.message || "Удалено");
  } catch (error) {
    if (button) button.disabled = false;
    setActionStatus(error.message, true);
  }
}

function handleSavedAction(event) {
  const button = event.target.closest("[data-item-action]");
  if (!button || button.disabled) return;

  const card = button.closest("[data-item-kind]");
  if (!card) return;

  const action = button.dataset.itemAction;
  if (action === "edit") startItemEdit(card);
  if (action === "cancel") stopItemEdit(card);
  if (action === "save") saveItemEdit(card);
  if (action === "publish") publishSavedItem(card);
  if (action === "delete") deleteSavedItem(card);
}

if (favoritesList) favoritesList.addEventListener("click", handleSavedAction);
if (scheduledList) scheduledList.addEventListener("click", handleSavedAction);

/* ── Планирование публикации ───────────────────────────────────── */

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

/* ── Автообновление отложенных ─────────────────────────────────── */

async function refreshScheduled() {
  if (!scheduledList) return;
  if (scheduledList.querySelector('[data-editing="true"]')) return;

  try {
    const response = await fetch("/api/scheduled");
    if (!response.ok) return;

    const data = await response.json();
    if (!data.ok || !Array.isArray(data.scheduled)) return;

    renderScheduledList(data.scheduled);
  } catch (error) {
    // Тихо пропускаем: обновим при следующей попытке.
  }
}

syncMode();
updateCharCount();
updateFavoritesState();
updateScheduledState();
setInterval(refreshScheduled, 20000);
