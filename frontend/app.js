"use strict";

/* UniView AI — vanilla JS frontend. Talks only to our own FastAPI backend;
   no secret keys ever live here. */

const API_BASE = "/api";

const views = {
  home: document.getElementById("view-home"),
  disambiguation: document.getElementById("view-disambiguation"),
  progress: document.getElementById("view-progress"),
  message: document.getElementById("view-message"),
  profile: document.getElementById("view-profile"),
  compare: document.getElementById("view-compare"),
};

const state = {
  lastQuery: "",
  researchId: null,
  universityId: null,
  currentFilterCategory: "all",
  officialOnly: false,
  images: [],
  researchedUniversities: JSON.parse(localStorage.getItem("uv_researched") || "[]"),
};

function showView(name) {
  Object.values(views).forEach((v) => (v.hidden = true));
  views[name].hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function api(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`Request failed (${resp.status}): ${text}`);
  }
  return resp.json();
}

/* ---------------- Home / search ---------------- */

const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const homeError = document.getElementById("home-error");

searchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return;
  homeError.hidden = true;
  await startSearch(query);
});

document.querySelectorAll("[data-example]").forEach((btn) => {
  btn.addEventListener("click", () => {
    searchInput.value = btn.dataset.example;
    startSearch(btn.dataset.example);
  });
});

document.querySelectorAll('[data-action="back-home"]').forEach((btn) => {
  btn.addEventListener("click", () => {
    searchInput.value = "";
    showView("home");
  });
});

async function startSearch(query) {
  state.lastQuery = query;
  try {
    const data = await api("/research", {
      method: "POST",
      body: JSON.stringify({ query, force_refresh: false }),
    });
    await handleResearchStart(data, query);
  } catch (err) {
    showMessage("Something went wrong", "We couldn't reach the research service. Please try again in a moment.");
  }
}

async function handleResearchStart(data, originalQuery) {
  if (data.status === "not_found") {
    showMessage("University not found", data.message || "Try checking the spelling or entering the official university name.");
    return;
  }
  if (data.status === "ambiguous") {
    renderDisambiguation(data.candidates, originalQuery);
    return;
  }
  if (data.status === "cached") {
    rememberUniversity(data.university_id);
    await pollUntilDone(data.research_id, data.university_id, true);
    return;
  }
  if (data.status === "started") {
    rememberUniversity(data.university_id);
    showView("progress");
    await pollUntilDone(data.research_id, data.university_id, false);
  }
}

/* ---------------- Disambiguation ---------------- */

function renderDisambiguation(candidates, originalQuery) {
  const list = document.getElementById("disambig-list");
  list.innerHTML = "";
  candidates.forEach((c) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.innerHTML = `<span class="disambig-title-text">${escapeHtml(c.title)}</span>
      ${c.snippet ? `<span class="disambig-snippet">${stripTags(c.snippet)}</span>` : ""}`;
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/research", {
          method: "POST",
          body: JSON.stringify({ query: originalQuery, resolved_title: c.title }),
        });
        await handleResearchStart(data, originalQuery);
      } catch {
        showMessage("Something went wrong", "Please try again.");
      }
    });
    li.appendChild(btn);
    list.appendChild(li);
  });
  showView("disambiguation");
}

/* ---------------- Progress polling ---------------- */

async function pollUntilDone(researchId, universityId, wasCached) {
  state.researchId = researchId;
  state.universityId = universityId;

  if (!wasCached) showView("progress");

  const stageOrder = ["identification", "sources", "images", "dedup", "verify", "categorize", "profile"];

  while (true) {
    let data;
    try {
      data = await api(`/research/${researchId}`);
    } catch {
      showMessage("Something went wrong", "Lost connection to the research service. Please try again.");
      return;
    }

    if (!wasCached) {
      updateProgressUI(data, stageOrder);
    }

    if (data.status === "done") {
      await loadProfile(universityId, data);
      if (!wasCached) {
        document.getElementById("profile-cache-note").hidden = true;
      } else {
        const note = document.getElementById("profile-cache-note");
        note.textContent = "Updated recently — showing cached results.";
        note.hidden = false;
      }
      return;
    }
    if (data.status === "failed") {
      showMessage("Research failed", data.error_message || "The research pipeline hit an error. Please try again.");
      return;
    }
    await sleep(1200);
  }
}

function updateProgressUI(data, stageOrder) {
  const bar = document.getElementById("progress-bar");
  const percentLabel = document.getElementById("progress-percent");
  const stageLabel = document.getElementById("progress-stage");
  const wrap = document.getElementById("progress-bar-wrap");

  const percent = data.progress_percent || 0;
  bar.style.width = `${percent}%`;
  wrap.setAttribute("aria-valuenow", String(percent));
  percentLabel.textContent = `${percent}%`;

  const stageNames = {
    identification: "University identification",
    sources: "Source discovery",
    images: "Image collection",
    dedup: "Duplicate detection",
    verify: "AI verification",
    categorize: "Categorization",
    profile: "Profile generation",
  };
  stageLabel.textContent = `Current stage: ${stageNames[data.stage] || "Processing"}`;

  const currentIdx = stageOrder.indexOf(data.stage);
  document.querySelectorAll("#progress-steps li").forEach((li) => {
    const idx = stageOrder.indexOf(li.dataset.stage);
    li.classList.remove("done", "active");
    if (idx < currentIdx) li.classList.add("done");
    else if (idx === currentIdx) li.classList.add("active");
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/* ---------------- Profile view ---------------- */

async function loadProfile(universityId, researchData) {
  const uni = await api(`/universities/${universityId}`);
  renderProfileHeader(uni, researchData);
  renderStats(researchData);
  renderFacts(uni.facts);
  await loadSources(universityId);
  state.currentFilterCategory = "all";
  state.officialOnly = false;
  document.querySelectorAll(".filter-chip").forEach((c) => c.classList.remove("active"));
  document.querySelector('[data-filter-category="all"]').classList.add("active");
  document.getElementById("filter-official-only").checked = false;
  await loadImages(universityId);
  showView("profile");
}

function renderProfileHeader(uni, researchData) {
  state.currentUniversityName = uni.canonical_name;
  document.getElementById("profile-name").textContent = uni.canonical_name;
  document.getElementById("profile-location").textContent = [uni.city, uni.country].filter(Boolean).join(", ") || "Location unavailable";

  const officialLink = document.getElementById("profile-official-link");
  if (uni.official_website) {
    officialLink.href = uni.official_website;
    officialLink.hidden = false;
  } else {
    officialLink.hidden = true;
  }

  const confidence = researchData.confidence ?? 0;
  document.getElementById("profile-confidence-value").textContent = `${confidence}%`;
  document.getElementById("profile-confidence-label").textContent = confidenceLabel(confidence);
  document.getElementById("profile-confidence-badge").style.borderColor = confidenceColor(confidence);
  document.getElementById("profile-confidence-value").style.color = confidenceColor(confidence);

  document.getElementById("profile-description").textContent =
    uni.description || "Not enough verified information was found to generate a description.";

  document.getElementById("refresh-research-btn").onclick = () => refreshResearch(uni.id);
  document.getElementById("add-to-compare-btn").onclick = () => {
    rememberUniversity(uni.id, uni.canonical_name);
    alert(`${uni.canonical_name} added to comparison list. Open "Compare universities" to use it.`);
  };
}

function renderStats(data) {
  const row = document.getElementById("profile-stats");
  const stats = [
    ["Sources used", data.sources_count],
    ["Images analyzed", data.images_analyzed],
    ["Images removed as duplicates", data.duplicate_images],
    ["Images rejected", data.rejected_images],
    ["Verified images", data.verified_images],
  ];
  row.innerHTML = stats
    .map(([label, value]) => `<div class="stat-chip"><strong>${value ?? 0}</strong>${label}</div>`)
    .join("");
}

function renderFacts(facts) {
  const grid = document.getElementById("profile-facts");
  grid.innerHTML = facts
    .map((f) => {
      const isAvailable = f.value && f.value !== "Not available from verified sources.";
      return `<div class="fact-card">
        <div class="fact-label">${escapeHtml(f.label)}</div>
        <div class="fact-value ${isAvailable ? "" : "unavailable"}">${escapeHtml(f.value)}</div>
        ${isAvailable && f.source_url ? `<a class="fact-source" href="${escapeAttr(f.source_url)}" target="_blank" rel="noopener">Source ↗</a>` : ""}
      </div>`;
    })
    .join("");
}

async function loadSources(universityId) {
  const data = await api(`/universities/${universityId}/sources`);
  const list = document.getElementById("sources-list");
  if (!data.sources.length) {
    list.innerHTML = `<li class="muted">No sources recorded.</li>`;
    return;
  }
  list.innerHTML = data.sources
    .map(
      (s) => `<li>
        <span class="source-badge">${escapeHtml(s.source_type)}</span>
        ${s.url ? `<a href="${escapeAttr(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.title || s.domain)}</a>` : escapeHtml(s.title || s.domain)}
      </li>`
    )
    .join("");
}

/* ---------------- Images / filters ---------------- */

document.querySelectorAll("#category-filters .filter-chip").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-chip").forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    state.currentFilterCategory = btn.dataset.filterCategory;
    loadImages(state.universityId);
  });
});

document.getElementById("filter-official-only").addEventListener("change", (e) => {
  state.officialOnly = e.target.checked;
  loadImages(state.universityId);
});

document.getElementById("show-uncertain-btn").addEventListener("click", () => {
  loadImages(state.universityId, true);
});

async function loadImages(universityId, includeUncertain = false) {
  const params = new URLSearchParams({
    category: state.currentFilterCategory,
    verified_only: "true",
    include_uncertain: includeUncertain ? "true" : "false",
  });
  const data = await api(`/universities/${universityId}/images?${params.toString()}`);
  let images = data.images;
  if (state.officialOnly) images = images.filter((i) => i.is_official_source);
  state.images = images;
  renderImageGrid(images);

  const note = document.getElementById("uncertain-note");
  const text = document.getElementById("uncertain-text");
  if (!includeUncertain && data.uncertain_count > 0) {
    text.textContent = `${data.uncertain_count} additional image${data.uncertain_count === 1 ? "" : "s"} could not be reliably verified.`;
    note.hidden = false;
  } else {
    note.hidden = true;
  }
}

function renderImageGrid(images) {
  const grid = document.getElementById("image-grid");
  if (!images.length) {
    grid.innerHTML = `<p class="empty-grid-note">No verified images in this category yet.</p>`;
    return;
  }
  grid.innerHTML = "";
  images.forEach((img) => {
    const card = document.createElement("button");
    card.className = "image-card";
    card.innerHTML = `
      <img src="${escapeAttr(img.image_url)}" alt="${escapeAttr(img.category)} photo of ${escapeAttr(state.currentUniversityName || "")}" loading="lazy" />
      <div class="image-card-body">
        <div class="image-card-category">${escapeHtml(formatCategory(img.category))}</div>
        <div class="image-card-meta">
          <span class="image-card-confidence ${confClass(img.confidence_score)}">${img.confidence_score}% ${escapeHtml(img.confidence_label)}</span>
        </div>
        <div class="image-card-source">${escapeHtml(img.source_domain || "")}${img.publication_date && img.publication_date !== "Information unavailable" ? " • " + escapeHtml(img.publication_date) : ""}</div>
      </div>`;
    card.addEventListener("click", () => openImageModal(img.id));
    grid.appendChild(card);
  });
}

function formatCategory(cat) {
  return (cat || "unknown").replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function confClass(score) {
  if (score >= 90) return "conf-high";
  if (score >= 75) return "conf-mid";
  return "conf-low";
}
function confidenceLabel(score) {
  if (score >= 90) return "Highly verified";
  if (score >= 75) return "Verified";
  if (score >= 60) return "Limited evidence";
  return "Unverified";
}
function confidenceColor(score) {
  if (score >= 90) return "#1c8a4c";
  if (score >= 75) return "#2b5cff";
  if (score >= 60) return "#b06a00";
  return "#c23b3b";
}

/* ---------------- Image detail modal ---------------- */

const modal = document.getElementById("image-modal");
document.querySelectorAll('[data-action="close-modal"]').forEach((el) =>
  el.addEventListener("click", () => (modal.hidden = true))
);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !modal.hidden) modal.hidden = true;
});

async function openImageModal(imageId) {
  const img = await api(`/images/${imageId}`);
  document.getElementById("modal-image").src = img.image_url;
  document.getElementById("modal-image").alt = `${formatCategory(img.category)} photo`;
  document.getElementById("modal-title").textContent = img.source_title || formatCategory(img.category);
  document.getElementById("modal-category").textContent = formatCategory(img.category);
  document.getElementById("modal-confidence").textContent = `${img.confidence_score}% ${img.confidence_label}`;
  document.getElementById("modal-confidence").style.color = confidenceColor(img.confidence_score);
  document.getElementById("modal-source").textContent = img.source_title || img.source_domain;
  document.getElementById("modal-domain").textContent = img.source_domain;
  document.getElementById("modal-published").textContent = img.publication_date;
  document.getElementById("modal-retrieved").textContent = img.retrieved_at ? new Date(img.retrieved_at).toLocaleDateString() : "—";
  document.getElementById("modal-license").textContent = img.license;

  const link = document.getElementById("modal-source-link");
  link.href = img.source_url;

  document.getElementById("modal-explanation").innerHTML = img.explanation.map((e) => `<li>${escapeHtml(e)}</li>`).join("");
  document.getElementById("modal-signals").innerHTML = img.signals
    .map((s) => `<li><span>${escapeHtml(s.signal)}</span><span>${s.score}%</span></li>`)
    .join("");

  modal.hidden = false;
}

/* ---------------- Refresh ---------------- */

async function refreshResearch(universityId) {
  const uni = await api(`/universities/${universityId}`);
  try {
    const data = await api("/research", {
      method: "POST",
      body: JSON.stringify({ resolved_title: uni.canonical_name, query: uni.canonical_name, force_refresh: true }),
    });
    await handleResearchStart(data, uni.canonical_name);
  } catch {
    showMessage("Something went wrong", "Couldn't refresh this university right now.");
  }
}

/* ---------------- Compare ---------------- */

document.getElementById("nav-compare").addEventListener("click", () => {
  populateCompareSelects();
  showView("compare");
});

function rememberUniversity(id, name) {
  if (!id) return;
  const existingIdx = state.researchedUniversities.findIndex((u) => u.id === id);
  const entry = { id, name: name || (existingIdx >= 0 ? state.researchedUniversities[existingIdx].name : id) };
  if (existingIdx >= 0) state.researchedUniversities[existingIdx] = entry;
  else state.researchedUniversities.push(entry);
  localStorage.setItem("uv_researched", JSON.stringify(state.researchedUniversities));
}

function populateCompareSelects() {
  const a = document.getElementById("compare-select-a");
  const b = document.getElementById("compare-select-b");
  const empty = document.getElementById("compare-empty");
  const table = document.getElementById("compare-table");

  if (state.researchedUniversities.length < 2) {
    empty.hidden = false;
    table.hidden = true;
    a.innerHTML = "";
    b.innerHTML = "";
    return;
  }
  empty.hidden = true;
  const options = state.researchedUniversities.map((u) => `<option value="${escapeAttr(u.id)}">${escapeHtml(u.name)}</option>`).join("");
  a.innerHTML = options;
  b.innerHTML = options;
  b.selectedIndex = Math.min(1, state.researchedUniversities.length - 1);
}

document.getElementById("run-compare-btn").addEventListener("click", async () => {
  const idA = document.getElementById("compare-select-a").value;
  const idB = document.getElementById("compare-select-b").value;
  if (!idA || !idB || idA === idB) {
    alert("Choose two different universities to compare.");
    return;
  }
  try {
    const data = await api("/compare", {
      method: "POST",
      body: JSON.stringify({ university_id_a: idA, university_id_b: idB }),
    });
    renderCompareTable(data);
  } catch {
    alert("Couldn't run the comparison. Please try again.");
  }
});

function renderCompareTable(data) {
  document.getElementById("compare-col-a").textContent = data.university_a.name;
  document.getElementById("compare-col-b").textContent = data.university_b.name;
  document.getElementById("compare-tbody").innerHTML = data.rows
    .map(
      (r) => `<tr>
        <td>${escapeHtml(r.dimension)}</td>
        <td>${escapeHtml(r.a)}${r.a_source ? ` <a href="${escapeAttr(r.a_source)}" target="_blank" rel="noopener">↗</a>` : ""}</td>
        <td>${escapeHtml(r.b)}${r.b_source ? ` <a href="${escapeAttr(r.b_source)}" target="_blank" rel="noopener">↗</a>` : ""}</td>
      </tr>`
    )
    .join("");
  document.getElementById("compare-table").hidden = false;
}

/* ---------------- Message / error view ---------------- */

function showMessage(title, body) {
  document.getElementById("message-title").textContent = title;
  document.getElementById("message-body").textContent = body;
  showView("message");
}

/* ---------------- Utilities ---------------- */

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function escapeAttr(str) {
  return escapeHtml(str);
}
function stripTags(str) {
  return String(str).replace(/<[^>]+>/g, "");
}
