/**
 * Infrastructure View Module
 *
 * Fetches infrastructure status from /api/infrastructure/status, renders
 * connection health tiles, broker details, and server information.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _statusDotClass(status) {
    if (status === 'healthy') return 'badge-success';
    if (status === 'unhealthy') return 'badge-error';
    if (status === 'not_configured') return 'badge-ghost';
    return 'badge-warning';
  }

  function _statusLabel(status) {
    if (status === 'healthy') return 'Connected';
    if (status === 'unhealthy') return 'Unavailable';
    if (status === 'not_configured') return 'Not Configured';
    return 'Unknown';
  }

  function _formatUptime(seconds) {
    if (seconds == null) return '--';
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h';
    return Math.floor(seconds / 86400) + 'd';
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  function _updateTile(prefix, conn) {
    const $dot = document.getElementById(prefix + '-dot');
    const $provider = document.getElementById(prefix + '-provider');
    const $status = document.getElementById(prefix + '-status');

    if ($dot) {
      $dot.className = 'badge badge-xs ' + _statusDotClass(conn.status);
    }
    if ($provider) {
      $provider.textContent = conn.provider || '--';
    }
    if ($status) {
      $status.textContent = _statusLabel(conn.status);
    }
  }

  function _updateConnectionTiles(connections) {
    if (connections.database) _updateTile('tile-database', connections.database);
    if (connections.broker) _updateTile('tile-broker', connections.broker);
    if (connections.event_store) _updateTile('tile-event-store', connections.event_store);
    if (connections.cache) _updateTile('tile-cache', connections.cache);
  }

  function _updateBrokerDetail(details) {
    const el = (id, val) => {
      const e = document.getElementById(id);
      if (e) e.textContent = val != null ? val : '--';
    };

    el('broker-redis-version', details.redis_version);
    el('broker-connected-clients', details.connected_clients);
    el('broker-memory', details.used_memory_human);
    el('broker-uptime', _formatUptime(details.uptime_in_seconds));
    el('broker-ops-per-sec', details.instantaneous_ops_per_sec);
    el('broker-stream-count', details.stream_count);
    el('broker-consumer-groups', details.consumer_group_count);
    el('broker-hit-rate', details.hit_rate != null ? details.hit_rate + '%' : '--');
  }

  function _updateServerInfo(server) {
    const el = (id, val) => {
      const e = document.getElementById(id);
      if (e) e.textContent = val != null ? val : '--';
    };

    el('server-python-version', server.python_version);
    el('server-protean-version', server.protean_version);
    el('server-platform', server.platform);

    // Domain configuration
    const $domains = document.getElementById('server-domains');
    if (!$domains) return;

    const domains = server.domains || [];
    if (domains.length === 0) {
      $domains.innerHTML = '<span class="text-base-content/50">No domains configured.</span>';
      return;
    }

    const html = domains.map(d => {
      const config = d.config || {};
      const rows = Object.entries(config).map(([key, value]) => {
        let displayVal;
        if (typeof value === 'object' && value !== null) {
          displayVal = Observatory.escapeHtml(JSON.stringify(value));
        } else {
          displayVal = Observatory.escapeHtml(String(value));
        }
        return `<tr>
          <td class="text-xs font-medium pr-4">${Observatory.escapeHtml(key)}</td>
          <td class="text-xs text-base-content/70 font-mono break-all">${displayVal}</td>
        </tr>`;
      }).join('');

      return `<div class="mb-4">
        <div class="font-semibold text-sm mb-2">${Observatory.escapeHtml(d.name)}</div>
        <table class="table table-xs">${rows}</table>
      </div>`;
    }).join('');

    $domains.innerHTML = html;
  }

  // ---------------------------------------------------------------------------
  // Data Loading
  // ---------------------------------------------------------------------------

  function _onDataLoaded(data) {
    if (!data) return;

    if (data.connections) {
      _updateConnectionTiles(data.connections);

      // Update broker detail if broker data available
      if (data.connections.broker && data.connections.broker.details) {
        _updateBrokerDetail(data.connections.broker.details);
      }
    }

    if (data.server) {
      _updateServerInfo(data.server);
    }
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  function init() {
    // Register poller for infrastructure status
    Observatory.poller.register(
      'infrastructure', '/api/infrastructure/status', 10000, _onDataLoaded
    );
  }

  // Wait for DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
