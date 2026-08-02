(() => {
  "use strict";

  const FIXED_USER_ID = "omega";

  const state = { page: 1, pageSize: 20, sort: "survey_id", direction: "desc", timer: null, requestId: 0, questionRequestId: 0, lastPayload: null, lastQuestionTrigger: null };
  const el = (id) => document.getElementById(id);
  const controls = {
    country: el("countryFilter"), company: el("companyFilter"), name: el("nameFilter"),
    search: el("searchInput"), pageSize: el("pageSize")
  };

  function debounce(callback, wait) {
    let timeout;
    return (...args) => { clearTimeout(timeout); timeout = setTimeout(() => callback(...args), wait); };
  }

  function formatNumber(value) { return new Intl.NumberFormat().format(value || 0); }
  function formatMoney(value) { return `$${Number(value || 0).toFixed(3)}`; }
  function displayCompany(value) { return value === "Unknown" ? value : value.charAt(0).toUpperCase() + value.slice(1); }
  const USER_ID_QUERY_KEYS = new Set(["user_id", "userid", "user-id", "uid", "pid", "vq_uid", "vendor_user_id"]);
  const USER_ID_PLACEHOLDER = /\{user_?id\}|\[%%(?:pid|vendor_user_id)%%\]/gi;

  function personalizedSurveyUrl(url) {
    const userId = FIXED_USER_ID;
    const parsed = new URL(url, window.location.origin);
    let replaced = false;
    Array.from(parsed.searchParams.entries()).forEach(([key, value]) => {
      if (USER_ID_QUERY_KEYS.has(key.toLowerCase())) {
        parsed.searchParams.set(key, userId);
        replaced = true;
      } else if (USER_ID_PLACEHOLDER.test(value)) {
        parsed.searchParams.set(key, value.replace(USER_ID_PLACEHOLDER, userId));
        replaced = true;
      }
      USER_ID_PLACEHOLDER.lastIndex = 0;
    });
    if (!replaced) parsed.searchParams.set("user_id", userId);
    return { url: parsed.toString(), userId };
  }

  function setOptions(select, values, label) {
    const current = select.value;
    const fragment = document.createDocumentFragment();
    const allOption = document.createElement("option");
    allOption.value = ""; allOption.textContent = label; fragment.appendChild(allOption);
    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value; option.textContent = select === controls.company ? displayCompany(value) : value;
      fragment.appendChild(option);
    });
    select.replaceChildren(fragment);
    if (values.includes(current)) select.value = current;
  }

  function makeCell(className, text) {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = text;
    return cell;
  }


  function closeQuestionModal() {
    state.questionRequestId += 1;
    el("questionModal").classList.add("hidden");
    document.body.classList.remove("modal-open");
    if (state.lastQuestionTrigger) state.lastQuestionTrigger.focus();
  }

  function questionState(title, message, loading = false) {
    const body = el("questionModalBody");
    body.replaceChildren();
    const stateBox = document.createElement("div"); stateBox.className = "question-state";
    if (loading) { const loader = document.createElement("div"); loader.className = "loader"; stateBox.appendChild(loader); }
    const heading = document.createElement("strong"); heading.textContent = title;
    const copy = document.createElement("span"); copy.textContent = message;
    stateBox.append(heading, copy); body.appendChild(stateBox);
  }

  function renderQuestions(payload) {
    const body = el("questionModalBody");
    body.replaceChildren();
    if (!payload.questions.length) {
      questionState("No pre-screeners supplied", "This supplier has not returned targeting or qualification questions for this survey.");
      return;
    }

    const summary = document.createElement("div"); summary.className = "question-summary";
    const summaryText = document.createElement("strong"); summaryText.textContent = `${formatNumber(payload.questions.length)} qualification${payload.questions.length === 1 ? "" : "s"}`;
    const summaryNote = document.createElement("span"); summaryNote.textContent = "Live targeting requirements from the supplier";
    summary.append(summaryText, summaryNote); body.appendChild(summary);

    const list = document.createElement("div"); list.className = "question-list";
    payload.questions.forEach((question, index) => {
      const card = document.createElement("article"); card.className = "question-card";
      const top = document.createElement("div"); top.className = "question-card-top";
      const number = document.createElement("span"); number.className = "question-number"; number.textContent = String(index + 1).padStart(2, "0");
      const tags = document.createElement("div"); tags.className = "question-tags";
      [question.category, question.type].filter(Boolean).forEach((value) => {
        const tag = document.createElement("span"); tag.textContent = value; tags.appendChild(tag);
      });
      top.append(number, tags);

      const text = document.createElement("h3"); text.textContent = question.text || question.code || `Question ${index + 1}`;
      card.append(top, text);
      if (question.code) {
        const code = document.createElement("code"); code.textContent = question.code; card.appendChild(code);
      }

      const options = document.createElement("div"); options.className = "question-options";
      if (question.options.length) {
        question.options.forEach((option) => {
          const chip = document.createElement("span"); chip.className = "question-option";
          chip.textContent = option.id && option.text !== option.id ? `${option.id} · ${option.text}` : option.text;
          options.appendChild(chip);
        });
      } else {
        const openEnded = document.createElement("span"); openEnded.className = "question-open-ended"; openEnded.textContent = "Open-ended or no fixed answer list";
        options.appendChild(openEnded);
      }
      card.appendChild(options); list.appendChild(card);
    });
    body.appendChild(list);
  }

  async function showQuestions(survey, trigger) {
    const requestId = ++state.questionRequestId;
    state.lastQuestionTrigger = trigger;
    el("questionModalTitle").textContent = survey.name;
    el("questionModalMeta").textContent = `${displayCompany(survey.company)} · Survey ${survey.survey_id}`;
    el("questionModal").classList.remove("hidden");
    document.body.classList.add("modal-open");
    questionState("Loading questions", "Fetching the latest supplier targeting and pre-screening requirements…", true);
    el("questionModalClose").focus();
    trigger.classList.add("loading"); trigger.disabled = true;
    const params = new URLSearchParams({ company: survey.company, survey_id: survey.survey_id });
    try {
      const response = await fetch(`/api/surveys/questions/?${params}`, { headers: { Accept: "application/json" } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || "Could not load question data.");
      if (requestId === state.questionRequestId) renderQuestions(payload);
    } catch (error) {
      if (requestId === state.questionRequestId) questionState("Questions unavailable", error.message);
    } finally {
      trigger.classList.remove("loading"); trigger.disabled = false;
    }
  }


  function renderRows(rows) {
    const body = el("surveyRows");
    body.replaceChildren();
    if (!rows.length) {
      const row = document.createElement("tr"); row.className = "empty-row";
      const cell = document.createElement("td"); cell.colSpan = 7;
      const box = document.createElement("div"); box.className = "empty-state";
      const title = document.createElement("strong"); title.textContent = "No surveys match these filters";
      const note = document.createElement("span"); note.textContent = "Try changing the country, company, name, or search term.";
      box.append(title, note); cell.appendChild(box); row.appendChild(cell); body.appendChild(row); return;
    }

    rows.forEach((survey) => {
      const row = document.createElement("tr");
      row.appendChild(makeCell("survey-code", survey.survey_id));
      row.appendChild(makeCell("survey-name", survey.name));

      const companyCell = document.createElement("td");
      const company = document.createElement("span"); company.className = "company-pill"; company.textContent = displayCompany(survey.company);
      companyCell.appendChild(company); row.appendChild(companyCell);

      const countryCell = document.createElement("td");
      const country = document.createElement("span"); country.className = "country-pill"; country.textContent = survey.country;
      countryCell.appendChild(country); row.appendChild(countryCell);

      row.appendChild(makeCell("payout", formatMoney(survey.payout)));
      const placement = makeCell("placement", survey.placement_id || "—"); placement.title = survey.placement_id; row.appendChild(placement);

      const actionCell = document.createElement("td");
      const actions = document.createElement("div"); actions.className = "link-actions";
      const copy = document.createElement("button"); copy.type = "button"; copy.className = "copy-button"; copy.textContent = "Copy link";
      copy.addEventListener("click", () => copyLink(survey.entry_url));
      const questions = document.createElement("button"); questions.type = "button"; questions.className = "question-button";
      questions.setAttribute("aria-label", `View pre-screening questions for ${survey.name}`); questions.title = "View questions";
      const eye = document.createElement("span"); eye.className = "eye-icon"; eye.setAttribute("aria-hidden", "true"); questions.appendChild(eye);
      questions.addEventListener("click", () => showQuestions(survey, questions));
      const open = document.createElement("button"); open.type = "button"; open.className = "open-button"; open.textContent = "Open ↗";
      open.addEventListener("click", () => {
        const personalized = personalizedSurveyUrl(survey.entry_url);
        window.open(personalized.url, "_blank", "noopener,noreferrer");
        // The supplier-specific respondent parameter has already been populated.
      });
      actions.append(copy, questions, open); actionCell.appendChild(actions); row.appendChild(actionCell);
      body.appendChild(row);
    });
  }

  async function copyLink(url) {
    const personalized = personalizedSurveyUrl(url);
    try { await navigator.clipboard.writeText(personalized.url); showToast(`Link copied with user ID ${personalized.userId}`); }
    catch (_) { showToast("Could not access the clipboard"); }
  }

  function showToast(message) {
    const toast = el("toast"); toast.textContent = message; toast.classList.add("show");
    window.clearTimeout(showToast.timeout); showToast.timeout = window.setTimeout(() => toast.classList.remove("show"), 2200);
  }

  function render(payload) {
    state.lastPayload = payload;
    const { summary, pagination, filters, live } = payload;
    setOptions(controls.country, filters.countries, "All countries");
    setOptions(controls.company, filters.companies, "All companies");
    setOptions(controls.name, filters.names, "All survey names");
    renderRows(payload.surveys);

    el("totalStat").textContent = formatNumber(summary.filtered_surveys);
    el("countryStat").textContent = formatNumber(summary.country_count);
    el("companyStat").textContent = formatNumber(summary.company_count);
    el("payoutStat").textContent = formatMoney(summary.average_payout);
    el("filteredNote").textContent = summary.filtered_surveys === summary.all_surveys ? "Across live feed" : `of ${formatNumber(summary.all_surveys)} total`;
    el("resultCount").textContent = pagination.total ? `Showing ${pagination.start}–${pagination.end} of ${formatNumber(pagination.total)} surveys` : "No surveys found";
    el("pageSummary").textContent = pagination.total ? `${pagination.start}–${pagination.end} of ${formatNumber(pagination.total)}` : "0 results";
    el("pageNumber").textContent = pagination.page;
    el("prevPage").disabled = pagination.page <= 1;
    el("nextPage").disabled = pagination.page >= pagination.total_pages;
    state.page = pagination.page;

    const fetched = live.fetched_at ? new Date(live.fetched_at) : null;
    el("lastSync").textContent = fetched ? fetched.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "Unavailable";
    el("liveBadge").classList.toggle("stale", live.stale);
    el("liveBadge").querySelector("b").textContent = live.stale ? "Cached feed" : "Live feed";
    el("notice").classList.toggle("hidden", !live.stale);
    if (live.stale) el("notice").textContent = "The provider could not be reached, so the last successful feed is being shown.";
  }

  function queryString(force) {
    const params = new URLSearchParams({ page: state.page, page_size: state.pageSize, sort: state.sort, direction: state.direction });
    if (controls.country.value) params.set("country", controls.country.value);
    if (controls.company.value) params.set("company", controls.company.value);
    if (controls.name.value) params.set("name", controls.name.value);
    if (controls.search.value.trim()) params.set("search", controls.search.value.trim());
    if (force) params.set("refresh", "1");
    return params.toString();
  }

  async function loadSurveys(force = false) {
    const requestId = ++state.requestId;
    el("refreshButton").classList.add("spinning");
    try {
      const response = await fetch(`/api/surveys/?${queryString(force)}`, { headers: { Accept: "application/json" } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || "Could not load surveys.");
      if (requestId === state.requestId) render(payload);
    } catch (error) {
      if (requestId !== state.requestId) return;
      const notice = el("notice"); notice.textContent = `${error.message} Please try again.`; notice.classList.remove("hidden");
      if (!state.lastPayload) renderRows([]);
    } finally { if (requestId === state.requestId) el("refreshButton").classList.remove("spinning"); }
  }

  function filtersChanged() { state.page = 1; loadSurveys(); }
  [controls.country, controls.company, controls.name].forEach((control) => control.addEventListener("change", filtersChanged));
  controls.search.addEventListener("input", debounce(filtersChanged, 300));
  controls.pageSize.addEventListener("change", () => { state.pageSize = Number(controls.pageSize.value); filtersChanged(); });
  el("clearFilters").addEventListener("click", () => { controls.country.value = ""; controls.company.value = ""; controls.name.value = ""; controls.search.value = ""; filtersChanged(); });
  el("refreshButton").addEventListener("click", () => loadSurveys(true));
  el("prevPage").addEventListener("click", () => { if (state.page > 1) { state.page -= 1; loadSurveys(); } });
  el("nextPage").addEventListener("click", () => { state.page += 1; loadSurveys(); });
  document.querySelectorAll("th button[data-sort]").forEach((button) => button.addEventListener("click", () => {
    const nextSort = button.dataset.sort;
    state.direction = state.sort === nextSort && state.direction === "asc" ? "desc" : "asc";
    state.sort = nextSort; state.page = 1; loadSurveys();
  }));

  el("questionModalClose").addEventListener("click", closeQuestionModal);
  el("questionModalBackdrop").addEventListener("click", closeQuestionModal);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !el("questionModal").classList.contains("hidden")) closeQuestionModal();
  });

  el("exportButton").addEventListener("click", async () => {
    const button = el("exportButton");
    const originalText = button.textContent;
    const params = new URLSearchParams(queryString(false));
    params.delete("page");
    params.delete("page_size");
    params.delete("refresh");
    params.set("user_id", FIXED_USER_ID);
    button.disabled = true;
    button.textContent = "Exporting…";
    try {
      const response = await fetch(`/api/surveys/export/?${params}`, { headers: { Accept: "text/csv" } });
      if (!response.ok) throw new Error("Export failed");
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = filenameMatch?.[1] || `surveys-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      const exportedCount = response.headers.get("X-Exported-Count");
      showToast(exportedCount ? `${formatNumber(exportedCount)} surveys exported` : "Full CSV export ready");
    } catch (_) {
      showToast("Export could not be created");
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  });

  loadSurveys();
  state.timer = window.setInterval(() => loadSurveys(true), 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadSurveys(); });
})();
