/* AgentOps Operator Console — live data adapter (AO-UI-01).
 *
 * Wires the OpenDesign screens to the harness FastAPI on the same origin:
 *   GET /runs           → runs table rows + KPIs
 *   GET /runs/kpis      → KPI strip
 *   GET /runs/{id}      → run detail
 *   GET /runs/{id}/events → replay timeline (graph stages + worker events)
 *
 * Honest states only: loading → data | empty | error. Never fake content.
 */
(function () {
  'use strict';

  function getJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('GET ' + url + ' → ' + r.status);
      return r.json();
    });
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* ── runs list ─────────────────────────────────────────────────── */
  function fillKpis(kpis, runs) {
    var q = function (sel) { return document.querySelector(sel); };
    if (!q('[data-od-id="kpi-strip"]')) return;
    var maxRisk = 0, liveNote = 'none';
    runs.forEach(function (r) {
      if (r.status !== 'completed') maxRisk = Math.max(maxRisk, r.risk_score || 0);
      if (r.source === 'interrupted') liveNote = 'interrupted · governed record missing';
    });
    var notes = {
      'kpi-runs': kpis.total + ' stored · honest statuses, never faked',
      'kpi-pass': kpis.passed + ' passed · ' + kpis.failed + ' failed · ' + kpis.blocked + ' blocked',
      'kpi-risk': 'avg ' + kpis.avg_risk + ' · max open ' + maxRisk,
      'kpi-live': liveNote
    };
    var vals = {
      'kpi-runs': kpis.total, 'kpi-pass': kpis.passed,
      'kpi-risk': kpis.avg_risk, 'kpi-live': runs.filter(function (r) { return r.source === 'interrupted'; }).length
    };
    Object.keys(vals).forEach(function (id) {
      var k = document.querySelector('[data-od-id="' + id + '"]');
      if (!k) return;
      var v = k.querySelector('.kpi-value'); if (v) v.textContent = vals[id];
      var n = k.querySelector('.kpi-note'); if (n) n.textContent = notes[id];
    });
  }

  function stageRail(r) {
    /* six stage dots: done count from execution stage logs */
    var done = r.stages_done || 0, total = 6, html = '';
    for (var i = 0; i < total; i++) {
      var cls = 'st' + (i < done ? ' done' : '');
      html += '<span class="' + cls + '"></span>';
    }
    return '<span class="stage-rail" title="' + done + '/6 stages">' + html + '</span>';
  }

  function riskBadge(r) {
    var score = r.risk_score == null ? 0 : r.risk_score;
    var cls = score >= 60 ? 'risk-high' : score >= 25 ? 'risk-med' : 'risk-low';
    var bar = score >= 60 ? 2 : score >= 25 ? 1 : 0;
    var ticks = '';
    for (var i = 0; i < 3; i++) ticks += '<i' + (i < bar ? ' style="background:currentColor"' : '') + '></i>';
    return '<a href="run-detail.html?id=' + encodeURIComponent(r.run_id) + '#risk">' + score + '</a>' +
      '<span class="rbar">' + ticks + '</span>';
  }

  function rowHtml(r) {
    var id = r.run_id.slice(0, 8);
    var href = 'run-detail.html?id=' + encodeURIComponent(r.run_id);
    var chip = r.status === 'completed' ? 'chip-ok' : r.status === 'failed' ? 'chip-fail' : 'chip-warn';
    var live = r.source === 'interrupted';
    var chipTxt = live ? 'blocked' : r.status;
    return '<tr tabindex="0" data-status="' + escapeHtml(r.status) + '"' + (live ? ' data-interrupted="1"' : '') + '>' +
      '<td>' + (live ? '<span class="live-ind" style="padding:2px 6px;"><span class="dot"></span></span>' : '') + '</td>' +
      '<td><a class="run-id" href="' + href + '" style="color:var(--info)">' + escapeHtml(id) + '</a></td>' +
      '<td class="run-task">' + escapeHtml(r.task) + (r.blocked_reason ? ' <span class="meta" style="color:var(--warn)">— ' + escapeHtml(r.blocked_reason) + '</span>' : '') + '</td>' +
      '<td class="run-repo">' + escapeHtml(r.repo || '—') + '</td>' +
      '<td class="mono">' + escapeHtml(r.worker || 'scripted') + '</td>' +
      '<td><span class="chip ' + chip + '"><span class="cdot"></span>' + escapeHtml(chipTxt) + '</span></td>' +
      '<td>' + stageRail(r) + '</td>' +
      '<td class="num">' + (r.attempts == null ? '—' : r.attempts) + '</td>' +
      '<td><span class="risk ' + (function (s) { return s >= 60 ? 'risk-high' : s >= 25 ? 'risk-med' : 'risk-low'; })(r.risk_score || 0) + '">' + riskBadge(r) + '</span></td>' +
      '<td class="num" style="text-align:right;color:' + (r.tests_exit === 0 ? 'var(--ok)' : r.tests_exit == null ? 'var(--muted)' : 'var(--fail)') + '">' +
        (r.tests_exit == null ? '—' : r.tests_exit) + '</td>' +
      '</tr>';
  }

  function wireRunsList() {
    var body = document.getElementById('runsBody');
    if (!body) return;
    var stateEmpty = document.getElementById('emptyState');
    Promise.all([getJSON('/runs?limit=50'), getJSON('/runs/kpis')]).then(function (res) {
      var runs = res[0], kpis = res[1];
      fillKpis(kpis, runs);
      body.textContent = '';
      runs.forEach(function (r) { body.insertAdjacentHTML('beforeend', rowHtml(r)); });
      var count = document.querySelector('[data-od-id="runs-table"] .count');
      if (count) count.textContent = String(runs.length);
      var filters = document.getElementById('statusFilters');
      if (filters) {
        filters.addEventListener('click', function (ev) {
          var btn = ev.target.closest('button[data-filter]');
          if (!btn) return;
          filters.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(b === btn)); });
          var f = btn.getAttribute('data-filter');
          var visible = 0;
          body.querySelectorAll('tr').forEach(function (tr) {
            var match = f === 'all' || tr.getAttribute('data-status') === f ||
              (f === 'live' && tr.getAttribute('data-interrupted') === '1');
            tr.hidden = !match; if (match) visible++;
          });
          if (stateEmpty) stateEmpty.hidden = visible !== 0;
        });
      }
    }).catch(function (err) {
      body.textContent = '';
      if (stateEmpty) {
        stateEmpty.hidden = false;
        var h3 = stateEmpty.querySelector('h3'); if (h3) h3.textContent = 'Cannot reach the harness API';
        var p = stateEmpty.querySelector('p'); if (p) p.textContent = String(err.message || err) + ' — start the FastAPI server that mounts this console.';
      }
    });
  }

  /* ── run detail ─────────────────────────────────────────────────── */
  function params() {
    var out = {};
    new URLSearchParams(window.location.search).forEach(function (v, k) { out[k] = v; });
    return out;
  }

  function fmtDuration(sec) {
    if (sec == null) return '—';
    if (sec < 60) return Math.round(sec) + 's';
    return Math.floor(sec / 60) + ':' + String(Math.round(sec % 60)).padStart(2, '0');
  }

  function fillRunDetail(record, events) {
    var q = function (sel) { return document.querySelector(sel); };
    var interrupted = record.source === 'interrupted';
    var chip = q('#statusChip');
    if (chip) {
      var txt = chip.querySelector('.cdot');
      chip.className = 'chip ' + (record.status === 'completed' ? 'chip-ok' : record.status === 'failed' ? 'chip-fail' : 'chip-warn');
      chip.textContent = '';
      chip.insertAdjacentHTML('beforeend', '<span class="cdot"></span>' + escapeHtml(record.status));
    }
    var title = q('.page-title');
    if (title) title.textContent = record.task;
    var sub = q('.page-sub');
    if (sub) {
      var workerModel = record.worker_summary ? record.worker_summary.model : null;
      sub.innerHTML = 'run <span class="mono">' + escapeHtml(record.run_id.slice(0, 8)) + '</span>' +
        ' · worker <span class="mono">' + escapeHtml(record.edit_result ? record.edit_result.worker_type : (record.worker_summary ? record.worker_summary.worker_type : 'scripted')) + '</span>' +
        (workerModel ? ' · <span class="mono">' + escapeHtml(workerModel) + '</span>' : '') +
        ' · <span class="mono">' + escapeHtml(String(record.attempts || 1)) + '</span> attempt' +
        (interrupted ? ' · <span style="color:var(--warn)">interrupted — governed record missing</span>' : '');
    }
    /* KPI strip */
    var kpis = q('[data-od-id="run-kpis"]');
    if (kpis) {
      var cells = kpis.querySelectorAll('.kpi');
      var cmd = record.test_results ? record.test_results.commands || [] : [];
      var passedAll = cmd.length && cmd.every(function (c) { return c.exit_code === 0; });
      var vals = [
        (record.changed_files || []).length,
        cmd.length ? (passedAll ? cmd.length + ' cmd ok' : 'cmd failed') : 'no tests',
        record.risk_report ? record.risk_report.risk_score : 0,
        fmtDuration(record.worker_summary ? record.worker_summary.duration_seconds : null)
      ];
      var notes = [
        (record.diff_summary || '') + ' · patch below',
        passedAll ? 'all commands exited 0' : cmd.length ? 'failures recorded honestly' : 'no validation commands ran',
        record.risk_report ? record.risk_report.risk_level : '—',
        (record.worker_summary ? record.worker_summary.observable_event_count : (events ? events.length : 0)) + ' observable worker events'
      ];
      cells.forEach(function (cell, i) {
        var v = cell.querySelector('.kpi-value'); if (v && vals[i] != null) v.textContent = String(vals[i]);
        var n = cell.querySelector('.kpi-note'); if (n && notes[i]) n.textContent = notes[i];
      });
    }
    /* stage timeline: light stages by graph log evidence */
    var pipeline = q('[data-od-id="stage-timeline"]');
    if (pipeline) {
      var logs = record.execution_logs || [];
      var has = function (name) { return logs.some(function (l) { return l.indexOf(name) === 0; }); };
      var stageDefs = [
        ['Plan', has('create_plan')],
        ['Dispatch', has('run_external_worker') || has('pre_dispatch')],
        ['Enforce', has('enforce_permissions') || has('check_convergence')],
        ['Validate', has('run_tests')],
        ['Retry', record.attempts > 1],
        ['Report', has('write_report') || has('build_product_review')]
      ];
      var stages = pipeline.querySelectorAll('.stage');
      stages.forEach(function (stage, i) {
        if (i >= stageDefs.length) return;
        stage.classList.toggle('done', Boolean(stageDefs[i][1]));
      });
      var meta = pipeline.querySelector('.pipeline-meta .meta b');
      if (meta) {
        var lit = stageDefs.filter(function (s) { return s[1]; }).length;
        meta.textContent = lit + '/6 stages evidenced';
        meta.style.color = lit === 6 ? 'var(--ok)' : 'var(--warn)';
      }
    }
    /* test results table */
    var tests = q('#tests');
    if (tests) {
      var tbody = tests.querySelector('tbody');
      var cmds = (record.test_results && record.test_results.commands) || [];
      if (cmds.length) {
        tbody.textContent = '';
        cmds.forEach(function (c, i) {
          var cls = c.exit_code === 0 ? 'exit-0' : 'exit-fail';
          tbody.insertAdjacentHTML('beforeend',
            '<tr><td class="cmd">' + escapeHtml(c.command) + '</td>' +
            '<td><span class="exit ' + cls + '">' + escapeHtml(String(c.exit_code)) + '</span></td>' +
            '<td class="num" style="text-align:right;">' + escapeHtml(c.duration_seconds.toFixed(1)) + 's</td>' +
            '<td class="log-link"><a href="#log-' + (i + 1) + '">open log ↗</a></td></tr>');
        });
      } else {
        var row = tests.querySelector('tbody tr td');
        if (row) row.colSpan = 4;
      }
    }
    /* risk factors */
    var risk = q('#risk');
    if (risk && record.risk_report) {
      var body = risk.querySelector('.panel-body');
      body.textContent = '';
      var factors = record.risk_report.factors || [];
      if (!factors.length) factors = ['No material risk factors detected'];
      factors.forEach(function (f) {
        body.insertAdjacentHTML('beforeend', '<div class="risk-factor">' + escapeHtml(f) + '</div>');
      });
      var head = risk.querySelector('.panel-title');
      if (head) head.innerHTML = 'Risk · score ' + escapeHtml(String(record.risk_report.risk_score)) + ' / ' + escapeHtml(record.risk_report.risk_level);
    }
    /* replay timeline: replace embedded demo EV_RAW with real events */
    var evCount = document.getElementById('evCount');
    if (evCount) evCount.textContent = String(events.length);
    if (events.length && typeof window.__consoleWireReplay === 'function') {
      window.__consoleWireReplay(events);
    }
  }

  function wireRunDetail() {
    if (!document.getElementById('evLog')) return;
    var id = params().id;
    if (!id) return; /* demo mode: keep OpenDesign's curated flagship content */
    Promise.all([
      getJSON('/runs/' + encodeURIComponent(id)),
      getJSON('/runs/' + encodeURIComponent(id) + '/events')
    ]).then(function (res) { fillRunDetail(res[0], res[1]); })
      .catch(function (err) {
        var el = document.getElementById('evLog');
        if (el) el.textContent = 'cannot load run: ' + (err.message || err);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else { run(); }
  function run() {
    wireRunsList();
    wireRunDetail();
  }
})();
