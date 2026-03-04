/**
 * Overview page — live KPI cards, subscription health, recent errors, activity timeline.
 *
 * Polls:
 *   /api/traces/stats   → KPI cards + event breakdown
 *   /api/subscriptions   → subscription health table
 *   /api/stats           → in-flight / DLQ counts
 *   /api/traces          → recent errors panel
 *
 * SSE:
 *   trace events → activity timeline (append new points)
 */
(function () {
  'use strict';

  // Sparkline history (ring buffers, max 30 data points)
  const MAX_HISTORY = 30;
  const history = {
    total: [],
    latency: [],
    errors: [],
    dlq: [],
  };

  function pushHistory(key, value) {
    const arr = history[key];
    arr.push(value);
    if (arr.length > MAX_HISTORY) arr.shift();
  }

  // Activity timeline data (timestamp → counts)
  const activityData = [];
  const MAX_ACTIVITY = 60;

  // ── KPI Cards ──────────────────────────────────────────────────
  function updateKPIs(data) {
    const total = data.total || 0;
    const errorRate = data.error_rate || 0;
    const avgLatency = data.avg_latency_ms || 0;
    const errorCount = data.error_count || 0;
    const window = data.window || '5m';

    // Parse window to seconds for throughput calculation
    const windowSec = { '5m': 300, '15m': 900, '1h': 3600, '24h': 86400, '7d': 604800 }[window] || 300;
    const throughput = total > 0 ? (total / windowSec) : 0;

    document.getElementById('kpi-total').textContent = Observatory.fmt.number(total);
    document.getElementById('kpi-throughput').textContent = Observatory.fmt.number(throughput);
    document.getElementById('kpi-latency').textContent = Observatory.fmt.duration(avgLatency);
    document.getElementById('kpi-error-rate').textContent = Observatory.fmt.percent(errorRate);

    // Push to sparkline history
    pushHistory('total', total);
    pushHistory('latency', avgLatency);
    pushHistory('errors', errorCount);

    // Render sparklines
    Charts.sparkline('#spark-total', history.total, { width: 80, height: 20, color: '#3b82f6' });
    Charts.sparkline('#spark-latency', history.latency, { width: 80, height: 20, color: '#f59e0b' });
    Charts.sparkline('#spark-errors', history.errors, { width: 80, height: 20, color: '#ef4444' });

    // Event breakdown
    updateEventBreakdown(data.counts || {});
  }

  // ── Event Breakdown ────────────────────────────────────────────
  function updateEventBreakdown(counts) {
    const container = document.getElementById('event-breakdown');
    if (!container) return;

    const eventColors = {
      'handler.started': 'badge-info',
      'handler.completed': 'badge-success',
      'handler.failed': 'badge-error',
      'message.dispatched': 'badge-primary',
      'message.handled': 'badge-success',
      'message.dlq': 'badge-warning',
      'subscription.connected': 'badge-info',
      'subscription.disconnected': 'badge-ghost',
    };

    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
      container.innerHTML = '<div class="text-base-content/50 text-sm col-span-full">No events in window</div>';
      return;
    }

    container.innerHTML = entries.map(([event, count]) => {
      const badge = eventColors[event] || 'badge-ghost';
      const shortName = event.split('.').pop();
      return `<div class="text-center">
        <div class="text-lg font-mono-metric font-semibold">${Observatory.fmt.number(count)}</div>
        <div class="badge ${badge} badge-sm mt-1">${Observatory.escapeHtml(shortName)}</div>
      </div>`;
    }).join('');
  }

  // ── Stats (in-flight, DLQ) ─────────────────────────────────────
  function updateStats(data) {
    const mc = data.message_counts || {};
    document.getElementById('kpi-inflight').textContent = Observatory.fmt.number(mc.in_flight || 0);
    document.getElementById('kpi-dlq').textContent = Observatory.fmt.number(mc.dlq || 0);

    pushHistory('dlq', mc.dlq || 0);
    Charts.sparkline('#spark-dlq', history.dlq, { width: 80, height: 20, color: '#f59e0b' });
  }

  // ── Subscription Health Table ──────────────────────────────────
  function updateSubscriptions(data) {
    const tbody = document.getElementById('subscriptions-tbody');
    const countBadge = document.getElementById('sub-count');
    if (!tbody) return;

    // Flatten all domains' subscriptions
    const rows = [];
    for (const [domainName, domainData] of Object.entries(data)) {
      if (domainData.status === 'error') continue;
      const subs = domainData.subscriptions || [];
      for (const sub of subs) {
        rows.push({ ...sub, domain: domainName });
      }
    }

    countBadge.textContent = rows.length;

    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-base-content/50 py-8">No subscriptions found</td></tr>';
      return;
    }

    // Sort: unhealthy first, then by lag descending
    rows.sort((a, b) => {
      const statusOrder = { lagging: 0, unknown: 1, ok: 2 };
      const sa = statusOrder[a.status] ?? 1;
      const sb = statusOrder[b.status] ?? 1;
      if (sa !== sb) return sa - sb;
      return (b.lag || 0) - (a.lag || 0);
    });

    tbody.innerHTML = rows.map(sub => {
      const statusClass = Observatory.statusClass(sub.status);
      return `<tr class="hover">
        <td><span class="status ${statusClass}"></span></td>
        <td class="font-medium text-sm">${Observatory.escapeHtml(sub.subscription || sub.name || '--')}</td>
        <td class="text-xs text-base-content/60">${Observatory.escapeHtml(sub.stream || '--')}</td>
        <td class="text-right font-mono-metric text-sm">${Observatory.fmt.number(sub.lag || 0)}</td>
        <td class="text-right font-mono-metric text-sm">${Observatory.fmt.number(sub.pending || 0)}</td>
        <td class="text-right font-mono-metric text-sm">
          ${sub.dlq_depth > 0
            ? '<span class="text-warning font-semibold">' + Observatory.fmt.number(sub.dlq_depth) + '</span>'
            : '0'}
        </td>
      </tr>`;
    }).join('');
  }

  // ── Recent Errors ──────────────────────────────────────────────
  function updateRecentErrors(data) {
    const container = document.getElementById('recent-errors');
    const countBadge = document.getElementById('error-count');
    if (!container) return;

    const traces = data.traces || [];
    countBadge.textContent = traces.length;

    if (traces.length === 0) {
      container.innerHTML = '<div class="text-center text-base-content/50 py-4 text-sm">No recent errors</div>';
      return;
    }

    container.innerHTML = traces.map(t => {
      const ts = t.timestamp ? Observatory.fmt.timeAgo(new Date(t.timestamp * 1000)) : '--';
      const handler = t.handler || t.subscription || '--';
      const msgType = t.message_type || '--';
      const errorType = t.event === 'message.dlq' ? 'DLQ' : 'Failed';
      const badgeClass = t.event === 'message.dlq' ? 'badge-warning' : 'badge-error';
      return `<div class="flex items-start gap-2 p-2 rounded-lg bg-base-200/50 text-sm">
        <span class="badge ${badgeClass} badge-xs mt-1">${errorType}</span>
        <div class="flex-1 min-w-0">
          <div class="font-medium truncate">${Observatory.escapeHtml(handler)}</div>
          <div class="text-xs text-base-content/60 truncate">${Observatory.escapeHtml(msgType)}</div>
        </div>
        <span class="text-xs text-base-content/40 whitespace-nowrap">${ts}</span>
      </div>`;
    }).join('');
  }

  // ── Activity Timeline (SSE-driven) ─────────────────────────────
  function appendActivityPoint(trace) {
    const now = Date.now();
    // Bucket into 10-second intervals
    const bucket = Math.floor(now / 10000) * 10000;

    let last = activityData[activityData.length - 1];
    if (!last || last.time !== bucket) {
      last = { time: bucket, total: 0, success: 0, errors: 0 };
      activityData.push(last);
      if (activityData.length > MAX_ACTIVITY) activityData.shift();
    }

    last.total++;
    if (trace.event === 'handler.completed' || trace.event === 'message.handled') {
      last.success++;
    } else if (trace.event === 'handler.failed' || trace.event === 'message.dlq') {
      last.errors++;
    }

    renderActivityChart();
  }

  function renderActivityChart() {
    if (activityData.length < 2) return;

    const series = [
      {
        name: 'Total',
        color: '#3b82f6',
        values: activityData.map(d => ({ x: new Date(d.time), y: d.total })),
      },
      {
        name: 'Success',
        color: '#22c55e',
        values: activityData.map(d => ({ x: new Date(d.time), y: d.success })),
      },
      {
        name: 'Errors',
        color: '#ef4444',
        values: activityData.map(d => ({ x: new Date(d.time), y: d.errors })),
      },
    ];

    Charts.areaChart('#activity-chart', series, {
      height: 200,
    });
  }

  // ── Health Banner ──────────────────────────────────────────────
  function updateHealthBanner(subsData, statsData) {
    const banner = document.getElementById('health-banner');
    const text = document.getElementById('health-text');
    if (!banner || !text) return;

    // Determine health from subscription data
    let totalSubs = 0;
    let lagging = 0;
    let totalDlq = 0;
    for (const domainData of Object.values(subsData)) {
      if (domainData.summary) {
        totalSubs += domainData.summary.total || 0;
        lagging += domainData.summary.lagging || 0;
        totalDlq += domainData.summary.total_dlq || 0;
      }
    }

    // Remove existing alert classes
    banner.classList.remove('alert-success', 'alert-warning', 'alert-error');

    if (lagging > 0 || totalDlq > 0) {
      if (totalDlq > 10 || lagging > totalSubs * 0.5) {
        banner.classList.add('alert-error');
        text.textContent = `${lagging} subscription(s) lagging, ${totalDlq} DLQ messages — attention needed`;
      } else {
        banner.classList.add('alert-warning');
        text.textContent = `${lagging} subscription(s) lagging, ${totalDlq} DLQ messages`;
      }
    } else {
      banner.classList.add('alert-success');
      text.textContent = `All ${totalSubs} subscriptions healthy — system operating normally`;
    }

    // Update nav health dot
    const navDot = document.getElementById('nav-health-dot');
    if (navDot) {
      navDot.className = 'badge badge-xs';
      if (lagging > 0 || totalDlq > 10) {
        navDot.classList.add(totalDlq > 10 ? 'badge-error' : 'badge-warning');
      } else {
        navDot.classList.add('badge-success');
      }
    }
  }

  // ── Initialization ─────────────────────────────────────────────
  let latestSubsData = {};

  function init() {
    // Register pollers
    Observatory.poller.register('traces-stats', '/api/traces/stats', 5000, updateKPIs);
    Observatory.poller.register('stats', '/api/stats', 10000, updateStats);
    Observatory.poller.register('subscriptions', '/api/subscriptions', 10000, function (data) {
      latestSubsData = data;
      updateSubscriptions(data);
      updateHealthBanner(data, {});
    });
    Observatory.poller.register('recent-errors', '/api/traces?event=handler.failed&count=10', 10000, updateRecentErrors);

    // Start polling
    Observatory.poller.startAll();

    // SSE for activity timeline
    Observatory.sse.onTrace(appendActivityPoint);
  }

  // Wait for Observatory core to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      // Small delay to ensure core.js has initialized
      setTimeout(init, 100);
    });
  } else {
    setTimeout(init, 100);
  }
})();
