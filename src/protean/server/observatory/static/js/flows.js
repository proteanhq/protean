/**
 * Event Flows View Module
 *
 * Fetches domain topology from /api/flows/graph, renders a D3 force-directed
 * graph, and provides causation tracing via /api/flows/trace/{correlation_id}.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let _graphData = null;   // { nodes, edges, clusters }
  let _graphControl = null; // returned by Charts.flowGraph()
  let _currentCluster = 'all';

  // DOM refs
  let $graphContainer, $clusterFilter, $traceSearch, $traceBtn, $causationTree;
  let $nodeDetail, $nodeDetailName, $nodeDetailType, $nodeDetailFqn;
  let $nodeDetailAggregate, $nodeDetailConnections;

  // ---------------------------------------------------------------------------
  // Graph Rendering
  // ---------------------------------------------------------------------------

  function _renderGraph() {
    if (!$graphContainer || !_graphData) return;

    // Destroy previous graph
    if (_graphControl) {
      _graphControl.destroy();
      _graphControl = null;
    }

    if (_graphData.nodes.length === 0) {
      $graphContainer.innerHTML =
        '<div class="flex items-center justify-center py-16 text-base-content/40">' +
        '<p class="text-sm">No domain elements registered.</p></div>';
      return;
    }

    // Deep copy nodes/edges (D3 mutates them)
    const nodes = _graphData.nodes.map(n => Object.assign({}, n));
    const edges = _graphData.edges.map(e => ({
      source: e.source,
      target: e.target,
      type: e.type,
    }));

    _graphControl = Charts.flowGraph($graphContainer, nodes, edges, {
      height: 500,
      filterCluster: _currentCluster,
      onNodeClick: _onNodeClick,
    });
  }

  function _updateClusterFilter() {
    if (!$clusterFilter || !_graphData) return;

    const current = $clusterFilter.value;
    $clusterFilter.innerHTML = '<option value="all">All Aggregates</option>';

    for (const name of _graphData.clusters) {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      $clusterFilter.appendChild(opt);
    }

    // Restore selection if still valid
    if (_graphData.clusters.includes(current)) {
      $clusterFilter.value = current;
    }
  }

  // ---------------------------------------------------------------------------
  // Node Detail
  // ---------------------------------------------------------------------------

  function _onNodeClick(node) {
    if (!$nodeDetail) return;
    $nodeDetail.classList.remove('hidden');

    $nodeDetailName.textContent = node.label || node.id;
    $nodeDetailType.textContent = node.type || '--';
    $nodeDetailFqn.textContent = node.fqn || node.id;
    $nodeDetailAggregate.textContent = node.aggregate || '--';

    // Find connections
    if (_graphData) {
      const connections = [];
      for (const e of _graphData.edges) {
        if (e.source === node.id) {
          connections.push({ direction: 'out', type: e.type, target: e.target });
        }
        if (e.target === node.id) {
          connections.push({ direction: 'in', type: e.type, source: e.source });
        }
      }

      if (connections.length > 0) {
        $nodeDetailConnections.innerHTML = connections
          .map(c => {
            const label = c.direction === 'out'
              ? `→ ${Observatory.escapeHtml(c.target)} (${c.type})`
              : `← ${Observatory.escapeHtml(c.source)} (${c.type})`;
            return `<span class="badge badge-sm badge-outline">${label}</span>`;
          })
          .join('');
      } else {
        $nodeDetailConnections.innerHTML =
          '<span class="text-sm text-base-content/50">No connections</span>';
      }
    }

    // Fetch full element detail
    const fqn = node.fqn || node.id;
    Observatory.fetchJSON(`/api/flows/element/${encodeURIComponent(fqn)}`)
      .then(data => {
        if (data && data.element) {
          // Could enhance detail panel with more info
        }
      })
      .catch(() => {});
  }

  function _closeNodeDetail() {
    if ($nodeDetail) $nodeDetail.classList.add('hidden');
  }

  // ---------------------------------------------------------------------------
  // Causation Trace
  // ---------------------------------------------------------------------------

  async function _doTrace() {
    if (!$traceSearch || !$causationTree) return;

    const correlationId = $traceSearch.value.trim();
    if (!correlationId) return;

    $causationTree.innerHTML =
      '<div class="flex items-center justify-center py-4 text-base-content/40">' +
      '<span class="loading loading-spinner loading-sm"></span>' +
      '<span class="ml-2 text-sm">Tracing...</span></div>';

    try {
      const data = await Observatory.fetchJSON(
        `/api/flows/trace/${encodeURIComponent(correlationId)}`
      );

      if (data && data.tree) {
        Charts.causationTree($causationTree, data.tree, {
          onNodeClick: (node) => {
            // Could show node detail
          },
        });
      } else if (data && data.error) {
        $causationTree.innerHTML =
          `<div class="text-center text-warning py-4 text-sm">${Observatory.escapeHtml(data.error)}</div>`;
      }
    } catch (e) {
      $causationTree.innerHTML =
        `<div class="text-center text-error py-4 text-sm">Failed to trace: ${Observatory.escapeHtml(e.message)}</div>`;
    }
  }

  // ---------------------------------------------------------------------------
  // Data Loading
  // ---------------------------------------------------------------------------

  function _onDataLoaded(data) {
    if (!data) return;
    _graphData = data;
    _updateClusterFilter();
    _renderGraph();
  }

  // ---------------------------------------------------------------------------
  // Event Binding
  // ---------------------------------------------------------------------------

  function _bindEvents() {
    // Cluster filter
    if ($clusterFilter) {
      $clusterFilter.addEventListener('change', () => {
        _currentCluster = $clusterFilter.value;
        _renderGraph();
      });
    }

    // Zoom controls
    const $zoomIn = document.getElementById('zoom-in');
    const $zoomOut = document.getElementById('zoom-out');
    const $zoomReset = document.getElementById('zoom-reset');

    if ($zoomIn) {
      $zoomIn.addEventListener('click', () => {
        if (_graphControl) _graphControl.zoomTo(1.5);
      });
    }
    if ($zoomOut) {
      $zoomOut.addEventListener('click', () => {
        if (_graphControl) _graphControl.zoomTo(0.7);
      });
    }
    if ($zoomReset) {
      $zoomReset.addEventListener('click', () => {
        if (_graphControl) _graphControl.resetZoom();
      });
    }

    // Node detail close
    const $closeBtn = document.getElementById('node-detail-close');
    if ($closeBtn) {
      $closeBtn.addEventListener('click', _closeNodeDetail);
    }

    // Trace
    if ($traceBtn) {
      $traceBtn.addEventListener('click', _doTrace);
    }
    if ($traceSearch) {
      $traceSearch.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') _doTrace();
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  function init() {
    $graphContainer = document.getElementById('flow-graph');
    $clusterFilter = document.getElementById('cluster-filter');
    $traceSearch = document.getElementById('trace-search');
    $traceBtn = document.getElementById('trace-btn');
    $causationTree = document.getElementById('causation-tree');
    $nodeDetail = document.getElementById('node-detail');
    $nodeDetailName = document.getElementById('node-detail-name');
    $nodeDetailType = document.getElementById('node-detail-type');
    $nodeDetailFqn = document.getElementById('node-detail-fqn');
    $nodeDetailAggregate = document.getElementById('node-detail-aggregate');
    $nodeDetailConnections = document.getElementById('node-detail-connections');

    _bindEvents();

    // Fetch graph once (IR is static)
    Observatory.fetchJSON('/api/flows/graph')
      .then(_onDataLoaded)
      .catch(err => {
        console.warn('Failed to load flow graph:', err.message);
        if ($graphContainer) {
          $graphContainer.innerHTML =
            '<div class="flex items-center justify-center py-16 text-error/60">' +
            '<p class="text-sm">Failed to load flow graph.</p></div>';
        }
      });
  }

  // Wait for DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
