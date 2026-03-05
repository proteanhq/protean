/**
 * Observatory Core Module
 *
 * Centralized SSE connection, polling scheduler, fetch helpers, and formatting
 * utilities. Shared across all views.
 */
const Observatory = (() => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const state = {
    connected: false,
    paused: false,
    window: '5m',
    domain: null,
    theme: localStorage.getItem('observatory-theme') || 'light',
  };

  // SSE event listeners (keyed by event name)
  const _sseListeners = {};

  // Active pollers: { name: { url, intervalMs, callback, timerId } }
  const _pollers = {};

  let _eventSource = null;

  // ---------------------------------------------------------------------------
  // SSE Connection
  // ---------------------------------------------------------------------------
  const sse = {
    /**
     * Connect to the SSE stream endpoint.
     * Automatically reconnects on error.
     */
    connect(domain) {
      if (_eventSource) {
        _eventSource.close();
      }

      let url = '/stream';
      if (domain) {
        url += `?domain=${encodeURIComponent(domain)}`;
      }

      _eventSource = new EventSource(url);

      _eventSource.onopen = () => {
        state.connected = true;
        _updateConnectionUI(true);
      };

      _eventSource.onerror = () => {
        state.connected = false;
        _updateConnectionUI(false);
        // EventSource reconnects automatically
      };

      _eventSource.addEventListener('trace', (event) => {
        if (state.paused) return;
        try {
          const data = JSON.parse(event.data);
          // Dispatch to registered listeners
          const listeners = _sseListeners['trace'] || [];
          for (const cb of listeners) {
            cb(data);
          }
        } catch (e) {
          console.warn('Failed to parse SSE trace event:', e);
        }
      });

      _eventSource.addEventListener('error', (event) => {
        try {
          const data = JSON.parse(event.data);
          console.warn('SSE error event:', data);
        } catch (e) {
          // Connection error, not a data error
        }
      });
    },

    /**
     * Register a callback for SSE trace events.
     * Returns an unsubscribe function.
     */
    onTrace(callback) {
      if (!_sseListeners['trace']) {
        _sseListeners['trace'] = [];
      }
      _sseListeners['trace'].push(callback);
      return () => {
        _sseListeners['trace'] = _sseListeners['trace'].filter(cb => cb !== callback);
      };
    },

    disconnect() {
      if (_eventSource) {
        _eventSource.close();
        _eventSource = null;
      }
      state.connected = false;
      _updateConnectionUI(false);
    },
  };

  // ---------------------------------------------------------------------------
  // Polling Scheduler
  // ---------------------------------------------------------------------------
  const poller = {
    /**
     * Register a polling endpoint.
     * @param {string} name - Unique name for this poller
     * @param {string} url - API endpoint URL
     * @param {number} intervalMs - Polling interval in ms
     * @param {function} callback - Called with JSON response data
     */
    register(name, url, intervalMs, callback) {
      // Stop existing poller with same name
      if (_pollers[name]) {
        clearInterval(_pollers[name].timerId);
      }

      const poll = async () => {
        if (state.paused) return;
        try {
          const data = await fetchWithWindow(url);
          callback(data);
        } catch (e) {
          console.warn(`Poller '${name}' failed:`, e.message);
        }
      };

      // Initial fetch
      poll();

      // Schedule recurring
      const timerId = setInterval(poll, intervalMs);
      _pollers[name] = { url, intervalMs, callback, timerId };
    },

    /** Stop a specific poller. */
    stop(name) {
      if (_pollers[name]) {
        clearInterval(_pollers[name].timerId);
        delete _pollers[name];
      }
    },

    /** Stop all pollers. */
    stopAll() {
      for (const name of Object.keys(_pollers)) {
        clearInterval(_pollers[name].timerId);
      }
      Object.keys(_pollers).forEach(k => delete _pollers[k]);
    },

    /** Pause all pollers (they remain registered but don't fire). */
    pause() {
      state.paused = true;
    },

    /** Resume all pollers. */
    resume() {
      state.paused = false;
    },
  };

  // ---------------------------------------------------------------------------
  // Fetch Helpers
  // ---------------------------------------------------------------------------

  /**
   * Fetch JSON from an API endpoint with error handling.
   */
  async function fetchJSON(url) {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return response.json();
  }

  /**
   * Fetch JSON with the current time window appended.
   */
  async function fetchWithWindow(url) {
    const separator = url.includes('?') ? '&' : '?';
    return fetchJSON(`${url}${separator}window=${state.window}`);
  }

  // ---------------------------------------------------------------------------
  // Formatting Utilities
  // ---------------------------------------------------------------------------
  const fmt = {
    /** Format a number with SI suffixes: 1234 → "1.2K", 1234567 → "1.2M" */
    number(n) {
      if (n == null) return '—';
      if (typeof n !== 'number') n = Number(n);
      if (isNaN(n)) return '—';
      if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + 'M';
      if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'K';
      if (Number.isInteger(n)) return n.toString();
      return n.toFixed(1);
    },

    /** Format a duration in ms: 23 → "23ms", 1234 → "1.2s", 65000 → "1.1m" */
    duration(ms) {
      if (ms == null) return '—';
      if (ms < 1) return '<1ms';
      if (ms < 1000) return Math.round(ms) + 'ms';
      if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
      return (ms / 60000).toFixed(1) + 'm';
    },

    /** Format a timestamp as relative time: "2m ago", "1h ago" */
    timeAgo(ts) {
      if (!ts) return '—';
      const now = Date.now();
      const then = typeof ts === 'string' ? new Date(ts).getTime() : ts;
      const diff = now - then;
      if (diff < 60000) return Math.floor(diff / 1000) + 's ago';
      if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
      if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
      return Math.floor(diff / 86400000) + 'd ago';
    },

    /** Format a percentage: 0.0523 → "5.2%" */
    percent(n) {
      if (n == null) return '—';
      return (n * 100).toFixed(1) + '%';
    },

    /** Format a percentage that's already in 0-100 range */
    pct(n) {
      if (n == null) return '—';
      if (n > 0 && n < 0.1) return '< 0.1%';
      return n.toFixed(1) + '%';
    },

    /** Format an ISO timestamp for display */
    time(ts) {
      if (!ts) return '—';
      const d = new Date(ts);
      return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    },

    /** Format a full date-time */
    datetime(ts) {
      if (!ts) return '—';
      const d = new Date(ts);
      return d.toLocaleString();
    },
  };

  // ---------------------------------------------------------------------------
  // UI Helpers
  // ---------------------------------------------------------------------------

  function _updateConnectionUI(connected) {
    const dot = document.getElementById('sse-dot');
    const badge = document.getElementById('sse-status');
    if (dot) {
      dot.className = connected
        ? 'status status-xs status-success'
        : 'status status-xs status-error';
    }
    if (badge) {
      badge.className = connected
        ? 'badge badge-sm badge-success badge-outline'
        : 'badge badge-sm badge-error badge-outline';
    }
  }

  /**
   * Set the active time window and update UI.
   */
  function setWindow(w) {
    state.window = w;
    loading.start();
    // Update button styles
    document.querySelectorAll('#window-selector button').forEach(btn => {
      if (btn.dataset.window === w) {
        btn.className = 'join-item btn btn-xs btn-primary';
      } else {
        btn.className = 'join-item btn btn-xs btn-ghost';
      }
    });
    // Trigger a refresh of all pollers with updated window
    for (const [name, p] of Object.entries(_pollers)) {
      p.callback(null); // Signal to re-fetch
      clearInterval(p.timerId);
      const poll = async () => {
        if (state.paused) return;
        try {
          const data = await fetchWithWindow(p.url);
          p.callback(data);
        } catch (e) {
          console.warn(`Poller '${name}' failed:`, e.message);
        }
      };
      poll();
      p.timerId = setInterval(poll, p.intervalMs);
    }
  }

  /**
   * Toggle pause/resume state.
   */
  function togglePause() {
    state.paused = !state.paused;
    const pauseIcon = document.getElementById('pause-icon');
    const playIcon = document.getElementById('play-icon');
    if (pauseIcon && playIcon) {
      pauseIcon.classList.toggle('hidden', state.paused);
      playIcon.classList.toggle('hidden', !state.paused);
    }
  }

  /**
   * Toggle dark/light theme.
   */
  function toggleTheme() {
    state.theme = state.theme === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', state.theme);
    localStorage.setItem('observatory-theme', state.theme);
  }

  // ---------------------------------------------------------------------------
  // Health Status Helpers
  // ---------------------------------------------------------------------------

  /**
   * Returns a DaisyUI status color class based on health status.
   * @param {string} status - "ok", "lagging", "error", "unknown"
   * @returns {string} - CSS class like "status-success", "status-warning", etc.
   */
  function statusClass(status) {
    switch (status) {
      case 'ok': case 'healthy': case 'active': return 'status-success';
      case 'lagging': case 'degraded': case 'warning': return 'status-warning';
      case 'error': case 'critical': case 'offline': return 'status-error';
      default: return 'status-neutral';
    }
  }

  /**
   * Returns a DaisyUI badge color class based on health status.
   */
  function badgeClass(status) {
    switch (status) {
      case 'ok': case 'healthy': return 'badge-success';
      case 'lagging': case 'degraded': return 'badge-warning';
      case 'error': case 'critical': return 'badge-error';
      default: return 'badge-ghost';
    }
  }

  /**
   * Escape HTML entities in a string to prevent XSS.
   */
  function escapeHtml(str) {
    if (typeof str !== 'string') return str;
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ---------------------------------------------------------------------------
  // Keyboard Navigation
  // ---------------------------------------------------------------------------

  const _NAV_SHORTCUTS = {
    'o': '/',
    'h': '/handlers',
    'p': '/processes',
    'e': '/eventstore',
    'i': '/infrastructure',
    'm': '/messages',
  };

  let _chordPrefix = null;
  let _chordTimer = null;

  function _initKeyboard() {
    document.addEventListener('keydown', (e) => {
      // Ignore when typing in inputs/textareas
      const tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') {
        // Escape blurs the focused input
        if (e.key === 'Escape') e.target.blur();
        return;
      }

      // Chord: g + <key>
      if (_chordPrefix === 'g') {
        _chordPrefix = null;
        clearTimeout(_chordTimer);
        const dest = _NAV_SHORTCUTS[e.key];
        if (dest) {
          e.preventDefault();
          window.location.href = dest;
          return;
        }
      }

      if (e.key === 'g' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        _chordPrefix = 'g';
        clearTimeout(_chordTimer);
        _chordTimer = setTimeout(() => { _chordPrefix = null; }, 800);
        return;
      }

      // Single-key shortcuts
      if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        const search = document.querySelector('[data-search-input]');
        if (search) search.focus();
        return;
      }

      if (e.key === 'r' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        _refreshAllPollers();
        return;
      }

      if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        _toggleShortcutsModal();
        return;
      }

      if (e.key === 'Escape') {
        const modal = document.getElementById('shortcuts-modal');
        if (modal) modal.close();
      }
    });
  }

  function _refreshAllPollers() {
    for (const [name, p] of Object.entries(_pollers)) {
      (async () => {
        try {
          const data = await fetchWithWindow(p.url);
          p.callback(data);
        } catch (e) {
          console.warn(`Refresh '${name}' failed:`, e.message);
        }
      })();
    }
  }

  function _toggleShortcutsModal() {
    const modal = document.getElementById('shortcuts-modal');
    if (!modal) return;
    if (modal.open) {
      modal.close();
    } else {
      modal.showModal();
    }
  }

  // ---------------------------------------------------------------------------
  // Loading Indicator
  // ---------------------------------------------------------------------------

  let _loadingTimer = null;

  const loading = {
    /** Show the progress bar and fade KPI values. */
    start() {
      const bar = document.getElementById('loading-bar');
      if (bar) {
        bar.classList.add('active');
      }
      document.querySelectorAll('[data-kpi]').forEach(el => el.classList.add('loading-fade'));
      // Safety timeout — auto-done after 10s
      clearTimeout(_loadingTimer);
      _loadingTimer = setTimeout(() => loading.done(), 10000);
    },

    /** Hide the progress bar and restore KPI values. */
    done() {
      clearTimeout(_loadingTimer);
      const bar = document.getElementById('loading-bar');
      if (bar) {
        bar.classList.remove('active');
      }
      document.querySelectorAll('[data-kpi]').forEach(el => el.classList.remove('loading-fade'));
    },
  };

  // ---------------------------------------------------------------------------
  // CSV Export
  // ---------------------------------------------------------------------------

  /**
   * Export table data as a CSV file download.
   * @param {string} filename - Name of the downloaded file
   * @param {string[]} headers - Column header labels
   * @param {Array<Array<string|number>>} rows - Row data
   */
  function exportCSV(filename, headers, rows) {
    const escape = (val) => {
      const s = val == null ? '' : String(val);
      if (s.includes(',') || s.includes('"') || s.includes('\n')) {
        return '"' + s.replace(/"/g, '""') + '"';
      }
      return s;
    };
    const lines = [headers.map(escape).join(',')];
    for (const row of rows) {
      lines.push(row.map(escape).join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ---------------------------------------------------------------------------
  // Initialization
  // ---------------------------------------------------------------------------

  function init() {
    // Apply saved theme
    document.documentElement.setAttribute('data-theme', state.theme);
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
      toggle.checked = state.theme === 'dark';
    }

    // Initialize keyboard shortcuts
    _initKeyboard();

    // Connect SSE
    sse.connect(state.domain);
  }

  // Auto-initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------
  return {
    state,
    sse,
    poller,
    loading,
    fetchJSON,
    fetchWithWindow,
    fmt,
    setWindow,
    togglePause,
    toggleTheme,
    statusClass,
    badgeClass,
    escapeHtml,
    exportCSV,
    init,
  };
})();
