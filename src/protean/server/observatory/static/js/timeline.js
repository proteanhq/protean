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

  // Current view: 'list' | 'correlation' | 'aggregate'
  let _currentView = 'list';

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
    var $corr = document.getElementById('correlation-view');
    var $agg = document.getElementById('aggregate-view');

    if ($list) $list.classList.toggle('hidden', view !== 'list');
    if ($corr) $corr.classList.toggle('hidden', view !== 'correlation');
    if ($agg) $agg.classList.toggle('hidden', view !== 'aggregate');
  }

  function _enterListView() {
    _showView('list');
    _syncUIFromState();
    _updateURL();
    fetchEvents(false);
    window.scrollTo(0, 0);
  }

  function _backToList() {
    _enterListView();
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
  // Correlation Chain
  // ---------------------------------------------------------------------------

  async function _showCorrelationView(correlationId) {
    _showView('correlation');

    var $idDisplay = document.getElementById('correlation-id-display');
    var $eventCount = document.getElementById('correlation-event-count');
    var $rootType = document.getElementById('correlation-root-type');
    var $depth = document.getElementById('correlation-depth');
    var $tree = document.getElementById('correlation-tree');
    var $corrTbody = document.getElementById('correlation-events-tbody');

    if ($idDisplay) $idDisplay.textContent = correlationId;
    if ($eventCount) $eventCount.textContent = '--';
    if ($rootType) $rootType.textContent = 'Loading...';
    if ($depth) $depth.textContent = '--';
    if ($tree) $tree.innerHTML = '<div class="text-center py-8"><span class="loading loading-spinner loading-sm"></span></div>';
    if ($corrTbody) $corrTbody.innerHTML = '<tr><td colspan="5" class="text-center text-base-content/50 py-4">Loading...</td></tr>';

    // Push a new history entry so browser Back returns to the previous view
    var params = new URLSearchParams();
    params.set('correlation', correlationId);
    history.pushState({view: 'correlation', correlationId: correlationId}, '', window.location.pathname + '?' + params.toString());

    try {
      var data = await Observatory.fetchJSON('/api/timeline/correlation/' + encodeURIComponent(correlationId));

      if ($eventCount) $eventCount.textContent = data.event_count || 0;

      // Render causation tree
      if (data.tree && $tree) {
        var treeDepth = _computeTreeDepth(data.tree);
        if ($depth) $depth.textContent = treeDepth;
        if ($rootType) $rootType.textContent = _shortTypeName(data.tree.message_type || '');
        $tree.innerHTML = '';
        $tree.appendChild(_renderCausationTree(data.tree, 0));
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

  function _renderCausationTree(node, depth) {
    var container = document.createElement('div');
    container.className = 'vtl-node' + (depth === 0 ? ' vtl-root' : '');

    var kindClass = node.kind === 'COMMAND' ? 'badge-secondary' : 'badge-primary';
    var kindLabel = node.kind === 'COMMAND' ? 'CMD' : 'EVT';
    var shortType = Observatory.escapeHtml(_shortTypeName(node.message_type || ''));
    var fullType = Observatory.escapeHtml(node.message_type || '');
    var stream = Observatory.escapeHtml(node.stream || '--');
    var time = node.time ? Observatory.fmt.time(node.time) : '--';
    var timeAgo = node.time ? Observatory.fmt.timeAgo(node.time) : '';
    var pos = node.global_position != null ? node.global_position : '--';

    var card = document.createElement('div');
    card.className = 'vtl-card cursor-pointer';
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('data-message-id', node.message_id || '');
    card.setAttribute('title', 'View event detail for ' + (node.message_type || 'event'));
    card.innerHTML =
      '<div class="flex items-center gap-2 mb-1">' +
        '<span class="badge badge-xs ' + kindClass + '">' + kindLabel + '</span>' +
        '<span class="font-semibold text-sm" title="' + fullType + '">' + shortType + '</span>' +
        '<span class="text-xs text-base-content/40 ml-auto font-mono-metric">#' + pos + '</span>' +
      '</div>' +
      '<div class="flex items-center gap-3 text-xs text-base-content/60">' +
        '<span class="font-mono">' + stream + '</span>' +
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

    // Render children
    if (node.children && node.children.length > 0) {
      var childrenWrap = document.createElement('div');
      childrenWrap.className = 'vtl-children';
      for (var i = 0; i < node.children.length; i++) {
        childrenWrap.appendChild(_renderCausationTree(node.children[i], depth + 1));
      }
      container.appendChild(childrenWrap);
    }

    return container;
  }

  // ---------------------------------------------------------------------------
  // Aggregate History
  // ---------------------------------------------------------------------------

  async function _showAggregateView(streamCategory, aggregateId) {
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

    // Browser back/forward navigation
    window.addEventListener('popstate', function () {
      var params = new URLSearchParams(window.location.search);
      if (params.has('correlation')) {
        _showCorrelationView(params.get('correlation'));
      } else if (params.has('stream') && params.has('aggregate')) {
        _showAggregateView(params.get('stream'), params.get('aggregate'));
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
