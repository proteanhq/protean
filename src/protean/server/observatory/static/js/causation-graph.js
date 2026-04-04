/**
 * Causation Graph Module — D3-Based Interactive Visualization
 *
 * Renders a horizontal left-to-right tree layout of causation chains
 * using D3.js. Supports zoom/pan, collapse/expand subtrees, hover
 * highlighting of causal paths, and click-to-detail.
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

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  var _svg = null;
  var _g = null;         // Main group (transformed by zoom)
  var _zoom = null;
  var _root = null;      // D3 hierarchy root
  var _treeFn = null;    // d3.tree() layout
  var _onNodeClick = null;

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
    var width = rect.width || 800;
    var height = Math.max(400, rect.height || 500);

    // Create SVG
    _svg = d3.select(containerSelector)
      .append('svg')
      .attr('class', 'causation-graph-svg')
      .attr('width', '100%')
      .attr('height', height);

    // Zoom behavior
    _zoom = d3.zoom()
      .scaleExtent([0.2, 3])
      .on('zoom', function (event) {
        _g.attr('transform', event.transform);
      });

    _svg.call(_zoom);

    // Main group for zoomable content
    _g = _svg.append('g')
      .attr('class', 'cg-canvas')
      .attr('transform', 'translate(40, ' + (height / 2) + ')');

    // Build hierarchy
    _root = d3.hierarchy(treeData, function (d) {
      return d._children || d.children;
    });
    _root.x0 = 0;
    _root.y0 = 0;

    // Preserve original children for collapse/expand
    _root.descendants().forEach(function (d) {
      d.data._children = d.data.children;
    });

    // Tree layout (horizontal: swap x/y)
    _treeFn = d3.tree().nodeSize([NODE_HEIGHT + NODE_MARGIN_Y, NODE_WIDTH + NODE_MARGIN_X]);

    _update(_root);

    // Auto-fit after initial render
    _fitToView(width, height);
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
  }

  // ---------------------------------------------------------------------------
  // Layout & Rendering
  // ---------------------------------------------------------------------------

  function _update(source) {
    if (!_root || !_g) return;

    var treeData = _treeFn(_root);
    var nodes = treeData.descendants();
    var links = treeData.links();

    // Horizontal layout: d3.tree uses x for vertical, y for horizontal
    // We swap: node.y = depth * spacing (horizontal), node.x = separation (vertical)

    // --- Links ---
    var linkSel = _g.selectAll('.cg-link')
      .data(links, function (d) { return d.target.data.message_id; });

    // Enter
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

    // Update + Enter
    var linkUpdate = linkEnter.merge(linkSel);
    linkUpdate.transition()
      .duration(TRANSITION_DURATION)
      .attr('d', function (d) {
        return _diagonal(d.source, d.target);
      });

    // Exit
    linkSel.exit()
      .transition()
      .duration(TRANSITION_DURATION)
      .attr('d', function () {
        var o = { x: source.x, y: source.y };
        return _diagonal(o, o);
      })
      .remove();

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

    // Enter
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
    // Collect ancestors
    var curr = d;
    while (curr) {
      activeIds[curr.data.message_id] = true;
      curr = curr.parent;
    }
    // Collect descendants
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

    var xMin = Infinity, xMax = -Infinity;
    var yMin = Infinity, yMax = -Infinity;
    nodes.forEach(function (d) {
      var nx = d.x - NODE_HEIGHT / 2;
      var ny = d.y;
      if (nx < xMin) xMin = nx;
      if (d.x + NODE_HEIGHT / 2 > xMax) xMax = d.x + NODE_HEIGHT / 2;
      if (ny < yMin) yMin = ny;
      if (ny + NODE_WIDTH > yMax) yMax = ny + NODE_WIDTH;
    });

    var graphWidth = yMax - yMin + 80;
    var graphHeight = xMax - xMin + 80;

    var scale = Math.min(
      width / graphWidth,
      height / graphHeight,
      1.0  // Don't zoom in beyond 100%
    );

    var tx = (width / 2) - (scale * (yMin + graphWidth / 2));
    var ty = (height / 2) - (scale * (xMin + graphHeight / 2));

    var transform = d3.zoomIdentity.translate(tx, ty).scale(scale);

    _svg.transition()
      .duration(TRANSITION_DURATION)
      .call(_zoom.transform, transform);
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _diagonal(s, d) {
    // Cubic bezier from source to target (horizontal layout)
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

  // ---------------------------------------------------------------------------
  // Exports
  // ---------------------------------------------------------------------------

  return {
    render: render,
    destroy: destroy
  };
})();
