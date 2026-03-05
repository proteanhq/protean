/**
 * Event Store View Module
 *
 * Fetches aggregate stream data from /api/eventstore/streams, renders the
 * stream table, and outbox status.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let _aggregates = [];
  let _searchQuery = '';
  let _sortKey = 'name';
  let _sortAsc = true;

  // DOM refs
  let $tbody, $search;

  // ---------------------------------------------------------------------------
  // Filtering & Sorting
  // ---------------------------------------------------------------------------

  function _filtered() {
    return _aggregates.filter(a => {
      if (_searchQuery) {
        const q = _searchQuery.toLowerCase();
        const name = (a.name || '').toLowerCase();
        const stream = (a.stream_category || '').toLowerCase();
        const domain = (a.domain || '').toLowerCase();
        if (!name.includes(q) && !stream.includes(q) && !domain.includes(q)) return false;
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
        case 'instances':
          va = a.instance_count || 0;
          vb = b.instance_count || 0;
          break;
        case 'head_position':
          va = a.head_position || 0;
          vb = b.head_position || 0;
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

  function _renderTable() {
    if (!$tbody) return;
    const list = _sorted(_filtered());

    if (list.length === 0) {
      $tbody.innerHTML = `<tr><td colspan="6" class="text-center text-base-content/50 py-8">
        ${_aggregates.length === 0 ? 'No aggregates registered.' : 'No aggregates match the current filter.'}
      </td></tr>`;
      return;
    }

    const rows = list.map(a => {
      const name = Observatory.escapeHtml(a.name);
      const instances = a.instance_count != null ? Observatory.fmt.number(a.instance_count) : '--';
      const headPos = a.head_position != null ? a.head_position.toLocaleString() : '--';
      const stream = Observatory.escapeHtml(a.stream_category || '--');
      const domain = Observatory.escapeHtml(a.domain || '--');
      const esBadge = a.is_event_sourced
        ? '<span class="badge badge-xs badge-primary">ES</span>'
        : '<span class="badge badge-xs badge-ghost">No</span>';

      return `<tr class="hover">
        <td class="font-medium">${name}</td>
        <td class="text-center">${esBadge}</td>
        <td class="text-right font-mono-metric">${instances}</td>
        <td class="text-right font-mono-metric">${headPos}</td>
        <td class="text-sm text-base-content/60 font-mono">${stream}</td>
        <td class="text-sm text-base-content/60">${domain}</td>
      </tr>`;
    });

    $tbody.innerHTML = rows.join('');
  }

  function _updateSummary(summary, outbox) {
    const el = (id, val) => {
      const e = document.getElementById(id);
      if (e) e.textContent = val;
    };
    el('summary-total-aggregates', summary.total_aggregates != null ? summary.total_aggregates : '--');
    el('summary-event-sourced', summary.total_event_sourced != null ? summary.total_event_sourced : '--');
    el('summary-total-instances', summary.total_instances != null ? summary.total_instances : '--');

    // Sum outbox pending across domains
    let totalPending = 0;
    if (outbox) {
      for (const domainName in outbox) {
        const d = outbox[domainName];
        if (d && d.counts) {
          totalPending += (d.counts.pending || 0) + (d.counts.processing || 0);
        }
      }
    }
    el('summary-outbox-pending', totalPending);
  }

  function _renderOutbox(outbox) {
    const $tbody = document.getElementById('outbox-tbody');
    if (!$tbody) return;

    if (!outbox || Object.keys(outbox).length === 0) {
      $tbody.innerHTML = '<tr><td colspan="6" class="text-center text-base-content/50 py-4">No outbox data available.</td></tr>';
      return;
    }

    const rows = Object.entries(outbox).map(([domainName, data]) => {
      if (data.status === 'error') {
        return `<tr><td class="font-medium">${Observatory.escapeHtml(domainName)}</td>
          <td colspan="5" class="text-error text-sm">${Observatory.escapeHtml(data.error || 'Error')}</td></tr>`;
      }
      const c = data.counts || {};
      const failed = c.failed || 0;
      const abandoned = c.abandoned || 0;
      return `<tr class="hover">
        <td class="font-medium">${Observatory.escapeHtml(domainName)}</td>
        <td class="text-right font-mono-metric">${c.pending || 0}</td>
        <td class="text-right font-mono-metric">${c.processing || 0}</td>
        <td class="text-right font-mono-metric">${c.published || 0}</td>
        <td class="text-right font-mono-metric ${failed > 0 ? 'text-error font-semibold' : ''}">${failed}</td>
        <td class="text-right font-mono-metric ${abandoned > 0 ? 'text-warning font-semibold' : ''}">${abandoned}</td>
      </tr>`;
    });

    $tbody.innerHTML = rows.join('');
  }

  // ---------------------------------------------------------------------------
  // Data Loading
  // ---------------------------------------------------------------------------

  function _onDataLoaded(data) {
    if (!data) return;
    _aggregates = data.aggregates || [];
    if (data.summary) _updateSummary(data.summary, data.outbox);
    if (data.outbox) _renderOutbox(data.outbox);
    _renderTable();
  }

  // ---------------------------------------------------------------------------
  // Event Binding
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Deep Linking
  // ---------------------------------------------------------------------------

  function _readURL() {
    const params = new URLSearchParams(window.location.search);
    if (params.has('q')) _searchQuery = params.get('q');
    if (params.has('sort')) _sortKey = params.get('sort');
    if (params.has('asc')) _sortAsc = params.get('asc') !== '0';
  }

  function _updateURL() {
    const params = new URLSearchParams();
    if (_searchQuery) params.set('q', _searchQuery);
    if (_sortKey !== 'name') params.set('sort', _sortKey);
    if (!_sortAsc) params.set('asc', '0');
    const qs = params.toString();
    const url = window.location.pathname + (qs ? '?' + qs : '');
    history.replaceState(null, '', url);
  }

  function _syncUIFromState() {
    if ($search && _searchQuery) $search.value = _searchQuery;
  }

  // ---------------------------------------------------------------------------
  // Event Binding
  // ---------------------------------------------------------------------------

  function _bindEvents() {
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

    // CSV export
    const $exportBtn = document.getElementById('export-csv');
    if ($exportBtn) {
      $exportBtn.addEventListener('click', _exportCSV);
    }
  }

  function _exportCSV() {
    const list = _sorted(_filtered());
    const headers = ['Name', 'Event Sourced', 'Instances', 'Head Position', 'Stream Category', 'Domain'];
    const rows = list.map(a => [
      a.name || '',
      a.is_event_sourced ? 'Yes' : 'No',
      a.instance_count != null ? a.instance_count : '',
      a.head_position != null ? a.head_position : '',
      a.stream_category || '',
      a.domain || '',
    ]);
    Observatory.exportCSV('eventstore.csv', headers, rows);
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  function init() {
    $tbody = document.getElementById('streams-tbody');
    $search = document.getElementById('stream-search');

    // Read URL params for deep linking
    _readURL();
    _syncUIFromState();
    _bindEvents();

    // Register poller for event store data (15s — stream stats change slowly)
    Observatory.poller.register('eventstore', '/api/eventstore/streams', 15000, _onDataLoaded);
  }

  // Wait for DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
