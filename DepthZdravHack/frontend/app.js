const REGION_LABELS = {
  spine: "позвоночник",
  hip_left: "левое бедро",
  hip_right: "правое бедро",
  "": "не определена",
};

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const browseBtn = document.getElementById("browse-btn");
const processBtn = document.getElementById("process-btn");
const selectedInfo = document.getElementById("selected-info");
const summary = document.getElementById("summary");
const resultsEl = document.getElementById("results");
const downloadBtn = document.getElementById("download-btn");

let selectedFiles = [];
let currentJobId = null;

browseBtn.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
  setSelectedFiles(Array.from(fileInput.files));
});

["dragenter", "dragover"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("is-dragover");
  })
);

["dragleave", "drop"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("is-dragover");
  })
);

dropzone.addEventListener("drop", (e) => {
  const files = Array.from(e.dataTransfer.files).filter((f) =>
    f.name.toLowerCase().endsWith(".dcm")
  );
  setSelectedFiles(files);
});

function setSelectedFiles(files) {
  selectedFiles = files;
  if (files.length === 0) {
    selectedInfo.hidden = true;
    processBtn.disabled = true;
    return;
  }
  selectedInfo.hidden = false;
  selectedInfo.textContent =
    files.length === 1 ? `Выбран файл: ${files[0].name}` : `Выбрано файлов: ${files.length}`;
  processBtn.disabled = false;
}

processBtn.addEventListener("click", async () => {
  if (selectedFiles.length === 0) return;

  processBtn.disabled = true;
  processBtn.textContent = "Обрабатываю...";
  resultsEl.innerHTML = "";
  summary.hidden = true;

  const formData = new FormData();
  selectedFiles.forEach((f) => formData.append("files", f));

  try {
    const resp = await fetch("/api/process", { method: "POST", body: formData });
    if (!resp.ok) {
      throw new Error(`Сервер вернул ошибку ${resp.status}`);
    }
    const data = await resp.json();
    currentJobId = data.job_id;
    renderResults(data.results);
  } catch (err) {
    resultsEl.innerHTML = `<div class="result-row"><div class="result-row__main">Не удалось обработать файлы: ${escapeHtml(
      String(err)
    )}</div></div>`;
  } finally {
    processBtn.disabled = false;
    processBtn.textContent = "Обработать";
  }
});

downloadBtn.addEventListener("click", () => {
  if (!currentJobId) return;
  window.location = `/api/download/${currentJobId}`;
});

function renderResults(results) {
  const total = results.length;
  const violations = results.filter((r) => r.quality_class === 1).length;
  const failures = results.filter((r) => r.processing_status === "Failure").length;
  const successTimes = results
    .filter((r) => r.processing_status === "Success")
    .map((r) => r.time_of_processing);
  const avgTime = successTimes.length
    ? successTimes.reduce((a, b) => a + b, 0) / successTimes.length
    : 0;

  document.getElementById("stat-total").textContent = total;
  document.getElementById("stat-violations").textContent = violations;
  document.getElementById("stat-failures").textContent = failures;
  document.getElementById("stat-avgtime").textContent = `${avgTime.toFixed(2)}с`;
  summary.hidden = false;

  resultsEl.innerHTML = results.map(renderRow).join("");
}

function renderRow(r) {
  const thumb = r.thumbnail_png_b64
    ? `<img class="result-row__thumb" src="data:image/png;base64,${r.thumbnail_png_b64}" alt="" />`
    : `<div class="result-row__thumb result-row__thumb--empty">нет превью</div>`;

  let badge;
  let comment;
  if (r.processing_status === "Failure") {
    badge = `<span class="badge badge--fail">ошибка обработки</span>`;
    comment = escapeHtml(r.error_message || "");
  } else if (r.quality_class === 1) {
    badge = `<span class="badge badge--bad">нарушение</span>`;
    comment = escapeHtml(r.comment || "");
  } else {
    badge = `<span class="badge badge--ok">норма</span>`;
    comment = escapeHtml(r.comment || "");
  }

  const regionLabel = REGION_LABELS[r.anatomical_region] ?? r.anatomical_region;

  return `
    <div class="result-row">
      ${thumb}
      <div class="result-row__main">
        <div class="result-row__filename">${escapeHtml(r.filename)}</div>
        <div class="result-row__meta">
          <span class="result-row__region">${escapeHtml(regionLabel)}</span>
          &middot; ${r.time_of_processing.toFixed(2)}с
        </div>
        <div class="result-row__comment">${comment}</div>
      </div>
      ${badge}
    </div>
  `;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
