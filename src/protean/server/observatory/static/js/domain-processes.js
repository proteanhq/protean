/**
 * Domain Processes Module — D3 State Machine Diagrams
 *
 * Renders each process manager as a visual state machine diagram:
 *   - States shown as circles/rounded rectangles
 *   - Transitions shown as directed arrows labeled with triggering events
 *   - Start state marked with double border
 *   - Terminal states marked with filled style
 *   - Aggregate badges on each PM card
 *
 * Usage:
 *   DomainProcesses.render('#dv-pm-container', pmGraphs);
 *   DomainProcesses.destroy();
 */
var DomainProcesses = (function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------------

  var STATE_RADIUS = 28;
  var STATE_SPACING_X = 180;
  var CARD_PADDING = 24;

  var STATE_COLORS = {
    start:        { fill: 'var(--color-base-100)', stroke: 'oklch(0.55 0.12 300)', strokeWidth: 3 },
    intermediate: { fill: 'var(--color-base-100)', stroke: 'oklch(0.55 0.10 250)', strokeWidth: 2 },
    end:          { fill: 'oklch(0.55 0.10 150)',  stroke: 'oklch(0.55 0.10 150)', strokeWidth: 2 },
  };

  var EDGE_COLOR = 'oklch(0.55 0.10 250)';
  var EDGE_COLOR_END = 'oklch(0.55 0.10 150)';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  var _container = null;
  var _expanded = {};  // pm fqn -> bool (track expand/collapse)

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  function render(containerSelector, pmGraphs) {
    destroy();

    _container = document.querySelector(containerSelector);
    if (!_container) return;
    _container.innerHTML = '';

    if (!pmGraphs || pmGraphs.length === 0) {
      _container.innerHTML =
        '<div class="flex items-center justify-center h-64 text-base-content/40">' +
        'No process managers found in domain.</div>';
      return;
    }

    // Default: all expanded
    pmGraphs.forEach(function (pm) { _expanded[pm.fqn] = true; });

    var wrapper = document.createElement('div');
    wrapper.className = 'flex flex-col gap-4';
    _container.appendChild(wrapper);

    pmGraphs.forEach(function (pm) {
      _renderPMCard(wrapper, pm);
    });
  }

  function destroy() {
    if (_container) {
      _container.innerHTML = '';
      _container = null;
    }
    _expanded = {};
  }

  // ---------------------------------------------------------------------------
  // PM Card Rendering
  // ---------------------------------------------------------------------------

  function _renderPMCard(wrapper, pm) {
    var card = document.createElement('div');
    card.className = 'card bg-base-200 shadow-sm dv-pm-card';
    card.dataset.pmFqn = pm.fqn;

    // Header (clickable for expand/collapse)
    var header = document.createElement('div');
    header.className = 'dv-pm-header cursor-pointer';
    header.innerHTML = _buildHeaderHTML(pm);
    header.addEventListener('click', function () {
      _toggleExpand(pm.fqn, card);
    });
    card.appendChild(header);

    // Body (state machine SVG)
    var body = document.createElement('div');
    body.className = 'dv-pm-body';
    if (!_expanded[pm.fqn]) {
      body.style.display = 'none';
    }
    card.appendChild(body);

    wrapper.appendChild(card);

    if (pm.states.length > 0) {
      _renderStateMachine(body, pm);
    } else {
      body.innerHTML =
        '<div class="flex items-center justify-center h-32 text-base-content/40 text-sm">' +
        'No handlers defined for this process manager.</div>';
    }
  }

  function _buildHeaderHTML(pm) {
    var html = '<div class="flex items-center gap-3 p-4">';

    // Chevron
    var rotated = _expanded[pm.fqn] ? ' dv-pm-chevron-open' : '';
    html += '<svg class="dv-pm-chevron' + rotated + '" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" width="16" height="16">';
    html += '<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />';
    html += '</svg>';

    // Name and FQN
    html += '<div class="flex-1 min-w-0">';
    html += '<div class="font-bold text-base">' + _esc(pm.name) + '</div>';
    html += '<div class="text-xs text-base-content/40 font-mono truncate">' + _esc(pm.fqn) + '</div>';
    html += '</div>';

    // Badges
    html += '<div class="flex flex-wrap gap-2">';
    html += '<span class="badge badge-sm badge-ghost">' +
      pm.transitions.length + ' transition' +
      (pm.transitions.length !== 1 ? 's' : '') + '</span>';
    html += '<span class="badge badge-sm badge-ghost">' +
      pm.states.length + ' state' +
      (pm.states.length !== 1 ? 's' : '') + '</span>';
    if (pm.stream_categories && pm.stream_categories.length > 0) {
      html += '<span class="badge badge-sm badge-info">' +
        pm.stream_categories.length + ' stream' +
        (pm.stream_categories.length !== 1 ? 's' : '') + '</span>';
    }
    // Aggregate badges
    if (pm.aggregates && pm.aggregates.length > 0) {
      pm.aggregates.forEach(function (agg) {
        html += '<span class="badge badge-sm badge-secondary badge-outline">' +
          _esc(agg) + '</span>';
      });
    }
    html += '</div>';

    html += '</div>';
    return html;
  }

  function _toggleExpand(fqn, card) {
    _expanded[fqn] = !_expanded[fqn];
    var body = card.querySelector('.dv-pm-body');
    var chevron = card.querySelector('.dv-pm-chevron');
    if (body) {
      body.style.display = _expanded[fqn] ? '' : 'none';
    }
    if (chevron) {
      if (_expanded[fqn]) {
        chevron.classList.add('dv-pm-chevron-open');
      } else {
        chevron.classList.remove('dv-pm-chevron-open');
      }
    }
  }

  // ---------------------------------------------------------------------------
  // State Machine SVG Rendering
  // ---------------------------------------------------------------------------

  function _renderStateMachine(container, pm) {
    var positions = _computeStateLayout(pm.states);

    // Compute SVG dimensions
    var maxX = 0, maxY = 0;
    pm.states.forEach(function (s) {
      var pos = positions[s.id];
      if (pos) {
        if (pos.x + STATE_RADIUS > maxX) maxX = pos.x + STATE_RADIUS;
        if (pos.y + STATE_RADIUS > maxY) maxY = pos.y + STATE_RADIUS;
      }
    });

    var svgW = Math.max(400, maxX + CARD_PADDING * 2);
    var svgH = Math.max(120, maxY + CARD_PADDING * 2 + 20);

    var svg = d3.select(container)
      .append('svg')
      .attr('class', 'dv-pm-svg')
      .attr('width', '100%')
      .attr('height', svgH)
      .attr('viewBox', '0 0 ' + svgW + ' ' + svgH);

    // Arrow marker
    var defs = svg.append('defs');
    _renderArrowMarker(defs, 'dv-pm-arrow', EDGE_COLOR);
    _renderArrowMarker(defs, 'dv-pm-arrow-end', EDGE_COLOR_END);

    var g = svg.append('g').attr('transform', 'translate(' + CARD_PADDING + ',' + CARD_PADDING + ')');

    // Render edges first (below nodes)
    _renderTransitions(g, pm.transitions, positions);

    // Render state nodes
    _renderStates(g, pm.states, positions);
  }

  function _computeStateLayout(states) {
    var positions = {};

    // Separate by type for ordering: start, intermediates, end
    var starts = [];
    var mids = [];
    var ends = [];
    states.forEach(function (s) {
      if (s.type === 'start') starts.push(s);
      else if (s.type === 'end') ends.push(s);
      else mids.push(s);
    });

    var ordered = starts.concat(mids).concat(ends);
    var x = STATE_RADIUS + 10;
    var y = STATE_RADIUS + 10;

    ordered.forEach(function (s) {
      positions[s.id] = { x: x, y: y };
      x += STATE_SPACING_X;
    });

    return positions;
  }

  function _renderStates(g, states, positions) {
    var stateG = g.append('g').attr('class', 'dv-pm-states');

    states.forEach(function (s) {
      var pos = positions[s.id];
      if (!pos) return;

      var colors = STATE_COLORS[s.type] || STATE_COLORS.intermediate;
      var nodeG = stateG.append('g')
        .attr('class', 'dv-pm-state dv-pm-state--' + s.type)
        .attr('transform', 'translate(' + pos.x + ',' + pos.y + ')');

      // Start state: double border (outer ring)
      if (s.type === 'start') {
        nodeG.append('circle')
          .attr('r', STATE_RADIUS + 4)
          .attr('fill', 'none')
          .attr('stroke', colors.stroke)
          .attr('stroke-width', 1.5);
      }

      // Main circle
      nodeG.append('circle')
        .attr('r', STATE_RADIUS)
        .attr('fill', colors.fill)
        .attr('stroke', colors.stroke)
        .attr('stroke-width', colors.strokeWidth);

      // End state: inner filled circle
      if (s.type === 'end') {
        nodeG.append('circle')
          .attr('r', STATE_RADIUS - 6)
          .attr('fill', colors.fill)
          .attr('stroke', 'none');
        // White text for end states
        nodeG.append('text')
          .attr('class', 'dv-pm-state-label')
          .attr('text-anchor', 'middle')
          .attr('dy', '0.35em')
          .attr('fill', 'var(--color-primary-content)')
          .text(s.label);
      } else {
        // Label below the circle for start/intermediate
        nodeG.append('text')
          .attr('class', 'dv-pm-state-label')
          .attr('text-anchor', 'middle')
          .attr('y', STATE_RADIUS + 16)
          .text(s.label);
      }
    });
  }

  function _renderTransitions(g, transitions, positions) {
    var edgeG = g.append('g').attr('class', 'dv-pm-transitions');

    transitions.forEach(function (t) {
      var src = positions[t.source];
      var tgt = positions[t.target];
      if (!src || !tgt) return;

      var isEnd = t.target === 'completed';
      var markerUrl = isEnd ? 'url(#dv-pm-arrow-end)' : 'url(#dv-pm-arrow)';
      var edgeColor = isEnd ? EDGE_COLOR_END : EDGE_COLOR;

      // Compute path — curved for same-row, straight otherwise
      var path = _transitionPath(src, tgt);

      edgeG.append('path')
        .attr('class', 'dv-pm-transition')
        .attr('d', path)
        .attr('fill', 'none')
        .attr('stroke', edgeColor)
        .attr('stroke-width', 1.5)
        .attr('marker-end', markerUrl);

      // Edge label (event name)
      var midX = (src.x + tgt.x) / 2;
      var midY = (src.y + tgt.y) / 2;
      // Offset label above the line
      var labelY = midY - 12;

      // For self-referencing or backward edges, adjust label position
      if (src.x >= tgt.x) {
        labelY = Math.min(src.y, tgt.y) - STATE_RADIUS - 30;
      }

      edgeG.append('text')
        .attr('class', 'dv-pm-transition-label')
        .attr('x', midX)
        .attr('y', labelY)
        .attr('text-anchor', 'middle')
        .text(t.event);
    });
  }

  function _transitionPath(src, tgt) {
    // Compute start/end points on circle edges
    var dx = tgt.x - src.x;
    var dy = tgt.y - src.y;
    var dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < 1) {
      // Self-loop
      return 'M' + (src.x) + ',' + (src.y - STATE_RADIUS) +
        ' C' + (src.x - 40) + ',' + (src.y - STATE_RADIUS - 50) +
        ' ' + (src.x + 40) + ',' + (src.y - STATE_RADIUS - 50) +
        ' ' + (src.x) + ',' + (src.y - STATE_RADIUS);
    }

    var nx = dx / dist;
    var ny = dy / dist;

    var sx = src.x + nx * (STATE_RADIUS + 2);
    var sy = src.y + ny * (STATE_RADIUS + 2);
    var tx = tgt.x - nx * (STATE_RADIUS + 8);  // +8 for arrow marker
    var ty = tgt.y - ny * (STATE_RADIUS + 8);

    // Backward edge: arc over the top
    if (dx <= 0) {
      var arcY = Math.min(src.y, tgt.y) - STATE_RADIUS - 40;
      return 'M' + sx + ',' + sy +
        ' C' + src.x + ',' + arcY +
        ' ' + tgt.x + ',' + arcY +
        ' ' + tx + ',' + ty;
    }

    // Forward edge: gentle curve
    if (Math.abs(dy) < 5) {
      // Straight horizontal
      return 'M' + sx + ',' + sy + ' L' + tx + ',' + ty;
    }

    var cx1 = sx + (tx - sx) * 0.4;
    var cy1 = sy;
    var cx2 = sx + (tx - sx) * 0.6;
    var cy2 = ty;
    return 'M' + sx + ',' + sy + ' C' + cx1 + ',' + cy1 + ' ' + cx2 + ',' + cy2 + ' ' + tx + ',' + ty;
  }

  // ---------------------------------------------------------------------------
  // Arrow Marker
  // ---------------------------------------------------------------------------

  function _renderArrowMarker(defs, id, color) {
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
      .attr('fill', color);
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  var _esc = (typeof Observatory !== 'undefined' && Observatory.escapeHtml)
    ? Observatory.escapeHtml
    : function (str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str || ''));
        return div.innerHTML;
      };

  // ---------------------------------------------------------------------------
  // Module Export
  // ---------------------------------------------------------------------------

  return {
    render: render,
    destroy: destroy,
  };
})();
