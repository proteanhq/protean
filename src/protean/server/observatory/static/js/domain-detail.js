/**
 * Domain Detail Panel — Aggregate Cluster Drill-Down
 *
 * Renders a slide-in panel showing the complete contents of an
 * aggregate cluster: fields, entities, value objects, commands,
 * events, handlers, invariants, and repository/models.
 *
 * Data is read from the cached IR response — no additional API call.
 *
 * Usage:
 *   DomainDetail.show(fqn, clusterData);
 *   DomainDetail.hide();
 *   DomainDetail.init();   // Wire close handlers (call once)
 */
var DomainDetail = (function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // DOM refs
  // ---------------------------------------------------------------------------

  var _initialized = false;
  var $panel = null;
  var $backdrop = null;
  var $title = null;
  var $fqn = null;
  var $content = null;
  var $close = null;

  // ---------------------------------------------------------------------------
  // Chevron SVG (reused in every accordion toggle)
  // ---------------------------------------------------------------------------

  var CHEVRON_SVG =
    '<svg class="dv-section-chevron" viewBox="0 0 16 16" fill="currentColor">' +
    '<path d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z"/>' +
    '</svg>';

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Wire up close handlers. Call once after DOMContentLoaded.
   */
  function init() {
    if (_initialized) return;
    _initialized = true;

    $panel = document.getElementById('dv-detail-panel');
    $backdrop = document.getElementById('dv-detail-backdrop');
    $title = document.getElementById('dv-detail-title');
    $fqn = document.getElementById('dv-detail-fqn');
    $content = document.getElementById('dv-detail-content');
    $close = document.getElementById('dv-detail-close');

    if ($close) {
      $close.addEventListener('click', hide);
    }
    if ($backdrop) {
      $backdrop.addEventListener('click', hide);
    }

    // Delegated accordion toggle — survives innerHTML replacement in show()
    if ($content) {
      $content.addEventListener('click', function (e) {
        var toggle = e.target.closest('.dv-section-toggle');
        if (!toggle) return;
        var section = toggle.closest('.dv-section');
        if (section) section.classList.toggle('dv-open');
      });
    }

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && _isOpen()) {
        hide();
      }
    });
  }

  /**
   * Show the detail panel for the given aggregate.
   *
   * @param {string} fqn       Aggregate FQN
   * @param {object} cluster   Cluster data from IR (clusters[fqn])
   */
  function show(fqn, cluster) {
    if (!$panel || !cluster) return;

    var agg = cluster.aggregate || {};
    var options = agg.options || {};

    $title.textContent = agg.name || _shortName(fqn);
    $fqn.textContent = fqn;

    var html = '';

    html += '<div class="mb-3">';
    if (options.is_event_sourced) {
      html += '<span class="dv-badge dv-badge--es">Event Sourced</span> ';
    } else {
      html += '<span class="dv-badge dv-badge--cqrs">CQRS</span> ';
    }
    if (options.stream_category) {
      html += '<span class="dv-elem-meta">' + _esc(options.stream_category) + '</span>';
    }
    html += '</div>';

    html += _renderFieldsSection('Fields', agg.fields, agg.identity_field);

    html += _renderElementSection('Entities', cluster.entities, function (elem) {
      return _renderFieldsTable(elem.fields, elem.identity_field);
    });

    html += _renderElementSection('Value Objects', cluster.value_objects, function (elem) {
      return _renderFieldsTable(elem.fields, null);
    });

    html += _renderElementSection('Commands', cluster.commands, function (elem) {
      var meta = '';
      if (elem.__type__) {
        meta += '<span class="dv-badge dv-badge--version">' + _esc(elem.__type__) + '</span> ';
      }
      meta += _renderFieldsTable(elem.fields, null);
      return meta;
    });

    html += _renderElementSection('Events', cluster.events, function (elem) {
      var meta = '';
      if (elem.__type__) {
        meta += '<span class="dv-badge dv-badge--version">' + _esc(elem.__type__) + '</span> ';
      }
      if (elem.published) {
        meta += '<span class="dv-badge dv-badge--published">published</span> ';
      }
      if (elem.is_fact_event) {
        meta += '<span class="dv-badge dv-badge--fact">fact</span> ';
      }
      meta += _renderFieldsTable(elem.fields, null);
      return meta;
    });

    html += _renderHandlerSection('Command Handlers', cluster.command_handlers);
    html += _renderHandlerSection('Event Handlers', cluster.event_handlers);
    html += _renderInvariantsSection(agg.invariants);
    html += _renderRepoSection(cluster.repositories, cluster.database_models);

    $content.innerHTML = html;

    $panel.classList.add('dv-open');
    if ($backdrop) $backdrop.classList.add('dv-open');
  }

  /**
   * Hide the detail panel.
   */
  function hide() {
    if ($panel) $panel.classList.remove('dv-open');
    if ($backdrop) $backdrop.classList.remove('dv-open');
  }

  // ---------------------------------------------------------------------------
  // Section Renderers
  // ---------------------------------------------------------------------------

  /**
   * Render a Fields section (aggregate-level fields).
   */
  function _renderFieldsSection(label, fields, identityField) {
    if (!fields) return '';
    var keys = Object.keys(fields);
    if (keys.length === 0) return '';

    var body = _renderFieldsTable(fields, identityField);
    return _wrapSection(label, keys.length, body, true);
  }

  /**
   * Render a section containing named elements (entities, VOs, commands, events).
   *
   * @param {string}   label       Section label
   * @param {object}   elements    Map of FQN -> element data
   * @param {function} renderBody  Callback(elem) returning extra HTML per element
   */
  function _renderElementSection(label, elements, renderBody) {
    if (!elements) return '';
    var keys = Object.keys(elements);
    if (keys.length === 0) return '';

    var body = '';
    keys.forEach(function (key) {
      var elem = elements[key];
      body += '<div class="dv-elem">';
      body += '<div class="dv-elem-name">' + _esc(elem.name || _shortName(key)) + '</div>';
      if (renderBody) {
        body += renderBody(elem);
      }
      body += '</div>';
    });

    return _wrapSection(label, keys.length, body, false);
  }

  /**
   * Render handler section (command or event handlers).
   */
  function _renderHandlerSection(label, handlers) {
    if (!handlers) return '';
    var keys = Object.keys(handlers);
    if (keys.length === 0) return '';

    var body = '';
    keys.forEach(function (key) {
      var handler = handlers[key];
      body += '<div class="dv-elem">';
      body += '<div class="dv-elem-name">' + _esc(handler.name || _shortName(key)) + '</div>';

      // Handler mappings: type_key -> [method_names]
      var maps = handler.handlers || {};
      Object.keys(maps).forEach(function (typeKey) {
        var methods = maps[typeKey];
        body += '<div class="dv-handler-map">';
        body += '<span class="dv-handler-type">' + _esc(_shortName(typeKey)) + '</span>';
        body += '<span class="dv-handler-arrow">&rarr;</span>';
        body += '<span class="dv-handler-method">' +
          (Array.isArray(methods) ? methods.map(_esc).join(', ') : _esc(String(methods))) +
          '</span>';
        body += '</div>';
      });

      body += '</div>';
    });

    return _wrapSection(label, keys.length, body, false);
  }

  /**
   * Render invariants section.
   */
  function _renderInvariantsSection(invariants) {
    if (!invariants) return '';
    var pre = invariants.pre || [];
    var post = invariants.post || [];
    if (pre.length === 0 && post.length === 0) return '';

    var total = pre.length + post.length;
    var body = '';

    pre.forEach(function (name) {
      body += '<div class="dv-elem">';
      body += '<span class="dv-badge dv-badge--pre">pre</span> ';
      body += '<span class="dv-elem-name">' + _esc(name) + '</span>';
      body += '</div>';
    });

    post.forEach(function (name) {
      body += '<div class="dv-elem">';
      body += '<span class="dv-badge dv-badge--post">post</span> ';
      body += '<span class="dv-elem-name">' + _esc(name) + '</span>';
      body += '</div>';
    });

    return _wrapSection('Invariants', total, body, false);
  }

  /**
   * Render Repository & Models section.
   */
  function _renderRepoSection(repositories, models) {
    var repos = repositories || {};
    var dbModels = models || {};
    var repoKeys = Object.keys(repos);
    var modelKeys = Object.keys(dbModels);
    if (repoKeys.length === 0 && modelKeys.length === 0) return '';

    var total = repoKeys.length + modelKeys.length;
    var body = '';

    repoKeys.forEach(function (key) {
      var repo = repos[key];
      body += '<div class="dv-elem">';
      body += '<div class="dv-elem-name">' + _esc(repo.name || _shortName(key)) + '</div>';
      if (repo.database) {
        body += '<div class="dv-elem-meta">database: ' + _esc(repo.database) + '</div>';
      }
      body += '</div>';
    });

    modelKeys.forEach(function (key) {
      var model = dbModels[key];
      body += '<div class="dv-elem">';
      body += '<div class="dv-elem-name">' + _esc(model.name || _shortName(key)) + '</div>';
      if (model.schema_name) {
        body += '<div class="dv-elem-meta">schema: ' + _esc(model.schema_name) + '</div>';
      }
      if (model.database) {
        body += '<div class="dv-elem-meta">database: ' + _esc(model.database) + '</div>';
      }
      body += '</div>';
    });

    return _wrapSection('Repository & Models', total, body, false);
  }

  // ---------------------------------------------------------------------------
  // Field Table
  // ---------------------------------------------------------------------------

  /**
   * Render a table of field definitions.
   */
  function _renderFieldsTable(fields, identityField) {
    if (!fields) return '';
    var keys = Object.keys(fields);
    if (keys.length === 0) return '';

    var html = '<table class="dv-field-table"><tbody>';
    keys.forEach(function (name) {
      var f = fields[name];
      html += '<tr>';
      html += '<td class="dv-field-name">' + _esc(name);
      if (identityField && name === identityField) {
        html += ' <span class="dv-badge dv-badge--id">id</span>';
      }
      html += '</td>';
      html += '<td class="dv-field-type">' + _esc(_fieldTypeLabel(f)) + '</td>';

      // Constraints
      var constraints = _fieldConstraints(f);
      if (constraints) {
        html += '<td class="dv-field-constraints">' + _esc(constraints) + '</td>';
      } else {
        html += '<td></td>';
      }

      html += '</tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  /**
   * Return a human-readable type label for a field.
   */
  function _fieldTypeLabel(field) {
    if (!field) return '';

    var kind = field.kind || 'standard';

    if (kind === 'has_one' || kind === 'has_many') {
      return kind.replace('_', ' ') + ' ' + _shortName(field.target || '');
    }
    if (kind === 'reference') {
      return 'ref ' + _shortName(field.target || '');
    }
    if (kind === 'value_object' || kind === 'value_object_list') {
      return _shortName(field.target || '');
    }

    return field.type || '';
  }

  /**
   * Build a constraints summary string for a field.
   */
  function _fieldConstraints(field) {
    if (!field) return '';
    var parts = [];

    if (field.required) parts.push('required');
    if (field.unique) parts.push('unique');
    if (field.max_length != null) parts.push('max:' + field.max_length);
    if (field.min_length != null) parts.push('min:' + field.min_length);
    if (field.max_value != null) parts.push('<=' + field.max_value);
    if (field.min_value != null) parts.push('>=' + field.min_value);
    if (field.choices && field.choices.length > 0) {
      parts.push('choices:' + field.choices.length);
    }

    return parts.join(', ');
  }

  // ---------------------------------------------------------------------------
  // Section Wrapper
  // ---------------------------------------------------------------------------

  /**
   * Wrap content in an accordion section.
   *
   * @param {string}  label       Section title
   * @param {number}  count       Item count (shown as badge)
   * @param {string}  body        Inner HTML
   * @param {boolean} openByDefault  Whether to start expanded
   */
  function _wrapSection(label, count, body, openByDefault) {
    var cls = 'dv-section' + (openByDefault ? ' dv-open' : '');
    var html = '<div class="' + cls + '">';
    html += '<button class="dv-section-toggle" type="button">';
    html += CHEVRON_SVG;
    html += _esc(label);
    html += '<span class="dv-section-count">(' + count + ')</span>';
    html += '</button>';
    html += '<div class="dv-section-body">' + body + '</div>';
    html += '</div>';
    return html;
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _isOpen() {
    return $panel && $panel.classList.contains('dv-open');
  }

  function _shortName(fqn) {
    if (!fqn) return '';
    var parts = fqn.split('.');
    return parts[parts.length - 1] || fqn;
  }

  function _fallbackEsc(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str || ''));
    return div.innerHTML;
  }

  var _esc = typeof Observatory !== 'undefined' ? Observatory.escapeHtml : _fallbackEsc;

  // ---------------------------------------------------------------------------
  // Module Export
  // ---------------------------------------------------------------------------

  return {
    init: init,
    show: show,
    hide: hide,
  };
})();
