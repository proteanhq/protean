/**
 * Causation Graph Module — D3-Based Interactive Visualization
 *
 * Renders a horizontal left-to-right tree layout of causation chains
 * using D3.js. Supports zoom/pan, collapse/expand subtrees, hover
 * highlighting of causal paths, click-to-detail, swimlane grouping
 * by stream category, timeline axis, legend, progressive disclosure,
 * and a mini-map overview.
 *
 * Usage:
 *   CausationGraph.render(containerSelector, treeData, onNodeClick);
 *   CausationGraph.destroy();
 */
var CausationGraph = (function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------------

  var NODE_WIDTH = 220;
  var NODE_HEIGHT = 72;
  var NODE_MARGIN_X = 60;
  var NODE_MARGIN_Y = 16;
  var TRANSITION_DURATION = 300;
  var SWIMLANE_PADDING = 24;
  var PROGRESSIVE_THRESHOLD = 50;
  var MINIMAP_WIDTH = 160;
  var MINIMAP_HEIGHT = 100;
  var MINIMAP_MARGIN = 12;

  // Stream category color palette (deterministic assignment)
  var LANE_COLORS = [
    'oklch(0.75 0.12 250)',  // blue
    'oklch(0.75 0.12 150)',  // green
    'oklch(0.75 0.12 30)',   // orange
    'oklch(0.75 0.12 320)',  // purple
    'oklch(0.75 0.12 80)',   // yellow-green
    'oklch(0.75 0.12 200)',  // teal
    'oklch(0.75 0.12 350)',  // pink
    'oklch(0.75 0.12 110)',  // lime
  ];

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  var _svg = null;
  var _g = null;         // Main group (transformed by zoom)
  var _zoom = null;
  var _root = null;      // D3 hierarchy root
  var _treeFn = null;    // d3.tree() layout
  var _onNodeClick = null;
  var _laneMap = {};     // stream category -> { index, color, label }
  var _svgWidth = 800;
  var _svgHeight = 500;
  var _minimapG = null;  // Mini-map group (fixed position)
  var _minimapBounds = null;  // Cached graph bounds for minimap viewport updates
  var _minimapScale = 1;
  var _minimapRafId = null;   // rAF guard for zoom-driven minimap updates

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Render the causation graph into a container element.
   *
   * @param {string} containerSelector  CSS selector for the container div
   * @param {object} treeData           CausationNode tree from the API
   * @param {function} onNodeClick      Callback(messageId) when a node is clicked
   */
  function render(containerSelector, treeData, onNodeClick) {
    destroy();
    _onNodeClick = onNodeClick || function () {};

    var container = document.querySelector(containerSelector);
    if (!container || !treeData) return;

    var rect = container.getBoundingClientRect();
    _svgWidth = rect.width || 800;
    _svgHeight = Math.max(400, rect.height || 500);

    // Build lane map from stream categories in the data
    _laneMap = _buildLaneMap(treeData);

    // Create SVG
    _svg = d3.select(containerSelector)
      .append('svg')
      .attr('class', 'causation-graph-svg')
      .attr('width', '100%')
      .attr('height', _svgHeight);

    // Zoom behavior
    _zoom = d3.zoom()
      .scaleExtent([0.2, 3])
      .on('zoom', function (event) {
        _g.attr('transform', event.transform);
        if (!_minimapRafId) {
          _minimapRafId = requestAnimationFrame(function () {
            _minimapRafId = null;
            _updateMinimap();
          });
        }
      });

    _svg.call(_zoom);

    // Main group for zoomable content
    _g = _svg.append('g')
      .attr('class', 'cg-canvas')
      .attr('transform', 'translate(40, ' + (_svgHeight / 2) + ')');

    // Build hierarchy
    _root = d3.hierarchy(treeData, function (d) {
      return d._children || d.children;
    });
    _root.x0 = 0;
    _root.y0 = 0;

    // Progressive disclosure: auto-collapse deep branches for large chains.
    // Mutate the raw data first, then rebuild the hierarchy so D3 nodes
    // reflect the collapsed state.
    var totalNodes = _root.descendants().length;
    var needsRebuild = false;
    _root.descendants().forEach(function (d) {
      d.data._children = d.data.children;
      if (totalNodes >= PROGRESSIVE_THRESHOLD && d.depth >= 3 && d.data.children && d.data.children.length > 0) {
        d.data.children = null;
        needsRebuild = true;
      }
    });
    if (needsRebuild) {
      _root = d3.hierarchy(treeData, function (node) {
        return node.children;
      });
      _root.x0 = 0;
      _root.y0 = 0;
    }

    // Tree layout (horizontal: swap x/y)
    _treeFn = d3.tree().nodeSize([NODE_HEIGHT + NODE_MARGIN_Y, NODE_WIDTH + NODE_MARGIN_X]);

    _update(_root);

    // Render overlays: timeline axis, legend, mini-map
    // (swimlanes are rendered inside _update)
    _renderTimelineAxis();
    _renderLegend();
    _renderMinimap();

    // Auto-fit after initial render
    _fitToView(_svgWidth, _svgHeight);
  }

  /**
   * Destroy the current graph and clean up DOM.
   */
  function destroy() {
    if (_svg) {
      _svg.remove();
      _svg = null;
    }
    _g = null;
    _zoom = null;
    _root = null;
    _treeFn = null;
    _onNodeClick = null;
    _laneMap = {};
    _minimapG = null;
    _minimapBounds = null;
    _minimapScale = 1;
    if (_minimapRafId) {
      cancelAnimationFrame(_minimapRafId);
      _minimapRafId = null;
    }
  }

  // ---------------------------------------------------------------------------
  // Lane Map
  // ---------------------------------------------------------------------------

  function _buildLaneMap(treeData) {
    var categories = {};
    _collectCategories(treeData, categories);
    var sorted = Object.keys(categories).sort();
    var map = {};
    for (var i = 0; i < sorted.length; i++) {
      map[sorted[i]] = {
        index: i,
        color: LANE_COLORS[i % LANE_COLORS.length],
        label: sorted[i]
      };
    }
    return map;
  }

  function _collectCategories(node, cats) {
    if (!node) return;
    var cat = _extractStreamCategory(node.stream);
    if (cat) cats[cat] = true;
    var children = node._children || node.children;
    if (children) {
      for (var i = 0; i < children.length; i++) {
        _collectCategories(children[i], cats);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Layout & Rendering
  // ---------------------------------------------------------------------------

  function _update(source) {
    if (!_root || !_g) return;

    var treeData = _treeFn(_root);
    var nodes = treeData.descendants();
    var links = treeData.links();

    _renderSwimlanes(nodes);

    // --- Links ---
    var linkSel = _g.selectAll('.cg-link')
      .data(links, function (d) { return d.target.data.message_id; });

    var linkEnter = linkSel.enter()
      .insert('path', 'g')
      .attr('class', function (d) {
        var cls = 'cg-link';
        if (_isCrossAggregate(d.source.data, d.target.data)) {
          cls += ' cg-link--cross';
        }
        return cls;
      })
      .attr('d', function () {
        var o = { x: source.x0, y: source.y0 };
        return _diagonal(o, o);
      });

    var linkUpdate = linkEnter.merge(linkSel);
    linkUpdate.transition()
      .duration(TRANSITION_DURATION)
      .attr('d', function (d) {
        return _diagonal(d.source, d.target);
      });

    linkSel.exit()
      .transition()
      .duration(TRANSITION_DURATION)
      .attr('d', function () {
        var o = { x: source.x, y: source.y };
        return _diagonal(o, o);
      })
      .remove();

    // --- Fan-out indicators ---
    var fanOutNodes = nodes.filter(function (d) {
      return d.children && d.children.length > 1;
    });
    var fanSel = _g.selectAll('.cg-fanout')
      .data(fanOutNodes, function (d) { return 'fan-' + d.data.message_id; });

    fanSel.enter()
      .append('text')
      .attr('class', 'cg-fanout')
      .attr('text-anchor', 'start')
      .attr('dy', 4)
      .merge(fanSel)
      .transition()
      .duration(TRANSITION_DURATION)
      .attr('x', function (d) { return d.y + NODE_WIDTH + 6; })
      .attr('y', function (d) { return d.x; })
      .text(function (d) { return d.children.length + '\u00d7'; });

    fanSel.exit().remove();

    // --- Latency labels on links ---
    var labelSel = _g.selectAll('.cg-latency')
      .data(links.filter(function (d) { return d.target.data.delta_ms != null; }),
        function (d) { return 'lat-' + d.target.data.message_id; });

    var labelEnter = labelSel.enter()
      .append('text')
      .attr('class', 'cg-latency')
      .attr('text-anchor', 'middle')
      .attr('dy', -6);

    labelEnter.merge(labelSel)
      .transition()
      .duration(TRANSITION_DURATION)
      .attr('x', function (d) { return (d.source.y + d.target.y) / 2; })
      .attr('y', function (d) { return (d.source.x + d.target.x) / 2; })
      .text(function (d) {
        return _formatDuration(d.target.data.delta_ms);
      });

    labelSel.exit().remove();

    // --- Nodes ---
    var nodeSel = _g.selectAll('.cg-node')
      .data(nodes, function (d) { return d.data.message_id; });

    var nodeEnter = nodeSel.enter()
      .append('g')
      .attr('class', 'cg-node')
      .attr('transform', function () {
        return 'translate(' + source.y0 + ',' + source.x0 + ')';
      })
      .attr('tabindex', 0)
      .attr('role', 'button')
      .attr('aria-label', function (d) {
        var kind = d.data.kind === 'COMMAND' ? 'Command' : 'Event';
        return kind + ': ' + _shortTypeName(d.data.message_type);
      })
      .on('click', function (event, d) {
        event.stopPropagation();
        if (event.shiftKey || event.metaKey) {
          _toggleCollapse(d);
        } else {
          _onNodeClick(d.data.message_id);
        }
      })
      .on('keydown', function (event, d) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          if (event.shiftKey) {
            _toggleCollapse(d);
          } else {
            _onNodeClick(d.data.message_id);
          }
        }
      })
      .on('mouseenter', function (event, d) {
        _highlightPath(d, true);
      })
      .on('mouseleave', function (event, d) {
        _highlightPath(d, false);
      })
      .on('focus', function (event, d) {
        _highlightPath(d, true);
      })
      .on('blur', function (event, d) {
        _highlightPath(d, false);
      });

    // Swimlane accent bar (left edge of card, colored by stream category)
    nodeEnter.append('rect')
      .attr('class', 'cg-lane-accent')
      .attr('rx', 8)
      .attr('ry', 8)
      .attr('x', 0)
      .attr('y', -NODE_HEIGHT / 2)
      .attr('width', 4)
      .attr('height', NODE_HEIGHT)
      .attr('fill', function (d) {
        var cat = _extractStreamCategory(d.data.stream);
        var lane = _laneMap[cat];
        return lane ? lane.color : 'oklch(var(--bc) / 0.1)';
      });

    // Node card background
    nodeEnter.append('rect')
      .attr('class', 'cg-card')
      .attr('rx', 8)
      .attr('ry', 8)
      .attr('x', 0)
      .attr('y', -NODE_HEIGHT / 2)
      .attr('width', NODE_WIDTH)
      .attr('height', NODE_HEIGHT);

    // Kind badge
    nodeEnter.append('rect')
      .attr('class', function (d) {
        return 'cg-badge ' + (d.data.kind === 'COMMAND' ? 'cg-badge--cmd' : 'cg-badge--evt');
      })
      .attr('rx', 4)
      .attr('ry', 4)
      .attr('x', 8)
      .attr('y', -NODE_HEIGHT / 2 + 8)
      .attr('width', 32)
      .attr('height', 16);

    nodeEnter.append('text')
      .attr('class', 'cg-badge-text')
      .attr('x', 24)
      .attr('y', -NODE_HEIGHT / 2 + 20)
      .attr('text-anchor', 'middle')
      .text(function (d) { return d.data.kind === 'COMMAND' ? 'CMD' : 'EVT'; });

    // Message type (short name)
    nodeEnter.append('text')
      .attr('class', 'cg-type')
      .attr('x', 46)
      .attr('y', -NODE_HEIGHT / 2 + 20)
      .text(function (d) { return _shortTypeName(d.data.message_type); });

    // Handler name
    nodeEnter.append('text')
      .attr('class', 'cg-handler')
      .attr('x', 8)
      .attr('y', -NODE_HEIGHT / 2 + 38)
      .text(function (d) {
        var h = d.data.handler;
        return h ? _truncate(h, 30) : '';
      });

    // Duration
    nodeEnter.append('text')
      .attr('class', 'cg-duration')
      .attr('x', NODE_WIDTH - 8)
      .attr('y', -NODE_HEIGHT / 2 + 38)
      .attr('text-anchor', 'end')
      .text(function (d) {
        return d.data.duration_ms != null ? _formatDuration(d.data.duration_ms) : '';
      });

    // Stream name
    nodeEnter.append('text')
      .attr('class', 'cg-stream')
      .attr('x', 8)
      .attr('y', -NODE_HEIGHT / 2 + 54)
      .text(function (d) {
        return _truncate(d.data.stream || '', 28);
      });

    // Position badge
    nodeEnter.append('text')
      .attr('class', 'cg-position')
      .attr('x', NODE_WIDTH - 8)
      .attr('y', -NODE_HEIGHT / 2 + 54)
      .attr('text-anchor', 'end')
      .text(function (d) {
        return d.data.global_position != null ? '#' + d.data.global_position : '';
      });

    // Collapse indicator
    nodeEnter.append('text')
      .attr('class', 'cg-collapse-indicator')
      .attr('x', NODE_WIDTH - 8)
      .attr('y', -NODE_HEIGHT / 2 + 20)
      .attr('text-anchor', 'end');

    // Update + Enter
    var nodeUpdate = nodeEnter.merge(nodeSel);
    nodeUpdate.transition()
      .duration(TRANSITION_DURATION)
      .attr('transform', function (d) {
        return 'translate(' + d.y + ',' + d.x + ')';
      });

    // Update collapse indicator
    nodeUpdate.select('.cg-collapse-indicator')
      .text(function (d) {
        if (!d.data._children || d.data._children.length === 0) return '';
        return d.data.children ? '' : '+' + _countDescendants(d.data);
      });

    // Exit
    nodeSel.exit()
      .transition()
      .duration(TRANSITION_DURATION)
      .attr('transform', function () {
        return 'translate(' + source.y + ',' + source.x + ')';
      })
      .remove();

    // Stash positions for transition
    nodes.forEach(function (d) {
      d.x0 = d.x;
      d.y0 = d.y;
    });
  }

  // ---------------------------------------------------------------------------
  // Swimlane Backgrounds
  // ---------------------------------------------------------------------------

  function _renderSwimlanes(nodes) {
    if (!_g || !_root) return;
    if (!nodes) nodes = _root.descendants();
    if (nodes.length === 0) return;

    // Group nodes by stream category
    var laneNodes = {};
    nodes.forEach(function (d) {
      var cat = _extractStreamCategory(d.data.stream);
      if (!cat) return;
      if (!laneNodes[cat]) laneNodes[cat] = [];
      laneNodes[cat].push(d);
    });

    var laneData = [];
    var cats = Object.keys(laneNodes).sort();
    for (var i = 0; i < cats.length; i++) {
      var cat = cats[i];
      var catNodes = laneNodes[cat];
      var xMin = Infinity, xMax = -Infinity;
      var yMin = Infinity, yMax = -Infinity;
      for (var j = 0; j < catNodes.length; j++) {
        var n = catNodes[j];
        if (n.x - NODE_HEIGHT / 2 < xMin) xMin = n.x - NODE_HEIGHT / 2;
        if (n.x + NODE_HEIGHT / 2 > xMax) xMax = n.x + NODE_HEIGHT / 2;
        if (n.y < yMin) yMin = n.y;
        if (n.y + NODE_WIDTH > yMax) yMax = n.y + NODE_WIDTH;
      }
      var lane = _laneMap[cat];
      laneData.push({
        key: cat,
        label: lane ? lane.label : cat,
        color: lane ? lane.color : 'oklch(var(--bc) / 0.05)',
        x: yMin - SWIMLANE_PADDING,
        y: xMin - SWIMLANE_PADDING,
        width: (yMax - yMin) + SWIMLANE_PADDING * 2,
        height: (xMax - xMin) + SWIMLANE_PADDING * 2
      });
    }

    // Only render swimlanes if there are 2+ categories
    if (laneData.length < 2) {
      _g.selectAll('.cg-swimlane').remove();
      _g.selectAll('.cg-swimlane-label').remove();
      return;
    }

    // Background rects
    var laneSel = _g.selectAll('.cg-swimlane')
      .data(laneData, function (d) { return d.key; });

    laneSel.enter()
      .insert('rect', ':first-child')
      .attr('class', 'cg-swimlane')
      .attr('rx', 8)
      .attr('ry', 8)
      .merge(laneSel)
      .transition()
      .duration(TRANSITION_DURATION)
      .attr('x', function (d) { return d.x; })
      .attr('y', function (d) { return d.y; })
      .attr('width', function (d) { return d.width; })
      .attr('height', function (d) { return d.height; })
      .attr('fill', function (d) { return d.color; })
      .attr('fill-opacity', 0.06)
      .attr('stroke', function (d) { return d.color; })
      .attr('stroke-opacity', 0.15)
      .attr('stroke-width', 1);

    laneSel.exit().remove();

    // Labels
    var labelSel = _g.selectAll('.cg-swimlane-label')
      .data(laneData, function (d) { return 'lbl-' + d.key; });

    labelSel.enter()
      .append('text')
      .attr('class', 'cg-swimlane-label')
      .attr('text-anchor', 'start')
      .merge(labelSel)
      .transition()
      .duration(TRANSITION_DURATION)
      .attr('x', function (d) { return d.x + 8; })
      .attr('y', function (d) { return d.y + 14; })
      .text(function (d) { return d.label; })
      .attr('fill', function (d) { return d.color; });

    labelSel.exit().remove();
  }

  // ---------------------------------------------------------------------------
  // Timeline Axis
  // ---------------------------------------------------------------------------

  function _renderTimelineAxis() {
    if (!_g || !_root) return;

    // Remove any existing axis
    _g.selectAll('.cg-timeline-axis').remove();

    var nodes = _root.descendants();
    if (nodes.length === 0) return;

    // Parse root time and compute elapsed ms for each depth level
    var rootTime = _parseTime(_root.data.time);
    if (!rootTime) return;

    // Gather unique depth positions (y in horizontal layout) and their min time
    var depthMap = {};
    nodes.forEach(function (d) {
      var t = _parseTime(d.data.time);
      if (!t) return;
      var elapsed = t - rootTime;
      var key = Math.round(d.y);
      if (depthMap[key] === undefined || elapsed < depthMap[key]) {
        depthMap[key] = elapsed;
      }
    });

    var depthEntries = Object.keys(depthMap).map(function (k) {
      return { y: parseInt(k), elapsed: depthMap[k] };
    }).sort(function (a, b) { return a.y - b.y; });

    if (depthEntries.length < 2) return;

    // Find vertical extent for axis line
    var xMin = Infinity;
    nodes.forEach(function (d) {
      if (d.x - NODE_HEIGHT / 2 < xMin) xMin = d.x - NODE_HEIGHT / 2;
    });
    var axisY = xMin - 40;

    var axisG = _g.append('g').attr('class', 'cg-timeline-axis');

    // Axis line
    axisG.append('line')
      .attr('class', 'cg-axis-line')
      .attr('x1', depthEntries[0].y)
      .attr('x2', depthEntries[depthEntries.length - 1].y + NODE_WIDTH)
      .attr('y1', axisY)
      .attr('y2', axisY);

    // Tick marks and labels
    for (var i = 0; i < depthEntries.length; i++) {
      var entry = depthEntries[i];
      var tickX = entry.y + NODE_WIDTH / 2;

      axisG.append('line')
        .attr('class', 'cg-axis-tick')
        .attr('x1', tickX)
        .attr('x2', tickX)
        .attr('y1', axisY - 4)
        .attr('y2', axisY + 4);

      axisG.append('text')
        .attr('class', 'cg-axis-label')
        .attr('x', tickX)
        .attr('y', axisY - 8)
        .attr('text-anchor', 'middle')
        .text(entry.elapsed === 0 ? 'T\u2080' : '+' + _formatDuration(entry.elapsed));
    }
  }

  // ---------------------------------------------------------------------------
  // Legend
  // ---------------------------------------------------------------------------

  function _renderLegend() {
    if (!_svg) return;

    // Remove existing legend
    _svg.selectAll('.cg-legend').remove();

    var legendG = _svg.append('g')
      .attr('class', 'cg-legend')
      .attr('transform', 'translate(12, 12)');

    // Background
    legendG.append('rect')
      .attr('class', 'cg-legend-bg')
      .attr('rx', 6)
      .attr('ry', 6)
      .attr('x', 0)
      .attr('y', 0)
      .attr('width', 200)
      .attr('height', 88);

    var y = 16;
    var x = 12;

    // Command badge
    legendG.append('rect')
      .attr('class', 'cg-badge--cmd')
      .attr('rx', 3).attr('ry', 3)
      .attr('x', x).attr('y', y - 8)
      .attr('width', 24).attr('height', 12);
    legendG.append('text')
      .attr('class', 'cg-legend-text')
      .attr('x', x + 30).attr('y', y)
      .text('Command');

    // Event badge
    legendG.append('rect')
      .attr('class', 'cg-badge--evt')
      .attr('rx', 3).attr('ry', 3)
      .attr('x', x + 100).attr('y', y - 8)
      .attr('width', 24).attr('height', 12);
    legendG.append('text')
      .attr('class', 'cg-legend-text')
      .attr('x', x + 130).attr('y', y)
      .text('Event');

    y += 22;

    // Same-aggregate link
    legendG.append('line')
      .attr('class', 'cg-link')
      .attr('x1', x).attr('x2', x + 24)
      .attr('y1', y - 4).attr('y2', y - 4)
      .style('stroke', 'oklch(var(--bc) / 0.3)')
      .style('stroke-width', 1.5);
    legendG.append('text')
      .attr('class', 'cg-legend-text')
      .attr('x', x + 30).attr('y', y)
      .text('Same aggregate');

    y += 22;

    // Cross-aggregate link
    legendG.append('line')
      .attr('class', 'cg-link cg-link--cross')
      .attr('x1', x).attr('x2', x + 24)
      .attr('y1', y - 4).attr('y2', y - 4)
      .style('stroke-dasharray', '6 3')
      .style('stroke', 'oklch(var(--wa) / 0.5)')
      .style('stroke-width', 1.5);
    legendG.append('text')
      .attr('class', 'cg-legend-text')
      .attr('x', x + 30).attr('y', y)
      .text('Cross-aggregate');

    y += 22;

    // Duration badge
    legendG.append('text')
      .attr('class', 'cg-duration')
      .attr('x', x).attr('y', y)
      .text('12ms');
    legendG.append('text')
      .attr('class', 'cg-legend-text')
      .attr('x', x + 30).attr('y', y)
      .text('Handler duration');

    // Adjust background height to fit content
    legendG.select('.cg-legend-bg')
      .attr('height', y + 10);
  }

  // ---------------------------------------------------------------------------
  // Mini-Map
  // ---------------------------------------------------------------------------

  function _renderMinimap() {
    if (!_svg || !_root) return;

    var nodes = _root.descendants();
    if (nodes.length < 8) return;  // Only show for non-trivial graphs

    // Remove existing minimap
    _svg.selectAll('.cg-minimap').remove();

    var mmX = _svgWidth - MINIMAP_WIDTH - MINIMAP_MARGIN;
    var mmY = _svgHeight - MINIMAP_HEIGHT - MINIMAP_MARGIN;

    _minimapG = _svg.append('g')
      .attr('class', 'cg-minimap')
      .attr('transform', 'translate(' + mmX + ',' + mmY + ')');

    // Background
    _minimapG.append('rect')
      .attr('class', 'cg-minimap-bg')
      .attr('rx', 4)
      .attr('ry', 4)
      .attr('width', MINIMAP_WIDTH)
      .attr('height', MINIMAP_HEIGHT);

    // Cache graph bounds and scale for fast viewport updates during zoom
    _minimapBounds = _getGraphBounds(nodes);
    var gw = _minimapBounds.yMax - _minimapBounds.yMin + 40;
    var gh = _minimapBounds.xMax - _minimapBounds.xMin + 40;
    _minimapScale = Math.min(
      (MINIMAP_WIDTH - 8) / gw,
      (MINIMAP_HEIGHT - 8) / gh
    );

    var mmContentG = _minimapG.append('g')
      .attr('transform', 'translate(4, 4) scale(' + _minimapScale + ') translate(' + (-_minimapBounds.yMin + 20) + ',' + (-_minimapBounds.xMin + 20) + ')');

    var links = _root.links();
    links.forEach(function (l) {
      mmContentG.append('line')
        .attr('class', 'cg-minimap-link')
        .attr('x1', l.source.y + NODE_WIDTH / 2)
        .attr('y1', l.source.x)
        .attr('x2', l.target.y + NODE_WIDTH / 2)
        .attr('y2', l.target.x);
    });

    nodes.forEach(function (d) {
      mmContentG.append('rect')
        .attr('class', 'cg-minimap-node')
        .attr('x', d.y)
        .attr('y', d.x - 3)
        .attr('width', NODE_WIDTH)
        .attr('height', 6)
        .attr('rx', 2);
    });

    _minimapG.append('rect')
      .attr('class', 'cg-minimap-viewport')
      .attr('rx', 2)
      .attr('ry', 2);

    _updateMinimap();
  }

  function _updateMinimap() {
    if (!_minimapG || !_svg || !_minimapBounds) return;

    var viewport = _minimapG.select('.cg-minimap-viewport');
    if (viewport.empty()) return;

    var transform = d3.zoomTransform(_svg.node());

    // Map SVG viewport back to graph coordinates
    var invScale = 1 / transform.k;
    var vx = (-transform.x) * invScale;
    var vy = (-transform.y) * invScale;
    var vw = _svgWidth * invScale;
    var vh = _svgHeight * invScale;

    // Convert to minimap coordinates
    var ox = 4 + (vx - _minimapBounds.yMin + 20) * _minimapScale;
    var oy = 4 + (vy - _minimapBounds.xMin + 20) * _minimapScale;
    var ow = vw * _minimapScale;
    var oh = vh * _minimapScale;

    viewport
      .attr('x', Math.max(0, ox))
      .attr('y', Math.max(0, oy))
      .attr('width', Math.min(MINIMAP_WIDTH, ow))
      .attr('height', Math.min(MINIMAP_HEIGHT, oh));
  }

  // ---------------------------------------------------------------------------
  // Collapse / Expand
  // ---------------------------------------------------------------------------

  function _toggleCollapse(d) {
    if (d.data.children) {
      d.data.children = null;
    } else {
      d.data.children = d.data._children;
    }

    // Rebuild hierarchy preserving collapse state
    var rawRoot = _root.data;
    _root = d3.hierarchy(rawRoot, function (node) {
      return node.children;
    });
    _root.x0 = d.x;
    _root.y0 = d.y;

    _update(_root);
    _renderTimelineAxis();
    _renderMinimap();
  }

  function _countDescendants(nodeData) {
    if (!nodeData._children) return 0;
    var count = nodeData._children.length;
    for (var i = 0; i < nodeData._children.length; i++) {
      count += _countDescendants(nodeData._children[i]);
    }
    return count;
  }

  // ---------------------------------------------------------------------------
  // Path Highlighting
  // ---------------------------------------------------------------------------

  function _highlightPath(d, highlight) {
    var activeIds = {};
    var curr = d;
    while (curr) {
      activeIds[curr.data.message_id] = true;
      curr = curr.parent;
    }
    _collectDescendantIds(d, activeIds);

    _g.selectAll('.cg-node').each(function (n) {
      var active = activeIds[n.data.message_id];
      var sel = d3.select(this);
      sel.classed('cg-dimmed', highlight && !active);
      sel.classed('cg-highlighted', highlight && !!active);
    });

    _g.selectAll('.cg-link').each(function (l) {
      var active = activeIds[l.source.data.message_id] && activeIds[l.target.data.message_id];
      var sel = d3.select(this);
      sel.classed('cg-dimmed', highlight && !active);
      sel.classed('cg-highlighted', highlight && !!active);
    });
  }

  function _collectDescendantIds(d, ids) {
    if (!d.children) return;
    for (var i = 0; i < d.children.length; i++) {
      ids[d.children[i].data.message_id] = true;
      _collectDescendantIds(d.children[i], ids);
    }
  }

  // ---------------------------------------------------------------------------
  // Auto-Fit
  // ---------------------------------------------------------------------------

  function _fitToView(width, height) {
    if (!_svg || !_g || !_root) return;

    var nodes = _root.descendants();
    if (nodes.length === 0) return;

    var bounds = _getGraphBounds(nodes);
    var graphWidth = bounds.yMax - bounds.yMin + 80;
    var graphHeight = bounds.xMax - bounds.xMin + 80;

    var scale = Math.min(
      width / graphWidth,
      height / graphHeight,
      1.0
    );

    var tx = (width / 2) - (scale * (bounds.yMin + graphWidth / 2));
    var ty = (height / 2) - (scale * (bounds.xMin + graphHeight / 2));

    var transform = d3.zoomIdentity.translate(tx, ty).scale(scale);

    _svg.transition()
      .duration(TRANSITION_DURATION)
      .call(_zoom.transform, transform);
  }

  function _getGraphBounds(nodes) {
    var xMin = Infinity, xMax = -Infinity;
    var yMin = Infinity, yMax = -Infinity;
    nodes.forEach(function (d) {
      if (d.x - NODE_HEIGHT / 2 < xMin) xMin = d.x - NODE_HEIGHT / 2;
      if (d.x + NODE_HEIGHT / 2 > xMax) xMax = d.x + NODE_HEIGHT / 2;
      if (d.y < yMin) yMin = d.y;
      if (d.y + NODE_WIDTH > yMax) yMax = d.y + NODE_WIDTH;
    });
    return { xMin: xMin, xMax: xMax, yMin: yMin, yMax: yMax };
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _diagonal(s, d) {
    var midY = (s.y + d.y) / 2;
    return 'M' + s.y + ',' + s.x +
      'C' + midY + ',' + s.x +
      ' ' + midY + ',' + d.x +
      ' ' + d.y + ',' + d.x;
  }

  function _isCrossAggregate(parentData, childData) {
    if (!parentData.stream || !childData.stream) return false;
    var parentCat = _extractStreamCategory(parentData.stream);
    var childCat = _extractStreamCategory(childData.stream);
    return parentCat !== childCat;
  }

  function _extractStreamCategory(stream) {
    if (!stream) return '';
    var idx = stream.indexOf('-');
    return idx > 0 ? stream.substring(0, idx) : stream;
  }

  function _shortTypeName(fullType) {
    if (!fullType) return '';
    var parts = fullType.split('.');
    if (parts.length >= 2) return parts[parts.length - 2];
    return parts[parts.length - 1];
  }

  function _truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.substring(0, maxLen - 1) + '\u2026' : str;
  }

  function _formatDuration(ms) {
    if (ms == null) return '';
    return Observatory.fmt.duration(ms);
  }

  function _parseTime(timeStr) {
    if (!timeStr) return null;
    var d = new Date(timeStr);
    return isNaN(d.getTime()) ? null : d.getTime();
  }

  // ---------------------------------------------------------------------------
  // Live Update
  // ---------------------------------------------------------------------------

  /**
   * Update the graph with new tree data, animating new nodes.
   *
   * Diffs the old tree against newTreeData by message_id to identify nodes
   * that were not present before. New nodes fade in with a highlight pulse.
   * The layout is recomputed and all overlays (swimlanes, axis, minimap)
   * are refreshed.
   *
   * @param {object} newTreeData  Fresh CausationNode tree from the API
   * @returns {string[]}  Array of message_ids for newly added nodes
   */
  function update(newTreeData) {
    if (!_svg || !_g || !_root || !newTreeData) return [];

    // Collect existing message_ids before update
    var oldIds = {};
    _root.descendants().forEach(function (d) {
      oldIds[d.data.message_id] = true;
    });

    // Also collect ids from collapsed branches (._children in raw data)
    _collectAllIds(_root.data, oldIds);

    // Preserve collapse state: transfer _children/children from old data
    _transferCollapseState(_root.data, newTreeData);

    // Rebuild hierarchy from new data
    _root = d3.hierarchy(newTreeData, function (node) {
      return node.children;
    });
    _root.x0 = 0;
    _root.y0 = 0;

    // Rebuild lane map (new streams may have appeared)
    _laneMap = _buildLaneMap(newTreeData);

    // Re-run layout
    _update(_root);

    // Identify new nodes and apply highlight animation
    var newIds = [];
    _root.descendants().forEach(function (d) {
      if (!oldIds[d.data.message_id]) {
        newIds.push(d.data.message_id);
      }
    });

    if (newIds.length > 0) {
      var newIdSet = {};
      for (var i = 0; i < newIds.length; i++) {
        newIdSet[newIds[i]] = true;
      }

      _g.selectAll('.cg-node').each(function (d) {
        if (newIdSet[d.data.message_id]) {
          d3.select(this).classed('cg-node-new', true);
        }
      });

      _g.selectAll('.cg-link').each(function (l) {
        if (newIdSet[l.target.data.message_id]) {
          d3.select(this).classed('cg-link-new', true);
        }
      });

      // Remove highlight class after animation completes
      setTimeout(function () {
        if (_g) {
          _g.selectAll('.cg-node-new').classed('cg-node-new', false);
          _g.selectAll('.cg-link-new').classed('cg-link-new', false);
        }
      }, 2000);
    }

    // Refresh overlays
    _renderTimelineAxis();
    _renderLegend();
    _renderMinimap();

    return newIds;
  }

  /**
   * Collect all message_ids from raw tree data (including collapsed _children).
   */
  function _collectAllIds(nodeData, ids) {
    if (!nodeData) return;
    if (nodeData.message_id) ids[nodeData.message_id] = true;
    var children = nodeData._children || nodeData.children;
    if (children) {
      for (var i = 0; i < children.length; i++) {
        _collectAllIds(children[i], ids);
      }
    }
  }

  /**
   * Transfer collapse state from oldData to newData by matching message_id.
   * If a node was collapsed in oldData (children === null, _children present),
   * apply the same collapse in newData.
   */
  function _transferCollapseState(oldData, newData) {
    if (!oldData || !newData) return;
    if (oldData.message_id !== newData.message_id) return;

    // Preserve _children reference for progressive disclosure
    if (newData.children) {
      newData._children = newData.children;
    }

    // If old node was collapsed, collapse the new one too
    if (oldData._children && !oldData.children) {
      newData.children = null;
    }

    // Recurse into matching children
    var oldChildren = oldData._children || oldData.children;
    var newChildren = newData._children || newData.children;
    if (oldChildren && newChildren) {
      // Build lookup by message_id for efficient matching
      var oldByMid = {};
      for (var i = 0; i < oldChildren.length; i++) {
        if (oldChildren[i].message_id) {
          oldByMid[oldChildren[i].message_id] = oldChildren[i];
        }
      }
      for (var j = 0; j < newChildren.length; j++) {
        var match = oldByMid[newChildren[j].message_id];
        if (match) {
          _transferCollapseState(match, newChildren[j]);
        }
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Exports
  // ---------------------------------------------------------------------------

  return {
    render: render,
    update: update,
    destroy: destroy
  };
})();
