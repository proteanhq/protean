/**
 * Timeline View Module
 *
 * Chronological event browser for the Observatory. Fetches events from
 * /api/timeline/* endpoints, renders the event list with filtering,
 * cursor-based pagination, and an event detail panel.
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

  // DOM refs
  let $tbody, $empty, $loadMore, $loadingMore;

  // ---------------------------------------------------------------------------
  // Data Fetching
  // ---------------------------------------------------------------------------

  function _buildQueryString(cursor) {
    const params = new URLSearchParams();
    params.set('limit', '50');
    params.set('order', _order);
    if (cursor) params.set('cursor', String(cursor));
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

    const cursor = append ? _nextCursor : 0;
    if (append && cursor == null) {
      _loading = false;
      return;
    }

    if ($loadingMore) $loadingMore.classList.remove('hidden');

    try {
      const qs = _buildQueryString(cursor);
      const data = await Observatory.fetchJSON('/api/timeline/events?' + qs);
      const newEvents = data.events || [];

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
  }

  async function fetchStats() {
    try {
      const data = await Observatory.fetchJSON('/api/timeline/stats');
      _renderStats(data);
    } catch (e) {
      console.warn('Failed to fetch timeline stats:', e.message);
    }
  }

  async function fetchStreams() {
    try {
      const data = await Observatory.fetchJSON('/api/eventstore/streams');
      _populateStreamFilter(data.aggregates || []);
    } catch (e) {
      console.warn('Failed to fetch stream categories:', e.message);
    }
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

    $tbody.innerHTML = _events.map(evt => {
      const time = evt.time ? Observatory.fmt.time(evt.time) : '--';
      const timeTitle = evt.time ? Observatory.fmt.datetime(evt.time) : '';
      const timeAgo = evt.time ? Observatory.fmt.timeAgo(evt.time) : '';

      const kindBadge = evt.kind === 'COMMAND'
        ? '<span class="badge badge-xs badge-secondary">CMD</span>'
        : '<span class="badge badge-xs badge-primary">EVT</span>';

      const stream = Observatory.escapeHtml(_extractStreamCategory(evt.stream || ''));
      const streamFull = Observatory.escapeHtml(evt.stream || '--');
      const msgType = Observatory.escapeHtml(_shortTypeName(evt.type || ''));
      const msgTypeFull = Observatory.escapeHtml(evt.type || '');
      const globalPos = evt.global_position != null ? evt.global_position : '--';
      const msgId = Observatory.escapeHtml(evt.message_id || '');

      return '<tr class="hover cursor-pointer event-row" data-message-id="' + msgId + '">' +
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

    // Bind row click for detail panel
    $tbody.querySelectorAll('.event-row').forEach(function (row) {
      row.addEventListener('click', function () {
        _showEventDetail(row.getAttribute('data-message-id'));
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
    var $corrLink = document.getElementById('event-detail-correlation-link');
    if (!modal || !$meta) return;

    $meta.innerHTML = '<div class="col-span-2 text-center"><span class="loading loading-spinner loading-sm"></span></div>';
    if ($payload) $payload.textContent = 'Loading...';
    if ($metadata) $metadata.textContent = 'Loading...';
    if ($corrLink) $corrLink.classList.add('hidden');
    modal.showModal();

    try {
      var data = await Observatory.fetchJSON('/api/timeline/events/' + encodeURIComponent(messageId));

      var kindBadge = data.kind === 'COMMAND'
        ? '<span class="badge badge-sm badge-secondary">COMMAND</span>'
        : '<span class="badge badge-sm badge-primary">EVENT</span>';

      $meta.innerHTML =
        '<div class="font-semibold">Message ID</div><div class="font-mono text-xs">' + Observatory.escapeHtml(data.message_id || '') + '</div>' +
        '<div class="font-semibold">Type</div><div class="font-mono text-xs">' + Observatory.escapeHtml(data.type || '') + '</div>' +
        '<div class="font-semibold">Kind</div><div>' + kindBadge + '</div>' +
        '<div class="font-semibold">Stream</div><div class="font-mono text-xs">' + Observatory.escapeHtml(data.stream || '') + '</div>' +
        '<div class="font-semibold">Time</div><div>' + (data.time ? Observatory.fmt.datetime(data.time) : '--') + '</div>' +
        '<div class="font-semibold">Global Position</div><div class="font-mono-metric">' + (data.global_position != null ? data.global_position : '--') + '</div>' +
        '<div class="font-semibold">Position</div><div class="font-mono-metric">' + (data.position != null ? data.position : '--') + '</div>' +
        '<div class="font-semibold">Correlation ID</div><div class="font-mono text-xs">' + Observatory.escapeHtml(data.correlation_id || '--') + '</div>' +
        '<div class="font-semibold">Causation ID</div><div class="font-mono text-xs">' + Observatory.escapeHtml(data.causation_id || '--') + '</div>' +
        '<div class="font-semibold">Domain</div><div>' + Observatory.escapeHtml(data.domain || '--') + '</div>';

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

      // Show correlation link if available
      if ($corrLink && data.correlation_id) {
        $corrLink.href = '/timeline?correlation=' + encodeURIComponent(data.correlation_id);
        $corrLink.classList.remove('hidden');
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
    // "SomeModule.UserRegistered.v1" → "UserRegistered"
    var parts = fullType.split('.');
    if (parts.length >= 2) {
      return parts[parts.length - 2];
    }
    return parts[parts.length - 1];
  }

  // ---------------------------------------------------------------------------
  // Deep Linking
  // ---------------------------------------------------------------------------

  function _readURL() {
    var params = new URLSearchParams(window.location.search);
    if (params.has('stream_category')) _streamCategory = params.get('stream_category');
    if (params.has('event_type')) _eventType = params.get('event_type');
    if (params.has('aggregate_id')) _aggregateId = params.get('aggregate_id');
    if (params.has('kind')) _kind = params.get('kind');
    if (params.has('order')) _order = params.get('order') === 'asc' ? 'asc' : 'desc';
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
        if (_loading || _nextCursor == null) return;
        var scrollBottom = window.innerHeight + window.scrollY;
        var docHeight = document.documentElement.scrollHeight;
        if (docHeight - scrollBottom < 300) {
          fetchEvents(true);
        }
      }, 100);
    });
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  function init() {
    $tbody = document.getElementById('events-tbody');
    $empty = document.getElementById('events-empty');
    $loadMore = document.getElementById('load-more');
    $loadingMore = document.getElementById('loading-more');

    _readURL();
    _syncUIFromState();
    _bindEvents();

    // Fetch initial data
    fetchEvents(false);
    fetchStats();
    fetchStreams();

    // Register stats poller (refresh every 15s)
    Observatory.poller.register('timeline-stats', '/api/timeline/stats', 15000, function (data) {
      if (data) _renderStats(data);
    });
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
