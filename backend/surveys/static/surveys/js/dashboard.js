(() => {
  "use strict";

  const state = { page: 1, pageSize: 20, sort: "survey_id", direction: "desc", timer: null, requestId: 0, lastPayload: null };
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
  function personalizedSurveyUrl(url) {
    const userId = "opop";
    const parsed = new URL(url, window.location.origin);
    parsed.searchParams.set("user_id", userId);
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
      const open = document.createElement("button"); open.type = "button"; open.className = "open-button"; open.textContent = "Open ↗";
      open.addEventListener("click", () => {
        const personalized = personalizedSurveyUrl(survey.entry_url);
        window.open(personalized.url, "_blank", "noopener,noreferrer");
        showToast("Opened with user ID opop");
      });
      actions.append(copy, open); actionCell.appendChild(actions); row.appendChild(actionCell);
      body.appendChild(row);
    });
  }

  async function copyLink(url) {
    const personalized = personalizedSurveyUrl(url);
    try { await navigator.clipboard.writeText(personalized.url); showToast("Link copied with user ID opop"); }
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

  el("exportButton").addEventListener("click", async () => {
    const originalPage = state.page, originalSize = state.pageSize;
    const params = new URLSearchParams(queryString(false)); params.set("page", "1"); params.set("page_size", "100");
    try {
      const response = await fetch(`/api/surveys/?${params}`); const payload = await response.json();
      if (!response.ok) throw new Error(payload.message);
      const header = ["Survey ID", "Survey name", "Company", "Country", "Payout", "Placement ID", "Entry URL"];
      const escape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
      const lines = [header, ...payload.surveys.map((s) => [s.survey_id, s.name, s.company, s.country, s.payout, s.placement_id, personalizedSurveyUrl(s.entry_url).url])];
      const blob = new Blob([lines.map((row) => row.map(escape).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" });
      const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `surveys-${new Date().toISOString().slice(0,10)}.csv`; link.click(); URL.revokeObjectURL(link.href);
      if (payload.pagination.total > 100) showToast("Exported the first 100 filtered surveys"); else showToast("CSV export ready");
    } catch (_) { showToast("Export could not be created"); }
    finally { state.page = originalPage; state.pageSize = originalSize; }
  });

  loadSurveys();
  state.timer = window.setInterval(() => loadSurveys(true), 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadSurveys(); });
})();
