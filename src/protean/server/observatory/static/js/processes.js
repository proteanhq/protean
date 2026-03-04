/**
 * Processes View Module
 *
 * Fetches process manager data from /api/processes, renders the summary table,
 * and provides an instance explorer for individual PM types.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let _processes = [];
  let _searchQuery = '';
  let _statusFilter = 'all';
  let _sortKey = 'name';
  let _sortAsc = true;
  let _selectedPM = null;

  // DOM refs
  let $tbody, $search, $statusFilter, $instanceExplorer;

  // ---------------------------------------------------------------------------
  // Filtering & Sorting
  // ---------------------------------------------------------------------------

  function _filtered() {
    return _processes.filter(p => {
      // Status filter
      if (_statusFilter !== 'all') {
        const status = (p.subscription && p.subscription.status) || 'unknown';
        if (status !== _statusFilter) return false;
      }

      // Search filter
      if (_searchQuery) {
        const q = _searchQuery.toLowerCase();
        const name = (p.name || '').toLowerCase();
        const streams = (p.stream_categories || []).join(' ').toLowerCase();
        if (!name.includes(q) && !streams.includes(q)) return false;
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
        case 'processed':
          va = (a.metrics && a.metrics.processed) || 0;
          vb = (b.metrics && b.metrics.processed) || 0;
          break;
        case 'errors':
          va = (a.metrics && a.metrics.failed) || 0;
          vb = (b.metrics && b.metrics.failed) || 0;
          break;
        case 'latency':
          va = (a.metrics && a.metrics.avg_latency_ms) || 0;
          vb = (b.metrics && b.metrics.avg_latency_ms) || 0;
          break;
        case 'lag':
          va = (a.subscription && a.subscription.lag) || 0;
          vb = (b.subscription && b.subscription.lag) || 0;
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

  function _statusDot(pm) {
    const sub = pm.subscription;
    if (!sub) return '<span class="badge badge-xs badge-ghost" title="Unknown">?</span>';
    const status = sub.status || 'unknown';
    if (status === 'ok') return '<span class="badge badge-xs badge-success" title="Healthy"></span>';
    if (status === 'lagging') return '<span class="badge badge-xs badge-warning" title="Lagging"></span>';
    return '<span class="badge badge-xs badge-ghost" title="Unknown">?</span>';
  }

  function _renderTable() {
    if (!$tbody) return;
    const list = _sorted(_filtered());

    if (list.length === 0) {
      $tbody.innerHTML = `<tr><td colspan="9" class="text-center text-base-content/50 py-8">
        ${_processes.length === 0 ? 'No process managers registered.' : 'No process managers match the current filters.'}
      </td></tr>`;
      return;
    }

    const rows = list.map(p => {
      const m = p.metrics || {};
      const s = p.subscription || {};
      const instances = p.instance_count != null ? Observatory.fmt.number(p.instance_count) : '--';
      const processed = m.processed != null ? Observatory.fmt.number(m.processed) : '--';
      const errors = m.failed != null ? Observatory.fmt.number(m.failed) : '--';
      const latency = m.avg_latency_ms != null ? Observatory.fmt.duration(m.avg_latency_ms) : '--';
      const lag = s.lag != null ? Observatory.fmt.number(s.lag) : '--';
      const dlq = s.dlq_depth != null ? Observatory.fmt.number(s.dlq_depth) : '--';
      const errorClass = (m.failed && m.failed > 0) ? 'text-error' : '';
      const lagClass = (s.lag && s.lag > 0) ? 'text-warning' : '';
      const dlqClass = (s.dlq_depth && s.dlq_depth > 0) ? 'text-error' : '';
      const streams = (p.stream_categories || []).join(', ') || '--';
      const name = Observatory.escapeHtml(p.name);

      return `<tr class="hover cursor-pointer pm-row" data-pm="${Observatory.escapeHtml(p.name)}">
        <td>${_statusDot(p)}</td>
        <td class="font-medium">${name}</td>
        <td class="text-right font-mono-metric">${instances}</td>
        <td class="text-right font-mono-metric">${processed}</td>
        <td class="text-right font-mono-metric ${errorClass}">${errors}</td>
        <td class="text-right font-mono-metric">${latency}</td>
        <td class="text-right font-mono-metric ${lagClass}">${lag}</td>
        <td class="text-right font-mono-metric ${dlqClass}">${dlq}</td>
        <td class="text-sm text-base-content/60">${Observatory.escapeHtml(streams)}</td>
      </tr>`;
    });

    $tbody.innerHTML = rows.join('');

    // Attach row click handlers
    $tbody.querySelectorAll('.pm-row').forEach(row => {
      row.addEventListener('click', () => {
        const name = row.getAttribute('data-pm');
        _showInstances(name);
      });
    });
  }

  function _updateSummary(summary) {
    const el = (id, val) => {
      const e = document.getElementById(id);
      if (e) e.textContent = val;
    };
    el('summary-total', summary.total != null ? summary.total : '--');
    el('summary-instances', summary.total_instances != null ? summary.total_instances : '--');
    el('summary-healthy', summary.healthy != null ? summary.healthy : '--');
    el('summary-lagging', summary.lagging != null ? summary.lagging : '--');
  }

  // ---------------------------------------------------------------------------
  // Instance Explorer
  // ---------------------------------------------------------------------------

  async function _showInstances(name) {
    _selectedPM = name;
    if (!$instanceExplorer) return;

    $instanceExplorer.classList.remove('hidden');
    document.getElementById('explorer-pm-name').textContent = name;

    const $itbody = document.getElementById('instances-tbody');
    if ($itbody) {
      $itbody.innerHTML = '<tr><td colspan="7" class="text-center text-base-content/50 py-4">' +
        '<span class="loading loading-spinner loading-sm"></span> Loading instances...</td></tr>';
    }

    try {
      const data = await Observatory.fetchJSON(`/api/processes/${encodeURIComponent(name)}/instances`);
      if (data && data.instances) {
        _renderInstances(data.instances);
      }
    } catch (e) {
      console.warn('Failed to fetch instances:', e.message);
      _renderInstances([]);
    }
  }

  function _renderInstances(instances) {
    const $itbody = document.getElementById('instances-tbody');
    if (!$itbody) return;

    if (instances.length === 0) {
      $itbody.innerHTML = '<tr><td colspan="7" class="text-center text-base-content/50 py-4">No instances found.</td></tr>';
      return;
    }

    $itbody.innerHTML = instances.map(inst => {
      const id = Observatory.escapeHtml(inst.instance_id || '--');
      const version = inst.version != null ? inst.version : '--';
      const status = inst.is_complete
        ? '<span class="badge badge-xs badge-success">Complete</span>'
        : '<span class="badge badge-xs badge-info">Active</span>';
      const state = inst.state
        ? Observatory.escapeHtml(JSON.stringify(inst.state).substring(0, 80))
        : '--';
      const started = inst.started_at ? Observatory.fmt.timeAgo(inst.started_at) : '--';
      const lastActivity = inst.last_activity ? Observatory.fmt.timeAgo(inst.last_activity) : '--';
      const events = inst.event_count != null ? inst.event_count : '--';

      return `<tr>
        <td class="font-mono text-xs">${id}</td>
        <td class="text-right font-mono-metric">${version}</td>
        <td>${status}</td>
        <td class="text-xs max-w-xs truncate" title="${Observatory.escapeHtml(JSON.stringify(inst.state || {}))}">${state}</td>
        <td class="text-xs text-base-content/60">${started}</td>
        <td class="text-xs text-base-content/60">${lastActivity}</td>
        <td class="text-right font-mono-metric">${events}</td>
      </tr>`;
    }).join('');
  }

  function _closeInstances() {
    _selectedPM = null;
    if ($instanceExplorer) $instanceExplorer.classList.add('hidden');
  }

  // ---------------------------------------------------------------------------
  // Data Loading
  // ---------------------------------------------------------------------------

  function _onDataLoaded(data) {
    if (!data) return;
    _processes = data.processes || [];
    if (data.summary) _updateSummary(data.summary);
    _renderTable();
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
          _renderTable();
        }, 200);
      });
    }

    // Status filter
    if ($statusFilter) {
      $statusFilter.addEventListener('change', () => {
        _statusFilter = $statusFilter.value;
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
        _renderTable();
      });
    });

    // Instance explorer close
    const $closeBtn = document.getElementById('explorer-close');
    if ($closeBtn) {
      $closeBtn.addEventListener('click', _closeInstances);
    }
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  function init() {
    $tbody = document.getElementById('processes-tbody');
    $search = document.getElementById('process-search');
    $statusFilter = document.getElementById('process-status-filter');
    $instanceExplorer = document.getElementById('instance-explorer');

    _bindEvents();

    // Register poller for process data
    const w = Observatory.state.window;
    Observatory.poller.register('processes', `/api/processes?window=${w}`, 10000, _onDataLoaded);
  }

  // Wait for DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
