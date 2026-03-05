/**
 * Messages View Module
 *
 * Displays failed handler traces and DLQ entries with filtering,
 * search, time window selection, detail inspection, and bulk actions.
 *
 * Uses server-side pagination — only one page of data is fetched at a time.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let _tab = 'failed';       // 'failed' | 'dlq'
  let _window = '5m';
  let _search = '';
  let _customStart = null;
  let _customEnd = null;
  let _selectedDlqId = null;

  // Server-side pagination state
  const PAGE_SIZE = 25;
  let _failedPage = 1;
  let _failedTotal = 0;
  let _failedTraces = [];    // current page only
  let _dlqPage = 1;
  let _dlqTotal = 0;
  let _dlqEntries = [];      // current page only

  // DOM refs
  let $search, $tabs, $panelFailed, $panelDlq;

  // ---------------------------------------------------------------------------
  // Data Fetching (server-side paginated)
  // ---------------------------------------------------------------------------

  async function fetchFailed() {
    const offset = (_failedPage - 1) * PAGE_SIZE;
    const params = new URLSearchParams({
      window: _window,
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    if (_customStart && _customEnd && _window === 'custom') {
      params.set('start', _customStart);
      params.set('end', _customEnd);
      params.delete('window');
    }
    try {
      const resp = await fetch('/api/traces/failed?' + params);
      const data = await resp.json();
      _failedTraces = data.traces || [];
      _failedTotal = data.total_count || 0;
    } catch (e) {
      console.warn('Failed to fetch failed traces:', e.message);
      _failedTraces = [];
      _failedTotal = 0;
    }
    renderFailed();
    updateSummaryFailed();
    updateNavBadge();
  }

  async function fetchDLQ() {
    const offset = (_dlqPage - 1) * PAGE_SIZE;
    try {
      const resp = await fetch('/api/dlq?limit=' + PAGE_SIZE + '&offset=' + offset);
      const data = await resp.json();
      _dlqEntries = data.entries || [];
      _dlqTotal = data.total_count || 0;
    } catch (e) {
      console.warn('Failed to fetch DLQ entries:', e.message);
      _dlqEntries = [];
      _dlqTotal = 0;
    }
    renderDLQ();
    updateSummaryDLQ();
    updateNavBadge();
  }

  // ---------------------------------------------------------------------------
  // Rendering — Failed Tab
  // ---------------------------------------------------------------------------

  function renderFailed() {
    const $tbody = document.getElementById('failed-tbody');
    const $empty = document.getElementById('failed-empty');
    const $count = document.getElementById('tab-failed-count');
    if (!$tbody) return;

    $count.textContent = _failedTotal;

    if (_failedTraces.length === 0) {
      $tbody.innerHTML = '';
      $empty.classList.remove('hidden');
      _renderPagination('failed-pagination', _failedTotal, _failedPage, function (p) {
        _failedPage = p;
        fetchFailed();
      });
      return;
    }

    $empty.classList.add('hidden');

    $tbody.innerHTML = _failedTraces.map(t => {
      const ts = t.timestamp ? Observatory.fmt.time(t.timestamp) : '--';
      const tsTitle = t.timestamp ? Observatory.fmt.datetime(t.timestamp) : '';
      const handler = Observatory.escapeHtml(t.handler || '--');
      const msgType = Observatory.escapeHtml(t.message_type || '--');
      const error = Observatory.escapeHtml(_truncate(t.error || '', 80));
      const errorFull = Observatory.escapeHtml(t.error || '');
      const duration = t.duration_ms != null ? Observatory.fmt.duration(t.duration_ms) : '--';
      const msgId = Observatory.escapeHtml(_truncate(t.message_id || '', 12));
      const msgIdFull = Observatory.escapeHtml(t.message_id || '');
      const streamId = Observatory.escapeHtml(t._stream_id || '');
      const eventBadge = t.event === 'message.dlq'
        ? '<span class="badge badge-xs badge-warning mr-1">DLQ</span>'
        : '<span class="badge badge-xs badge-error mr-1">FAIL</span>';

      return `<tr class="hover cursor-pointer trace-row" data-stream-id="${streamId}">
        <td class="text-xs" title="${tsTitle}">${eventBadge}${ts}</td>
        <td class="font-medium text-sm">${handler}</td>
        <td class="text-sm">${msgType}</td>
        <td class="text-xs text-error max-w-xs truncate" title="${errorFull}">${error}</td>
        <td class="text-right font-mono-metric text-sm">${duration}</td>
        <td class="text-xs font-mono" title="${msgIdFull}">${msgId}</td>
      </tr>`;
    }).join('');

    // Bind row click for trace detail modal
    $tbody.querySelectorAll('.trace-row').forEach(row => {
      row.addEventListener('click', () => {
        showTraceDetail(row.getAttribute('data-stream-id'));
      });
    });

    _renderPagination('failed-pagination', _failedTotal, _failedPage, function (p) {
      _failedPage = p;
      fetchFailed();
    });
  }

  // ---------------------------------------------------------------------------
  // Rendering — DLQ Tab
  // ---------------------------------------------------------------------------

  function renderDLQ() {
    const $tbody = document.getElementById('dlq-tbody');
    const $empty = document.getElementById('dlq-empty');
    const $count = document.getElementById('tab-dlq-count');
    const $actions = document.getElementById('dlq-actions');
    if (!$tbody) return;

    $count.textContent = _dlqTotal;

    if (_dlqEntries.length === 0) {
      $tbody.innerHTML = '';
      $empty.classList.remove('hidden');
      $actions.classList.add('hidden');
      _renderPagination('dlq-pagination', _dlqTotal, _dlqPage, function (p) {
        _dlqPage = p;
        fetchDLQ();
      });
      return;
    }

    $empty.classList.add('hidden');
    $actions.classList.remove('hidden');

    $tbody.innerHTML = _dlqEntries.map(e => {
      const failedAt = e.failed_at ? Observatory.fmt.timeAgo(e.failed_at) : '--';
      const failedAtTitle = e.failed_at ? Observatory.fmt.datetime(e.failed_at) : '';
      const stream = Observatory.escapeHtml(e.stream || '--');
      const group = Observatory.escapeHtml(_shortName(e.consumer_group || '--'));
      const groupFull = Observatory.escapeHtml(e.consumer_group || '');
      const retries = e.retry_count != null ? e.retry_count : '--';
      const reason = Observatory.escapeHtml(_truncate(e.failure_reason || '', 60));
      const reasonFull = Observatory.escapeHtml(e.failure_reason || '');
      const dlqId = Observatory.escapeHtml(e.dlq_id || '');

      return `<tr class="hover cursor-pointer dlq-row" data-dlq-id="${dlqId}">
        <td class="text-xs" title="${failedAtTitle}">${failedAt}</td>
        <td class="text-sm font-mono">${stream}</td>
        <td class="text-sm" title="${groupFull}">${group}</td>
        <td class="text-right font-mono-metric">${retries}</td>
        <td class="text-xs text-error max-w-xs truncate" title="${reasonFull}">${reason}</td>
        <td>
          <button class="btn btn-xs btn-warning btn-replay" data-dlq-id="${dlqId}" title="Replay">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3 h-3">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
            </svg>
          </button>
        </td>
      </tr>`;
    }).join('');

    // Bind row click for detail modal (exclude replay button clicks)
    $tbody.querySelectorAll('.dlq-row').forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.closest('.btn-replay')) return;
        const dlqId = row.getAttribute('data-dlq-id');
        showDlqDetail(dlqId);
      });
    });

    // Bind individual replay buttons
    $tbody.querySelectorAll('.btn-replay').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const dlqId = btn.getAttribute('data-dlq-id');
        replayOne(dlqId);
      });
    });

    _renderPagination('dlq-pagination', _dlqTotal, _dlqPage, function (p) {
      _dlqPage = p;
      fetchDLQ();
    });
  }

  // ---------------------------------------------------------------------------
  // Summary Cards
  // ---------------------------------------------------------------------------

  function updateSummaryFailed() {
    const $failed = document.getElementById('summary-failed');
    if ($failed) $failed.textContent = Observatory.fmt.number(_failedTotal);

    // Top failing handler (computed from current page — approximate)
    const handlerCounts = {};
    for (const t of _failedTraces) {
      const h = t.handler || 'unknown';
      handlerCounts[h] = (handlerCounts[h] || 0) + 1;
    }
    const topHandler = Object.entries(handlerCounts).sort((a, b) => b[1] - a[1])[0];
    const $topHandler = document.getElementById('summary-top-handler');
    const $topCount = document.getElementById('summary-top-handler-count');
    if ($topHandler) {
      if (topHandler) {
        $topHandler.textContent = _shortName(topHandler[0]);
        $topHandler.title = topHandler[0];
        if ($topCount) $topCount.textContent = topHandler[1] + ' failures';
      } else {
        $topHandler.textContent = '--';
        if ($topCount) $topCount.textContent = '';
      }
    }
  }

  function updateSummaryDLQ() {
    const $dlq = document.getElementById('summary-dlq');
    if ($dlq) $dlq.textContent = Observatory.fmt.number(_dlqTotal);

    // Oldest DLQ (from current page — the last item since sorted newest-first)
    const $oldest = document.getElementById('summary-oldest-dlq');
    const $oldestStream = document.getElementById('summary-oldest-dlq-stream');
    if ($oldest) {
      if (_dlqEntries.length > 0) {
        const last = _dlqEntries[_dlqEntries.length - 1];
        $oldest.textContent = last.failed_at ? Observatory.fmt.timeAgo(last.failed_at) : '--';
        if ($oldestStream) $oldestStream.textContent = last.stream || '';
      } else {
        $oldest.textContent = '--';
        if ($oldestStream) $oldestStream.textContent = '';
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Nav Badge
  // ---------------------------------------------------------------------------

  function updateNavBadge() {
    const badge = document.getElementById('nav-messages-badge');
    if (!badge) return;
    const total = _failedTotal + _dlqTotal;
    if (total > 0) {
      badge.textContent = total > 99 ? '99+' : total;
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
  }

  // ---------------------------------------------------------------------------
  // Trace Detail Modal
  // ---------------------------------------------------------------------------

  async function showTraceDetail(streamId) {
    const modal = document.getElementById('trace-detail-modal');
    const $meta = document.getElementById('trace-detail-meta');
    const $error = document.getElementById('trace-detail-error');
    const $payload = document.getElementById('trace-detail-payload');
    if (!modal || !$meta || !$error || !$payload) return;

    $meta.innerHTML = '<div class="col-span-2 text-center"><span class="loading loading-spinner loading-sm"></span></div>';
    $error.textContent = 'Loading...';
    $payload.textContent = 'Loading...';
    modal.showModal();

    try {
      const resp = await fetch(`/api/traces/${encodeURIComponent(streamId)}`);
      const data = await resp.json();

      if (data.error && !data.event) {
        $meta.innerHTML = `<div class="col-span-2 text-error">${Observatory.escapeHtml(data.error)}</div>`;
        $error.textContent = '';
        $payload.textContent = '';
        return;
      }

      const eventBadge = data.event === 'message.dlq'
        ? '<span class="badge badge-sm badge-warning">DLQ</span>'
        : '<span class="badge badge-sm badge-error">FAILED</span>';

      $meta.innerHTML = `
        <div class="font-semibold">Event</div><div>${eventBadge} ${Observatory.escapeHtml(data.event || '')}</div>
        <div class="font-semibold">Timestamp</div><div>${data.timestamp ? Observatory.fmt.datetime(data.timestamp) : '--'}</div>
        <div class="font-semibold">Handler</div><div class="font-mono text-xs">${Observatory.escapeHtml(data.handler || '--')}</div>
        <div class="font-semibold">Message Type</div><div class="font-mono text-xs">${Observatory.escapeHtml(data.message_type || '--')}</div>
        <div class="font-semibold">Message ID</div><div class="font-mono text-xs">${Observatory.escapeHtml(data.message_id || '--')}</div>
        <div class="font-semibold">Stream</div><div class="font-mono text-xs">${Observatory.escapeHtml(data.stream || '--')}</div>
        <div class="font-semibold">Domain</div><div>${Observatory.escapeHtml(data.domain || '--')}</div>
        <div class="font-semibold">Duration</div><div>${data.duration_ms != null ? Observatory.fmt.duration(data.duration_ms) : '--'}</div>
        <div class="font-semibold">Worker</div><div class="font-mono text-xs">${Observatory.escapeHtml(data.worker_id || '--')}</div>
        <div class="font-semibold">Stream ID</div><div class="font-mono text-xs">${Observatory.escapeHtml(data._stream_id || streamId)}</div>
      `;

      $error.textContent = data.error || '(no error message)';

      if (data.payload) {
        $payload.textContent = JSON.stringify(data.payload, null, 2);
      } else if (data.metadata && Object.keys(data.metadata).length > 0) {
        $payload.textContent = JSON.stringify(data.metadata, null, 2);
      } else {
        $payload.textContent = '(no payload)';
      }
    } catch (e) {
      $meta.innerHTML = `<div class="col-span-2 text-error">Failed to load: ${Observatory.escapeHtml(e.message)}</div>`;
      $error.textContent = '';
      $payload.textContent = '';
    }
  }

  // ---------------------------------------------------------------------------
  // DLQ Detail Modal
  // ---------------------------------------------------------------------------

  async function showDlqDetail(dlqId) {
    _selectedDlqId = dlqId;
    const modal = document.getElementById('dlq-detail-modal');
    const $meta = document.getElementById('dlq-detail-meta');
    const $payload = document.getElementById('dlq-detail-payload');
    if (!modal || !$meta || !$payload) return;

    $meta.innerHTML = '<div class="col-span-2 text-center"><span class="loading loading-spinner loading-sm"></span></div>';
    $payload.textContent = 'Loading...';
    modal.showModal();

    try {
      const resp = await fetch(`/api/dlq/${encodeURIComponent(dlqId)}`);
      const data = await resp.json();

      if (data.error) {
        $meta.innerHTML = `<div class="col-span-2 text-error">${Observatory.escapeHtml(data.error)}</div>`;
        $payload.textContent = '';
        return;
      }

      $meta.innerHTML = `
        <div class="font-semibold">DLQ ID</div><div class="font-mono text-xs">${Observatory.escapeHtml(data.dlq_id || '')}</div>
        <div class="font-semibold">Original ID</div><div class="font-mono text-xs">${Observatory.escapeHtml(data.original_id || '')}</div>
        <div class="font-semibold">Stream</div><div>${Observatory.escapeHtml(data.stream || '')}</div>
        <div class="font-semibold">Consumer Group</div><div>${Observatory.escapeHtml(data.consumer_group || '')}</div>
        <div class="font-semibold">DLQ Stream</div><div class="font-mono text-xs">${Observatory.escapeHtml(data.dlq_stream || '')}</div>
        <div class="font-semibold">Failed At</div><div>${data.failed_at ? Observatory.fmt.datetime(data.failed_at) : '--'}</div>
        <div class="font-semibold">Retry Count</div><div>${data.retry_count != null ? data.retry_count : '--'}</div>
        <div class="font-semibold">Failure Reason</div><div class="text-error">${Observatory.escapeHtml(data.failure_reason || '')}</div>
      `;

      $payload.textContent = data.payload
        ? JSON.stringify(data.payload, null, 2)
        : '(no payload)';
    } catch (e) {
      $meta.innerHTML = `<div class="col-span-2 text-error">Failed to load: ${Observatory.escapeHtml(e.message)}</div>`;
      $payload.textContent = '';
    }
  }

  // ---------------------------------------------------------------------------
  // DLQ Actions
  // ---------------------------------------------------------------------------

  async function replayOne(dlqId) {
    try {
      const resp = await fetch(`/api/dlq/${encodeURIComponent(dlqId)}/replay`, { method: 'POST' });
      const data = await resp.json();
      if (data.status === 'ok') {
        // Re-fetch current page from server
        await fetchDLQ();
      } else {
        alert('Replay failed: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Replay failed: ' + e.message);
    }
  }

  function _confirm(title, message) {
    return new Promise((resolve) => {
      const modal = document.getElementById('confirm-modal');
      const $title = document.getElementById('confirm-title');
      const $msg = document.getElementById('confirm-message');
      const $ok = document.getElementById('confirm-ok');
      const $cancel = document.getElementById('confirm-cancel');
      if (!modal) { resolve(false); return; }

      $title.textContent = title;
      $msg.textContent = message;
      modal.showModal();

      function cleanup() {
        $ok.removeEventListener('click', onOk);
        $cancel.removeEventListener('click', onCancel);
        modal.close();
      }
      function onOk() { cleanup(); resolve(true); }
      function onCancel() { cleanup(); resolve(false); }

      $ok.addEventListener('click', onOk);
      $cancel.addEventListener('click', onCancel);
    });
  }

  async function replayAll() {
    if (_dlqTotal === 0) return;
    const ok = await _confirm('Replay All', `Replay all ${_dlqTotal} DLQ messages back to their original streams?`);
    if (!ok) return;

    // Collect streams from current page (best effort)
    const streams = new Set(_dlqEntries.map(e => e.stream).filter(Boolean));
    for (const stream of streams) {
      try {
        await fetch(`/api/dlq/replay-all?subscription=${encodeURIComponent(stream)}`, { method: 'POST' });
      } catch (e) {
        console.warn('Replay-all failed for', stream, e.message);
      }
    }

    _dlqPage = 1;
    await fetchDLQ();
  }

  async function purgeAll() {
    if (_dlqTotal === 0) return;
    const ok = await _confirm('Purge All', `Permanently delete all ${_dlqTotal} DLQ messages? This cannot be undone.`);
    if (!ok) return;

    const streams = new Set(_dlqEntries.map(e => e.stream).filter(Boolean));
    for (const stream of streams) {
      try {
        await fetch(`/api/dlq?subscription=${encodeURIComponent(stream)}`, { method: 'DELETE' });
      } catch (e) {
        console.warn('Purge failed for', stream, e.message);
      }
    }

    _dlqPage = 1;
    await fetchDLQ();
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _truncate(str, maxLen) {
    if (str.length <= maxLen) return str;
    return str.slice(0, maxLen) + '...';
  }

  function _shortName(qualname) {
    if (!qualname) return '';
    const parts = qualname.split('.');
    return parts[parts.length - 1];
  }

  // ---------------------------------------------------------------------------
  // Pagination
  // ---------------------------------------------------------------------------

  function _renderPagination(containerId, totalItems, currentPage, onPageChange) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const totalPages = Math.ceil(totalItems / PAGE_SIZE);

    if (totalPages <= 1) {
      container.innerHTML = '';
      return;
    }

    const startItem = (currentPage - 1) * PAGE_SIZE + 1;
    const endItem = Math.min(currentPage * PAGE_SIZE, totalItems);

    container.innerHTML =
      '<div class="flex items-center justify-between mt-3 text-sm">' +
        '<span class="text-base-content/50">' +
          'Showing ' + startItem + '\u2013' + endItem + ' of ' + totalItems +
        '</span>' +
        '<div class="join">' +
          '<button class="join-item btn btn-xs' + (currentPage <= 1 ? ' btn-disabled' : '') + '" data-page="prev">' +
            '\u00ab Prev' +
          '</button>' +
          '<button class="join-item btn btn-xs btn-active no-animation">Page ' + currentPage + ' / ' + totalPages + '</button>' +
          '<button class="join-item btn btn-xs' + (currentPage >= totalPages ? ' btn-disabled' : '') + '" data-page="next">' +
            'Next \u00bb' +
          '</button>' +
        '</div>' +
      '</div>';

    container.querySelector('[data-page="prev"]').addEventListener('click', function () {
      if (currentPage > 1) onPageChange(currentPage - 1);
    });
    container.querySelector('[data-page="next"]').addEventListener('click', function () {
      if (currentPage < totalPages) onPageChange(currentPage + 1);
    });
  }

  // ---------------------------------------------------------------------------
  // Tab Switching
  // ---------------------------------------------------------------------------

  function switchTab(tab) {
    _tab = tab;
    const $tabs = document.querySelectorAll('[role="tablist"] [role="tab"]');
    $tabs.forEach(t => {
      t.classList.toggle('tab-active', t.getAttribute('data-tab') === tab);
    });

    $panelFailed = document.getElementById('panel-failed');
    $panelDlq = document.getElementById('panel-dlq');
    if ($panelFailed) $panelFailed.classList.toggle('hidden', tab !== 'failed');
    if ($panelDlq) $panelDlq.classList.toggle('hidden', tab !== 'dlq');

    _updateURL();
  }

  // ---------------------------------------------------------------------------
  // Window Switching
  // ---------------------------------------------------------------------------

  function setLocalWindow(w) {
    _window = w;

    // Update button styles
    document.querySelectorAll('#msg-window-selector button').forEach(btn => {
      if (btn.dataset.window === w) {
        btn.className = 'join-item btn btn-xs btn-primary';
      } else {
        btn.className = 'join-item btn btn-xs btn-ghost';
      }
    });

    // Show/hide custom range inputs
    const $customRange = document.getElementById('custom-range');
    if ($customRange) {
      $customRange.classList.toggle('hidden', w !== 'custom');
    }

    if (w !== 'custom') {
      _customStart = null;
      _customEnd = null;
      _failedPage = 1;
      fetchFailed();
    }

    _updateURL();
  }

  // ---------------------------------------------------------------------------
  // Deep Linking
  // ---------------------------------------------------------------------------

  function _readURL() {
    const params = new URLSearchParams(window.location.search);
    if (params.has('tab')) _tab = params.get('tab');
    if (params.has('window')) _window = params.get('window');
    if (params.has('q')) _search = params.get('q');
  }

  function _updateURL() {
    const params = new URLSearchParams();
    if (_tab !== 'failed') params.set('tab', _tab);
    if (_window !== '5m') params.set('window', _window);
    if (_search) params.set('q', _search);
    const qs = params.toString();
    const url = window.location.pathname + (qs ? '?' + qs : '');
    history.replaceState(null, '', url);
  }

  // ---------------------------------------------------------------------------
  // Event Binding
  // ---------------------------------------------------------------------------

  function _bindEvents() {
    // Tab clicks
    document.querySelectorAll('[role="tablist"] [role="tab"]').forEach(tab => {
      tab.addEventListener('click', () => {
        switchTab(tab.getAttribute('data-tab'));
      });
    });

    // Search — triggers server re-fetch with page reset
    $search = document.getElementById('msg-search');
    if ($search) {
      let debounceTimer;
      $search.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          _search = $search.value.trim();
          _failedPage = 1;
          _dlqPage = 1;
          _updateURL();
          // Note: search is still client-side for the failed tab since the
          // API doesn't have a search param. For DLQ it's also client-side.
          // With server-side pagination, re-fetch to get fresh data.
          fetchFailed();
          fetchDLQ();
        }, 300);
      });
      if (_search) $search.value = _search;
    }

    // Window selector buttons
    document.querySelectorAll('#msg-window-selector button').forEach(btn => {
      btn.addEventListener('click', () => {
        setLocalWindow(btn.dataset.window);
      });
    });

    // Custom range apply
    const $applyRange = document.getElementById('btn-apply-range');
    if ($applyRange) {
      $applyRange.addEventListener('click', () => {
        const start = document.getElementById('range-start');
        const end = document.getElementById('range-end');
        if (start && end && start.value && end.value) {
          _customStart = new Date(start.value).toISOString();
          _customEnd = new Date(end.value).toISOString();
          _failedPage = 1;
          fetchFailed();
        }
      });
    }

    // DLQ bulk actions
    const $replayAll = document.getElementById('btn-replay-all');
    if ($replayAll) $replayAll.addEventListener('click', replayAll);

    const $purgeAll = document.getElementById('btn-purge-all');
    if ($purgeAll) $purgeAll.addEventListener('click', purgeAll);

    // Modal replay button
    const $replayOne = document.getElementById('btn-replay-one');
    if ($replayOne) {
      $replayOne.addEventListener('click', () => {
        if (_selectedDlqId) {
          const modal = document.getElementById('dlq-detail-modal');
          if (modal) modal.close();
          replayOne(_selectedDlqId);
        }
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  function init() {
    _readURL();

    $panelFailed = document.getElementById('panel-failed');
    $panelDlq = document.getElementById('panel-dlq');

    // Sync tab state from URL
    switchTab(_tab);

    // Sync window buttons from URL
    if (_window !== '5m') {
      setLocalWindow(_window);
    }

    _bindEvents();

    // Initial data fetch
    fetchFailed();
    fetchDLQ();

    // Self-managed refresh intervals (NOT Observatory.poller which uses the
    // global window and races with our local _window state).
    setInterval(function () {
      if (!Observatory.state.paused) fetchFailed();
    }, 10000);
    setInterval(function () {
      if (!Observatory.state.paused) fetchDLQ();
    }, 15000);
  }

  // Wait for Observatory core
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      setTimeout(init, 100);
    });
  } else {
    setTimeout(init, 100);
  }
})();
