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
      'dv-stat-handlers': stats.handlers,
      'dv-stat-process-managers': stats.process_managers,
      'dv-stat-projections': stats.projections,
      'dv-stat-diagnostics': stats.diagnostics,
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

    // Deferred render: these tabs need visible container for correct sizing
    if (tab === 'event-flows' && !_flowsRendered && _data) {
      _renderEventFlows(_data);
    }
    if (tab === 'process-managers' && !_pmRendered && _data) {
      _renderProcessManagers(_data);
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
  // Event Flows — D3 Directed Acyclic Graph
  // ---------------------------------------------------------------------------

  var _flowsRendered = false;

  function _renderEventFlows(data) {
    // Defer rendering until the tab is visible (hidden panels have zero width)
    if (_currentTab !== 'event-flows') return;

    var container = document.getElementById('dv-flows-container');
    if (!container) return;

    var flowGraph = data.flow_graph || { nodes: [], edges: [] };

    if (typeof DomainFlows !== 'undefined') {
      DomainFlows.render('#dv-flows-container', flowGraph);
      _wireFilterToggles();
      _flowsRendered = true;
    } else {
      container.innerHTML =
        '<div class="flex items-center justify-center h-64 px-4 text-center text-base-content/60">' +
        'Event flow visualization could not be loaded. Please refresh the page.' +
        '</div>';
    }
  }

  var _filtersWired = false;

  function _wireFilterToggles() {
    if (_filtersWired) return;
    _filtersWired = true;
    var toggles = document.querySelectorAll('[data-flow-filter]');
    toggles.forEach(function (toggle) {
      toggle.addEventListener('change', function () {
        if (typeof DomainFlows !== 'undefined') {
          DomainFlows.setFilter(toggle.dataset.flowFilter, toggle.checked);
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Process Managers — D3 State Machine Diagrams
  // ---------------------------------------------------------------------------

  var _pmRendered = false;

  function _renderProcessManagers(data) {
    // Defer rendering until the tab is visible (hidden panels have zero width)
    if (_currentTab !== 'process-managers') return;

    var container = document.getElementById('dv-pm-container');
    if (!container) return;

    var pmGraphs = data.pm_graphs || [];

    if (pmGraphs.length === 0) {
      container.innerHTML =
        '<div class="flex items-center justify-center h-64 text-base-content/40">' +
        'No process managers found in domain.</div>';
      _pmRendered = true;
      return;
    }

    if (typeof DomainProcesses !== 'undefined') {
      DomainProcesses.render('#dv-pm-container', pmGraphs);
      _pmRendered = true;
    } else {
      container.innerHTML =
        '<div class="flex items-center justify-center h-64 px-4 text-center text-base-content/60">' +
        'Process manager visualization could not be loaded. Please refresh the page.' +
        '</div>';
    }
  }

  // ---------------------------------------------------------------------------
  // Detail panel (delegated to DomainDetail module)
  // ---------------------------------------------------------------------------

  function _showDetail(fqn, data) {
    var cluster = (data.clusters || {})[fqn];
    if (!cluster) return;
    if (typeof DomainDetail !== 'undefined') {
      DomainDetail.show(fqn, cluster);
    }
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

    // Initialize detail panel (close button, backdrop, Escape key)
    if (typeof DomainDetail !== 'undefined') {
      DomainDetail.init();
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
