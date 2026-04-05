/**
 * Domain Topology Module — D3 Force-Directed Graph
 *
 * Renders an interactive force-directed graph of aggregate clusters.
 * Nodes represent aggregates; edges represent cross-aggregate relationships
 * (event handlers, process managers, projections).
 *
 * Usage:
 *   DomainTopology.render(containerSelector, graphData, onNodeClick);
 *   DomainTopology.destroy();
 */
var DomainTopology = (function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------------

  var NODE_WIDTH = 200;
  var NODE_HEIGHT = 80;
  var MINIMAP_WIDTH = 140;
  var MINIMAP_HEIGHT = 90;
  var MINIMAP_MARGIN = 12;

  // Color palette (reuse causation-graph OKLCH colors)
  var NODE_COLORS = [
    'oklch(0.75 0.12 250)',  // blue
    'oklch(0.75 0.12 150)',  // green
    'oklch(0.75 0.12 30)',   // orange
    'oklch(0.75 0.12 320)',  // purple
    'oklch(0.75 0.12 80)',   // yellow-green
    'oklch(0.75 0.12 200)',  // teal
    'oklch(0.75 0.12 350)',  // pink
    'oklch(0.75 0.12 110)',  // lime
  ];

  // Link style configs by relationship type
  var LINK_STYLES = {
    event:           { dasharray: 'none' },
    process_manager: { dasharray: '8 4' },
  };

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  var _svg = null;
  var _g = null;           // Main canvas group (transformed by zoom)
  var _zoom = null;
  var _simulation = null;  // D3 force simulation
  var _onNodeClick = null;
  var _colorMap = {};      // aggregate fqn -> color
  var _svgWidth = 800;
  var _svgHeight = 500;
  var _minimapG = null;
  var _minimapRafId = null;
  var _minimapBounds = null;  // Cached graph bounds for minimap viewport updates
  var _minimapScale = 1;
  var _nodes = [];
  var _links = [];
  var _nodeSel = null;
  var _linkSel = null;
  var _labelSel = null;

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Render the topology graph.
   *
   * @param {string} containerSelector  CSS selector for the container
   * @param {object} graphData          { nodes, links } from /api/domain/ir
   * @param {function} onNodeClick      Callback(fqn) when a node is clicked
   */
  function render(containerSelector, graphData, onNodeClick) {
    destroy();
    _onNodeClick = onNodeClick || function () {};

    var container = document.querySelector(containerSelector);
    if (!container) return;

    var nodes = graphData.nodes || [];
    if (nodes.length === 0) {
      container.innerHTML =
        '<div class="flex items-center justify-center h-64 text-base-content/40">' +
        'No aggregates found in domain.</div>';
      return;
    }

    // Single aggregate — show centered, no force simulation needed
    if (nodes.length === 1) {
      _renderSingleNode(container, nodes[0]);
      return;
    }

    var rect = container.getBoundingClientRect();
    _svgWidth = rect.width || 800;
    _svgHeight = Math.max(400, rect.height || 500);

    // Deep-copy nodes/links so D3 mutation doesn't affect source data
    _nodes = nodes.map(function (n) { return Object.assign({}, n); });
    _links = (graphData.links || []).map(function (l) { return Object.assign({}, l); });

    // Build color map
    _colorMap = _buildColorMap(_nodes);

    // Create SVG
    _svg = d3.select(containerSelector)
      .append('svg')
      .attr('class', 'dv-topology-svg')
      .attr('width', '100%')
      .attr('height', _svgHeight);

    // Arrow marker defs
    _renderArrowDefs();

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

    // Main canvas group
    _g = _svg.append('g').attr('class', 'dv-canvas');

    // Render links first (behind nodes)
    _renderLinks();

    // Render nodes
    _renderNodes();

    // Force simulation
    _simulation = d3.forceSimulation(_nodes)
      .force('link', d3.forceLink(_links)
        .id(function (d) { return d.id; })
        .distance(function (d) { return 220 + (_links.length > 5 ? 40 : 0); })
      )
      .force('charge', d3.forceManyBody()
        .strength(function () { return -800; })
      )
      .force('center', d3.forceCenter(_svgWidth / 2, _svgHeight / 2))
      .force('collision', d3.forceCollide()
        .radius(NODE_WIDTH / 2 + 20)
      )
      .force('x', d3.forceX(_svgWidth / 2).strength(0.05))
      .force('y', d3.forceY(_svgHeight / 2).strength(0.05))
      .on('tick', _onTick)
      .on('end', function () {
        _renderMinimap();
      });

    // Render legend
    _renderLegend();
  }

  /**
   * Destroy the current graph and clean up.
   */
  function destroy() {
    if (_simulation) {
      _simulation.stop();
      _simulation = null;
    }
    if (_svg) {
      _svg.remove();
      _svg = null;
    }
    _g = null;
    _zoom = null;
    _onNodeClick = null;
    _colorMap = {};
    _minimapG = null;
    _minimapBounds = null;
    _minimapScale = 1;
    _nodes = [];
    _links = [];
    _nodeSel = null;
    _linkSel = null;
    _labelSel = null;
    if (_minimapRafId) {
      cancelAnimationFrame(_minimapRafId);
      _minimapRafId = null;
    }
  }

  // ---------------------------------------------------------------------------
  // Single-node rendering (no force simulation needed)
  // ---------------------------------------------------------------------------

  function _renderSingleNode(container, node) {
    var color = NODE_COLORS[0];
    var counts = node.counts || {};
    var badges = _buildBadgeText(counts);

    var html = '<div class="flex items-center justify-center" style="min-height:300px">';
    html += '<div class="card bg-base-200 shadow-md cursor-pointer dv-node-card" ';
    html += 'data-fqn="' + _esc(node.fqn) + '" style="border-left:4px solid ' + color + ';min-width:240px">';
    html += '<div class="card-body p-5">';
    html += '<div class="font-bold text-lg">' + _esc(node.name) + '</div>';
    html += '<div class="text-xs text-base-content/50 font-mono mb-2">' + _esc(node.stream_category || '') + '</div>';
    if (node.is_event_sourced) {
      html += '<span class="badge badge-sm badge-primary mb-2">Event Sourced</span> ';
    } else {
      html += '<span class="badge badge-sm badge-secondary mb-2">CQRS</span> ';
    }
    if (badges) {
      html += '<div class="text-xs text-base-content/60">' + _esc(badges) + '</div>';
    }
    html += '</div></div></div>';
    container.innerHTML = html;
  }

  // ---------------------------------------------------------------------------
  // Color Map
  // ---------------------------------------------------------------------------

  function _buildColorMap(nodes) {
    var map = {};
    var sorted = nodes.slice().sort(function (a, b) {
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
    for (var i = 0; i < sorted.length; i++) {
      map[sorted[i].id] = NODE_COLORS[i % NODE_COLORS.length];
    }
    return map;
  }

  // ---------------------------------------------------------------------------
  // Arrow Marker Definitions
  // ---------------------------------------------------------------------------

  function _renderArrowDefs() {
    if (!_svg) return;

    var defs = _svg.append('defs');
    var markers = [
      { id: 'dv-arrow', cls: 'dv-arrow-head' },
      { id: 'dv-arrow-pm', cls: 'dv-arrow-head-pm' },
    ];

    markers.forEach(function (cfg) {
      defs.append('marker')
        .attr('id', cfg.id)
        .attr('viewBox', '0 0 10 10')
        .attr('refX', 10)
        .attr('refY', 5)
        .attr('markerWidth', 8)
        .attr('markerHeight', 8)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M 0 0 L 10 5 L 0 10 Z')
        .attr('class', cfg.cls);
    });
  }

  // ---------------------------------------------------------------------------
  // Link Rendering
  // ---------------------------------------------------------------------------

  function _renderLinks() {
    if (!_g) return;

    var linkG = _g.append('g').attr('class', 'dv-links');

    _linkSel = linkG.selectAll('.dv-link')
      .data(_links)
      .enter()
      .append('path')
      .attr('class', function (d) {
        return 'dv-link dv-link--' + d.type;
      })
      .attr('stroke-dasharray', function (d) {
        var style = LINK_STYLES[d.type] || LINK_STYLES.event;
        return style.dasharray;
      })
      .attr('marker-end', function (d) {
        return d.type === 'process_manager' ? 'url(#dv-arrow-pm)' : 'url(#dv-arrow)';
      });

    // Edge labels
    _labelSel = linkG.selectAll('.dv-link-label')
      .data(_links)
      .enter()
      .append('text')
      .attr('class', 'dv-link-label')
      .attr('text-anchor', 'middle')
      .attr('dy', -6)
      .text(function (d) { return d.label || ''; });
  }

  // ---------------------------------------------------------------------------
  // Node Rendering
  // ---------------------------------------------------------------------------

  function _renderNodes() {
    if (!_g) return;

    var nodeG = _g.append('g').attr('class', 'dv-nodes');

    _nodeSel = nodeG.selectAll('.dv-node')
      .data(_nodes, function (d) { return d.id; })
      .enter()
      .append('g')
      .attr('class', 'dv-node')
      .attr('tabindex', 0)
      .attr('role', 'button')
      .attr('aria-label', function (d) {
        return 'Aggregate: ' + d.name;
      })
      .on('click', function (event, d) {
        event.stopPropagation();
        _onNodeClick(d.fqn);
      })
      .on('keydown', function (event, d) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          _onNodeClick(d.fqn);
        }
      })
      .on('mouseenter', function (event, d) {
        _highlightConnected(d, true);
      })
      .on('mouseleave', function (event, d) {
        _highlightConnected(d, false);
      })
      .call(d3.drag()
        .on('start', _onDragStart)
        .on('drag', _onDrag)
        .on('end', _onDragEnd)
      );

    // Lane accent bar (left edge, colored)
    _nodeSel.append('rect')
      .attr('class', 'dv-lane-accent')
      .attr('rx', 8)
      .attr('ry', 8)
      .attr('x', -NODE_WIDTH / 2)
      .attr('y', -NODE_HEIGHT / 2)
      .attr('width', 4)
      .attr('height', NODE_HEIGHT)
      .attr('fill', function (d) {
        return _colorMap[d.id] || NODE_COLORS[0];
      });

    // Card background
    _nodeSel.append('rect')
      .attr('class', 'dv-card')
      .attr('rx', 8)
      .attr('ry', 8)
      .attr('x', -NODE_WIDTH / 2)
      .attr('y', -NODE_HEIGHT / 2)
      .attr('width', NODE_WIDTH)
      .attr('height', NODE_HEIGHT);

    // Aggregate name
    _nodeSel.append('text')
      .attr('class', 'dv-name')
      .attr('x', -NODE_WIDTH / 2 + 14)
      .attr('y', -NODE_HEIGHT / 2 + 22)
      .text(function (d) { return d.name; });

    // Stream category
    _nodeSel.append('text')
      .attr('class', 'dv-stream')
      .attr('x', -NODE_WIDTH / 2 + 14)
      .attr('y', -NODE_HEIGHT / 2 + 38)
      .text(function (d) { return d.stream_category || ''; });

    // Architecture badge (ES vs CQRS)
    _nodeSel.append('rect')
      .attr('class', function (d) {
        return 'dv-arch-badge ' + (d.is_event_sourced ? 'dv-arch-badge--es' : 'dv-arch-badge--cqrs');
      })
      .attr('rx', 3)
      .attr('ry', 3)
      .attr('x', NODE_WIDTH / 2 - 36)
      .attr('y', -NODE_HEIGHT / 2 + 8)
      .attr('width', 28)
      .attr('height', 14);

    _nodeSel.append('text')
      .attr('class', 'dv-arch-badge-text')
      .attr('x', NODE_WIDTH / 2 - 22)
      .attr('y', -NODE_HEIGHT / 2 + 19)
      .attr('text-anchor', 'middle')
      .text(function (d) { return d.is_event_sourced ? 'ES' : 'CQRS'; });

    // Element counts
    _nodeSel.append('text')
      .attr('class', 'dv-counts')
      .attr('x', -NODE_WIDTH / 2 + 14)
      .attr('y', -NODE_HEIGHT / 2 + 56)
      .text(function (d) {
        return _buildBadgeText(d.counts || {});
      });

    // Selected ring (hidden by default)
    _nodeSel.append('rect')
      .attr('class', 'dv-select-ring')
      .attr('rx', 10)
      .attr('ry', 10)
      .attr('x', -NODE_WIDTH / 2 - 3)
      .attr('y', -NODE_HEIGHT / 2 - 3)
      .attr('width', NODE_WIDTH + 6)
      .attr('height', NODE_HEIGHT + 6)
      .style('display', 'none');
  }

  // ---------------------------------------------------------------------------
  // Force Simulation Tick
  // ---------------------------------------------------------------------------

  function _onTick() {
    if (_linkSel) {
      _linkSel.attr('d', function (d) {
        return _linkPath(d.source, d.target);
      });
    }

    if (_labelSel) {
      _labelSel
        .attr('x', function (d) { return (d.source.x + d.target.x) / 2; })
        .attr('y', function (d) { return (d.source.y + d.target.y) / 2; });
    }

    if (_nodeSel) {
      _nodeSel.attr('transform', function (d) {
        return 'translate(' + d.x + ',' + d.y + ')';
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Link Path (curved)
  // ---------------------------------------------------------------------------

  function _linkPath(source, target) {
    var dx = target.x - source.x;
    var dy = target.y - source.y;
    var dist = Math.sqrt(dx * dx + dy * dy);
    if (dist === 0) return 'M0,0';

    // Offset start/end to node edge
    var ux = dx / dist;
    var uy = dy / dist;
    var sx = source.x + ux * (NODE_WIDTH / 2 + 4);
    var sy = source.y + uy * (NODE_HEIGHT / 2 + 4);
    var tx = target.x - ux * (NODE_WIDTH / 2 + 12);
    var ty = target.y - uy * (NODE_HEIGHT / 2 + 12);

    // Gentle curve
    var mx = (sx + tx) / 2;
    var my = (sy + ty) / 2;
    var cx = mx - (ty - sy) * 0.15;
    var cy = my + (tx - sx) * 0.15;

    return 'M' + sx + ',' + sy + ' Q' + cx + ',' + cy + ' ' + tx + ',' + ty;
  }

  // ---------------------------------------------------------------------------
  // Drag Handlers
  // ---------------------------------------------------------------------------

  function _onDragStart(event, d) {
    if (!event.active) _simulation.alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;
  }

  function _onDrag(event, d) {
    d.fx = event.x;
    d.fy = event.y;
  }

  function _onDragEnd(event, d) {
    if (!event.active) _simulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;
  }

  // ---------------------------------------------------------------------------
  // Hover Highlighting
  // ---------------------------------------------------------------------------

  function _highlightConnected(node, highlight) {
    if (!_g) return;

    var connectedIds = {};
    connectedIds[node.id] = true;

    _links.forEach(function (l) {
      var sid = _linkId(l.source);
      var tid = _linkId(l.target);
      if (sid === node.id) connectedIds[tid] = true;
      if (tid === node.id) connectedIds[sid] = true;
    });

    _g.selectAll('.dv-node').each(function (d) {
      var sel = d3.select(this);
      sel.classed('dv-dimmed', highlight && !connectedIds[d.id]);
      sel.classed('dv-highlighted', highlight && !!connectedIds[d.id]);
    });

    _g.selectAll('.dv-link').each(function (l) {
      var active = connectedIds[_linkId(l.source)] && connectedIds[_linkId(l.target)];
      var sel = d3.select(this);
      sel.classed('dv-dimmed', highlight && !active);
      sel.classed('dv-highlighted', highlight && !!active);
    });

    _g.selectAll('.dv-link-label').each(function (l) {
      var active = connectedIds[_linkId(l.source)] && connectedIds[_linkId(l.target)];
      d3.select(this).classed('dv-dimmed', highlight && !active);
    });
  }

  // ---------------------------------------------------------------------------
  // Legend
  // ---------------------------------------------------------------------------

  function _renderLegend() {
    if (!_svg) return;

    _svg.selectAll('.dv-legend').remove();

    var legendG = _svg.append('g')
      .attr('class', 'dv-legend')
      .attr('transform', 'translate(12, 12)');

    // Background
    legendG.append('rect')
      .attr('class', 'dv-legend-bg')
      .attr('rx', 6)
      .attr('ry', 6)
      .attr('width', 180)
      .attr('height', 60);

    var y = 16;
    var x = 12;

    // Event link
    legendG.append('line')
      .attr('class', 'dv-link dv-link--event')
      .attr('x1', x).attr('x2', x + 24)
      .attr('y1', y - 3).attr('y2', y - 3)
      .style('stroke-dasharray', 'none');
    legendG.append('text')
      .attr('class', 'dv-legend-text')
      .attr('x', x + 30).attr('y', y)
      .text('Event flow');

    y += 22;

    // Process Manager link
    legendG.append('line')
      .attr('class', 'dv-link dv-link--process_manager')
      .attr('x1', x).attr('x2', x + 24)
      .attr('y1', y - 3).attr('y2', y - 3)
      .style('stroke-dasharray', '8 4');
    legendG.append('text')
      .attr('class', 'dv-legend-text')
      .attr('x', x + 30).attr('y', y)
      .text('Process manager');
  }

  // ---------------------------------------------------------------------------
  // Mini-Map
  // ---------------------------------------------------------------------------

  function _renderMinimap() {
    if (!_svg || !_nodes || _nodes.length < 4) return;

    _svg.selectAll('.dv-minimap').remove();

    var mmX = _svgWidth - MINIMAP_WIDTH - MINIMAP_MARGIN;
    var mmY = _svgHeight - MINIMAP_HEIGHT - MINIMAP_MARGIN;

    _minimapG = _svg.append('g')
      .attr('class', 'dv-minimap')
      .attr('transform', 'translate(' + mmX + ',' + mmY + ')');

    // Background
    _minimapG.append('rect')
      .attr('class', 'dv-minimap-bg')
      .attr('rx', 4)
      .attr('ry', 4)
      .attr('width', MINIMAP_WIDTH)
      .attr('height', MINIMAP_HEIGHT);

    // Cache bounds and scale for fast viewport updates during zoom
    _minimapBounds = _getGraphBounds();
    var gw = _minimapBounds.xMax - _minimapBounds.xMin + 40;
    var gh = _minimapBounds.yMax - _minimapBounds.yMin + 40;
    _minimapScale = Math.min(
      (MINIMAP_WIDTH - 8) / gw,
      (MINIMAP_HEIGHT - 8) / gh
    );

    var mmContentG = _minimapG.append('g')
      .attr('class', 'dv-minimap-content')
      .attr('transform', 'translate(4, 4) scale(' + _minimapScale + ') translate(' +
        (-_minimapBounds.xMin + 20) + ',' + (-_minimapBounds.yMin + 20) + ')');

    // Links
    _links.forEach(function (l) {
      var sx = typeof l.source === 'object' ? l.source.x : 0;
      var sy = typeof l.source === 'object' ? l.source.y : 0;
      var tx = typeof l.target === 'object' ? l.target.x : 0;
      var ty = typeof l.target === 'object' ? l.target.y : 0;
      mmContentG.append('line')
        .attr('class', 'dv-minimap-link')
        .attr('x1', sx).attr('y1', sy)
        .attr('x2', tx).attr('y2', ty);
    });

    // Nodes
    _nodes.forEach(function (d) {
      mmContentG.append('rect')
        .attr('class', 'dv-minimap-node')
        .attr('x', d.x - 6)
        .attr('y', d.y - 3)
        .attr('width', 12)
        .attr('height', 6)
        .attr('rx', 2)
        .attr('fill', _colorMap[d.id] || NODE_COLORS[0]);
    });

    // Viewport rectangle
    _minimapG.append('rect')
      .attr('class', 'dv-minimap-viewport')
      .attr('rx', 2)
      .attr('ry', 2);

    _updateMinimap();
  }

  function _updateMinimap() {
    if (!_minimapG || !_svg || !_minimapBounds) return;

    var viewport = _minimapG.select('.dv-minimap-viewport');
    if (viewport.empty()) return;

    var transform = d3.zoomTransform(_svg.node());

    var invScale = 1 / transform.k;
    var vx = (-transform.x) * invScale;
    var vy = (-transform.y) * invScale;
    var vw = _svgWidth * invScale;
    var vh = _svgHeight * invScale;

    var ox = 4 + (vx - _minimapBounds.xMin + 20) * _minimapScale;
    var oy = 4 + (vy - _minimapBounds.yMin + 20) * _minimapScale;
    var ow = vw * _minimapScale;
    var oh = vh * _minimapScale;

    viewport
      .attr('x', Math.max(0, ox))
      .attr('y', Math.max(0, oy))
      .attr('width', Math.min(MINIMAP_WIDTH, ow))
      .attr('height', Math.min(MINIMAP_HEIGHT, oh));
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _getGraphBounds() {
    var xMin = Infinity, xMax = -Infinity;
    var yMin = Infinity, yMax = -Infinity;
    _nodes.forEach(function (d) {
      if (d.x - NODE_WIDTH / 2 < xMin) xMin = d.x - NODE_WIDTH / 2;
      if (d.x + NODE_WIDTH / 2 > xMax) xMax = d.x + NODE_WIDTH / 2;
      if (d.y - NODE_HEIGHT / 2 < yMin) yMin = d.y - NODE_HEIGHT / 2;
      if (d.y + NODE_HEIGHT / 2 > yMax) yMax = d.y + NODE_HEIGHT / 2;
    });
    return { xMin: xMin, xMax: xMax, yMin: yMin, yMax: yMax };
  }

  function _linkId(ref) {
    return typeof ref === 'object' ? ref.id : ref;
  }

  function _buildBadgeText(counts) {
    var parts = [];
    if (counts.commands) parts.push(counts.commands + ' cmd');
    if (counts.events) parts.push(counts.events + ' evt');
    if (counts.entities) parts.push(counts.entities + ' ent');
    if (counts.value_objects) parts.push(counts.value_objects + ' vo');
    if (counts.event_handlers) parts.push(counts.event_handlers + ' hdl');
    return parts.join(' \u00b7 ');
  }

  function _esc(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str || ''));
    return div.innerHTML.replace(/"/g, '&quot;');
  }

  // ---------------------------------------------------------------------------
  // Module Export
  // ---------------------------------------------------------------------------

  return {
    render: render,
    destroy: destroy,
  };
})();
