/**
 * Domain View Module
 *
 * Fetches the domain IR graph from /api/domain/ir and renders
 * three views: Topology, Event Flows, and Process Managers.
 * Subsequent sub-issues (#876-#879) will add D3 visualizations.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let _data = null;
  let _currentTab = 'topology';

  // DOM refs (cached after DOMContentLoaded)
  let $tabs, $panels;

  // ---------------------------------------------------------------------------
  // Stats rendering
  // ---------------------------------------------------------------------------

  function _updateStats(stats) {
    const mapping = {
      'dv-stat-aggregates': stats.aggregates,
      'dv-stat-commands': stats.commands,
      'dv-stat-events': stats.events,
      'dv-stat-process-managers': stats.process_managers,
      'dv-stat-projections': stats.projections,
    };

    for (const [id, value] of Object.entries(mapping)) {
      const el = document.getElementById(id);
      if (el) el.textContent = value != null ? value : '--';
    }
  }

  // ---------------------------------------------------------------------------
  // Tab switching
  // ---------------------------------------------------------------------------

  function _switchTab(tab) {
    _currentTab = tab;

    // Update tab active state
    if ($tabs) {
      $tabs.querySelectorAll('[data-tab]').forEach(function (el) {
        if (el.dataset.tab === tab) {
          el.classList.add('tab-active');
        } else {
          el.classList.remove('tab-active');
        }
      });
    }

    // Show/hide panels
    document.querySelectorAll('.dv-panel').forEach(function (panel) {
      panel.classList.add('hidden');
    });
    var activePanel = document.getElementById('dv-panel-' + tab);
    if (activePanel) {
      activePanel.classList.remove('hidden');
    }
  }

  function _onTabClick(e) {
    var el = e.target.closest ? e.target.closest('[data-tab]') : null;
    if (el && el.dataset.tab) {
      _switchTab(el.dataset.tab);
    }
  }

  // ---------------------------------------------------------------------------
  // Topology — D3 Force-Directed Graph
  // ---------------------------------------------------------------------------

  function _renderTopology(data) {
    var container = document.getElementById('dv-topology-container');
    if (!container) return;

    // Delegate to DomainTopology D3 module
    if (typeof DomainTopology !== 'undefined') {
      DomainTopology.render('#dv-topology-container', data, function (fqn) {
        if (_data) _showDetail(fqn, _data);
      });
    } else {
      container.innerHTML =
        '<div class="flex items-center justify-center h-64 px-4 text-center text-base-content/60">' +
        'Topology visualization could not be loaded. Please refresh the page.' +
        '</div>';
    }
  }

  // ---------------------------------------------------------------------------
  // Event Flows placeholder
  // ---------------------------------------------------------------------------

  function _renderEventFlows(data) {
    var container = document.getElementById('dv-flows-container');
    if (!container) return;

    var links = (data.links || []).filter(function (l) {
      return l.type === 'event' || l.type === 'projection';
    });

    if (links.length === 0) {
      container.innerHTML =
        '<div class="flex items-center justify-center h-64 text-base-content/40">' +
        'No cross-aggregate event flows detected.</div>';
      return;
    }

    // Table of event flows (D3 DAG in #878)
    var html = '<table class="table table-sm"><thead><tr>' +
      '<th>Source</th><th>Target</th><th>Type</th><th>Label</th></tr></thead><tbody>';
    links.forEach(function (link) {
      html += '<tr>';
      html += '<td class="font-mono text-xs">' + _esc(_shortName(link.source)) + '</td>';
      html += '<td class="font-mono text-xs">' + _esc(_shortName(link.target)) + '</td>';
      html += '<td><span class="badge badge-sm badge-ghost">' + _esc(link.type) + '</span></td>';
      html += '<td class="text-sm">' + _esc(link.label) + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  }

  // ---------------------------------------------------------------------------
  // Process Managers placeholder
  // ---------------------------------------------------------------------------

  function _renderProcessManagers(data) {
    var container = document.getElementById('dv-pm-container');
    if (!container) return;

    var pms = data.flows && data.flows.process_managers ? data.flows.process_managers : {};
    var pmList = Object.entries(pms);

    if (pmList.length === 0) {
      container.innerHTML =
        '<div class="flex items-center justify-center h-64 text-base-content/40">' +
        'No process managers found in domain.</div>';
      return;
    }

    // Cards per PM (state machine view in #879)
    var html = '<div class="grid grid-cols-1 md:grid-cols-2 gap-4">';
    pmList.forEach(function (entry) {
      var fqn = entry[0];
      var pm = entry[1];
      var handlers = pm.handlers || {};
      var handlerCount = Object.keys(handlers).length;

      html += '<div class="card bg-base-200 shadow-sm">';
      html += '<div class="card-body p-4">';
      html += '<div class="font-bold text-base">' + _esc(pm.name || fqn) + '</div>';
      html += '<div class="text-xs text-base-content/50 font-mono mb-2">' + _esc(fqn) + '</div>';
      html += '<div class="flex gap-2 mb-2">';
      html += '<span class="badge badge-sm badge-ghost">' + handlerCount + ' handler' +
        (handlerCount !== 1 ? 's' : '') + '</span>';
      if (pm.stream_categories && pm.stream_categories.length > 0) {
        html += '<span class="badge badge-sm badge-info">' +
          pm.stream_categories.length + ' stream' +
          (pm.stream_categories.length !== 1 ? 's' : '') + '</span>';
      }
      html += '</div>';
      html += '</div></div>';
    });
    html += '</div>';
    container.innerHTML = html;
  }

  // ---------------------------------------------------------------------------
  // Detail panel
  // ---------------------------------------------------------------------------

  function _showDetail(fqn, data) {
    var panel = document.getElementById('dv-detail-panel');
    var title = document.getElementById('dv-detail-title');
    var content = document.getElementById('dv-detail-content');
    if (!panel || !title || !content) return;

    var cluster = (data.clusters || {})[fqn];
    if (!cluster) return;

    var agg = cluster.aggregate || {};
    title.textContent = agg.name || fqn;

    var html = '<div class="text-xs text-base-content/50 font-mono mb-3">' + _esc(fqn) + '</div>';

    // Element counts
    var sections = [
      ['Commands', cluster.commands],
      ['Events', cluster.events],
      ['Entities', cluster.entities],
      ['Value Objects', cluster.value_objects],
      ['Command Handlers', cluster.command_handlers],
      ['Event Handlers', cluster.event_handlers],
    ];

    sections.forEach(function (s) {
      var label = s[0];
      var items = s[1] || {};
      var keys = Object.keys(items);
      if (keys.length === 0) return;

      html += '<div class="mb-2">';
      html += '<div class="text-xs font-semibold text-base-content/60 mb-1">' + _esc(label) +
        ' (' + keys.length + ')</div>';
      html += '<div class="flex flex-wrap gap-1">';
      keys.forEach(function (k) {
        var name = items[k].name || k.split('.').pop();
        html += '<span class="badge badge-sm badge-ghost">' + _esc(name) + '</span>';
      });
      html += '</div></div>';
    });

    content.innerHTML = html;
    panel.classList.remove('hidden');
  }

  function _hideDetail() {
    var panel = document.getElementById('dv-detail-panel');
    if (panel) panel.classList.add('hidden');
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _esc(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str || ''));
    return div.innerHTML;
  }

  function _shortName(fqn) {
    return (fqn || '').split('.').pop();
  }

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  function _onData(data) {
    _data = data;

    if (data.stats) {
      _updateStats(data.stats);
    }

    _renderTopology(data);
    _renderEventFlows(data);
    _renderProcessManagers(data);
  }

  // ---------------------------------------------------------------------------
  // Initialization
  // ---------------------------------------------------------------------------

  function _init() {
    $tabs = document.getElementById('dv-tabs');
    if (!$tabs) return; // Not on the domain page

    // Tab click handler
    $tabs.addEventListener('click', _onTabClick);

    // Detail panel close
    var closeBtn = document.getElementById('dv-detail-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', _hideDetail);
    }

    // Node card click delegation (guard for non-Element targets)
    document.addEventListener('click', function (e) {
      if (!e.target || !e.target.closest) return;
      var card = e.target.closest('.dv-node-card');
      if (card && _data) {
        _showDetail(card.dataset.fqn, _data);
      }
    });

    // Fetch data once (no polling needed — domain topology is static)
    Observatory.fetchJSON('/api/domain/ir').then(function (data) {
      if (data) _onData(data);
    }).catch(function () {
      // Ignore fetch errors — loading state remains
    });
  }

  // Auto-init
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }
})();
