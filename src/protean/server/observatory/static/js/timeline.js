/**
 * Timeline View Module
 *
 * Chronological event browser for the Observatory. Fetches events from
 * /api/timeline/* endpoints, renders the event list with filtering,
 * cursor-based pagination, event detail panel, correlation chain view,
 * and aggregate history view.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let _events = [];
  let _nextCursor = null;
  let _loading = false;
  let _order = 'desc';     // 'asc' | 'desc'
  let _streamCategory = '';
  let _eventType = '';
  let _aggregateId = '';
  let _kind = '';

  // Current view: 'list' | 'traces' | 'correlation' | 'aggregate'
  let _currentView = 'list';

  // Traces view state
  let _traces = [];
  let _traceSearchTimer = null;
  let _traceSearchSeq = 0;  // Sequence token to discard stale search responses

  // SSE real-time state
  let _pendingNewEvents = 0;   // Count of events arrived while scrolled down
  let _lastKnownPosition = 0;  // Highest global_position we know about
  let _sseDebounceTimer = null; // Debounce timer for SSE trace handling

  // DOM refs
  let $tbody, $empty, $loadMore, $loadingMore, $toast;

  // ---------------------------------------------------------------------------
  // View Management
  // ---------------------------------------------------------------------------

  function _showView(view) {
    _currentView = view;
    var $list = document.getElementById('timeline-list-view');
    var $tracesView = document.getElementById('traces-view');
    var $corr = document.getElementById('correlation-view');
    var $agg = document.getElementById('aggregate-view');

    if ($list) $list.classList.toggle('hidden', view !== 'list');
    if ($tracesView) $tracesView.classList.toggle('hidden', view !== 'traces');
    if ($corr) $corr.classList.toggle('hidden', view !== 'correlation');
    if ($agg) $agg.classList.toggle('hidden', view !== 'aggregate');

    // Update tab bar active state
    var $tabEvents = document.getElementById('tab-events');
    var $tabTraces = document.getElementById('tab-traces');
    if ($tabEvents) $tabEvents.classList.toggle('tab-active', view === 'list');
    if ($tabTraces) $tabTraces.classList.toggle('tab-active', view === 'traces');
  }

  function _enterListView() {
    _showView('list');
    _syncUIFromState();
    _updateURL();
    fetchEvents(false);
    window.scrollTo(0, 0);
  }

  // Track which tab the user came from before entering a sub-view
  let _previousTab = 'list';

  function _backToList() {
    if (_previousTab === 'traces') {
      _enterTracesView();
    } else {
      _enterListView();
    }
  }

  // ---------------------------------------------------------------------------
  // Data Fetching
  // ---------------------------------------------------------------------------

  function _buildQueryString(cursor) {
    var params = new URLSearchParams();
    params.set('limit', '50');
    params.set('order', _order);
    if (cursor != null) params.set('cursor', String(cursor));
    if (_streamCategory) params.set('stream_category', _streamCategory);
    if (_eventType) params.set('event_type', _eventType);
    if (_aggregateId) params.set('aggregate_id', _aggregateId);
    if (_kind) params.set('kind', _kind);
    return params.toString();
  }

  async function fetchEvents(append) {
    if (_loading) return;
    _loading = true;

    if (!append) {
      _events = [];
      _nextCursor = null;
    }

    var cursor = append ? _nextCursor : 0;
    if (append && cursor == null) {
      _loading = false;
      return;
    }

    if ($loadingMore) $loadingMore.classList.remove('hidden');

    try {
      var qs = _buildQueryString(cursor);
      var data = await Observatory.fetchJSON('/api/timeline/events?' + qs);
      var newEvents = data.events || [];

      if (append) {
        _events = _events.concat(newEvents);
      } else {
        _events = newEvents;
      }
      _nextCursor = data.next_cursor;
    } catch (e) {
      console.warn('Failed to fetch timeline events:', e.message);
      if (!append) _events = [];
    }

    _loading = false;
    if ($loadingMore) $loadingMore.classList.add('hidden');
    _renderTable();
    _updateLoadMore();

    // Track highest known position for SSE deduplication
    if (_events.length > 0) {
      for (var k = 0; k < _events.length; k++) {
        var p = _events[k].global_position;
        if (p != null && p > _lastKnownPosition) {
          _lastKnownPosition = p;
        }
      }
    }
  }

  async function fetchStats() {
    try {
      var data = await Observatory.fetchJSON('/api/timeline/stats');
      _renderStats(data);
    } catch (e) {
      console.warn('Failed to fetch timeline stats:', e.message);
    }
  }

  async function fetchStreams() {
    try {
      var data = await Observatory.fetchJSON('/api/eventstore/streams');
      _populateStreamFilter(data.aggregates || []);
    } catch (e) {
      console.warn('Failed to fetch stream categories:', e.message);
    }
  }

  // ---------------------------------------------------------------------------
  // Traces View
  // ---------------------------------------------------------------------------

  async function fetchRecentTraces() {
    try {
      var data = await Observatory.fetchJSON('/api/timeline/traces/recent?limit=50');
      _traces = data.traces || [];
    } catch (e) {
      console.warn('Failed to fetch recent traces:', e.message);
      _traces = [];
    }
    _renderTracesTable();
  }

  async function searchTraces() {
    var aggId = (document.getElementById('trace-search-aggregate-id') || {}).value || '';
    var evtType = (document.getElementById('trace-search-event-type') || {}).value || '';
    var cmdType = (document.getElementById('trace-search-command-type') || {}).value || '';
    var streamCat = (document.getElementById('trace-search-stream-category') || {}).value || '';

    aggId = aggId.trim();
    evtType = evtType.trim();
    cmdType = cmdType.trim();
    streamCat = streamCat.trim();

    // If all fields are empty, fetch recent traces instead
    if (!aggId && !evtType && !cmdType && !streamCat) {
      fetchRecentTraces();
      _updateTracesURL();
      return;
    }

    var params = new URLSearchParams();
    if (aggId) params.set('aggregate_id', aggId);
    if (evtType) params.set('event_type', evtType);
    if (cmdType) params.set('command_type', cmdType);
    if (streamCat) params.set('stream_category', streamCat);
    params.set('limit', '50');

    // Sequence token: discard responses from stale requests
    var seq = ++_traceSearchSeq;

    try {
      var data = await Observatory.fetchJSON('/api/timeline/traces/search?' + params.toString());
      if (seq !== _traceSearchSeq) return; // Stale response, discard
      _traces = data.traces || [];
    } catch (e) {
      if (seq !== _traceSearchSeq) return;
      console.warn('Failed to search traces:', e.message);
      _traces = [];
    }
    _renderTracesTable();
    _updateTracesURL();
  }

  function _renderTracesTable() {
    var $tracesTbody = document.getElementById('traces-tbody');
    var $tracesEmpty = document.getElementById('traces-empty');
    if (!$tracesTbody) return;

    if (_traces.length === 0) {
      $tracesTbody.innerHTML = '';
      if ($tracesEmpty) $tracesEmpty.classList.remove('hidden');
      return;
    }

    if ($tracesEmpty) $tracesEmpty.classList.add('hidden');

    $tracesTbody.innerHTML = _traces.map(function (trace) {
      var rootType = Observatory.escapeHtml(_shortTypeName(trace.root_type || ''));
      var rootTypeFull = Observatory.escapeHtml(trace.root_type || '--');
      var eventCount = trace.event_count != null ? trace.event_count : '--';
      var streams = (trace.streams || []).map(function (s) {
        return Observatory.escapeHtml(_extractStreamCategory(s));
      });
      var uniqueStreams = [];
      var seen = {};
      for (var i = 0; i < streams.length; i++) {
        if (!seen[streams[i]]) {
          seen[streams[i]] = true;
          uniqueStreams.push(streams[i]);
        }
      }
      var streamsHtml = uniqueStreams.join(', ') || '--';
      var startedAt = trace.started_at ? Observatory.fmt.timeAgo(trace.started_at) : '--';
      var startedAtFull = trace.started_at ? Observatory.fmt.datetime(trace.started_at) : '';
      var corrId = Observatory.escapeHtml(trace.correlation_id || '');

      return '<tr class="hover cursor-pointer trace-row" data-correlation-id="' + corrId + '" tabindex="0" role="button" title="View correlation chain">' +
        '<td class="text-sm" title="' + rootTypeFull + '">' + rootType + '</td>' +
        '<td class="text-right font-mono-metric">' + eventCount + '</td>' +
        '<td class="text-sm font-mono">' + streamsHtml + '</td>' +
        '<td class="text-xs" title="' + Observatory.escapeHtml(startedAtFull) + '">' + startedAt + '</td>' +
      '</tr>';
    }).join('');

    // Bind row click → navigate to correlation view
    $tracesTbody.querySelectorAll('.trace-row').forEach(function (row) {
      var _onActivate = function () {
        var cid = row.getAttribute('data-correlation-id');
        if (cid) _showCorrelationView(cid);
      };
      row.addEventListener('click', _onActivate);
      row.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          _onActivate();
        }
      });
    });
  }

  function _hasTraceSearchCriteria() {
    var aggId = (document.getElementById('trace-search-aggregate-id') || {}).value || '';
    var evtType = (document.getElementById('trace-search-event-type') || {}).value || '';
    var cmdType = (document.getElementById('trace-search-command-type') || {}).value || '';
    var streamCat = (document.getElementById('trace-search-stream-category') || {}).value || '';
    return !!(aggId.trim() || evtType.trim() || cmdType.trim() || streamCat.trim());
  }

  function _enterTracesView() {
    _showView('traces');
    _updateTracesURL();
    if (_hasTraceSearchCriteria()) {
      searchTraces();
    } else {
      fetchRecentTraces();
    }
    window.scrollTo(0, 0);
  }

  function _updateTracesURL() {
    var params = new URLSearchParams();
    params.set('view', 'traces');
    var aggId = (document.getElementById('trace-search-aggregate-id') || {}).value || '';
    var evtType = (document.getElementById('trace-search-event-type') || {}).value || '';
    var cmdType = (document.getElementById('trace-search-command-type') || {}).value || '';
    var streamCat = (document.getElementById('trace-search-stream-category') || {}).value || '';
    if (aggId.trim()) params.set('aggregate_id', aggId.trim());
    if (evtType.trim()) params.set('event_type', evtType.trim());
    if (cmdType.trim()) params.set('command_type', cmdType.trim());
    if (streamCat.trim()) params.set('stream_category', streamCat.trim());
    var qs = params.toString();
    var url = window.location.pathname + (qs ? '?' + qs : '');
    history.replaceState(null, '', url);
  }

  // ---------------------------------------------------------------------------
  // Correlation Chain
  // ---------------------------------------------------------------------------

  async function _showCorrelationView(correlationId) {
    // Remember which tab the user was on before entering correlation view
    if (_currentView === 'list' || _currentView === 'traces') {
      _previousTab = _currentView;
    }
    _showView('correlation');

    var $idDisplay = document.getElementById('correlation-id-display');
    var $eventCount = document.getElementById('correlation-event-count');
    var $rootType = document.getElementById('correlation-root-type');
    var $depth = document.getElementById('correlation-depth');
    var $totalDuration = document.getElementById('correlation-total-duration');
    var $streamsTouched = document.getElementById('correlation-streams-touched');
    var $tree = document.getElementById('correlation-tree');
    var $corrTbody = document.getElementById('correlation-events-tbody');

    if ($idDisplay) $idDisplay.textContent = correlationId;
    if ($eventCount) $eventCount.textContent = '--';
    if ($rootType) $rootType.textContent = 'Loading...';
    if ($depth) $depth.textContent = '--';
    if ($totalDuration) $totalDuration.textContent = '--';
    if ($streamsTouched) $streamsTouched.textContent = '--';
    if ($tree) $tree.innerHTML = '<div class="text-center py-8"><span class="loading loading-spinner loading-sm"></span></div>';
    if ($corrTbody) $corrTbody.innerHTML = '<tr><td colspan="5" class="text-center text-base-content/50 py-4">Loading...</td></tr>';

    // Push a new history entry so browser Back returns to the previous view
    var params = new URLSearchParams();
    params.set('correlation', correlationId);
    history.pushState({view: 'correlation', correlationId: correlationId}, '', window.location.pathname + '?' + params.toString());

    try {
      var data = await Observatory.fetchJSON('/api/timeline/correlation/' + encodeURIComponent(correlationId));

      if ($eventCount) $eventCount.textContent = data.event_count || 0;

      // Total duration
      if ($totalDuration) {
        $totalDuration.textContent = data.total_duration_ms != null
          ? Observatory.fmt.duration(data.total_duration_ms)
          : '--';
      }

      // Streams touched — count unique stream categories in the tree
      if ($streamsTouched && data.tree) {
        var streams = _collectTreeStreams(data.tree);
        $streamsTouched.textContent = streams.length;
      }

      // Render causation tree
      if (data.tree && $tree) {
        var treeDepth = _computeTreeDepth(data.tree);
        if ($depth) $depth.textContent = treeDepth;
        if ($rootType) $rootType.textContent = _shortTypeName(data.tree.message_type || '');
        $tree.innerHTML = '';
        $tree.appendChild(_renderCausationTree(data.tree, 0, null));
      } else {
        if ($tree) $tree.innerHTML = '<div class="text-center py-4 text-base-content/40">No causation tree available</div>';
        if ($depth) $depth.textContent = '0';
        if ($rootType) $rootType.textContent = '--';
      }

      // Render flat event list
      if ($corrTbody && data.events) {
        _renderEventRows($corrTbody, data.events);
      }
    } catch (e) {
      console.warn('Failed to fetch correlation chain:', e.message);
      if ($tree) $tree.innerHTML = '<div class="text-center py-4 text-error">Failed to load correlation chain</div>';
      if ($corrTbody) $corrTbody.innerHTML = '<tr><td colspan="5" class="text-center text-error py-4">Failed to load</td></tr>';
    }

    window.scrollTo(0, 0);
  }

  function _computeTreeDepth(node) {
    if (!node || !node.children || node.children.length === 0) return 1;
    var maxChild = 0;
    for (var i = 0; i < node.children.length; i++) {
      var d = _computeTreeDepth(node.children[i]);
      if (d > maxChild) maxChild = d;
    }
    return 1 + maxChild;
  }

  function _renderCausationTree(node, depth, parentStream) {
    var container = document.createElement('div');
    container.className = 'vtl-node' + (depth === 0 ? ' vtl-root' : '');

    if (depth > 0 && node.delta_ms != null) {
      var latencyEl = document.createElement('div');
      latencyEl.className = 'vtl-latency';
      latencyEl.textContent = '+' + Observatory.fmt.duration(node.delta_ms);
      container.appendChild(latencyEl);
    }

    var kindClass = node.kind === 'COMMAND' ? 'badge-secondary' : 'badge-primary';
    var kindLabel = node.kind === 'COMMAND' ? 'CMD' : 'EVT';
    var shortType = Observatory.escapeHtml(_shortTypeName(node.message_type || ''));
    var fullType = Observatory.escapeHtml(node.message_type || '');
    var stream = Observatory.escapeHtml(node.stream || '--');
    var time = node.time ? Observatory.fmt.time(node.time) : '--';
    var timeAgo = node.time ? Observatory.fmt.timeAgo(node.time) : '';
    var pos = node.global_position != null ? node.global_position : '--';

    var nodeStreamCat = _extractStreamCategory(node.stream || '');
    var parentStreamCat = parentStream ? _extractStreamCategory(parentStream) : null;
    var isCrossAggregate = parentStreamCat != null && nodeStreamCat !== '--' && nodeStreamCat !== parentStreamCat;

    var card = document.createElement('div');
    card.className = 'vtl-card cursor-pointer' + (isCrossAggregate ? ' vtl-cross-aggregate' : '');
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('data-message-id', node.message_id || '');
    card.setAttribute('title', 'View event detail for ' + (node.message_type || 'event'));

    var handlerHtml = '';
    if (node.handler) {
      handlerHtml = '<span class="vtl-handler" title="Handled by: ' + Observatory.escapeHtml(node.handler) + '">' +
        '\u2192 ' + Observatory.escapeHtml(node.handler) + '</span>';
    }

    var durationHtml = '';
    if (node.duration_ms != null) {
      durationHtml = '<span class="vtl-duration">' + Observatory.fmt.duration(node.duration_ms) + '</span>';
    }

    var crossAggHtml = '';
    if (isCrossAggregate) {
      crossAggHtml = '<span class="vtl-cross-aggregate-icon" title="Cross-aggregate: ' +
        Observatory.escapeHtml(parentStreamCat) + ' \u2192 ' + Observatory.escapeHtml(nodeStreamCat) +
        '">\u21C4</span>';
    }

    card.innerHTML =
      '<div class="flex items-center gap-2 mb-1">' +
        '<span class="badge badge-xs ' + kindClass + '">' + kindLabel + '</span>' +
        '<span class="font-semibold text-sm" title="' + fullType + '">' + shortType + '</span>' +
        crossAggHtml +
        durationHtml +
        '<span class="text-xs text-base-content/40 ml-auto font-mono-metric">#' + pos + '</span>' +
      '</div>' +
      '<div class="flex items-center gap-3 text-xs text-base-content/60">' +
        '<span class="font-mono">' + stream + '</span>' +
        handlerHtml +
        '<span>' + time + '</span>' +
        (timeAgo ? '<span class="text-base-content/40">' + timeAgo + '</span>' : '') +
      '</div>';

    var _onCardActivate = function () {
      _showEventDetail(node.message_id);
    };
    card.addEventListener('click', _onCardActivate);
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        _onCardActivate();
      }
    });

    container.appendChild(card);

    // Render children — pass this node's stream for cross-aggregate detection
    if (node.children && node.children.length > 0) {
      var childrenWrap = document.createElement('div');
      childrenWrap.className = 'vtl-children';
      for (var i = 0; i < node.children.length; i++) {
        childrenWrap.appendChild(_renderCausationTree(node.children[i], depth + 1, node.stream));
      }
      container.appendChild(childrenWrap);
    }

    return container;
  }

  // ---------------------------------------------------------------------------
  // Aggregate History
  // ---------------------------------------------------------------------------

  async function _showAggregateView(streamCategory, aggregateId) {
    if (_currentView === 'list' || _currentView === 'traces') {
      _previousTab = _currentView;
    }
    _showView('aggregate');

    var $streamDisplay = document.getElementById('aggregate-stream-display');
    var $category = document.getElementById('aggregate-category');
    var $aggId = document.getElementById('aggregate-id-display');
    var $version = document.getElementById('aggregate-version');
    var $timeline = document.getElementById('aggregate-timeline');
    var $aggEmpty = document.getElementById('aggregate-empty');

    if ($streamDisplay) $streamDisplay.textContent = streamCategory + '-' + aggregateId;
    if ($category) $category.textContent = streamCategory;
    if ($aggId) $aggId.textContent = aggregateId;
    if ($version) $version.textContent = '--';
    if ($timeline) $timeline.innerHTML = '<div class="text-center py-8"><span class="loading loading-spinner loading-sm"></span></div>';
    if ($aggEmpty) $aggEmpty.classList.add('hidden');

    // Push a new history entry so browser Back returns to the previous view
    var params = new URLSearchParams();
    params.set('stream', streamCategory);
    params.set('aggregate', aggregateId);
    history.pushState({view: 'aggregate', stream: streamCategory, aggregate: aggregateId}, '', window.location.pathname + '?' + params.toString());

    try {
      var data = await Observatory.fetchJSON(
        '/api/timeline/aggregate/' + encodeURIComponent(streamCategory) +
        '/' + encodeURIComponent(aggregateId)
      );

      if ($version) $version.textContent = data.current_version != null ? data.current_version : '--';

      if (data.events && data.events.length > 0 && $timeline) {
        $timeline.innerHTML = '';
        _renderAggregateTimeline($timeline, data.events);
      } else {
        if ($timeline) $timeline.innerHTML = '';
        if ($aggEmpty) $aggEmpty.classList.remove('hidden');
      }
    } catch (e) {
      console.warn('Failed to fetch aggregate history:', e.message);
      if ($timeline) $timeline.innerHTML = '<div class="text-center py-4 text-error">Failed to load aggregate history</div>';
    }

    window.scrollTo(0, 0);
  }

  function _renderAggregateTimeline($container, events) {
    for (var i = 0; i < events.length; i++) {
      var evt = events[i];
      var node = document.createElement('div');
      node.className = 'agg-tl-node';

      var kindClass = evt.kind === 'COMMAND' ? 'badge-secondary' : 'badge-primary';
      var kindLabel = evt.kind === 'COMMAND' ? 'CMD' : 'EVT';
      var shortType = Observatory.escapeHtml(_shortTypeName(evt.type || ''));
      var fullType = Observatory.escapeHtml(evt.type || '');
      var time = evt.time ? Observatory.fmt.time(evt.time) : '--';
      var timeTitle = evt.time ? Observatory.fmt.datetime(evt.time) : '';
      var timeAgo = evt.time ? Observatory.fmt.timeAgo(evt.time) : '';
      var version = evt.position != null ? 'v' + evt.position : '';
      var msgId = evt.message_id || '';

      node.innerHTML =
        '<div class="agg-tl-marker">' +
          '<div class="agg-tl-dot"></div>' +
          (i < events.length - 1 ? '<div class="agg-tl-line"></div>' : '') +
        '</div>' +
        '<div class="agg-tl-content cursor-pointer" role="button" tabindex="0" data-message-id="' + Observatory.escapeHtml(msgId) + '" title="View event detail">' +
          '<div class="flex items-center gap-2 mb-1">' +
            (version ? '<span class="badge badge-xs badge-outline font-mono-metric">' + version + '</span>' : '') +
            '<span class="badge badge-xs ' + kindClass + '">' + kindLabel + '</span>' +
            '<span class="font-semibold text-sm" title="' + fullType + '">' + shortType + '</span>' +
          '</div>' +
          '<div class="text-xs text-base-content/60" title="' + Observatory.escapeHtml(timeTitle) + '">' +
            time + (timeAgo ? ' <span class="text-base-content/40">' + timeAgo + '</span>' : '') +
          '</div>' +
          (evt.correlation_id ?
            '<div class="text-xs text-base-content/40 mt-1">' +
              'Correlation: <a class="link link-hover link-primary correlation-link" role="button" tabindex="0" data-correlation-id="' +
              Observatory.escapeHtml(evt.correlation_id) + '" title="View correlation chain">' +
              Observatory.escapeHtml(evt.correlation_id.substring(0, 8)) + '...</a>' +
            '</div>'
          : '') +
        '</div>';

      $container.appendChild(node);
    }

    // Bind click and keyboard events for event detail
    $container.querySelectorAll('.agg-tl-content[data-message-id]').forEach(function (el) {
      var _onActivate = function (e) {
        // Don't open detail if activating a correlation link
        if (e.target.classList.contains('correlation-link')) return;
        _showEventDetail(el.getAttribute('data-message-id'));
      };
      el.addEventListener('click', _onActivate);
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          _onActivate(e);
        }
      });
    });

    // Bind correlation links (click and keyboard)
    $container.querySelectorAll('.correlation-link').forEach(function (link) {
      var _onActivate = function (e) {
        e.preventDefault();
        e.stopPropagation();
        _showCorrelationView(link.getAttribute('data-correlation-id'));
      };
      link.addEventListener('click', _onActivate);
      link.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          e.stopPropagation();
          _onActivate(e);
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  function _renderTable() {
    if (!$tbody) return;

    if (_events.length === 0) {
      $tbody.innerHTML = '';
      if ($empty) $empty.classList.remove('hidden');
      return;
    }

    if ($empty) $empty.classList.add('hidden');
    _renderEventRows($tbody, _events);
  }

  function _renderEventRows($target, events) {
    $target.innerHTML = events.map(function (evt) {
      var time = evt.time ? Observatory.fmt.time(evt.time) : '--';
      var timeTitle = evt.time ? Observatory.fmt.datetime(evt.time) : '';
      var timeAgo = evt.time ? Observatory.fmt.timeAgo(evt.time) : '';

      var kindBadge = evt.kind === 'COMMAND'
        ? '<span class="badge badge-xs badge-secondary">CMD</span>'
        : '<span class="badge badge-xs badge-primary">EVT</span>';

      var stream = Observatory.escapeHtml(_extractStreamCategory(evt.stream || ''));
      var streamFull = Observatory.escapeHtml(evt.stream || '--');
      var msgType = Observatory.escapeHtml(_shortTypeName(evt.type || ''));
      var msgTypeFull = Observatory.escapeHtml(evt.type || '');
      var globalPos = evt.global_position != null ? evt.global_position : '--';
      var msgId = Observatory.escapeHtml(evt.message_id || '');

      return '<tr class="hover cursor-pointer event-row" data-message-id="' + msgId + '" tabindex="0" role="button" title="View event detail">' +
        '<td class="text-xs whitespace-nowrap" title="' + timeTitle + '">' +
          '<div>' + time + '</div>' +
          '<div class="text-base-content/40">' + timeAgo + '</div>' +
        '</td>' +
        '<td>' + kindBadge + '</td>' +
        '<td class="text-sm font-mono" title="' + streamFull + '">' + stream + '</td>' +
        '<td class="text-sm" title="' + msgTypeFull + '">' + msgType + '</td>' +
        '<td class="text-right font-mono-metric">' + globalPos + '</td>' +
      '</tr>';
    }).join('');

    // Bind row click and keyboard for detail panel
    $target.querySelectorAll('.event-row').forEach(function (row) {
      var _onActivate = function () {
        _showEventDetail(row.getAttribute('data-message-id'));
      };
      row.addEventListener('click', _onActivate);
      row.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          _onActivate();
        }
      });
    });
  }

  function _renderStats(data) {
    var el = function (id, val) {
      var e = document.getElementById(id);
      if (e) e.textContent = val;
    };
    el('stats-total-events', data.total_events != null ? Observatory.fmt.number(data.total_events) : '--');
    el('stats-active-streams', data.active_streams != null ? Observatory.fmt.number(data.active_streams) : '--');
    el('stats-events-per-min', data.events_per_minute != null ? Observatory.fmt.number(data.events_per_minute) : '--');
    el('stats-last-event', data.last_event_time ? Observatory.fmt.timeAgo(data.last_event_time) : '--');
  }

  function _populateStreamFilter(aggregates) {
    var $select = document.getElementById('filter-stream');
    if (!$select) return;

    // Collect unique stream categories
    var categories = {};
    for (var i = 0; i < aggregates.length; i++) {
      var cat = aggregates[i].stream_category;
      if (cat && !categories[cat]) {
        categories[cat] = true;
      }
    }

    var cats = Object.keys(categories).sort();
    // Keep the "All Streams" option, add others
    var options = '<option value="">All Streams</option>';
    for (var j = 0; j < cats.length; j++) {
      var selected = cats[j] === _streamCategory ? ' selected' : '';
      options += '<option value="' + Observatory.escapeHtml(cats[j]) + '"' + selected + '>' +
        Observatory.escapeHtml(cats[j]) + '</option>';
    }
    $select.innerHTML = options;
  }

  function _updateLoadMore() {
    if (!$loadMore) return;
    if (_nextCursor != null && _events.length > 0) {
      $loadMore.classList.remove('hidden');
    } else {
      $loadMore.classList.add('hidden');
    }
  }

  // ---------------------------------------------------------------------------
  // Event Detail Panel
  // ---------------------------------------------------------------------------

  async function _showEventDetail(messageId) {
    var modal = document.getElementById('event-detail-modal');
    var $meta = document.getElementById('event-detail-meta');
    var $payload = document.getElementById('event-detail-payload');
    var $metadata = document.getElementById('event-detail-metadata');
    if (!modal || !$meta) return;

    $meta.innerHTML = '<div class="col-span-2 text-center"><span class="loading loading-spinner loading-sm"></span></div>';
    if ($payload) $payload.textContent = 'Loading...';
    if ($metadata) $metadata.textContent = 'Loading...';
    modal.showModal();

    try {
      var data = await Observatory.fetchJSON('/api/timeline/events/' + encodeURIComponent(messageId));

      var kindBadge = data.kind === 'COMMAND'
        ? '<span class="badge badge-sm badge-secondary">COMMAND</span>'
        : '<span class="badge badge-sm badge-primary">EVENT</span>';

      // Build correlation link (clickable if present)
      var correlationHtml;
      if (data.correlation_id && data.correlation_id !== '--') {
        correlationHtml = '<a class="link link-hover link-primary font-mono text-xs cursor-pointer" role="button" tabindex="0" id="detail-correlation-link" title="View correlation chain">' +
          Observatory.escapeHtml(data.correlation_id) + '</a>';
      } else {
        correlationHtml = '<span class="font-mono text-xs">--</span>';
      }

      // Build stream link (clickable to navigate to aggregate history)
      var streamHtml;
      if (data.stream) {
        streamHtml = '<a class="link link-hover link-primary font-mono text-xs cursor-pointer" role="button" tabindex="0" id="detail-stream-link" title="View aggregate history">' +
          Observatory.escapeHtml(data.stream) + '</a>';
      } else {
        streamHtml = '<span class="font-mono text-xs">--</span>';
      }

      $meta.innerHTML =
        '<div class="font-semibold">Message ID</div><div class="font-mono text-xs">' + Observatory.escapeHtml(data.message_id || '') + '</div>' +
        '<div class="font-semibold">Type</div><div class="font-mono text-xs">' + Observatory.escapeHtml(data.type || '') + '</div>' +
        '<div class="font-semibold">Kind</div><div>' + kindBadge + '</div>' +
        '<div class="font-semibold">Stream</div><div>' + streamHtml + '</div>' +
        '<div class="font-semibold">Time</div><div>' + (data.time ? Observatory.fmt.datetime(data.time) : '--') + '</div>' +
        '<div class="font-semibold">Global Position</div><div class="font-mono-metric">' + (data.global_position != null ? data.global_position : '--') + '</div>' +
        '<div class="font-semibold">Position</div><div class="font-mono-metric">' + (data.position != null ? data.position : '--') + '</div>' +
        '<div class="font-semibold">Correlation ID</div><div>' + correlationHtml + '</div>' +
        '<div class="font-semibold">Causation ID</div><div class="font-mono text-xs">' + Observatory.escapeHtml(data.causation_id || '--') + '</div>' +
        '<div class="font-semibold">Domain</div><div>' + Observatory.escapeHtml(data.domain || '--') + '</div>';

      // Bind correlation link click and keyboard
      var $corrLink = document.getElementById('detail-correlation-link');
      if ($corrLink) {
        var _onCorrActivate = function () {
          modal.close();
          _showCorrelationView(data.correlation_id);
        };
        $corrLink.addEventListener('click', _onCorrActivate);
        $corrLink.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            _onCorrActivate();
          }
        });
      }

      // Bind stream link click and keyboard (navigate to aggregate history)
      var $streamLink = document.getElementById('detail-stream-link');
      if ($streamLink && data.stream) {
        var _onStreamActivate = function () {
          var parts = _parseStream(data.stream);
          if (parts) {
            modal.close();
            _showAggregateView(parts.category, parts.id);
          }
        };
        $streamLink.addEventListener('click', _onStreamActivate);
        $streamLink.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            _onStreamActivate();
          }
        });
      }

      if ($payload) {
        $payload.textContent = data.data
          ? JSON.stringify(data.data, null, 2)
          : '(no payload)';
      }

      if ($metadata) {
        $metadata.textContent = data.metadata
          ? JSON.stringify(data.metadata, null, 2)
          : '(no metadata)';
      }

    } catch (e) {
      $meta.innerHTML = '<div class="col-span-2 text-error">Failed to load: ' + Observatory.escapeHtml(e.message) + '</div>';
      if ($payload) $payload.textContent = '';
      if ($metadata) $metadata.textContent = '';
    }
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _collectTreeStreams(node) {
    var seen = {};
    var result = [];
    function _walk(n) {
      var cat = _extractStreamCategory(n.stream || '');
      if (cat && cat !== '--' && !seen[cat]) {
        seen[cat] = true;
        result.push(cat);
      }
      if (n.children) {
        for (var i = 0; i < n.children.length; i++) {
          _walk(n.children[i]);
        }
      }
    }
    _walk(node);
    return result;
  }

  function _extractStreamCategory(stream) {
    if (!stream) return '--';
    var idx = stream.indexOf('-');
    return idx > 0 ? stream.substring(0, idx) : stream;
  }

  function _shortTypeName(fullType) {
    if (!fullType) return '';
    // "SomeModule.UserRegistered.v1" -> "UserRegistered"
    var parts = fullType.split('.');
    if (parts.length >= 2) {
      return parts[parts.length - 2];
    }
    return parts[parts.length - 1];
  }

  function _parseStream(stream) {
    if (!stream) return null;
    var idx = stream.indexOf('-');
    if (idx <= 0) return null;
    return {
      category: stream.substring(0, idx),
      id: stream.substring(idx + 1)
    };
  }

  // ---------------------------------------------------------------------------
  // Deep Linking
  // ---------------------------------------------------------------------------

  function _readURL() {
    var params = new URLSearchParams(window.location.search);

    // Check for sub-view deep links first
    if (params.has('correlation')) {
      _showCorrelationView(params.get('correlation'));
      return true; // Signal that we're in a sub-view
    }
    if (params.has('stream') && params.has('aggregate')) {
      _showAggregateView(params.get('stream'), params.get('aggregate'));
      return true;
    }

    // Traces view
    if (params.get('view') === 'traces') {
      // Populate search fields from URL
      var $aggId = document.getElementById('trace-search-aggregate-id');
      var $evtType = document.getElementById('trace-search-event-type');
      var $cmdType = document.getElementById('trace-search-command-type');
      var $streamCat = document.getElementById('trace-search-stream-category');
      if ($aggId && params.has('aggregate_id')) $aggId.value = params.get('aggregate_id');
      if ($evtType && params.has('event_type')) $evtType.value = params.get('event_type');
      if ($cmdType && params.has('command_type')) $cmdType.value = params.get('command_type');
      if ($streamCat && params.has('stream_category')) $streamCat.value = params.get('stream_category');

      _showView('traces');
      // If any search params, trigger search; otherwise fetch recent
      if (params.has('aggregate_id') || params.has('event_type') || params.has('command_type') || params.has('stream_category')) {
        searchTraces();
      } else {
        fetchRecentTraces();
      }
      return true;
    }

    // Normal list view filters
    if (params.has('stream_category')) _streamCategory = params.get('stream_category');
    if (params.has('event_type')) _eventType = params.get('event_type');
    if (params.has('aggregate_id')) _aggregateId = params.get('aggregate_id');
    if (params.has('kind')) _kind = params.get('kind');
    if (params.has('order')) _order = params.get('order') === 'asc' ? 'asc' : 'desc';

    return false; // Normal list view
  }

  function _updateURL() {
    var params = new URLSearchParams();
    if (_streamCategory) params.set('stream_category', _streamCategory);
    if (_eventType) params.set('event_type', _eventType);
    if (_aggregateId) params.set('aggregate_id', _aggregateId);
    if (_kind) params.set('kind', _kind);
    if (_order !== 'desc') params.set('order', _order);
    var qs = params.toString();
    var url = window.location.pathname + (qs ? '?' + qs : '');
    history.replaceState(null, '', url);
  }

  function _syncUIFromState() {
    var $stream = document.getElementById('filter-stream');
    var $evtType = document.getElementById('filter-event-type');
    var $aggId = document.getElementById('filter-aggregate-id');
    var $kindSel = document.getElementById('filter-kind');

    if ($stream) $stream.value = _streamCategory;
    if ($evtType) $evtType.value = _eventType;
    if ($aggId) $aggId.value = _aggregateId;
    if ($kindSel) $kindSel.value = _kind;

    _updateOrderButtons();
  }

  function _updateOrderButtons() {
    var $asc = document.getElementById('btn-order-asc');
    var $desc = document.getElementById('btn-order-desc');
    if ($asc) {
      $asc.className = 'join-item btn btn-xs ' + (_order === 'asc' ? 'btn-primary' : 'btn-ghost');
    }
    if ($desc) {
      $desc.className = 'join-item btn btn-xs ' + (_order === 'desc' ? 'btn-primary' : 'btn-ghost');
    }
  }

  // ---------------------------------------------------------------------------
  // Filter Change Handler
  // ---------------------------------------------------------------------------

  function _onFilterChange() {
    _updateURL();
    fetchEvents(false);
  }

  // ---------------------------------------------------------------------------
  // Event Binding
  // ---------------------------------------------------------------------------

  function _bindEvents() {
    // Stream category filter
    var $stream = document.getElementById('filter-stream');
    if ($stream) {
      $stream.addEventListener('change', function () {
        _streamCategory = $stream.value;
        _onFilterChange();
      });
    }

    // Event type filter (debounced)
    var $evtType = document.getElementById('filter-event-type');
    if ($evtType) {
      var evtTypeTimer;
      $evtType.addEventListener('input', function () {
        clearTimeout(evtTypeTimer);
        evtTypeTimer = setTimeout(function () {
          _eventType = $evtType.value.trim();
          _onFilterChange();
        }, 300);
      });
    }

    // Aggregate ID filter (debounced)
    var $aggId = document.getElementById('filter-aggregate-id');
    if ($aggId) {
      var aggIdTimer;
      $aggId.addEventListener('input', function () {
        clearTimeout(aggIdTimer);
        aggIdTimer = setTimeout(function () {
          _aggregateId = $aggId.value.trim();
          _onFilterChange();
        }, 300);
      });
    }

    // Kind filter
    var $kindSel = document.getElementById('filter-kind');
    if ($kindSel) {
      $kindSel.addEventListener('change', function () {
        _kind = $kindSel.value;
        _onFilterChange();
      });
    }

    // Order buttons
    var $btnAsc = document.getElementById('btn-order-asc');
    var $btnDesc = document.getElementById('btn-order-desc');
    if ($btnAsc) {
      $btnAsc.addEventListener('click', function () {
        _order = 'asc';
        _updateOrderButtons();
        _onFilterChange();
      });
    }
    if ($btnDesc) {
      $btnDesc.addEventListener('click', function () {
        _order = 'desc';
        _updateOrderButtons();
        _onFilterChange();
      });
    }

    // Clear filters
    var $clear = document.getElementById('btn-clear-filters');
    if ($clear) {
      $clear.addEventListener('click', function () {
        _streamCategory = '';
        _eventType = '';
        _aggregateId = '';
        _kind = '';
        _order = 'desc';
        _syncUIFromState();
        _onFilterChange();
      });
    }

    // Load more button
    var $btnLoadMore = document.getElementById('btn-load-more');
    if ($btnLoadMore) {
      $btnLoadMore.addEventListener('click', function () {
        fetchEvents(true);
      });
    }

    // Infinite scroll: load more when scrolling near bottom
    var _scrollTimer;
    window.addEventListener('scroll', function () {
      clearTimeout(_scrollTimer);
      _scrollTimer = setTimeout(function () {
        if (_loading || _nextCursor == null || _currentView !== 'list') return;
        var scrollBottom = window.innerHeight + window.scrollY;
        var docHeight = document.documentElement.scrollHeight;
        if (docHeight - scrollBottom < 300) {
          fetchEvents(true);
        }
      }, 100);
    });

    // Back buttons
    var $backCorr = document.getElementById('btn-back-from-correlation');
    if ($backCorr) {
      $backCorr.addEventListener('click', _backToList);
    }

    var $backAgg = document.getElementById('btn-back-from-aggregate');
    if ($backAgg) {
      $backAgg.addEventListener('click', _backToList);
    }

    // Tab switching
    var $tabEvents = document.getElementById('tab-events');
    var $tabTraces = document.getElementById('tab-traces');
    if ($tabEvents) {
      $tabEvents.addEventListener('click', function () {
        _enterListView();
      });
    }
    if ($tabTraces) {
      $tabTraces.addEventListener('click', function () {
        _enterTracesView();
      });
    }

    // Trace search inputs (debounced)
    var traceSearchIds = [
      'trace-search-aggregate-id',
      'trace-search-event-type',
      'trace-search-command-type',
      'trace-search-stream-category'
    ];
    traceSearchIds.forEach(function (id) {
      var $input = document.getElementById(id);
      if ($input) {
        $input.addEventListener('input', function () {
          clearTimeout(_traceSearchTimer);
          _traceSearchTimer = setTimeout(function () {
            searchTraces();
          }, 300);
        });
      }
    });

    // Clear trace search
    var $clearTrace = document.getElementById('btn-clear-trace-search');
    if ($clearTrace) {
      $clearTrace.addEventListener('click', function () {
        traceSearchIds.forEach(function (id) {
          var $input = document.getElementById(id);
          if ($input) $input.value = '';
        });
        fetchRecentTraces();
        _updateTracesURL();
      });
    }

    // Browser back/forward navigation
    window.addEventListener('popstate', function () {
      var params = new URLSearchParams(window.location.search);
      if (params.has('correlation')) {
        _showCorrelationView(params.get('correlation'));
      } else if (params.has('stream') && params.has('aggregate')) {
        _showAggregateView(params.get('stream'), params.get('aggregate'));
      } else if (params.get('view') === 'traces') {
        // Re-apply search params from URL into inputs
        var $aggId = document.getElementById('trace-search-aggregate-id');
        var $evtType = document.getElementById('trace-search-event-type');
        var $cmdType = document.getElementById('trace-search-command-type');
        var $streamCat = document.getElementById('trace-search-stream-category');
        if ($aggId) $aggId.value = params.get('aggregate_id') || '';
        if ($evtType) $evtType.value = params.get('event_type') || '';
        if ($cmdType) $cmdType.value = params.get('command_type') || '';
        if ($streamCat) $streamCat.value = params.get('stream_category') || '';
        _showView('traces');
        if (_hasTraceSearchCriteria()) {
          searchTraces();
        } else {
          fetchRecentTraces();
        }
      } else {
        _enterListView();
      }
    });
  }

  // ---------------------------------------------------------------------------
  // SSE Real-Time Updates
  // ---------------------------------------------------------------------------

  /** Trace event types that signal new events in the event store. */
  var _LIVE_TRACE_EVENTS = {
    'handler.completed': true,
    'outbox.published': true,
    'outbox.external_published': true,
  };

  /**
   * Handle an incoming SSE trace event.  When a handler completes or an
   * outbox publishes, new events may have landed in the event store.
   * Fetch the latest event and, if it matches the active filters, prepend
   * it to the list (when sorted newest-first).
   *
   * Debounced to coalesce bursts of traces into a single API call, and
   * skipped entirely while a fetchEvents() call is in progress to avoid
   * race conditions with _events mutations.
   */
  function _onTraceEvent(trace) {
    if (!_LIVE_TRACE_EVENTS[trace.event]) return;
    if (_currentView !== 'list') return;
    if (_loading) return;

    // Debounce: coalesce rapid traces into one fetch
    clearTimeout(_sseDebounceTimer);
    _sseDebounceTimer = setTimeout(function () {
      // Refresh stats
      fetchStats();
      // Fetch the newest event
      _fetchLatestEvent();
    }, 300);
  }

  /**
   * Fetch the most recent event from the event store and prepend it to the
   * list if it's genuinely new and matches the current filters.
   */
  async function _fetchLatestEvent() {
    try {
      var qs = new URLSearchParams();
      qs.set('limit', '1');
      qs.set('order', 'desc');
      if (_streamCategory) qs.set('stream_category', _streamCategory);
      if (_eventType) qs.set('event_type', _eventType);
      if (_aggregateId) qs.set('aggregate_id', _aggregateId);
      if (_kind) qs.set('kind', _kind);

      var data = await Observatory.fetchJSON('/api/timeline/events?' + qs.toString());
      var newEvents = data.events || [];
      if (newEvents.length === 0) return;

      var latest = newEvents[0];
      var latestPos = latest.global_position;

      // Skip if we already have this event
      if (latestPos != null && latestPos <= _lastKnownPosition) return;

      // Update high-water mark
      if (latestPos != null) _lastKnownPosition = latestPos;

      if (_order === 'desc') {
        // Check if already present by message_id
        var dominated = false;
        for (var i = 0; i < _events.length; i++) {
          if (_events[i].message_id === latest.message_id) {
            dominated = true;
            break;
          }
        }
        if (dominated) return;

        // Prepend to the list
        _events.unshift(latest);
        _renderTable();

        // Highlight the new row
        if ($tbody && $tbody.firstElementChild) {
          $tbody.firstElementChild.classList.add('sse-new-event');
        }

        // If user is scrolled down, show/update toast
        if (_isScrolledDown()) {
          _pendingNewEvents++;
          _showToast(_pendingNewEvents);
        }
      } else {
        // In ascending order, new events belong at the end — just refresh
        fetchEvents(false);
      }
    } catch (e) {
      // Non-fatal: the next SSE trace or manual refresh will retry
      console.warn('SSE fetch latest event failed:', e.message);
    }
  }

  /**
   * Check whether the user has scrolled away from the top.
   */
  function _isScrolledDown() {
    return window.scrollY > 200;
  }

  /**
   * Show or update the "N new events" toast at the top of the timeline.
   */
  function _showToast(count) {
    if (!$toast) return;
    var label = count === 1 ? '1 new event' : count + ' new events';
    $toast.querySelector('.toast-label').textContent = label + ' \u2014 click to scroll to top';
    $toast.classList.remove('hidden');
  }

  /**
   * Hide the toast and reset the pending counter.
   */
  function _dismissToast() {
    _pendingNewEvents = 0;
    if ($toast) $toast.classList.add('hidden');
  }

  /**
   * Scroll to the top and dismiss the toast.
   */
  function _scrollToTopAndDismiss() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    _dismissToast();
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  function init() {
    $tbody = document.getElementById('events-tbody');
    $empty = document.getElementById('events-empty');
    $loadMore = document.getElementById('load-more');
    $loadingMore = document.getElementById('loading-more');
    $toast = document.getElementById('sse-toast');

    _bindEvents();

    // Bind toast click
    if ($toast) {
      $toast.addEventListener('click', _scrollToTopAndDismiss);
    }

    // Dismiss toast when user scrolls back to top
    window.addEventListener('scroll', function () {
      if (!_isScrolledDown() && _pendingNewEvents > 0) {
        _dismissToast();
      }
    });

    // Read URL — may switch to sub-view
    var isSubView = _readURL();

    if (!isSubView) {
      _syncUIFromState();
      fetchEvents(false);
    }

    // Always fetch stats and streams (needed for list view)
    fetchStats();
    fetchStreams();

    // Register stats poller (refresh every 15s)
    Observatory.poller.register('timeline-stats', '/api/timeline/stats', 15000, function (data) {
      if (data) _renderStats(data);
    });

    // SSE: listen for trace events that indicate new events in the store
    Observatory.sse.onTrace(_onTraceEvent);
  }

  // Wait for Observatory core
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      setTimeout(init, 100);
    });
  } else {
    setTimeout(init, 100);
  }
})();
