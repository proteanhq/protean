/**
 * Observatory Charts Module
 *
 * Reusable D3.js chart functions for the Observatory dashboard.
 * All functions follow the D3 enter/update/exit pattern for efficient re-rendering.
 */
const Charts = (() => {
  // ---------------------------------------------------------------------------
  // Sparkline
  // ---------------------------------------------------------------------------

  /**
   * Render an inline sparkline (small line chart, no axes).
   *
   * @param {HTMLElement|string} container - DOM element or CSS selector
   * @param {number[]} data - Array of numeric values
   * @param {Object} opts - Options
   * @param {number} [opts.width=80] - Chart width in pixels
   * @param {number} [opts.height=24] - Chart height in pixels
   * @param {string} [opts.color='oklch(0.65 0.2 250)'] - Line color
   * @param {boolean} [opts.fill=false] - Fill area under line
   * @param {number} [opts.strokeWidth=1.5] - Line stroke width
   */
  function sparkline(container, data, opts = {}) {
    const el = typeof container === 'string' ? document.querySelector(container) : container;
    if (!el || !data || data.length === 0) return;

    const width = opts.width || 80;
    const height = opts.height || 24;
    const color = opts.color || 'oklch(0.65 0.2 250)';
    const strokeWidth = opts.strokeWidth || 1.5;
    const padding = 1;

    // Clear previous
    el.innerHTML = '';

    const svg = d3.select(el)
      .append('svg')
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', `0 0 ${width} ${height}`);

    const x = d3.scaleLinear()
      .domain([0, data.length - 1])
      .range([padding, width - padding]);

    const y = d3.scaleLinear()
      .domain([0, d3.max(data) || 1])
      .range([height - padding, padding]);

    const line = d3.line()
      .x((d, i) => x(i))
      .y(d => y(d))
      .curve(d3.curveMonotoneX);

    if (opts.fill) {
      const area = d3.area()
        .x((d, i) => x(i))
        .y0(height)
        .y1(d => y(d))
        .curve(d3.curveMonotoneX);

      svg.append('path')
        .datum(data)
        .attr('d', area)
        .attr('fill', color)
        .attr('fill-opacity', 0.15);
    }

    svg.append('path')
      .datum(data)
      .attr('d', line)
      .attr('fill', 'none')
      .attr('stroke', color)
      .attr('stroke-width', strokeWidth);

    // Dot at the end
    if (data.length > 0) {
      const lastIdx = data.length - 1;
      svg.append('circle')
        .attr('cx', x(lastIdx))
        .attr('cy', y(data[lastIdx]))
        .attr('r', 2)
        .attr('fill', color);
    }
  }

  // ---------------------------------------------------------------------------
  // Time-Series Area Chart
  // ---------------------------------------------------------------------------

  /**
   * Render a time-series area chart with multiple series.
   *
   * @param {HTMLElement|string} container - DOM element or CSS selector
   * @param {Object[]} series - Array of { name, data: [{x: Date, y: number}], color }
   * @param {Object} opts - Options
   * @param {number} [opts.width] - Chart width (default: container width)
   * @param {number} [opts.height=200] - Chart height
   * @param {boolean} [opts.stacked=false] - Stack series
   * @param {boolean} [opts.showAxes=true] - Show axes
   * @param {function} [opts.tooltipFormat] - Custom tooltip format function
   */
  function areaChart(container, series, opts = {}) {
    const el = typeof container === 'string' ? document.querySelector(container) : container;
    if (!el || !series || series.length === 0) return;

    const width = opts.width || el.clientWidth || 400;
    const height = opts.height || 200;
    const margin = { top: 10, right: 10, bottom: 25, left: 40 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    // Clear previous
    el.innerHTML = '';

    const svg = d3.select(el)
      .append('svg')
      .attr('width', width)
      .attr('height', height);

    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Compute domains
    const allData = series.flatMap(s => s.data);
    const xExtent = d3.extent(allData, d => d.x);
    const yMax = d3.max(allData, d => d.y) || 1;

    const x = d3.scaleTime()
      .domain(xExtent)
      .range([0, innerWidth]);

    const y = d3.scaleLinear()
      .domain([0, yMax * 1.1])
      .range([innerHeight, 0]);

    // Axes
    if (opts.showAxes !== false) {
      g.append('g')
        .attr('transform', `translate(0,${innerHeight})`)
        .call(d3.axisBottom(x).ticks(5).tickSize(-innerHeight).tickFormat(d3.timeFormat('%H:%M')))
        .call(g => g.select('.domain').remove())
        .call(g => g.selectAll('.tick line').attr('stroke', 'currentColor').attr('stroke-opacity', 0.1))
        .call(g => g.selectAll('.tick text').attr('class', 'text-xs fill-base-content/50'));

      g.append('g')
        .call(d3.axisLeft(y).ticks(4).tickSize(-innerWidth).tickFormat(Observatory.fmt.number))
        .call(g => g.select('.domain').remove())
        .call(g => g.selectAll('.tick line').attr('stroke', 'currentColor').attr('stroke-opacity', 0.1))
        .call(g => g.selectAll('.tick text').attr('class', 'text-xs fill-base-content/50'));
    }

    // Render each series
    for (const s of series) {
      const area = d3.area()
        .x(d => x(d.x))
        .y0(innerHeight)
        .y1(d => y(d.y))
        .curve(d3.curveMonotoneX);

      const line = d3.line()
        .x(d => x(d.x))
        .y(d => y(d.y))
        .curve(d3.curveMonotoneX);

      g.append('path')
        .datum(s.data)
        .attr('d', area)
        .attr('fill', s.color)
        .attr('fill-opacity', 0.12);

      g.append('path')
        .datum(s.data)
        .attr('d', line)
        .attr('fill', 'none')
        .attr('stroke', s.color)
        .attr('stroke-width', 1.5);
    }
  }

  // ---------------------------------------------------------------------------
  // Bar Chart
  // ---------------------------------------------------------------------------

  /**
   * Render a vertical bar chart.
   *
   * @param {HTMLElement|string} container - DOM element or CSS selector
   * @param {Object[]} data - Array of { label, value, color? }
   * @param {Object} opts
   */
  function barChart(container, data, opts = {}) {
    const el = typeof container === 'string' ? document.querySelector(container) : container;
    if (!el || !data || data.length === 0) return;

    const width = opts.width || el.clientWidth || 300;
    const height = opts.height || 150;
    const color = opts.color || 'oklch(0.7 0.15 250)';
    const margin = { top: 10, right: 10, bottom: 25, left: 40 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    el.innerHTML = '';

    const svg = d3.select(el)
      .append('svg')
      .attr('width', width)
      .attr('height', height);

    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3.scaleBand()
      .domain(data.map(d => d.label))
      .range([0, innerWidth])
      .padding(0.2);

    const y = d3.scaleLinear()
      .domain([0, d3.max(data, d => d.value) || 1])
      .range([innerHeight, 0]);

    // Axes
    g.append('g')
      .attr('transform', `translate(0,${innerHeight})`)
      .call(d3.axisBottom(x).tickSize(0))
      .call(g => g.select('.domain').remove())
      .call(g => g.selectAll('.tick text').attr('class', 'text-xs fill-base-content/50'));

    g.append('g')
      .call(d3.axisLeft(y).ticks(4).tickSize(-innerWidth))
      .call(g => g.select('.domain').remove())
      .call(g => g.selectAll('.tick line').attr('stroke', 'currentColor').attr('stroke-opacity', 0.1))
      .call(g => g.selectAll('.tick text').attr('class', 'text-xs fill-base-content/50'));

    // Bars
    g.selectAll('.bar')
      .data(data)
      .enter()
      .append('rect')
      .attr('x', d => x(d.label))
      .attr('y', d => y(d.value))
      .attr('width', x.bandwidth())
      .attr('height', d => innerHeight - y(d.value))
      .attr('fill', d => d.color || color)
      .attr('rx', 2);
  }

  // ---------------------------------------------------------------------------
  // Gauge (radial progress)
  // ---------------------------------------------------------------------------

  /**
   * Render a simple gauge / radial progress indicator.
   *
   * @param {HTMLElement|string} container
   * @param {number} value - Current value (0-100)
   * @param {Object} opts
   * @param {number} [opts.size=80]
   * @param {string} [opts.color]
   * @param {string} [opts.label]
   */
  function gauge(container, value, opts = {}) {
    const el = typeof container === 'string' ? document.querySelector(container) : container;
    if (!el) return;

    const size = opts.size || 80;
    const radius = size / 2 - 6;
    const color = opts.color || (value > 80 ? 'oklch(0.7 0.2 25)' : value > 50 ? 'oklch(0.75 0.15 85)' : 'oklch(0.7 0.2 150)');

    el.innerHTML = '';

    const svg = d3.select(el)
      .append('svg')
      .attr('width', size)
      .attr('height', size);

    const g = svg.append('g')
      .attr('transform', `translate(${size / 2},${size / 2})`);

    // Background arc
    const arc = d3.arc()
      .innerRadius(radius - 5)
      .outerRadius(radius)
      .startAngle(0)
      .cornerRadius(3);

    g.append('path')
      .attr('d', arc({ endAngle: 2 * Math.PI }))
      .attr('fill', 'currentColor')
      .attr('opacity', 0.1);

    // Value arc
    g.append('path')
      .attr('d', arc({ endAngle: (value / 100) * 2 * Math.PI }))
      .attr('fill', color);

    // Center text
    g.append('text')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'central')
      .attr('class', 'text-sm font-bold fill-base-content')
      .text(Math.round(value) + '%');
  }

  // ---------------------------------------------------------------------------
  // Flow Graph (D3 force-directed)
  // ---------------------------------------------------------------------------

  /**
   * Render a D3 force-directed graph of the domain topology.
   *
   * @param {HTMLElement|string} container - DOM element or CSS selector
   * @param {Object[]} nodes - [{id, label, type, aggregate?}, ...]
   * @param {Object[]} edges - [{source, target, type}, ...]
   * @param {Object} opts
   * @param {number} [opts.width] - Chart width (default: container width)
   * @param {number} [opts.height=500] - Chart height
   * @param {function} [opts.onNodeClick] - Callback(node) on node click
   * @param {string} [opts.filterCluster] - Only show nodes in this aggregate cluster
   * @returns {Object} Control object { update, zoomTo, destroy }
   */
  function flowGraph(container, nodes, edges, opts = {}) {
    const el = typeof container === 'string' ? document.querySelector(container) : container;
    if (!el) return null;

    const width = opts.width || el.clientWidth || 800;
    const height = opts.height || 500;

    // Color map by node type
    const colorMap = {
      'command': 'oklch(0.65 0.2 250)',       // blue
      'event': 'oklch(0.7 0.2 150)',           // green
      'command_handler': 'oklch(0.7 0.05 250)',// gray-blue
      'event_handler': 'oklch(0.7 0.05 250)',  // gray-blue
      'aggregate': 'oklch(0.65 0.15 300)',     // indigo
      'projector': 'oklch(0.65 0.2 310)',      // purple
      'projection': 'oklch(0.75 0.1 310)',     // light purple
      'process_manager': 'oklch(0.7 0.2 60)',  // orange
      'subscriber': 'oklch(0.7 0.15 200)',     // cyan
      'domain_service': 'oklch(0.6 0.1 100)',  // olive
    };

    // Shape map: different shapes for different types
    const shapeSize = {
      'command': 12,
      'event': 12,
      'command_handler': 14,
      'event_handler': 14,
      'aggregate': 18,
      'projector': 14,
      'projection': 12,
      'process_manager': 16,
      'subscriber': 14,
      'domain_service': 14,
    };

    // Filter by cluster if specified
    let filteredNodes = nodes;
    let filteredEdges = edges;
    if (opts.filterCluster && opts.filterCluster !== 'all') {
      const cluster = opts.filterCluster;
      const nodeIds = new Set();
      filteredNodes = nodes.filter(n => {
        if (n.aggregate === cluster || n.label === cluster) {
          nodeIds.add(n.id);
          return true;
        }
        return false;
      });
      // Also include connected nodes (one hop)
      edges.forEach(e => {
        if (nodeIds.has(e.source) || nodeIds.has(e.source?.id)) {
          const tid = e.target?.id || e.target;
          nodeIds.add(tid);
        }
        if (nodeIds.has(e.target) || nodeIds.has(e.target?.id)) {
          const sid = e.source?.id || e.source;
          nodeIds.add(sid);
        }
      });
      filteredNodes = nodes.filter(n => nodeIds.has(n.id));
      filteredEdges = edges.filter(e => {
        const sid = e.source?.id || e.source;
        const tid = e.target?.id || e.target;
        return nodeIds.has(sid) && nodeIds.has(tid);
      });
    }

    if (filteredNodes.length === 0) {
      el.innerHTML = '<div class="flex items-center justify-center py-16 text-base-content/40"><p class="text-sm">No nodes to display.</p></div>';
      return null;
    }

    el.innerHTML = '';

    const svg = d3.select(el)
      .append('svg')
      .attr('width', width)
      .attr('height', height);

    // Arrow marker for edges
    svg.append('defs').append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', 'currentColor')
      .attr('opacity', 0.3);

    const g = svg.append('g');

    // Zoom behavior
    const zoom = d3.zoom()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });
    svg.call(zoom);

    // Force simulation
    const simulation = d3.forceSimulation(filteredNodes)
      .force('link', d3.forceLink(filteredEdges).id(d => d.id).distance(100))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide().radius(30));

    // Edges
    const link = g.append('g')
      .selectAll('line')
      .data(filteredEdges)
      .enter()
      .append('line')
      .attr('stroke', 'currentColor')
      .attr('stroke-opacity', 0.2)
      .attr('stroke-width', 1)
      .attr('marker-end', 'url(#arrow)');

    // Nodes
    const node = g.append('g')
      .selectAll('g')
      .data(filteredNodes)
      .enter()
      .append('g')
      .attr('class', 'cursor-pointer')
      .call(d3.drag()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x; d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        }));

    node.append('circle')
      .attr('r', d => (shapeSize[d.type] || 12) / 2 + 4)
      .attr('fill', d => colorMap[d.type] || '#999')
      .attr('fill-opacity', 0.8)
      .attr('stroke', d => colorMap[d.type] || '#999')
      .attr('stroke-width', 1.5);

    node.append('text')
      .text(d => d.label)
      .attr('text-anchor', 'middle')
      .attr('dy', d => (shapeSize[d.type] || 12) / 2 + 14)
      .attr('class', 'text-xs fill-base-content/70')
      .style('pointer-events', 'none');

    if (opts.onNodeClick) {
      node.on('click', (event, d) => opts.onNodeClick(d));
    }

    simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    return {
      zoomTo(level) {
        svg.transition().duration(300).call(zoom.scaleTo, level);
      },
      resetZoom() {
        svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity);
      },
      destroy() {
        simulation.stop();
        el.innerHTML = '';
      },
    };
  }

  // ---------------------------------------------------------------------------
  // Causation Tree
  // ---------------------------------------------------------------------------

  /**
   * Render a horizontal causation tree.
   *
   * @param {HTMLElement|string} container
   * @param {Object} tree - { message_id, message_type, kind, stream, time, children: [...] }
   * @param {Object} opts
   * @param {number} [opts.width] - Chart width (default: container width)
   * @param {number} [opts.nodeHeight=40] - Height per node
   * @param {function} [opts.onNodeClick] - Callback(node) on click
   */
  function causationTree(container, tree, opts = {}) {
    const el = typeof container === 'string' ? document.querySelector(container) : container;
    if (!el || !tree) return;

    const width = opts.width || el.clientWidth || 600;
    const nodeHeight = opts.nodeHeight || 40;
    const margin = { top: 20, right: 120, bottom: 20, left: 120 };

    el.innerHTML = '';

    // Convert to d3 hierarchy
    const root = d3.hierarchy(tree, d => d.children);
    const treeLayout = d3.tree().nodeSize([nodeHeight, 200]);
    treeLayout(root);

    // Compute bounds
    let x0 = Infinity, x1 = -Infinity;
    root.each(d => {
      if (d.x > x1) x1 = d.x;
      if (d.x < x0) x0 = d.x;
    });

    const height = x1 - x0 + margin.top + margin.bottom + nodeHeight;

    const svg = d3.select(el)
      .append('svg')
      .attr('width', width)
      .attr('height', height);

    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top - x0})`);

    // Links (curved)
    g.selectAll('.link')
      .data(root.links())
      .enter()
      .append('path')
      .attr('class', 'link')
      .attr('fill', 'none')
      .attr('stroke', 'currentColor')
      .attr('stroke-opacity', 0.2)
      .attr('stroke-width', 1.5)
      .attr('d', d3.linkHorizontal()
        .x(d => d.y)
        .y(d => d.x));

    // Nodes
    const nodeG = g.selectAll('.node')
      .data(root.descendants())
      .enter()
      .append('g')
      .attr('class', 'node')
      .attr('transform', d => `translate(${d.y},${d.x})`);

    // Kind colors
    const kindColor = {
      'COMMAND': 'oklch(0.65 0.2 250)',
      'EVENT': 'oklch(0.7 0.2 150)',
    };

    nodeG.append('circle')
      .attr('r', 5)
      .attr('fill', d => kindColor[d.data.kind] || '#999')
      .attr('stroke', d => kindColor[d.data.kind] || '#999')
      .attr('stroke-width', 1.5);

    // Label: short message type
    nodeG.append('text')
      .attr('dy', '0.31em')
      .attr('x', d => d.children ? -10 : 10)
      .attr('text-anchor', d => d.children ? 'end' : 'start')
      .attr('class', 'text-xs fill-base-content/80')
      .text(d => {
        const type = d.data.message_type || '?';
        const parts = type.rsplit ? type.split('.') : type.split('.');
        return parts.length >= 2 ? parts[parts.length - 2] : type;
      });

    // Time label (below)
    nodeG.append('text')
      .attr('dy', '1.5em')
      .attr('x', d => d.children ? -10 : 10)
      .attr('text-anchor', d => d.children ? 'end' : 'start')
      .attr('class', 'text-xs fill-base-content/40')
      .text(d => {
        if (d.data.time) {
          return typeof Observatory !== 'undefined' && Observatory.fmt
            ? Observatory.fmt.timeAgo(d.data.time)
            : d.data.time;
        }
        return '';
      });

    if (opts.onNodeClick) {
      nodeG.style('cursor', 'pointer')
        .on('click', (event, d) => opts.onNodeClick(d.data));
    }
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------
  return {
    sparkline,
    areaChart,
    barChart,
    gauge,
    flowGraph,
    causationTree,
  };
})();
