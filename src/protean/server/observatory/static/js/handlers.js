/**
 * Handlers View Module
 *
 * Fetches handler data from /api/handlers, renders the table with
 * tabs, search, sorting, sparklines, and an expandable detail panel.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let _handlers = [];
  let _currentTab = 'all';
  let _searchQuery = '';
  let _statusFilter = 'all';
  let _sortKey = 'name';
  let _sortAsc = true;
  let _selectedHandler = null;

  // DOM refs (cached after DOMContentLoaded)
  let $tbody, $tabs, $search, $statusFilter, $detailPanel;

  // ---------------------------------------------------------------------------
  // Filtering & Sorting
  // ---------------------------------------------------------------------------

  function _filtered() {
    return _handlers.filter(h => {
      // Tab filter
      if (_currentTab !== 'all' && h.type !== _currentTab) return false;

      // Status filter
      if (_statusFilter !== 'all') {
        const status = (h.subscription && h.subscription.status) || 'unknown';
        if (status !== _statusFilter) return false;
      }

      // Search filter (name, aggregate, stream categories)
      if (_searchQuery) {
        const q = _searchQuery.toLowerCase();
        const name = (h.name || '').toLowerCase();
        const agg = (h.aggregate || '').toLowerCase();
        const streams = (h.stream_categories || []).join(' ').toLowerCase();
        if (!name.includes(q) && !agg.includes(q) && !streams.includes(q)) {
          return false;
        }
      }

      return true;
    });
  }

  function _sorted(list) {
    const copy = list.slice();
    copy.sort((a, b) => {
      let va, vb;
      switch (_sortKey) {
        case 'name':
          va = (a.name || '').toLowerCase();
          vb = (b.name || '').toLowerCase();
          return _sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        case 'throughput':
          va = (a.metrics && a.metrics.processed) || 0;
          vb = (b.metrics && b.metrics.processed) || 0;
          break;
        case 'latency':
          va = (a.metrics && a.metrics.avg_latency_ms) || 0;
          vb = (b.metrics && b.metrics.avg_latency_ms) || 0;
          break;
        case 'lag':
          va = (a.subscription && a.subscription.lag) || 0;
          vb = (b.subscription && b.subscription.lag) || 0;
          break;
        case 'errors':
          va = (a.metrics && a.metrics.failed) || 0;
          vb = (b.metrics && b.metrics.failed) || 0;
          break;
        case 'dlq':
          va = (a.subscription && a.subscription.dlq_depth) || 0;
          vb = (b.subscription && b.subscription.dlq_depth) || 0;
          break;
        default:
          va = 0; vb = 0;
      }
      return _sortAsc ? va - vb : vb - va;
    });
    return copy;
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  function _statusDot(handler) {
    const sub = handler.subscription;
    if (!sub) return '<span class="badge badge-xs badge-ghost" title="Unknown">?</span>';
    const status = sub.status || 'unknown';
    if (status === 'ok') return '<span class="badge badge-xs badge-success" title="Healthy"></span>';
    if (status === 'lagging') return '<span class="badge badge-xs badge-warning" title="Lagging"></span>';
    return '<span class="badge badge-xs badge-ghost" title="Unknown">?</span>';
  }

  function _typeBadge(type) {
    const labels = {
      'command_handler': 'CMD',
      'event_handler': 'EVT',
      'projector': 'PRJ',
      'subscriber': 'SUB',
      'process_manager': 'PM',
    };
    const colors = {
      'command_handler': 'badge-primary',
      'event_handler': 'badge-secondary',
      'projector': 'badge-accent',
      'subscriber': 'badge-info',
      'process_manager': 'badge-warning',
    };
    const label = labels[type] || type;
    const color = colors[type] || 'badge-ghost';
    return `<span class="badge badge-xs ${color}">${Observatory.escapeHtml(label)}</span>`;
  }

  function _renderTable() {
    if (!$tbody) return;
    const list = _sorted(_filtered());

    if (list.length === 0) {
      $tbody.innerHTML = `<tr><td colspan="10" class="text-center text-base-content/50 py-8">
        ${_handlers.length === 0 ? 'No handlers registered.' : 'No handlers match the current filters.'}
      </td></tr>`;
      return;
    }

    const rows = list.map(h => {
      const m = h.metrics || {};
      const s = h.subscription || {};
      const processed = m.processed != null ? Observatory.fmt.number(m.processed) : '--';
      const latency = m.avg_latency_ms != null ? Observatory.fmt.duration(m.avg_latency_ms) : '--';
      const lag = s.lag != null ? Observatory.fmt.number(s.lag) : '--';
      const errors = m.failed != null ? Observatory.fmt.number(m.failed) : '--';
      const dlq = s.dlq_depth != null ? Observatory.fmt.number(s.dlq_depth) : '--';
      const errorClass = (m.failed && m.failed > 0) ? 'text-error' : '';
      const dlqClass = (s.dlq_depth && s.dlq_depth > 0) ? 'text-error' : '';
      const lagClass = (s.lag && s.lag > 0) ? 'text-warning' : '';
      const name = Observatory.escapeHtml(h.name);
      const agg = h.aggregate ? Observatory.escapeHtml(h.aggregate) : '<span class="text-base-content/30">--</span>';

      return `<tr class="hover cursor-pointer handler-row" data-handler="${Observatory.escapeHtml(h.name)}">
        <td>${_statusDot(h)}</td>
        <td class="font-medium">${name}</td>
        <td>${_typeBadge(h.type)}</td>
        <td class="text-sm">${agg}</td>
        <td class="text-right font-mono-metric">${processed}</td>
        <td class="text-right font-mono-metric">${latency}</td>
        <td class="text-right font-mono-metric ${lagClass}">${lag}</td>
        <td class="text-right font-mono-metric ${errorClass}">${errors}</td>
        <td class="text-right font-mono-metric ${dlqClass}">${dlq}</td>
        <td><span class="sparkline-container" id="spark-${Observatory.escapeHtml(h.name)}"></span></td>
      </tr>`;
    });

    $tbody.innerHTML = rows.join('');

    // Render sparklines
    if (typeof Charts !== 'undefined' && Charts.sparkline) {
      for (const h of list) {
        if (h.metrics && h.metrics.throughput) {
          const container = document.getElementById(`spark-${h.name}`);
          if (container) {
            Charts.sparkline(container, h.metrics.throughput, {
              width: 80, height: 20, color: '#3b82f6',
            });
          }
        }
      }
    }

    // Attach row click handlers
    $tbody.querySelectorAll('.handler-row').forEach(row => {
      row.addEventListener('click', () => {
        const name = row.getAttribute('data-handler');
        _showDetail(name);
      });
    });
  }

  function _updateSummary(summary) {
    const el = (id, val) => {
      const e = document.getElementById(id);
      if (e) e.textContent = val;
    };
    el('summary-total', summary.total != null ? summary.total : '--');
    el('summary-healthy', summary.healthy != null ? summary.healthy : '--');
    el('summary-lagging', summary.lagging != null ? summary.lagging : '--');
    el('summary-error-rate', summary.error_rate != null ? summary.error_rate + '%' : '--');
  }

  function _updateTabCounts() {
    const counts = { all: _handlers.length };
    for (const h of _handlers) {
      counts[h.type] = (counts[h.type] || 0) + 1;
    }
    for (const [type, count] of Object.entries(counts)) {
      const el = document.getElementById(`tab-count-${type}`);
      if (el) el.textContent = count;
    }
  }

  // ---------------------------------------------------------------------------
  // Detail Panel
  // ---------------------------------------------------------------------------

  async function _showDetail(name) {
    _selectedHandler = name;
    if (!$detailPanel) return;

    $detailPanel.classList.remove('hidden');

    // Fill identity from cached data
    const handler = _handlers.find(h => h.name === name);
    if (handler) {
      document.getElementById('detail-name').textContent = handler.name;
      document.getElementById('detail-type').textContent = handler.type;
      document.getElementById('detail-qualname').textContent = handler.qualname || '--';
      document.getElementById('detail-aggregate').textContent = handler.aggregate || '--';
      document.getElementById('detail-streams').textContent =
        (handler.stream_categories || []).join(', ') || '--';
      document.getElementById('detail-domain').textContent = handler.domain || '--';

      // Handled messages as badges
      const $msgs = document.getElementById('detail-messages');
      if (handler.handled_messages && handler.handled_messages.length > 0) {
        $msgs.innerHTML = handler.handled_messages
          .map(m => `<span class="badge badge-sm badge-outline">${Observatory.escapeHtml(m)}</span>`)
          .join('');
      } else {
        $msgs.innerHTML = '<span class="text-sm text-base-content/50">None</span>';
      }
    }

    // Fetch detail with recent messages
    try {
      const w = Observatory.state.window;
      const data = await Observatory.fetchJSON(`/api/handlers/${encodeURIComponent(name)}?window=${w}`);
      if (data && data.handler) {
        _renderRecentMessages(data.handler.recent_messages || []);
      }
    } catch (e) {
      console.warn('Failed to fetch handler detail:', e.message);
      _renderRecentMessages([]);
    }
  }

  function _renderRecentMessages(messages) {
    const $rtbody = document.getElementById('detail-recent-tbody');
    if (!$rtbody) return;

    if (messages.length === 0) {
      $rtbody.innerHTML = `<tr><td colspan="5" class="text-center text-base-content/50 py-4">
        No recent messages.
      </td></tr>`;
      return;
    }

    $rtbody.innerHTML = messages.map(m => {
      const event = Observatory.escapeHtml(m.event || '--');
      const msgType = Observatory.escapeHtml(m.message_type || '--');
      const duration = m.duration_ms != null ? Observatory.fmt.duration(m.duration_ms) : '--';
      const stream = Observatory.escapeHtml(m.stream || '--');
      const ts = m.timestamp ? Observatory.fmt.timeAgo(m.timestamp) : '--';
      const eventClass = (m.event === 'handler.failed' || m.event === 'message.dlq') ? 'text-error' : '';

      return `<tr>
        <td class="${eventClass}">${event}</td>
        <td>${msgType}</td>
        <td class="text-right font-mono-metric">${duration}</td>
        <td>${stream}</td>
        <td class="text-xs text-base-content/60">${ts}</td>
      </tr>`;
    }).join('');
  }

  function _closeDetail() {
    _selectedHandler = null;
    if ($detailPanel) $detailPanel.classList.add('hidden');
  }

  // ---------------------------------------------------------------------------
  // Data Loading
  // ---------------------------------------------------------------------------

  function _onDataLoaded(data) {
    if (!data) return;

    _handlers = data.handlers || [];
    if (data.summary) _updateSummary(data.summary);
    _updateTabCounts();
    _renderTable();
  }

  // ---------------------------------------------------------------------------
  // Deep Linking
  // ---------------------------------------------------------------------------

  function _readURL() {
    const params = new URLSearchParams(window.location.search);
    if (params.has('type')) _currentTab = params.get('type');
    if (params.has('status')) _statusFilter = params.get('status');
    if (params.has('q')) _searchQuery = params.get('q');
    if (params.has('sort')) _sortKey = params.get('sort');
    if (params.has('asc')) _sortAsc = params.get('asc') !== '0';
  }

  function _updateURL() {
    const params = new URLSearchParams();
    if (_currentTab !== 'all') params.set('type', _currentTab);
    if (_statusFilter !== 'all') params.set('status', _statusFilter);
    if (_searchQuery) params.set('q', _searchQuery);
    if (_sortKey !== 'name') params.set('sort', _sortKey);
    if (!_sortAsc) params.set('asc', '0');
    const qs = params.toString();
    const url = window.location.pathname + (qs ? '?' + qs : '');
    history.replaceState(null, '', url);
  }

  function _syncUIFromState() {
    // Sync tab UI
    if ($tabs) {
      $tabs.querySelectorAll('[role="tab"]').forEach(t => {
        t.classList.toggle('tab-active', t.getAttribute('data-type') === _currentTab);
      });
    }
    // Sync search input
    if ($search && _searchQuery) $search.value = _searchQuery;
    // Sync status filter
    if ($statusFilter) $statusFilter.value = _statusFilter;
  }

  // ---------------------------------------------------------------------------
  // Event Binding
  // ---------------------------------------------------------------------------

  function _bindEvents() {
    // Tab clicks
    if ($tabs) {
      $tabs.addEventListener('click', (e) => {
        const tab = e.target.closest('[data-type]');
        if (!tab) return;
        _currentTab = tab.getAttribute('data-type');
        // Update active state
        $tabs.querySelectorAll('[role="tab"]').forEach(t => t.classList.remove('tab-active'));
        tab.classList.add('tab-active');
        _updateURL();
        _renderTable();
      });
    }

    // Search input
    if ($search) {
      let debounceTimer;
      $search.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          _searchQuery = $search.value.trim();
          _updateURL();
          _renderTable();
        }, 200);
      });
    }

    // Status filter
    if ($statusFilter) {
      $statusFilter.addEventListener('change', () => {
        _statusFilter = $statusFilter.value;
        _updateURL();
        _renderTable();
      });
    }

    // Column sort headers
    document.querySelectorAll('[data-sort]').forEach(th => {
      th.addEventListener('click', () => {
        const key = th.getAttribute('data-sort');
        if (_sortKey === key) {
          _sortAsc = !_sortAsc;
        } else {
          _sortKey = key;
          _sortAsc = true;
        }
        _updateURL();
        _renderTable();
      });
    });

    // Detail close button
    const $closeBtn = document.getElementById('detail-close');
    if ($closeBtn) {
      $closeBtn.addEventListener('click', _closeDetail);
    }

    // CSV export
    const $exportBtn = document.getElementById('export-csv');
    if ($exportBtn) {
      $exportBtn.addEventListener('click', _exportCSV);
    }
  }

  function _exportCSV() {
    const list = _sorted(_filtered());
    const headers = ['Name', 'Type', 'Aggregate', 'Processed', 'Avg Latency (ms)', 'Lag', 'Errors', 'DLQ', 'Status'];
    const rows = list.map(h => {
      const m = h.metrics || {};
      const s = h.subscription || {};
      return [
        h.name || '',
        h.type || '',
        h.aggregate || '',
        m.processed != null ? m.processed : '',
        m.avg_latency_ms != null ? m.avg_latency_ms : '',
        s.lag != null ? s.lag : '',
        m.failed != null ? m.failed : '',
        s.dlq_depth != null ? s.dlq_depth : '',
        (s.status || 'unknown'),
      ];
    });
    Observatory.exportCSV('handlers.csv', headers, rows);
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  function init() {
    $tbody = document.getElementById('handlers-tbody');
    $tabs = document.getElementById('handler-tabs');
    $search = document.getElementById('handler-search');
    $statusFilter = document.getElementById('status-filter');
    $detailPanel = document.getElementById('handler-detail');

    // Read URL params for deep linking
    _readURL();
    _syncUIFromState();
    _bindEvents();

    // Register poller for handler data
    const w = Observatory.state.window;
    Observatory.poller.register('handlers', `/api/handlers?window=${w}`, 10000, _onDataLoaded);
  }

  // Wait for DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
