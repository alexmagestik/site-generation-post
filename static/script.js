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

if (copyBtn && postText) {
  copyBtn.addEventListener("click", async () => {
    const text = postText.textContent;

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

syncMode();
