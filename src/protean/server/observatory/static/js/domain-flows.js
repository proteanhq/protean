/**
 * Domain Flows Module — D3 Directed Acyclic Graph
 *
 * Renders an interactive left-to-right DAG showing the message flow:
 *   Command -> CommandHandler -> Aggregate -> Event -> [EventHandler | PM | Projector]
 *
 * Nodes have distinct shapes/colors by type. Edges show message direction.
 * Cluster subgraphs group elements by aggregate.
 *
 * Usage:
 *   DomainFlows.render('#dv-flows-container', flowGraphData);
 *   DomainFlows.destroy();
 *   DomainFlows.setFilter('projector', false);
 */
var DomainFlows = (function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------------

  var COLUMNS = {
    command: 0,
    command_handler: 1,
    aggregate: 2,
    event: 3,
    event_handler: 4,
    process_manager: 4,
    projector: 4,
  };

  var COL_SPACING = 220;
  var ROW_SPACING = 70;
  var NODE_W = 160;
  var NODE_H = 36;
  var MARGIN = { top: 60, right: 40, bottom: 40, left: 40 };

  var NODE_STYLES = {
    command:         { fill: 'oklch(0.82 0.10 250)', text: '#1a3a5c', rx: 14, label: 'Command' },
    command_handler: { fill: 'oklch(0.80 0.10 190)', text: '#1a3a4a', rx: 4,  label: 'Cmd Handler' },
    aggregate:       { fill: 'oklch(0.78 0.12 300)', text: '#3a1a5c', rx: 8,  label: 'Aggregate' },
    event:           { fill: 'oklch(0.82 0.12 70)',  text: '#5c3a1a', rx: 14, label: 'Event' },
    event_handler:   { fill: 'oklch(0.80 0.10 150)', text: '#1a4a2a', rx: 4,  label: 'Evt Handler' },
    process_manager: { fill: 'oklch(0.78 0.12 25)',  text: '#5c1a1a', rx: 4,  label: 'Process Mgr' },
    projector:       { fill: 'oklch(0.78 0.10 270)', text: '#2a1a5c', rx: 4,  label: 'Projector' },
  };

  var EDGE_STYLES = {
    command:        { stroke: 'oklch(0.55 0.10 250)', dash: 'none' },
    handler_to_agg: { stroke: 'oklch(0.55 0.10 190)', dash: 'none' },
    raises:         { stroke: 'oklch(0.55 0.12 300)', dash: 'none' },
    event:          { stroke: 'oklch(0.55 0.10 150)', dash: 'none' },
    projection:     { stroke: 'oklch(0.55 0.10 270)', dash: '6 3' },
  };

  var CLUSTER_PALETTE = [
    'oklch(0.96 0.02 250)',
    'oklch(0.96 0.02 150)',
    'oklch(0.96 0.02 30)',
    'oklch(0.96 0.02 320)',
    'oklch(0.96 0.02 80)',
    'oklch(0.96 0.02 200)',
  ];

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  var _svg = null;
  var _g = null;
  var _zoom = null;
  var _nodes = [];
  var _edges = [];
  var _nodePositions = {};
  var _nodeById = {};         // id -> node (O(1) lookup)
  var _adjForward = {};       // id -> [target ids] (downstream adjacency)
  var _adjReverse = {};       // id -> [source ids] (upstream adjacency)
  var _hiddenTypes = {};
  var _svgWidth = 800;
  var _svgHeight = 500;

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  function render(containerSelector, flowGraph) {
    destroy();

    var container = document.querySelector(containerSelector);
    if (!container) return;
    container.innerHTML = '';

    var rawNodes = flowGraph.nodes || [];
    var rawEdges = flowGraph.edges || [];

    if (rawNodes.length === 0) {
      container.innerHTML =
        '<div class="flex items-center justify-center h-64 text-base-content/40">' +
        'No event flows found in domain.</div>';
      return;
    }

    _nodes = rawNodes.map(function (n) { return Object.assign({}, n); });
    _edges = rawEdges.map(function (e) { return Object.assign({}, e); });

    _buildLookups();
    _computeLayout();

    var rect = container.getBoundingClientRect();
    _svgWidth = rect.width || 800;
    var bounds = _getGraphBounds();
    _svgHeight = Math.max(400, bounds.yMax + MARGIN.bottom + 20);

    _svg = d3.select(containerSelector)
      .append('svg')
      .attr('class', 'dv-flow-svg')
      .attr('width', '100%')
      .attr('height', _svgHeight);

    var defs = _svg.append('defs');
    _renderArrowMarker(defs, 'dv-flow-arrow', 'dv-flow-arrow-head');
    _renderArrowMarker(defs, 'dv-flow-arrow-cross', 'dv-flow-arrow-head-cross');
    _renderArrowMarker(defs, 'dv-flow-arrow-proj', 'dv-flow-arrow-head-proj');

    _zoom = d3.zoom()
      .scaleExtent([0.2, 3])
      .on('zoom', function (event) {
        _g.attr('transform', event.transform);
      });
    _svg.call(_zoom);

    _g = _svg.append('g').attr('class', 'dv-flow-canvas');

    _renderColumnHeaders();
    _renderClusterBackgrounds();
    _renderEdges();
    _renderNodes();
    _renderLegend();
    _fitToView();
  }

  function destroy() {
    if (_svg) {
      _svg.remove();
      _svg = null;
    }
    _g = null;
    _zoom = null;
    _nodes = [];
    _edges = [];
    _nodePositions = {};
    _nodeById = {};
    _adjForward = {};
    _adjReverse = {};
    _hiddenTypes = {};
    _svgWidth = 800;
    _svgHeight = 500;
  }

  function setFilter(type, visible) {
    if (visible) {
      delete _hiddenTypes[type];
    } else {
      _hiddenTypes[type] = true;
    }
    _applyFilters();
  }

  // ---------------------------------------------------------------------------
  // Lookup Tables (built once per render)
  // ---------------------------------------------------------------------------

  function _buildLookups() {
    _nodeById = {};
    _adjForward = {};
    _adjReverse = {};

    _nodes.forEach(function (n) {
      _nodeById[n.id] = n;
      _adjForward[n.id] = [];
      _adjReverse[n.id] = [];
    });

    _edges.forEach(function (e) {
      if (_adjForward[e.source]) _adjForward[e.source].push(e.target);
      if (_adjReverse[e.target]) _adjReverse[e.target].push(e.source);
    });
  }

  // ---------------------------------------------------------------------------
  // Layout — assign (x, y) to each node
  // ---------------------------------------------------------------------------

  function _computeLayout() {
    _nodePositions = {};

    var columnGroups = {};
    for (var col = 0; col <= 4; col++) {
      columnGroups[col] = {};
    }

    _nodes.forEach(function (n) {
      var col = COLUMNS[n.type] != null ? COLUMNS[n.type] : 2;
      var cluster = n.cluster || '__none__';
      if (!columnGroups[col][cluster]) {
        columnGroups[col][cluster] = [];
      }
      columnGroups[col][cluster].push(n);
    });

    var allClusters = {};
    _nodes.forEach(function (n) {
      if (n.cluster) allClusters[n.cluster] = true;
    });
    var clusterOrder = Object.keys(allClusters).sort();

    for (var col = 0; col <= 4; col++) {
      var y = MARGIN.top + 30;
      clusterOrder.forEach(function (cluster) {
        var group = (columnGroups[col] || {})[cluster];
        if (!group || group.length === 0) return;
        group.sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });
        group.forEach(function (n) {
          _nodePositions[n.id] = { x: MARGIN.left + col * COL_SPACING, y: y };
          y += ROW_SPACING;
        });
        y += 10;
      });
      var unclustered = (columnGroups[col] || {}).__none__;
      if (unclustered && unclustered.length > 0) {
        unclustered.sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });
        unclustered.forEach(function (n) {
          _nodePositions[n.id] = { x: MARGIN.left + col * COL_SPACING, y: y };
          y += ROW_SPACING;
        });
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Cluster Backgrounds
  // ---------------------------------------------------------------------------

  function _renderClusterBackgrounds() {
    if (!_g) return;

    var clusterNodes = {};
    _nodes.forEach(function (n) {
      if (!n.cluster) return;
      if (!clusterNodes[n.cluster]) clusterNodes[n.cluster] = [];
      clusterNodes[n.cluster].push(n);
    });

    var bgG = _g.append('g').attr('class', 'dv-flow-clusters');
    var clusterKeys = Object.keys(clusterNodes).sort();

    clusterKeys.forEach(function (cluster, i) {
      var cNodes = clusterNodes[cluster];
      var xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
      cNodes.forEach(function (n) {
        var pos = _nodePositions[n.id];
        if (!pos) return;
        if (pos.x - NODE_W / 2 < xMin) xMin = pos.x - NODE_W / 2;
        if (pos.x + NODE_W / 2 > xMax) xMax = pos.x + NODE_W / 2;
        if (pos.y - NODE_H / 2 < yMin) yMin = pos.y - NODE_H / 2;
        if (pos.y + NODE_H / 2 > yMax) yMax = pos.y + NODE_H / 2;
      });

      var pad = 16;
      bgG.append('rect')
        .attr('class', 'dv-flow-cluster-bg')
        .attr('rx', 10)
        .attr('ry', 10)
        .attr('x', xMin - pad)
        .attr('y', yMin - pad - 16)
        .attr('width', xMax - xMin + pad * 2)
        .attr('height', yMax - yMin + pad * 2 + 16)
        .attr('fill', CLUSTER_PALETTE[i % CLUSTER_PALETTE.length]);

      bgG.append('text')
        .attr('class', 'dv-flow-cluster-label')
        .attr('x', xMin - pad + 8)
        .attr('y', yMin - pad - 4)
        .text(_shortName(cluster));
    });
  }

  // ---------------------------------------------------------------------------
  // Edge Rendering
  // ---------------------------------------------------------------------------

  function _renderEdges() {
    if (!_g) return;

    var edgeG = _g.append('g').attr('class', 'dv-flow-edges');

    edgeG.selectAll('.dv-flow-edge')
      .data(_edges)
      .enter()
      .append('path')
      .attr('class', function (d) {
        var cls = 'dv-flow-edge dv-flow-edge--' + d.type;
        if (d.cross_aggregate) cls += ' dv-flow-edge--cross';
        return cls;
      })
      .attr('d', function (d) {
        return _edgePath(d.source, d.target);
      })
      .attr('stroke', function (d) {
        var style = EDGE_STYLES[d.type] || EDGE_STYLES.event;
        return style.stroke;
      })
      .attr('stroke-dasharray', function (d) {
        var style = EDGE_STYLES[d.type] || EDGE_STYLES.event;
        return style.dash;
      })
      .attr('marker-end', function (d) {
        if (d.cross_aggregate) return 'url(#dv-flow-arrow-cross)';
        if (d.type === 'projection') return 'url(#dv-flow-arrow-proj)';
        return 'url(#dv-flow-arrow)';
      })
      .attr('data-source-type', function (d) {
        var sn = _nodeById[d.source];
        return sn ? sn.type : '';
      })
      .attr('data-target-type', function (d) {
        var tn = _nodeById[d.target];
        return tn ? tn.type : '';
      });
  }

  function _edgePath(sourceId, targetId) {
    var s = _nodePositions[sourceId];
    var t = _nodePositions[targetId];
    if (!s || !t) return 'M0,0';

    var sx = s.x + NODE_W / 2;
    var sy = s.y;
    var tx = t.x - NODE_W / 2;
    var ty = t.y;

    // Backward/same-column edge: bezier curve around
    if (tx <= sx) {
      return 'M' + sx + ',' + sy + ' C' + (sx + 40) + ',' + sy + ' ' + (tx - 40) + ',' + ty + ' ' + tx + ',' + ty;
    }

    // Forward edge: gentle S-curve
    var cx1 = sx + (tx - sx) * 0.4;
    var cx2 = sx + (tx - sx) * 0.6;
    return 'M' + sx + ',' + sy + ' C' + cx1 + ',' + sy + ' ' + cx2 + ',' + ty + ' ' + tx + ',' + ty;
  }

  // ---------------------------------------------------------------------------
  // Node Rendering
  // ---------------------------------------------------------------------------

  function _renderNodes() {
    if (!_g) return;

    var nodeG = _g.append('g').attr('class', 'dv-flow-nodes');

    var nodeSel = nodeG.selectAll('.dv-flow-node')
      .data(_nodes, function (d) { return d.id; })
      .enter()
      .append('g')
      .attr('class', function (d) { return 'dv-flow-node dv-flow-node--' + d.type; })
      .attr('transform', function (d) {
        var pos = _nodePositions[d.id] || { x: 0, y: 0 };
        return 'translate(' + pos.x + ',' + pos.y + ')';
      })
      .on('mouseenter', function (event, d) { _highlightPath(d, true); })
      .on('mouseleave', function (event, d) { _highlightPath(d, false); });

    nodeSel.append('rect')
      .attr('class', 'dv-flow-card')
      .attr('rx', function (d) { return (NODE_STYLES[d.type] || NODE_STYLES.command).rx; })
      .attr('ry', function (d) { return (NODE_STYLES[d.type] || NODE_STYLES.command).rx; })
      .attr('x', -NODE_W / 2)
      .attr('y', -NODE_H / 2)
      .attr('width', NODE_W)
      .attr('height', NODE_H)
      .attr('fill', function (d) { return (NODE_STYLES[d.type] || NODE_STYLES.command).fill; });

    nodeSel.append('text')
      .attr('class', 'dv-flow-name')
      .attr('text-anchor', 'middle')
      .attr('dy', '0.35em')
      .attr('fill', function (d) { return (NODE_STYLES[d.type] || NODE_STYLES.command).text; })
      .text(function (d) {
        var name = d.name || '';
        return name.length > 20 ? name.substring(0, 18) + '..' : name;
      });

    // Type badge only for ambiguous consumer column nodes
    nodeSel.append('text')
      .attr('class', 'dv-flow-type-badge')
      .attr('text-anchor', 'middle')
      .attr('y', NODE_H / 2 + 12)
      .text(function (d) {
        var s = NODE_STYLES[d.type];
        if (s && (d.type === 'event_handler' || d.type === 'process_manager' || d.type === 'projector')) {
          return s.label;
        }
        return '';
      });
  }

  // ---------------------------------------------------------------------------
  // Path Highlighting (uses pre-built adjacency lists)
  // ---------------------------------------------------------------------------

  function _highlightPath(node, highlight) {
    if (!_g) return;

    var connected = {};
    connected[node.id] = true;
    _walkAdj(node.id, _adjReverse, connected);
    _walkAdj(node.id, _adjForward, connected);

    _g.selectAll('.dv-flow-node').each(function (d) {
      var sel = d3.select(this);
      sel.classed('dv-flow-dimmed', highlight && !connected[d.id]);
      sel.classed('dv-flow-highlighted', highlight && !!connected[d.id]);
    });

    _g.selectAll('.dv-flow-edge').each(function (d) {
      var onPath = !!connected[d.source] && !!connected[d.target];
      var sel = d3.select(this);
      sel.classed('dv-flow-dimmed', highlight && !onPath);
      sel.classed('dv-flow-highlighted', highlight && !!onPath);
    });
  }

  function _walkAdj(startId, adj, visited) {
    var queue = [startId];
    var head = 0;
    while (head < queue.length) {
      var current = queue[head++];
      var neighbors = adj[current] || [];
      for (var i = 0; i < neighbors.length; i++) {
        if (!visited[neighbors[i]]) {
          visited[neighbors[i]] = true;
          queue.push(neighbors[i]);
        }
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Filters
  // ---------------------------------------------------------------------------

  function _applyFilters() {
    if (!_g) return;

    _g.selectAll('.dv-flow-node').each(function (d) {
      d3.select(this).style('display', _hiddenTypes[d.type] ? 'none' : null);
    });

    _g.selectAll('.dv-flow-edge').each(function (d) {
      var sNode = _nodeById[d.source];
      var tNode = _nodeById[d.target];
      var hidden = (sNode && _hiddenTypes[sNode.type]) || (tNode && _hiddenTypes[tNode.type]);
      d3.select(this).style('display', hidden ? 'none' : null);
    });
  }

  // ---------------------------------------------------------------------------
  // Column Headers (inside zoom group so they pan with the graph)
  // ---------------------------------------------------------------------------

  function _renderColumnHeaders() {
    if (!_g) return;

    var headerG = _g.append('g').attr('class', 'dv-flow-headers');
    var labels = [
      { col: 0, text: 'Commands' },
      { col: 1, text: 'Handlers' },
      { col: 2, text: 'Aggregates' },
      { col: 3, text: 'Events' },
      { col: 4, text: 'Consumers' },
    ];

    labels.forEach(function (h) {
      headerG.append('text')
        .attr('class', 'dv-flow-col-header')
        .attr('x', MARGIN.left + h.col * COL_SPACING)
        .attr('y', MARGIN.top)
        .attr('text-anchor', 'middle')
        .text(h.text);
    });
  }

  // ---------------------------------------------------------------------------
  // Legend
  // ---------------------------------------------------------------------------

  function _renderLegend() {
    if (!_svg) return;

    _svg.selectAll('.dv-flow-legend').remove();

    var legendG = _svg.append('g')
      .attr('class', 'dv-flow-legend')
      .attr('transform', 'translate(' + (_svgWidth - 200) + ', 8)');

    legendG.append('rect')
      .attr('class', 'dv-flow-legend-bg')
      .attr('rx', 6)
      .attr('ry', 6)
      .attr('width', 190)
      .attr('height', 96);

    var items = [
      { type: 'command', label: 'Command' },
      { type: 'aggregate', label: 'Aggregate' },
      { type: 'event', label: 'Event' },
      { type: 'event_handler', label: 'Handler / PM / Proj' },
    ];

    items.forEach(function (item, i) {
      var y = 14 + i * 20;
      legendG.append('rect')
        .attr('x', 8)
        .attr('y', y - 6)
        .attr('width', 16)
        .attr('height', 12)
        .attr('rx', NODE_STYLES[item.type].rx > 8 ? 6 : 2)
        .attr('fill', NODE_STYLES[item.type].fill);
      legendG.append('text')
        .attr('class', 'dv-flow-legend-text')
        .attr('x', 30)
        .attr('y', y + 3)
        .text(item.label);
    });
  }

  // ---------------------------------------------------------------------------
  // Arrow Marker
  // ---------------------------------------------------------------------------

  function _renderArrowMarker(defs, id, cls) {
    defs.append('marker')
      .attr('id', id)
      .attr('viewBox', '0 0 10 10')
      .attr('refX', 10)
      .attr('refY', 5)
      .attr('markerWidth', 7)
      .attr('markerHeight', 7)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M 0 0 L 10 5 L 0 10 Z')
      .attr('class', cls);
  }

  // ---------------------------------------------------------------------------
  // View Fitting
  // ---------------------------------------------------------------------------

  function _fitToView() {
    if (!_svg || !_g || !_zoom) return;

    var bounds = _getGraphBounds();
    var gw = bounds.xMax - bounds.xMin + 40;
    var gh = bounds.yMax - bounds.yMin + 40;
    if (gw <= 0 || gh <= 0) return;

    var scale = Math.min(_svgWidth / gw, _svgHeight / gh, 1.0) * 0.92;
    var tx = (_svgWidth - gw * scale) / 2 - bounds.xMin * scale + 20;
    var ty = 30;

    _svg.call(_zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _getGraphBounds() {
    var xMin = Infinity, xMax = -Infinity;
    var yMin = Infinity, yMax = -Infinity;

    _nodes.forEach(function (n) {
      var pos = _nodePositions[n.id];
      if (!pos) return;
      var left = pos.x - NODE_W / 2;
      var right = pos.x + NODE_W / 2;
      var top = pos.y - NODE_H / 2;
      var bottom = pos.y + NODE_H / 2 + 16;
      if (left < xMin) xMin = left;
      if (right > xMax) xMax = right;
      if (top < yMin) yMin = top;
      if (bottom > yMax) yMax = bottom;
    });

    if (xMin === Infinity) return { xMin: 0, xMax: 800, yMin: 0, yMax: 400 };
    return { xMin: xMin, xMax: xMax, yMin: yMin, yMax: yMax };
  }

  function _shortName(fqn) {
    return (fqn || '').split('.').pop();
  }

  // ---------------------------------------------------------------------------
  // Module Export
  // ---------------------------------------------------------------------------

  return {
    render: render,
    destroy: destroy,
    setFilter: setFilter,
  };
})();
