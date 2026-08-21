/* Dashboard data loading, scoped graph controls, animated KPIs and SVG charts. */

(() => {
  const byId = (id) => document.getElementById(id);
  const ranges = new Set(['24h', '48h', '72h', '3m', '6m', '1y']);
  const initialQuery = new URLSearchParams(location.search);
  const initialMainRange = ranges.has(initialQuery.get('range')) ? initialQuery.get('range') : '24h';
  const state = {
    range: initialMainRange,
    trafficRange: ranges.has(initialQuery.get('traffic_range'))
      ? initialQuery.get('traffic_range') : initialMainRange,
    financeRange: ranges.has(initialQuery.get('finance_range'))
      ? initialQuery.get('finance_range') : initialMainRange,
    trafficClient: initialQuery.get('traffic_client') || '',
    financeClient: initialQuery.get('finance_client') || '',
    controller: null,
    requestId: 0,
    data: null,
    resizeTimer: null,
  };
  const colors = ['#15b8d8', '#4967d8', '#29ad7b', '#e6a43c', '#9165d5', '#e56472', '#57748f', '#1f9d9a'];
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function escapeHtml(value) {
    const node = document.createElement('div');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
  }

  const number = (value) => Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  const moneyNumber = (value) => Number(value || 0);

  function niceIntegerMaximum(value) {
    const maximum = Math.max(0, Math.ceil(Number(value || 0)));
    return Math.max(4, Math.ceil(maximum / 4) * 4);
  }

  function markReady(element) {
    element?.setAttribute('aria-busy', 'false');
  }

  function formatCurrency(value, currency, compact = false) {
    try {
      return new Intl.NumberFormat('en-IN', {
        style: 'currency', currency: currency || 'USD',
        notation: compact ? 'compact' : 'standard', maximumFractionDigits: 2,
      }).format(Number(value || 0));
    } catch (_error) {
      return `${currency || 'USD'} ${Number(value || 0).toFixed(2)}`;
    }
  }

  function formatLoi(seconds) {
    const total = Math.max(0, Math.round(Number(seconds || 0)));
    if (total < 60) return `${total}s`;
    const minutes = Math.floor(total / 60); const remainder = total % 60;
    return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
  }

  function animateNumber(element, target, formatter = number) {
    if (!element || target == null) return;
    const finalValue = Number(target || 0);
    const startValue = Number(element.dataset.value || 0);
    element.dataset.value = String(finalValue);
    if (reducedMotion) { element.textContent = formatter(finalValue); return; }
    const started = performance.now();
    const frame = (now) => {
      const progress = Math.min(1, (now - started) / 760);
      const eased = 1 - Math.pow(1 - progress, 3);
      element.textContent = formatter(startValue + (finalValue - startValue) * eased);
      if (progress < 1) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  function updateSummary(summary) {
    const currency = summary.revenue_currency || 'USD';
    animateNumber(byId('dashboardRevenue'), summary.revenue, (value) => formatCurrency(value, currency));
    animateNumber(byId('dashboardHits'), summary.hits);
    animateNumber(byId('dashboardCompletes'), summary.completes);
    animateNumber(byId('dashboardConversion'), summary.conversion_rate, (value) => `${value.toFixed(1)}%`);
    animateNumber(byId('dashboardAverageCpi'), summary.average_cpi, (value) => formatCurrency(value, currency));
    animateNumber(byId('dashboardRpc'), summary.rpc, (value) => formatCurrency(value, currency));
    animateNumber(byId('dashboardAverageLoi'), summary.average_loi_seconds, formatLoi);
    animateNumber(byId('dashboardActiveUsers'), summary.active_users);
    animateNumber(byId('dashboardIR'), summary.incidence_rate, (value) => `${value.toFixed(1)}%`);
    document.querySelectorAll('.bi-kpi').forEach((card, index) => {
      card.classList.remove('bi-kpi-ready');
      setTimeout(() => card.classList.add('bi-kpi-ready'), reducedMotion ? 0 : index * 45);
    });
    markReady(document.querySelector('.bi-kpi-grid'));
  }

  function svgLine(points) {
    return points.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');
  }

  function axisGrid({ width, height, left, right, top, bottom, maximum, formatter = number }) {
    const plotHeight = height - top - bottom;
    return [0, .25, .5, .75, 1].map((ratio) => {
      const y = top + plotHeight - ratio * plotHeight;
      return `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"/><text x="${left - 9}" y="${y + 4}" text-anchor="end">${escapeHtml(formatter(maximum * ratio))}</text>`;
    }).join('');
  }

  function labelStride(rows, host) {
    const target = host.clientWidth < 520 ? 4 : host.clientWidth < 760 ? 6 : 8;
    return Math.max(1, Math.ceil(rows.length / target));
  }

  function animateChart(host) {
    if (reducedMotion) return;
    requestAnimationFrame(() => {
      host.querySelectorAll('.bi-chart-line').forEach((path) => {
        const length = path.getTotalLength();
        path.style.strokeDasharray = length;
        path.style.strokeDashoffset = length;
        requestAnimationFrame(() => { path.style.strokeDashoffset = '0'; });
      });
    });
  }

  function renderVolume(rows, rangeLabel = '') {
    const host = byId('volumeChart'); if (!host) return;
    const totalHits = (rows || []).reduce((sum, row) => sum + Number(row.hits || 0), 0);
    const totalCompletes = (rows || []).reduce((sum, row) => sum + Number(row.completes || 0), 0);
    if (!rows?.length || (!totalHits && !totalCompletes)) {
      host.innerHTML = '<div class="dashboard-empty">No respondent traffic was recorded in this chart range.</div>';
      markReady(host);
      return;
    }
    const width = 860; const height = 300; const left = 52; const right = 48; const top = 24; const bottom = 42;
    const plotWidth = width - left - right; const plotHeight = height - top - bottom;
    const maximum = niceIntegerMaximum(Math.max(...rows.flatMap((row) => [Number(row.hits), Number(row.completes)])));
    const group = plotWidth / rows.length; const barWidth = Math.max(4, Math.min(18, group * .28));
    const x = (index) => left + group * index + group / 2;
    const y = (value) => top + plotHeight - Number(value || 0) / maximum * plotHeight;
    const rateY = (value) => top + plotHeight - Math.min(100, Number(value || 0)) / 100 * plotHeight;
    const stride = labelStride(rows, host);
    const bars = rows.map((row, index) => {
      const hitY = y(row.hits); const completeY = y(row.completes);
      return `<g class="bi-bar-group" style="--delay:${index * 40}ms"><rect class="bi-volume-hit" x="${x(index) - barWidth - 1}" y="${hitY}" width="${barWidth}" height="${top + plotHeight - hitY}"><title>${escapeHtml(row.label)} · Entrants ${number(row.hits)}</title></rect><rect class="bi-volume-complete" x="${x(index) + 1}" y="${completeY}" width="${barWidth}" height="${top + plotHeight - completeY}"><title>${escapeHtml(row.label)} · Completes ${number(row.completes)}</title></rect></g>`;
    }).join('');
    const ratePoints = rows.map((row, index) => ({ x: x(index), y: rateY(row.conversion_rate), value: row.conversion_rate }));
    const rateDots = ratePoints.map((point, index) => `<circle class="bi-rate-dot" cx="${point.x}" cy="${point.y}" r="3.5"><title>${escapeHtml(rows[index].label)} · Conversion ${Number(point.value).toFixed(1)}%</title></circle>`).join('');
    const labels = rows.map((row, index) => index % stride === 0 || index === rows.length - 1
      ? `<text class="bi-x-label" x="${x(index)}" y="${height - 15}" text-anchor="middle">${escapeHtml(row.short_label)}</text>` : '').join('');
    const rightAxis = [0, 50, 100].map((value) => `<text class="bi-right-axis" x="${width - right + 9}" y="${rateY(value) + 4}">${value}%</text>`).join('');
    host.innerHTML = `<svg class="bi-chart-svg" viewBox="0 0 ${width} ${height}" role="img" tabindex="0" aria-label="Entrants, completes and conversion over ${escapeHtml(rangeLabel)}"><desc>${number(totalHits)} entrants and ${number(totalCompletes)} completes in this chart range.</desc><g class="bi-chart-grid">${axisGrid({ width, height, left, right, top, bottom, maximum })}</g>${rightAxis}${bars}<path class="bi-chart-line bi-conversion-line" d="${svgLine(ratePoints)}"/>${rateDots}${labels}</svg>`;
    markReady(host);
    animateChart(host);
  }

  function renderFinance(rows, currency, rangeLabel = '') {
    const host = byId('financeChart'); if (!host) return;
    if (!rows?.length) {
      host.innerHTML = '<div class="dashboard-empty">No financial data is available for this chart range.</div>';
      markReady(host);
      return;
    }
    const hasRevenue = rows.some((row) => row.revenue != null);
    const lineKey = rows.some((row) => row.rpc != null) ? 'rpc' : 'average_cpi';
    const lineLabel = lineKey === 'rpc' ? 'RPC' : 'Average CPI';
    const hasLine = rows.some((row) => row[lineKey] != null);
    byId('financeBarLegend')?.toggleAttribute('hidden', !hasRevenue);
    const lineLegend = byId('financeLineLegend');
    if (lineLegend) {
      lineLegend.hidden = !hasLine;
      lineLegend.lastChild.textContent = lineLabel;
    }
    const revenueTotal = rows.reduce((sum, row) => sum + Number(row.revenue || 0), 0);
    const lineTotal = rows.reduce((sum, row) => sum + Number(row[lineKey] || 0), 0);
    if ((!hasRevenue || !revenueTotal) && (!hasLine || !lineTotal)) {
      host.innerHTML = '<div class="dashboard-empty">No completed revenue was recorded in this chart range.</div>';
      markReady(host);
      return;
    }
    const width = 620; const height = 300; const left = 58; const right = 48; const top = 24; const bottom = 42;
    const plotWidth = width - left - right; const plotHeight = height - top - bottom;
    const maxRevenue = Math.max(1, ...rows.map((row) => Number(row.revenue || 0)));
    const maxLine = Math.max(1, ...rows.map((row) => Number(row[lineKey] || 0)));
    const group = plotWidth / rows.length; const barWidth = Math.max(5, Math.min(25, group * .5));
    const x = (index) => left + group * index + group / 2;
    const revenueY = (value) => top + plotHeight - Number(value || 0) / maxRevenue * plotHeight;
    const lineY = (value) => top + plotHeight - Number(value || 0) / maxLine * plotHeight;
    const stride = labelStride(rows, host);
    const bars = hasRevenue ? rows.map((row, index) => {
      const y = revenueY(row.revenue);
      return `<rect class="bi-finance-bar" style="--delay:${index * 40}ms" x="${x(index) - barWidth / 2}" y="${y}" width="${barWidth}" height="${top + plotHeight - y}"><title>${escapeHtml(row.label)} · Revenue ${escapeHtml(formatCurrency(row.revenue, currency))}</title></rect>`;
    }).join('') : '';
    const linePoints = hasLine
      ? rows.map((row, index) => ({ x: x(index), y: lineY(row[lineKey]), value: row[lineKey] }))
      : [];
    const dots = linePoints.map((point, index) => `<circle class="bi-rpc-dot" cx="${point.x}" cy="${point.y}" r="3.5"><title>${escapeHtml(rows[index].label)} · ${lineLabel} ${escapeHtml(formatCurrency(point.value, currency))}</title></circle>`).join('');
    const labels = rows.map((row, index) => index % stride === 0 || index === rows.length - 1
      ? `<text class="bi-x-label" x="${x(index)}" y="${height - 15}" text-anchor="middle">${escapeHtml(row.short_label)}</text>` : '').join('');
    const rightAxis = hasLine
      ? [0, .5, 1].map((ratio) => `<text class="bi-right-axis" x="${width - right + 8}" y="${lineY(maxLine * ratio) + 4}">${escapeHtml(formatCurrency(maxLine * ratio, currency, true))}</text>`).join('')
      : '';
    const line = hasLine ? `<path class="bi-chart-line bi-rpc-line" d="${svgLine(linePoints)}"/>${dots}` : '';
    const accessibleLabel = hasLine ? `Revenue and ${lineLabel}` : 'Revenue';
    host.innerHTML = `<svg class="bi-chart-svg" viewBox="0 0 ${width} ${height}" role="img" tabindex="0" aria-label="${accessibleLabel} over ${escapeHtml(rangeLabel)}"><desc>Total revenue ${escapeHtml(formatCurrency(revenueTotal, currency))} in this chart range.</desc><g class="bi-chart-grid">${axisGrid({ width, height, left, right, top, bottom, maximum: maxRevenue, formatter: (value) => formatCurrency(value, currency, true) })}</g>${rightAxis}${bars}${line}${labels}</svg>`;
    markReady(host);
    animateChart(host);
  }

  function renderClients(rows) {
    const host = byId('clientShareChart'); if (!host) return;
    if (!rows?.length) {
      host.innerHTML = '<div class="dashboard-empty">No completed client activity matches this range.</div>';
      markReady(host);
      return;
    }
    let cursor = 0;
    const segments = rows.map((row, index) => {
      const start = cursor; cursor += Number(row.share_percent || 0);
      return `${colors[index % colors.length]} ${start}% ${cursor}%`;
    });
    if (cursor < 100) segments.push(`#edf2f6 ${cursor}% 100%`);
    const total = rows.reduce((sum, row) => sum + Number(row.completes || 0), 0);
    host.innerHTML = `<div class="bi-client-donut" style="--segments:${segments.join(',')}"><span><b>${number(total)}</b><small>Completes</small></span></div><ol class="bi-client-list">${rows.map((row, index) => `<li style="--index:${index}"><i style="--series:${colors[index % colors.length]}"></i><span><b>${escapeHtml(row.name)}</b><small>${number(row.completes)} completes</small></span><strong>${Number(row.share_percent || 0).toFixed(1)}%</strong></li>`).join('')}</ol>`;
    markReady(host);
  }

  function renderStatus(data) {
    const host = byId('statusBreakdown'); if (!host || !data) return;
    const rows = [
      ['initiated', 'Initiated', data.initiated], ['completed', 'Completed', data.completed],
      ['terminated', 'Terminated', data.terminated], ['quota', 'Quota full', data.quota],
      ['security', 'Quality / security', data.security],
    ];
    const total = Math.max(1, rows.reduce((sum, row) => sum + Number(row[2] || 0), 0));
    host.innerHTML = rows.map(([type, label, value], index) => {
      const percent = Number(value || 0) / total * 100;
      return `<div class="bi-status-row ${type}" style="--index:${index}"><span><i></i>${label}</span><div role="progressbar" aria-label="${escapeHtml(label)} share" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent.toFixed(1)}"><b style="--progress:${percent}%"></b></div><strong>${number(value)}</strong><em>${percent.toFixed(1)}%</em></div>`;
    }).join('');
    markReady(host);
  }

  function renderDevices(data) {
    const host = byId('deviceBreakdown'); if (!host || !data) return;
    const rows = [
      ['desktop', 'Desktop', '#15b8d8'], ['mobile', 'Mobile', '#4967d8'],
      ['tablet', 'Tablet', '#9165d5'], ['unclassified', 'Other', '#d8e0e8'],
    ];
    const total = rows.reduce((sum, [key]) => sum + Number(data[key] || 0), 0);
    let cursor = 0;
    const segments = rows.map(([key, _label, color]) => {
      const start = cursor; cursor += total ? Number(data[key] || 0) / total * 100 : 0;
      return `${color} ${start}% ${cursor}%`;
    });
    if (!total) segments.push('#edf2f6 0 100%');
    host.innerHTML = `<div class="bi-device-ring" style="--segments:${segments.join(',')}"><span><b>${number(total)}</b><small>Completes</small></span></div><div class="bi-device-list">${rows.map(([key, label, color], index) => `<div style="--index:${index}"><i style="--series:${color}"></i><span>${label}</span><strong>${number(data[key])}</strong><small>${total ? (Number(data[key] || 0) / total * 100).toFixed(1) : '0.0'}%</small></div>`).join('')}</div>`;
    markReady(host);
  }

  function renderTopUsers(rows) {
    const host = byId('dashboardTopUsers'); if (!host) return;
    if (!rows?.length) {
      host.innerHTML = '<div class="dashboard-empty">No user activity matches this range.</div>';
      markReady(host);
      return;
    }
    const maximum = Math.max(1, ...rows.map((row) => Number(row.completes || 0)));
    host.innerHTML = rows.map((row, index) => `<div class="bi-performer-row" style="--index:${index}"><span class="bi-performer-rank">${String(index + 1).padStart(2, '0')}</span><span class="bi-performer-avatar">${escapeHtml(String(row.name || '?').charAt(0).toUpperCase())}</span><div><b>${escapeHtml(row.name)}</b><small>${number(row.hits)} hits · ${Number(row.conversion_rate || 0).toFixed(1)}% conversion</small><span><i style="--progress:${Number(row.completes || 0) / maximum * 100}%"></i></span></div><strong>${number(row.completes)}<small>completes</small></strong></div>`).join('');
    markReady(host);
  }

  function updateGraphControls(data) {
    const clients = data.graph_clients || [];
    [['traffic', 'trafficGraphClient'], ['finance', 'financeGraphClient']].forEach(([graph, id]) => {
      const select = byId(id); if (!select) return;
      const selected = String(state[`${graph}Client`] || '');
      select.innerHTML = `<option value="">All clients</option>${clients.map((client) => `<option value="${escapeHtml(client.id)}">${escapeHtml(client.name)}</option>`).join('')}`;
      select.value = selected;
    });
    document.querySelectorAll('[data-graph-range]').forEach((button) => {
      const graph = button.dataset.graph;
      const active = button.dataset.graphRange === state[`${graph}Range`];
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
  }

  function render(data) {
    state.data = data;
    const errorBanner = byId('dashboardErrorBanner');
    if (errorBanner) errorBanner.hidden = true;
    updateSummary(data.summary || {});
    const caption = byId('dashboardRangeCaption'); if (caption) caption.textContent = data.range.label;
    if (byId('trafficBucketLabel') && data.traffic_chart) byId('trafficBucketLabel').textContent = data.traffic_chart.range.bucket_label;
    if (byId('financeBucketLabel') && data.finance_chart) byId('financeBucketLabel').textContent = data.finance_chart.range.bucket_label;
    updateGraphControls(data);
    renderVolume(data.traffic_chart?.points, data.traffic_chart?.range?.label || data.range.label);
    renderFinance(data.finance_chart?.points, data.summary?.revenue_currency || 'USD', data.finance_chart?.range?.label || data.range.label);
    renderClients(data.client_distribution);
    renderStatus(data.status_breakdown);
    renderDevices(data.device_breakdown);
    renderTopUsers(data.top_users);
    const updated = byId('dashboardUpdatedAt');
    if (updated) updated.textContent = `${new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(data.generated_at))} IST`;
  }

  function showError(message) {
    const banner = byId('dashboardErrorBanner');
    const errorMessage = byId('dashboardErrorMessage');
    if (errorMessage) errorMessage.textContent = message || 'Please try again.';
    if (banner) banner.hidden = false;
    if (!state.data) {
      document.querySelectorAll('.bi-chart-stage,.bi-client-body,.bi-status-list,.bi-device-body,.bi-performer-list').forEach((host) => {
        host.innerHTML = '<div class="dashboard-empty dashboard-error-placeholder">Analytics are unavailable until the request succeeds.</div>';
        markReady(host);
      });
    }
  }

  function setLoading(loading) {
    document.body.classList.toggle('dashboard-refreshing', loading);
    document.querySelectorAll('[data-dashboard-range],[data-graph-range],#trafficGraphClient,#financeGraphClient').forEach((control) => {
      control.disabled = loading;
    });
    document.querySelectorAll('.bi-kpi-grid,.bi-chart-stage,.bi-client-body,.bi-status-list,.bi-device-body,.bi-performer-list').forEach((host) => {
      host.setAttribute('aria-busy', String(loading));
    });
  }

  async function loadDashboard() {
    state.controller?.abort();
    const controller = new AbortController();
    const requestId = ++state.requestId;
    state.controller = controller;
    setLoading(true);
    try {
      const query = new URLSearchParams({ range: state.range });
      if (document.querySelector('[data-graph-toolbar="traffic"]')) {
        query.set('traffic_range', state.trafficRange);
        if (state.trafficClient) query.set('traffic_client', state.trafficClient);
      }
      if (document.querySelector('[data-graph-toolbar="finance"]')) {
        query.set('finance_range', state.financeRange);
        if (state.financeClient) query.set('finance_client', state.financeClient);
      }
      const response = await fetch(`/api/v1/dashboard/?${query.toString()}`, {
        signal: controller.signal, credentials: 'same-origin',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
      if (requestId !== state.requestId) return;
      render(data);
    } catch (error) {
      if (error.name !== 'AbortError' && requestId === state.requestId) showError(error.message);
    } finally {
      if (requestId === state.requestId) setLoading(false);
    }
  }

  byId('dashboardRetry')?.addEventListener('click', loadDashboard);

  document.querySelectorAll('[data-dashboard-range]').forEach((button) => {
    const selected = button.dataset.dashboardRange === state.range;
    button.classList.toggle('active', selected); button.setAttribute('aria-pressed', String(selected));
    button.addEventListener('click', () => {
      if (button.dataset.dashboardRange === state.range) return;
      state.range = button.dataset.dashboardRange;
      document.querySelectorAll('[data-dashboard-range]').forEach((item) => {
        const active = item === button;
        item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active));
      });
      const url = new URL(location.href); url.searchParams.set('range', state.range); history.replaceState({}, '', url);
      loadDashboard();
    });
  });

  document.querySelectorAll('[data-graph-range]').forEach((button) => {
    const graph = button.dataset.graph;
    const selected = button.dataset.graphRange === state[`${graph}Range`];
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
    button.addEventListener('click', () => {
      const nextRange = button.dataset.graphRange;
      if (nextRange === state[`${graph}Range`]) return;
      state[`${graph}Range`] = nextRange;
      const url = new URL(location.href);
      url.searchParams.set(`${graph}_range`, nextRange);
      history.replaceState({}, '', url);
      loadDashboard();
    });
  });

  [['traffic', 'trafficGraphClient'], ['finance', 'financeGraphClient']].forEach(([graph, id]) => {
    byId(id)?.addEventListener('change', (event) => {
      state[`${graph}Client`] = event.target.value;
      const url = new URL(location.href);
      if (event.target.value) url.searchParams.set(`${graph}_client`, event.target.value);
      else url.searchParams.delete(`${graph}_client`);
      history.replaceState({}, '', url);
      loadDashboard();
    });
  });

  const resizeObserver = new ResizeObserver(() => {
    clearTimeout(state.resizeTimer);
    state.resizeTimer = setTimeout(() => {
      if (!state.data) return;
      renderVolume(
        state.data.traffic_chart?.points,
        state.data.traffic_chart?.range?.label || state.data.range.label
      );
      renderFinance(
        state.data.finance_chart?.points,
        state.data.summary?.revenue_currency || 'USD',
        state.data.finance_chart?.range?.label || state.data.range.label
      );
    }, 120);
  });
  document.querySelectorAll('.bi-chart-stage').forEach((host) => resizeObserver.observe(host));
  loadDashboard();
})();
