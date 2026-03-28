const state = {
  manifest: [],
  pagesByBook: new Map(),
  currentBook: null,
  currentPage: null,
};

const bookSelect = document.getElementById("book-select");
const pageSelect = document.getElementById("page-select");
const editor = document.getElementById("editor");
const pageImage = document.getElementById("page-image");
const statusText = document.getElementById("status-text");

function setStatus(text) {
  statusText.textContent = text;
}

async function loadManifest() {
  const response = await fetch("/api/manifest");
  state.manifest = await response.json();
  const grouped = new Map();
  for (const row of state.manifest) {
    if (!grouped.has(row.book_id)) {
      grouped.set(row.book_id, []);
    }
    grouped.get(row.book_id).push(row);
  }
  for (const rows of grouped.values()) {
    rows.sort((a, b) => a.local_page - b.local_page);
  }
  state.pagesByBook = grouped;
  renderBookOptions();
}

function renderBookOptions() {
  bookSelect.innerHTML = "";
  for (const bookId of state.pagesByBook.keys()) {
    const option = document.createElement("option");
    option.value = bookId;
    option.textContent = bookId;
    bookSelect.appendChild(option);
  }
  if (!state.currentBook) {
    state.currentBook = bookSelect.value;
  }
  bookSelect.value = state.currentBook;
  renderPageOptions();
}

function renderPageOptions() {
  const pages = state.pagesByBook.get(state.currentBook) || [];
  pageSelect.innerHTML = "";
  for (const row of pages) {
    const option = document.createElement("option");
    option.value = String(row.local_page);
    option.textContent = `p.${String(row.local_page).padStart(4, "0")} | ${row.confidence}${row.review_needed ? " | review" : ""}`;
    pageSelect.appendChild(option);
  }
  if (!state.currentPage) {
    state.currentPage = pages[0]?.local_page || null;
  }
  pageSelect.value = String(state.currentPage);
  loadCurrentPage();
}

async function loadCurrentPage() {
  if (!state.currentBook || !state.currentPage) {
    return;
  }
  setStatus(`Loading ${state.currentBook} p.${state.currentPage} ...`);
  const response = await fetch(`/api/page?book_id=${encodeURIComponent(state.currentBook)}&local_page=${encodeURIComponent(state.currentPage)}`);
  const payload = await response.json();
  editor.value = payload.markdown;
  pageImage.src = `/api/image?book_id=${encodeURIComponent(state.currentBook)}&local_page=${encodeURIComponent(state.currentPage)}&t=${Date.now()}`;
  setStatus(`${payload.book_id} p.${String(payload.local_page).padStart(4, "0")} | ${payload.confidence}${payload.review_needed ? " | review" : ""}`);
}

async function saveCurrentPage() {
  if (!state.currentBook || !state.currentPage) {
    return;
  }
  setStatus(`Saving ${state.currentBook} p.${state.currentPage} ...`);
  const response = await fetch("/api/save", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      book_id: state.currentBook,
      local_page: state.currentPage,
      markdown: editor.value,
    }),
  });
  if (!response.ok) {
    setStatus("Save failed");
    return;
  }
  setStatus(`Saved ${state.currentBook} p.${String(state.currentPage).padStart(4, "0")}`);
}

function stepPage(offset) {
  const pages = state.pagesByBook.get(state.currentBook) || [];
  const index = pages.findIndex((row) => row.local_page === state.currentPage);
  if (index < 0) {
    return;
  }
  const next = pages[index + offset];
  if (!next) {
    return;
  }
  state.currentPage = next.local_page;
  pageSelect.value = String(state.currentPage);
  loadCurrentPage();
}

bookSelect.addEventListener("change", () => {
  state.currentBook = bookSelect.value;
  state.currentPage = null;
  renderPageOptions();
});

pageSelect.addEventListener("change", () => {
  state.currentPage = Number(pageSelect.value);
  loadCurrentPage();
});

document.getElementById("prev-btn").addEventListener("click", () => stepPage(-1));
document.getElementById("next-btn").addEventListener("click", () => stepPage(1));
document.getElementById("save-btn").addEventListener("click", saveCurrentPage);
document.getElementById("reload-btn").addEventListener("click", loadCurrentPage);

window.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveCurrentPage();
  }
  if (event.altKey && event.key === "ArrowLeft") {
    event.preventDefault();
    stepPage(-1);
  }
  if (event.altKey && event.key === "ArrowRight") {
    event.preventDefault();
    stepPage(1);
  }
});

loadManifest().catch((error) => {
  console.error(error);
  setStatus(`Failed to load: ${error}`);
});
