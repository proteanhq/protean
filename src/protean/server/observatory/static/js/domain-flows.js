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

  var COL_SPACING = 200;
  var ROW_SPACING = 56;
  var NODE_W = 150;
  var NODE_H = 34;
  var MARGIN = { top: 40, right: 20, bottom: 20, left: 20 };

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
  var _pinnedNodeId = null;   // Persistent search highlight
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
    // Use container height (viewport-filling) or fall back to graph bounds
    _svgHeight = rect.height || 600;

    _svg = d3.select(containerSelector)
      .append('svg')
      .attr('class', 'dv-flow-svg')
      .attr('width', '100%')
      .attr('height', '100%');

    var defs = _svg.append('defs');
    _renderArrowMarker(defs, 'dv-flow-arrow', 'dv-flow-arrow-head');
    _renderArrowMarker(defs, 'dv-flow-arrow-cross', 'dv-flow-arrow-head-cross');
    _renderArrowMarker(defs, 'dv-flow-arrow-proj', 'dv-flow-arrow-head-proj');

    _zoom = d3.zoom()
      .scaleExtent([0.4, 2])
      .on('zoom', function (event) {
        _g.attr('transform', event.transform);
      });
    _svg.call(_zoom);

    // Double-click resets to fit view
    _svg.on('dblclick.zoom', null);
    _svg.on('dblclick', function () { _fitToView(); });

    _g = _svg.append('g').attr('class', 'dv-flow-canvas');

    _renderColumnHeaders();
    _renderClusterBackgrounds();
    _renderEdges();
    _renderNodes();
    _renderLegend();
    _renderResetButton();
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
    _pinnedNodeId = null;
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

    // Infer cluster affinity for unclustered consumer nodes (projectors, PMs)
    // by tracing their incoming edges back to source events' clusters.
    _nodes.forEach(function (n) {
      if (n.cluster) return;
      var col = COLUMNS[n.type] != null ? COLUMNS[n.type] : 2;
      if (col !== 4) return; // Only consumer column

      // Find clusters of upstream nodes via incoming edges
      var clusterCounts = {};
      var sources = _adjReverse[n.id] || [];
      sources.forEach(function (srcId) {
        var srcNode = _nodeById[srcId];
        if (srcNode && srcNode.cluster) {
          clusterCounts[srcNode.cluster] = (clusterCounts[srcNode.cluster] || 0) + 1;
        }
      });

      // Assign to most-connected cluster
      var bestCluster = null;
      var bestCount = 0;
      for (var c in clusterCounts) {
        if (clusterCounts[c] > bestCount) {
          bestCount = clusterCounts[c];
          bestCluster = c;
        }
      }
      if (bestCluster) {
        n.cluster = bestCluster;
      }
    });

    // Group nodes by column and cluster
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

    // Sort nodes within each group
    for (var col = 0; col <= 4; col++) {
      for (var key in columnGroups[col]) {
        columnGroups[col][key].sort(function (a, b) {
          return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
        });
      }
    }

    var allClusters = {};
    _nodes.forEach(function (n) {
      if (n.cluster) allClusters[n.cluster] = true;
    });
    var clusterOrder = Object.keys(allClusters).sort();

    // Compute globally consistent vertical band per cluster:
    // each cluster's band height = max row count across all columns
    var clusterMaxRows = {};
    clusterOrder.forEach(function (cluster) {
      var maxRows = 0;
      for (var col = 0; col <= 4; col++) {
        var group = (columnGroups[col] || {})[cluster];
        if (group && group.length > maxRows) {
          maxRows = group.length;
        }
      }
      clusterMaxRows[cluster] = maxRows;
    });

    // Compute the y-start for each cluster band
    var clusterYStart = {};
    var y = MARGIN.top + 30;
    clusterOrder.forEach(function (cluster) {
      clusterYStart[cluster] = y;
      y += clusterMaxRows[cluster] * ROW_SPACING + 20; // gap between clusters
    });
    var unclusteredYStart = y;

    // Position nodes: center each column's group within its cluster band
    for (var col = 0; col <= 4; col++) {
      clusterOrder.forEach(function (cluster) {
        var group = (columnGroups[col] || {})[cluster];
        if (!group || group.length === 0) return;
        var bandHeight = clusterMaxRows[cluster] * ROW_SPACING;
        var groupHeight = group.length * ROW_SPACING;
        var yOffset = clusterYStart[cluster] + (bandHeight - groupHeight) / 2;
        group.forEach(function (n) {
          _nodePositions[n.id] = { x: MARGIN.left + col * COL_SPACING, y: yOffset };
          yOffset += ROW_SPACING;
        });
      });
      var unclustered = (columnGroups[col] || {}).__none__;
      if (unclustered && unclustered.length > 0) {
        var uy = unclusteredYStart;
        unclustered.forEach(function (n) {
          _nodePositions[n.id] = { x: MARGIN.left + col * COL_SPACING, y: uy };
          uy += ROW_SPACING;
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
      .on('mouseenter', function (event, d) { if (!_pinnedNodeId) _highlightPath(d, true); })
      .on('mouseleave', function (event, d) { if (!_pinnedNodeId) _highlightPath(d, false); })
      .on('click', function (event, d) {
        event.stopPropagation();
        if (_pinnedNodeId === d.id) {
          clearSearch();
        } else {
          setSearch(d.id);
        }
      });

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
  // Search — persistent highlight + zoom to connected subgraph
  // ---------------------------------------------------------------------------

  function setSearch(nodeId) {
    if (!_g || !_nodeById[nodeId]) return;
    _pinnedNodeId = nodeId;
    _highlightPath(_nodeById[nodeId], true);

    // Mark the focal node distinctly
    _g.selectAll('.dv-flow-node').classed('dv-flow-focal', function (d) {
      return d.id === nodeId;
    });

    // Highlight in place — no zoom/pan shift

    // Notify external listeners (search input sync)
    if (typeof _onSearchChange === 'function') _onSearchChange(nodeId);
  }

  function clearSearch() {
    if (!_g) return;
    _pinnedNodeId = null;
    // Remove all highlight/dim classes
    _g.selectAll('.dv-flow-node')
      .classed('dv-flow-dimmed', false)
      .classed('dv-flow-highlighted', false)
      .classed('dv-flow-focal', false);
    _g.selectAll('.dv-flow-edge')
      .classed('dv-flow-dimmed', false)
      .classed('dv-flow-highlighted', false);

    // Stay at current position — use Reset button to refit

    if (typeof _onSearchChange === 'function') _onSearchChange(null);
  }

  function getNodes() {
    return _nodes.map(function (n) {
      return { id: n.id, name: n.name, type: n.type, cluster: n.cluster };
    });
  }

  var _onSearchChange = null;

  function onSearchChange(fn) {
    _onSearchChange = fn;
  }

  function _zoomToConnected(nodeId) {
    if (!_svg || !_zoom) return;

    var connected = {};
    connected[nodeId] = true;
    _walkAdj(nodeId, _adjReverse, connected);
    _walkAdj(nodeId, _adjForward, connected);

    var xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
    for (var id in connected) {
      var pos = _nodePositions[id];
      if (!pos) continue;
      var left = pos.x - NODE_W / 2;
      var right = pos.x + NODE_W / 2;
      var top = pos.y - NODE_H / 2;
      var bottom = pos.y + NODE_H / 2 + 16;
      if (left < xMin) xMin = left;
      if (right > xMax) xMax = right;
      if (top < yMin) yMin = top;
      if (bottom > yMax) yMax = bottom;
    }

    if (xMin === Infinity) return;

    var pad = 60;
    xMin -= pad; yMin -= pad; xMax += pad; yMax += pad;
    var gw = xMax - xMin;
    var gh = yMax - yMin;
    if (gw <= 0 || gh <= 0) return;

    var scale = Math.min(_svgWidth / gw, _svgHeight / gh, 1.5) * 0.9;
    var tx = (_svgWidth - gw * scale) / 2 - xMin * scale;
    var ty = (_svgHeight - gh * scale) / 2 - yMin * scale;

    _svg.transition().duration(400).call(
      _zoom.transform,
      d3.zoomIdentity.translate(tx, ty).scale(scale)
    );
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
  // Reset View Button (fixed position, outside zoom group)
  // ---------------------------------------------------------------------------

  function _renderResetButton() {
    if (!_svg) return;

    var btnG = _svg.append('g')
      .attr('class', 'dv-flow-reset-btn')
      .attr('transform', 'translate(8, 8)')
      .style('cursor', 'pointer')
      .on('click', function () { clearSearch(); });

    btnG.append('rect')
      .attr('rx', 4).attr('ry', 4)
      .attr('width', 72).attr('height', 26)
      .attr('fill', 'oklch(0.92 0.02 250)')
      .attr('stroke', 'oklch(0.70 0.05 250)')
      .attr('stroke-width', 1);

    btnG.append('text')
      .attr('x', 36).attr('y', 17)
      .attr('text-anchor', 'middle')
      .attr('font-size', '11px')
      .attr('fill', 'oklch(0.35 0.05 250)')
      .text('⌂ Reset');

    // Show button only when view is not at default
    btnG.style('opacity', 0.6);
    btnG.on('mouseenter', function () { d3.select(this).style('opacity', 1); });
    btnG.on('mouseleave', function () { d3.select(this).style('opacity', 0.6); });
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
    // Re-read actual SVG dimensions in case container resized
    var svgEl = _svg.node();
    var svgW = svgEl.clientWidth || _svgWidth;
    var svgH = svgEl.clientHeight || _svgHeight;

    var gw = bounds.xMax - bounds.xMin + 20;
    var gh = bounds.yMax - bounds.yMin + 20;
    if (gw <= 0 || gh <= 0) return;

    var scale = Math.min(svgW / gw, svgH / gh, 1.0) * 0.96;
    var tx = (svgW - gw * scale) / 2 - bounds.xMin * scale + 10;
    var ty = (svgH - gh * scale) / 2 - bounds.yMin * scale + 10;

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
    setSearch: setSearch,
    clearSearch: clearSearch,
    getNodes: getNodes,
    onSearchChange: onSearchChange,
  };
})();
