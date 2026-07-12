/* New-Grad Job Monitor dashboard. Plain JS, no dependencies, no server needed
   beyond static hosting (GitHub Pages serves docs/). */
"use strict";

const state = { jobs: [], newIds: new Set(), health: [] };

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const FAMILY_RULES = [
  ["mlai", /machine learning|\bml\b|\bai\b|applied scientist|artificial intelligence|deep learning|llm/i],
  ["data", /data engineer|data scientist|analytics engineer|data platform/i],
  ["infra", /infrastructure|platform|devops|site reliability|\bsre\b|cloud engineer|systems engineer/i],
  ["research", /research/i],
  ["swe", /software|backend|back-end|full[ -]?stack|fullstack|developer|\bswe\b|\bsde\b|engineer/i],
];
function family(title) {
  for (const [fam, re] of FAMILY_RULES) if (re.test(title)) return fam;
  return "other";
}

function band(score) {
  if (score >= 80) return "excellent";
  if (score >= 65) return "strong";
  if (score >= 50) return "possible";
  return "low";
}

const SP_LABEL = {
  likely_supported: "sponsorship likely supported",
  possibly_supported: "sponsorship possibly supported",
  unclear: "sponsorship unclear",
  likely_not_supported: "sponsorship likely NOT supported",
  ineligible: "ineligible (restriction found)",
};

async function loadJSON(path) {
  const resp = await fetch(path, { cache: "no-store" });
  if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`);
  return resp.json();
}

async function init() {
  try {
    const [active, fresh, health] = await Promise.all([
      loadJSON("data/active_jobs.json"),
      loadJSON("data/new_jobs.json").catch(() => ({ jobs: [] })),
      loadJSON("data/source_health.json").catch(() => ({ sources: [] })),
    ]);
    state.jobs = active.jobs || [];
    state.newIds = new Set((fresh.jobs || []).map((j) => j.job_id));
    state.health = health.sources || [];
    $("meta").textContent =
      `Last update: ${active.generated_at || "?"} (UTC) · ${state.jobs.length} active jobs tracked`;
    fillCompanies();
    renderHealth();
    render();
  } catch (err) {
    $("meta").textContent = "Could not load data: " + err.message;
  }
}

function fillCompanies() {
  const companies = [...new Set(state.jobs.map((j) => j.company))].sort();
  for (const name of companies) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    $("company").appendChild(opt);
  }
}

function filtered() {
  const q = $("q").value.trim().toLowerCase();
  const company = $("company").value;
  const minScore = Number($("score").value);
  const sponsorship = $("sponsorship").value;
  const loc = $("location").value.trim().toLowerCase();
  const fam = $("family").value;
  const newOnly = $("newOnly").checked;
  const showDQ = $("showDisqualified").checked;

  let jobs = state.jobs.filter((j) => {
    if (!showDQ && j.disqualified) return false;
    if (q && !(j.title.toLowerCase().includes(q) || j.company.toLowerCase().includes(q))) return false;
    if (company && j.company !== company) return false;
    if (j.overall_score < minScore) return false;
    if (sponsorship && j.sponsorship_classification !== sponsorship) return false;
    if (loc && !(j.location || "").toLowerCase().includes(loc)) return false;
    if (fam && family(j.title) !== fam) return false;
    if (newOnly && !state.newIds.has(j.job_id)) return false;
    return true;
  });

  const sort = $("sort").value;
  jobs.sort((a, b) => {
    if (sort === "company") return a.company.localeCompare(b.company) || b.overall_score - a.overall_score;
    if (sort === "date") return (b.date_posted || "").localeCompare(a.date_posted || "") || b.overall_score - a.overall_score;
    return b.overall_score - a.overall_score || (b.date_posted || "").localeCompare(a.date_posted || "");
  });
  return jobs;
}

function render() {
  const jobs = filtered();
  $("count").textContent = `${jobs.length} job(s) shown`;
  const html = jobs.slice(0, 400).map(renderJob).join("");
  $("list").innerHTML = html || "<p>No jobs match the current filters.</p>";
}

function renderJob(j) {
  const isNew = state.newIds.has(j.job_id);
  const evidence = j.sponsorship_evidence
    ? `<div class="evidence"><span class="label">Confirmed posting text (evidence)</span>“${esc(j.sponsorship_evidence)}”</div>`
    : `<div class="evidence"><span class="label">Automated inference</span>No explicit sponsorship language found in the posting text.</div>`;
  const risks = (j.international_student_risk_flags || []).length
    ? `<div class="risk">Risk flags: ${esc(j.international_student_risk_flags.join(", "))}</div>`
    : "";
  const dq = j.disqualified
    ? `<div class="risk">Disqualified from recommendations: ${esc(j.disqualify_reason)}</div>`
    : "";
  return `
  <article class="job ${j.disqualified ? "disqualified" : ""}">
    <div class="job-head">
      <span class="job-company">${esc(j.company)}</span>
      <span class="job-title">${esc(j.title)}</span>
      ${isNew ? '<span class="badge new">NEW</span>' : ""}
      <span class="badge score-${band(j.overall_score)}">score ${j.overall_score}</span>
      <span class="badge sp-${esc(j.sponsorship_classification)}">${esc(SP_LABEL[j.sponsorship_classification] || j.sponsorship_classification)}</span>
    </div>
    <div class="job-meta">
      📍 ${esc(j.location || "location n/a")} · posted ${esc(j.date_posted || "n/a")}
      · first seen ${esc((j.first_seen || "").slice(0, 10))} · ${esc(j.graduation_match)}
    </div>
    ${evidence}
    <div class="explain"><strong>Why this score:</strong> ${esc(j.score_explanation)}</div>
    ${risks}${dq}
    <a class="apply" href="${esc(j.application_url)}" target="_blank" rel="noopener noreferrer">Apply on company site ↗</a>
  </article>`;
}

function renderHealth() {
  const bad = state.health.filter((h) => h.status === "failed" || h.status === "skipped");
  if (!bad.length) return;
  $("health-section").hidden = false;
  $("health").innerHTML = bad
    .map(
      (h) => `<div class="health-row"><strong>${esc(h.company)}</strong>
        <span class="cat">${esc(h.error_category)}</span> ${esc(h.error_message || "")}</div>`
    )
    .join("");
}

for (const id of ["q", "company", "score", "sponsorship", "location", "family", "newOnly", "showDisqualified", "sort"]) {
  $(id).addEventListener("input", render);
}
init();
