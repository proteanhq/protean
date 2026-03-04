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
  // Public API
  // ---------------------------------------------------------------------------
  return {
    sparkline,
    areaChart,
    barChart,
    gauge,
  };
})();
