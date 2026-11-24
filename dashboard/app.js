/* RL Tracker v4.0 Overdrive — Dashboard Controller */

let activeSessionId = null;
let activeSession = null;
let statsMode = 'all';
let statsPlaylist = 'all';
let statsDays = '';
let statsLimit = '';
let historyMode = 'all';
let playlistsCache = [];
let olderMatchesOffset = 0;
let lastSeenRecordedMatchId = null;
let confirmResolver = null;
let livePollTimer = null;

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[c]));
}

function packIcon(name, cls = 'pack-ico') {
  const sz = cls.includes('lg') ? 28 : 20;
  return `<img src="assets/icons/${name}.png" class="${cls}" width="${sz}" height="${sz}" alt="">`;
}

const ICO = {
  win: '<svg viewBox="0 0 24 24"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4z"/></svg>',
  loss: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12h8"/></svg>',
  goal: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18"/></svg>',
  shot: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>',
  save: '<svg viewBox="0 0 24 24"><path d="M12 3l8 4v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V7l8-4z"/></svg>',
  demo: '<svg viewBox="0 0 24 24"><path d="M13 2L4 14h7l-1 8 10-14h-7l0-6z"/></svg>',
  boost: '<svg viewBox="0 0 24 24"><path d="M13 3L5 14h6l-1 7 9-12h-6l0-6z"/></svg>',
  air: '<svg viewBox="0 0 24 24"><path d="M4 16c3-6 6-9 8-9s5 3 8 9"/><path d="M4 19h16"/></svg>',
  wall: '<svg viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/><path d="M4 10h16M4 16h16M10 4v16M16 4v16"/></svg>',
  ground: '<svg viewBox="0 0 24 24"><path d="M3 17h18"/><path d="M5 17l3-8h8l3 8"/></svg>',
  super: '<svg viewBox="0 0 24 24"><path d="M13 2L3 14h8l-1 8 11-14h-8l0-6z"/></svg>',
  touch: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  share: '<svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.5 13.5l7 4M15.5 6.5l-7 4"/></svg>',
  coach: '<svg viewBox="0 0 24 24"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4z"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/></svg>',
  rocket: '<svg viewBox="0 0 24 24"><path d="M5 19l4-1 9-9a3 3 0 0 0-4-4l-9 9-1 4z"/></svg>',
  users: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><circle cx="17" cy="9" r="2.5"/><path d="M2.5 19c1-3.5 3-5 6.5-5s5.5 1.5 6.5 5"/></svg>',
  user: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 20c1.5-4 4-6 8-6s6.5 2 8 6"/></svg>',
  edit: '<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  speed: '<svg viewBox="0 0 24 24"><path d="M12 14l4-4"/><path d="M3.3 17a10 10 0 1 1 17.4 0"/><path d="M7 17h10"/></svg>',
};

function ic(name, cls = 'ico') {
  return `<span class="${cls}">${ICO[name] || ICO.rocket}</span>`;
}
function n1(v) { return Number(v || 0); }
function fmtKph(v) { v = n1(v); return v > 0 ? v.toFixed(1) + ' km/h' : '—'; }
function fmtPct(v) { return n1(v).toFixed(1) + '%'; }
function fmtClock(sec, ot) {
  if (ot) return 'OT';
  const s = Math.max(0, Number(sec || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
function fmtDur(sec) {
  const s = Math.max(0, Number(sec || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

async function api(url, opts = {}) {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) }, ...opts });
  let d = {};
  try { d = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
  return d;
}

function showToast(m) {
  const e = document.createElement('div');
  e.className = 'toast';
  e.textContent = m;
  document.getElementById('toast-container').appendChild(e);
  setTimeout(() => e.remove(), 3400);
}

function askConfirm(title, body, okLabel = 'Confirm', danger = true) {
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-body').textContent = body;
  const okBtn = document.getElementById('confirm-ok-btn');
  okBtn.textContent = okLabel;
  okBtn.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
  document.getElementById('confirm-modal').style.display = 'flex';
  return new Promise(res => { confirmResolver = res; });
}

function closeConfirm(val) {
  document.getElementById('confirm-modal').style.display = 'none';
  if (confirmResolver) {
    const r = confirmResolver;
    confirmResolver = null;
    r(Boolean(val));
  }
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  } catch (e) {
    return String(iso || '');
  }
}
function relativeTime(iso) {
  const d = new Date(iso), n = new Date(), diff = Math.floor((n - d) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}
function gradeColor(g) {
  g = (g || '').toUpperCase();
  if (g.startsWith('S')) return 'var(--gold)';
  if (g.startsWith('A')) return 'var(--green)';
  if (g.startsWith('B')) return 'var(--cyan)';
  if (g.startsWith('C')) return 'var(--orange)';
  return 'var(--red)';
}
function resultClass(r) {
  return r === 'win' ? 'result-win' : r === 'draw' ? 'result-draw' : 'result-loss';
}
function trendIcon(t) { return t === 'up' ? '↑' : t === 'down' ? '↓' : '→'; }
function trendClass(t) { return t === 'up' ? 'trend-up' : t === 'down' ? 'trend-down' : 'trend-flat'; }

function tagPills(m) {
  const out = [];
  if (m.is_mvp) out.push(`<span class="tag mvp">MVP</span>`);
  const t = m.tags || '';
  if (t) {
    String(t).split(',').map(x => x.trim()).filter(Boolean).forEach(x => {
      if (x.toUpperCase() === 'MVP' && m.is_mvp) return;
      const cls = x === 'Forfeit' ? 'warn' : '';
      out.push(`<span class="tag ${cls}">${esc(x)}</span>`);
    });
  }
  return out.join('');
}

function matchBadges(s) {
  const g = s.player_goals != null ? s.player_goals : (s.goals || 0);
  return [
    `<span class="stat-pill g" title="Your Goals">${packIcon('football')} <b>${g}</b></span>`,
    `<span class="stat-pill b" title="Shots">${packIcon('target')} <b>${s.shots || 0}</b></span>`,
    `<span class="stat-pill o" title="Saves">${packIcon('shield')} <b>${s.saves || 0}</b></span>`,
    `<span class="stat-pill r" title="Demos">${packIcon('fire')} <b>${s.demos_given || 0}</b></span>`,
  ].join('');
}

function mv(name, val, label, cls = '') {
  return `<div class="metric-card ${cls}"><div class="metric-ico">${ic(name)}</div><div class="metric-value">${val}</div><div class="metric-label">${label}</div></div>`;
}

/** Shared deep stats blocks (100% consistent across Match Detail, Session Deep Stats & Analytics) */
function renderDeepBlocks(a) {
  const fg = n1(a.all_time_fastest_goal || a.fastest_goal_kph);
  const asp = n1(a.overall_avg_shot_power || a.avg_shot_power);
  const sa = n1(a.shot_accuracy);
  const avgSpd = n1(a.avg_speed_kph);
  const avgScore = n1(a.avg_score || a.player_score);
  return `
  <div class="deep-section"><h3>Shot Power &amp; Offense</h3><div class="deep-metrics">
    ${mv('rocket', fg > 0 ? fmtKph(fg) : '—', 'Fastest Goal', fg > 0 ? 'orange' : 'muted')}
    ${mv('demo', asp > 0 ? fmtKph(asp) : '—', 'Avg Shot Power', asp > 0 ? 'blue' : 'muted')}
    ${mv('shot', sa.toFixed(1) + '%', 'Shot Accuracy', 'green')}
    ${mv('shot', a.total_shots || 0, 'Total Shots', 'blue')}
    ${mv('goal', a.total_goals || 0, 'Personal Goals', 'green')}
    ${mv('users', a.total_assists || a.assists || 0, 'Assists', '')}
  </div></div>
  <div class="deep-section"><h3>Boost &amp; Speed Telemetry</h3><div class="deep-metrics">
    ${mv('boost', fmtPct(a.avg_boost), 'Avg Boost', 'blue')}
    ${mv('boost', fmtPct(a.avg_boost_time), 'Time Boosting', '')}
    ${mv('super', fmtPct(a.avg_supersonic_time), 'Supersonic', 'orange')}
    ${mv('air', fmtPct(a.avg_air_time), 'Air Time', '')}
    ${mv('ground', fmtPct(a.avg_ground_time), 'Ground Time', '')}
    ${mv('wall', fmtPct(a.avg_wall_time), 'Wall Time', n1(a.avg_wall_time) > 0 ? 'blue' : 'muted')}
    ${mv('rocket', fmtPct(a.avg_powerslide_time), 'Powerslide', n1(a.avg_powerslide_time) > 0 ? '' : 'muted')}
    ${mv('speed', avgSpd > 0 ? fmtKph(avgSpd) : '—', 'Avg Car Speed', avgSpd > 0 ? 'blue' : 'muted')}
  </div></div>
  <div class="deep-section"><h3>Combat, Defense &amp; Pickups</h3><div class="deep-metrics">
    ${mv('demo', a.total_demos_given || a.demos_given || 0, 'Demos Given', 'green')}
    ${mv('loss', a.total_demos_taken || a.demos_taken || 0, 'Demos Taken', 'red')}
    ${mv('save', a.total_saves || a.saves || 0, 'Saves', '')}
    ${mv('win', avgScore > 0 ? avgScore.toFixed(0) : '—', 'Match Score (PTS)', avgScore > 0 ? 'blue' : 'muted')}
    ${mv('clock', a.total_overtime || a.overtime || 0, 'Overtimes', '')}
    ${mv('shot', a.total_crossbars || a.crossbar_hits || 0, 'Crossbars', '')}
    ${mv('boost', a.total_boost_pills || a.boost_pills || 0, 'Big Boost Pills', '')}
    ${mv('boost', a.total_boost_pads || a.boost_pads || 0, 'Small Pads', '')}
    ${mv('touch', a.total_touches || a.touches || 0, 'Touches', '')}
    ${mv('touch', a.total_car_touches || a.car_touches || 0, 'Car Touches', '')}
  </div></div>`;
}

// ===== TAB NAVIGATION =====
document.querySelectorAll('.nav-btn').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.nav-btn').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-' + b.dataset.tab).classList.add('active');
  if (b.dataset.tab === 'active-session') loadActiveSession();
  if (b.dataset.tab === 'history') loadHistory();
  if (b.dataset.tab === 'stats') loadStats();
  if (b.dataset.tab === 'coach') loadCoach();
}));

// ===== LIVE HUD & POLLING =====
function renderLiveHud(s) {
  const root = document.getElementById('live-hud-root');
  if (!root) return;

  const scopeMap = { competitive: 'Competitive Only', all_online: 'All Online', custom: 'Custom Filter' };
  const sp = document.getElementById('scope-pill');
  if (sp && s.tracking_scope) sp.textContent = scopeMap[s.tracking_scope] || s.tracking_scope;

  if (!s.in_match) {
    const conn = s.connection_state === 'connected';
    const setupMsg = s.connection_state === 'no_player'
      ? 'Set your Rocket League nickname in Settings to start live tracking.'
      : (conn ? 'Connected to Rocket League — waiting for next competitive match.' : 'Launch Rocket League to stream live match telemetry.');
    root.innerHTML = `<div class="live-hud hud-idle">
      <div style="display:flex;align-items:center;gap:10px">
        ${packIcon('rocket', 'pack-ico-lg')}
        <div>
          <strong style="font-size:.9rem">${conn ? 'Rocket League Connected' : 'Standby'}</strong>
          <div class="hint-text">${esc(setupMsg)}</div>
        </div>
      </div>
      <span class="tag ${conn ? 'live' : ''}">${esc(scopeMap[s.tracking_scope] || 'Competitive Only')}</span>
    </div>`;
    return;
  }

  const ul = s.user_live || {};
  const boost = Math.max(0, Math.min(100, Number(ul.boost || 0)));
  const rec = Boolean(s.tracking_active);
  const modeTag = s.mode === 'duo'
    ? `<span class="tag duo">${ic('users')} Duo${s.friend_name ? ' · ' + esc(s.friend_name) : ''}</span>`
    : `<span class="tag solo">${ic('user')} Solo</span>`;

  const blueRoster = (s.players || []).filter(p => p.team_num === 0).map(p =>
    `<span class="tag ${p.is_user ? 'live' : ''}">${esc(p.name)}${p.is_user ? ' (You)' : ''}</span>`
  ).join('');
  const orangeRoster = (s.players || []).filter(p => p.team_num === 1).map(p =>
    `<span class="tag ${p.is_user ? 'live' : ''}">${esc(p.name)}${p.is_user ? ' (You)' : ''}</span>`
  ).join('');

  root.innerHTML = `<div class="live-hud ${rec ? '' : 'hud-ignored'}">
    <div class="hud-top">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <span class="hud-badge ${rec ? 'rec' : 'ign'}">${rec ? '● RECORDING MATCH' : '● IGNORED: ' + esc(s.skip_reason || 'Practice / Non-Competitive')}</span>
        <span class="tag">${esc(s.playlist || 'Unknown')}</span>
        ${s.arena_name ? `<span class="tag">${esc(s.arena_name)}</span>` : ''}
        ${modeTag}
      </div>
      <span class="hint-text">${s.in_replay ? 'Goal Replay' : 'Live Telemetry'}</span>
    </div>

    <div class="hud-scoreboard">
      <div class="hud-team blue">
        <div class="hud-team-score">${s.blue_score ?? 0}</div>
        <div>
          <div style="font-size:.74rem;color:var(--blue);font-weight:800">BLUE ${s.user_team_num === 0 ? '(YOU)' : ''}</div>
          <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px">${blueRoster || '<span class="hint-text">—</span>'}</div>
        </div>
      </div>
      <div class="hud-clock ${s.is_overtime ? 'ot' : ''}">${fmtClock(s.time_remaining, s.is_overtime)}</div>
      <div class="hud-team orange">
        <div>
          <div style="font-size:.74rem;color:var(--orange);font-weight:800">${s.user_team_num === 1 ? '(YOU) ' : ''}ORANGE</div>
          <div style="display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;margin-top:4px">${orangeRoster || '<span class="hint-text">—</span>'}</div>
        </div>
        <div class="hud-team-score">${s.orange_score ?? 0}</div>
      </div>
    </div>

    <div class="hud-telemetry">
      <div class="boost-box">
        <div class="boost-head"><span>BOOST</span><span>${boost}% · ${n1(ul.speed_kph).toFixed(0)} km/h ${ul.supersonic ? '⚡' : ''}</span></div>
        <div class="boost-bar"><div class="boost-fill" style="width:${boost}%"></div></div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <span class="stat-pill">PTS <b>${ul.score || 0}</b></span>
        <span class="stat-pill g">G <b>${ul.goals || 0}</b></span>
        <span class="stat-pill">A <b>${ul.assists || 0}</b></span>
        <span class="stat-pill o">Sv <b>${ul.saves || 0}</b></span>
        <span class="stat-pill b">Sh <b>${ul.shots || 0}</b></span>
        <span class="stat-pill r">Demos <b>${ul.demos || 0}</b></span>
      </div>
    </div>
  </div>`;
}

function updateListenerBarFromLive(s) {
  const d = document.getElementById('listener-dot');
  const m = document.getElementById('listener-msg');
  const bar = document.getElementById('listener-bar');
  const chip = document.getElementById('listener-chip');
  if (!d || !m || !bar) return;
  d.className = 'dot';
  bar.className = 'listener-bar';
  const set = (dot, state, text, chipText) => {
    d.classList.add(dot);
    bar.classList.add(state);
    m.textContent = text;
    if (chip) chip.textContent = chipText;
  };
  switch (s.connection_state) {
    case 'connected':
      set('dot-live', 'state-live', s.in_match ? `Live · ${s.playlist || 'Match'}` : 'Live — connected to RL', s.in_match ? 'IN GAME' : 'LIVE');
      break;
    case 'connecting':
    case 'starting':
      set('dot-connecting', 'state-connecting', 'Connecting to Rocket League...', 'WAIT');
      break;
    case 'no_player':
      set('dot-off', 'state-off', 'Set RL name in Settings', 'SETUP');
      break;
    case 'disconnected':
      set('dot-off', 'state-off', 'RL not running (port 49123)', 'OFF');
      break;
    default:
      set('dot-off', 'state-off', s.message || s.connection_state || 'Idle', '—');
  }
}

async function pollLiveOnce() {
  try {
    const s = await api('/api/live');
    updateListenerBarFromLive(s);
    renderLiveHud(s);
    if (s.last_recorded_match_id != null) {
      if (lastSeenRecordedMatchId !== null && s.last_recorded_match_id !== lastSeenRecordedMatchId) {
        const res = String(s.last_recorded_result || '').toUpperCase();
        showToast(`Match recorded: ${res} ${s.last_recorded_score || ''} (${s.last_recorded_playlist || ''})`);
        playlistsCache = [];
        loadActiveSession();
      }
      lastSeenRecordedMatchId = s.last_recorded_match_id;
    }
  } catch (e) {
    updateListenerBarFromLive({ connection_state: 'stopped', message: 'Server offline' });
  }
}

function scheduleLivePoll() {
  if (livePollTimer) clearTimeout(livePollTimer);
  const delay = document.visibilityState === 'visible' ? 1500 : 6000;
  livePollTimer = setTimeout(async () => {
    await pollLiveOnce();
    scheduleLivePoll();
  }, delay);
}

// ===== ACTIVE SESSION TAB =====
async function loadActiveSession() {
  const c = document.getElementById('active-content');
  if (!c.innerHTML.trim()) c.innerHTML = '<div class="loading"><div class="spinner"></div>Loading session...</div>';
  try {
    const ss = await api('/api/sessions');
    const a = ss.find(s => s.status === 'active');
    if (!a) {
      activeSessionId = null;
      activeSession = null;
      c.innerHTML = `<div class="card" style="text-align:center;padding:34px 20px">
        ${packIcon('trophy', 'pack-ico-lg')}
        <h3 style="margin:10px 0 6px">No active session</h3>
        <p class="hint-text" style="max-width:440px;margin:0 auto 16px">Play any Competitive Rocket League match and a session starts automatically, or start one manually below.</p>
        <button class="btn btn-primary" onclick="startManualSession()">Start Session Manually</button>
      </div>`;
      return;
    }
    activeSessionId = a.id;
    const f = await api('/api/sessions/' + a.id);
    activeSession = f;
    renderActiveSession(f);
  } catch (e) {
    c.innerHTML = `<div class="empty-state"><p>Error: ${esc(e.message)}</p></div>`;
  }
}

async function startManualSession() {
  try {
    await api('/api/sessions', { method: 'POST', body: JSON.stringify({ mode: 'solo' }) });
    showToast('New session started');
    loadActiveSession();
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

function renderActiveSession(s) {
  const ms = s.matches || [];
  const w = s.wins || 0, l = s.losses || 0, t = w + l;
  const wr = t ? Math.round((w / t) * 100) : 0;
  const gf = ms.reduce((acc, m) => acc + Number(m.user_score || 0), 0);
  const ga = ms.reduce((acc, m) => acc + Number(m.opponent_score || 0), 0);
  const gd = gf - ga;
  const pgoals = ms.reduce((acc, m) => acc + Number(m.player_goals != null ? m.player_goals : (m.user_score || 0)), 0);
  const mvps = ms.reduce((acc, m) => acc + (m.is_mvp ? 1 : 0), 0);

  let h = `<div class="card ${t > 0 ? (w >= l ? 'win-card' : 'loss-card') : ''}">
    <div class="session-head">
      <div>
        <h2 style="font-size:1.2rem;font-weight:800">Active Session</h2>
        <div class="session-meta">
          <span class="tag">${ic('clock')} ${formatDate(s.started_at)}</span>
          <span class="tag ${s.mode === 'duo' ? 'duo' : 'solo'}">${ic(s.mode === 'duo' ? 'users' : 'user')} ${s.mode === 'duo' ? ('Duo' + (s.friend_name ? ' · ' + esc(s.friend_name) : '')) : 'Solo'}</span>
          <span class="tag live">Live Session</span>
        </div>
      </div>
      <div class="actions" style="margin:0">
        ${t > 0 ? `<button class="btn btn-share btn-sm" onclick="shareSessionCard(${s.id})">${ic('share')} Share Card</button>
        <button class="btn btn-ghost btn-sm" onclick="showCoachReport(${s.id})">${ic('coach')} Coach Report</button>` : ''}
        <button class="btn btn-danger btn-sm" onclick="endSession()">End Session</button>
      </div>
    </div>`;

  if (t > 0) {
    h += `<div class="kpi-strip">
      <div class="kpi-box"><div class="kpi-val" style="color:var(--green)">${w}</div><div class="kpi-lab">Wins</div></div>
      <div class="kpi-box"><div class="kpi-val" style="color:var(--red)">${l}</div><div class="kpi-lab">Losses</div></div>
      <div class="kpi-box"><div class="kpi-val" style="color:${wr >= 50 ? 'var(--cyan)' : 'var(--orange)'}">${wr}%</div><div class="kpi-lab">Winrate</div></div>
      <div class="kpi-box"><div class="kpi-val" style="color:${gd >= 0 ? 'var(--green)' : 'var(--red)'}">${gd > 0 ? '+' + gd : gd}</div><div class="kpi-lab">Goal Diff</div></div>
      <div class="kpi-box"><div class="kpi-val" style="color:var(--blue)">${pgoals}</div><div class="kpi-lab">Your Goals</div></div>
      <div class="kpi-box"><div class="kpi-val" style="color:var(--gold)">${mvps}</div><div class="kpi-lab">MVPs</div></div>
    </div>
    <div id="session-coach-box"></div>
    <div style="margin-top:8px">${ms.slice().reverse().map((m, i) => matchRowHtml(m, ms.length - 1 - i)).join('')}</div>
    <div id="session-deep-active"></div>`;
  } else {
    h += `<div class="empty-state"><p>No competitive matches recorded in this session yet. Queue up and play!</p></div>`;
  }
  h += `</div>`;
  document.getElementById('active-content').innerHTML = h;
  if (t > 0) loadSessionDeepStats(s.id, 'session-deep-active');
}

function matchRowHtml(m, i) {
  const rowCls = m.result === 'win' ? 'win-row' : (m.result === 'loss' ? 'loss-row' : '');
  const arenaChip = m.arena_name ? `<span class="tag">${esc(m.arena_name)}</span>` : '';
  const scoreChip = m.player_score > 0 ? `<span class="stat-pill">PTS <b>${m.player_score}</b></span>` : '';
  const otChip = m.overtime ? `<span class="tag warn">OT</span>` : '';
  return `<div class="match-row ${rowCls}" onclick="toggleMatchDetail(${m.id}, this)">
    <div>
      <div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Match ${i + 1}</div>
      <div class="score">${m.user_score} – ${m.opponent_score}</div>
    </div>
    <div class="meta">
      <span class="${resultClass(m.result)}">${esc((m.result || '').toUpperCase())}</span>
      <span class="tag">${esc(m.playlist || 'Unknown')}</span>
      ${arenaChip}
      ${otChip}
      ${tagPills(m)}
      ${matchBadges(m)}
      ${scoreChip}
    </div>
    <div style="color:var(--muted);font-size:.74rem">Inspect ▾</div>
    <div class="match-detail-popup" onclick="event.stopPropagation()"></div>
  </div>`;
}

async function toggleMatchDetail(mid, el) {
  const popup = el.querySelector('.match-detail-popup');
  if (!popup) return;
  if (popup.classList.contains('show')) {
    popup.classList.remove('show');
    popup.innerHTML = '';
    return;
  }
  popup.classList.add('show');
  popup.innerHTML = '<div class="loading" style="padding:12px"><div class="spinner"></div>Loading telemetry...</div>';
  try {
    const r = await api('/api/matches/' + mid);
    const m = r.match || {};
    const d = r.details || {};
    const goals = r.goals || [];
    const totalShots = d.shots || 0;
    const pgoals = d.player_goals != null ? d.player_goals : (m.user_score || 0);
    const sa = totalShots ? Math.min(Number((pgoals / Math.max(totalShots, 1) * 100).toFixed(1)), 100) : 0;

    let coachHtml = '';
    try {
      const cr = await api('/api/coach/match/' + mid);
      const ins = cr.insights || [];
      if (ins.length) {
        coachHtml = `<div class="deep-section" style="margin-top:0"><h3>Match Coach Insights</h3>${ins.map(i => `<div class="tip ${i.severity || 'info'}"><span>${esc(i.icon || '•')}</span><span>${esc(i.text)}</span></div>`).join('')}</div>`;
      }
    } catch (e) {}

    let scoreboardHtml = '';
    const players = d.players || [];
    if (players.length) {
      scoreboardHtml = `<div class="deep-section" style="margin-top:0"><h3>Match Scoreboard${d.arena_name ? ' · ' + esc(d.arena_name) : ''}</h3>
        <table class="scoreboard-table">
          <thead><tr><th>Player</th><th>Score</th><th>Goals</th><th>Ast</th><th>Saves</th><th>Shots</th><th>Demos</th></tr></thead>
          <tbody>
            ${players.map(p => `<tr class="team-${p.team_num} ${p.is_user ? 'is-you' : ''}">
              <td>${esc(p.name)}${p.is_user ? ' <span class="tag live" style="padding:1px 6px;font-size:.64rem">YOU</span>' : (p.is_friend ? ' <span class="tag duo" style="padding:1px 6px;font-size:.64rem">DUO</span>' : '')}</td>
              <td><b>${p.score || 0}</b></td>
              <td>${p.goals || 0}</td>
              <td>${p.assists || 0}</td>
              <td>${p.saves || 0}</td>
              <td>${p.shots || 0}</td>
              <td>${p.demos || 0}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    }

    const timelineHtml = `<div class="deep-section" style="margin-top:0"><h3>Goal Timeline</h3>${renderGoalTimeline(goals)}</div>`;

    const a = {
      fastest_goal_kph: d.fastest_goal_kph,
      avg_shot_power: d.avg_shot_power,
      shot_accuracy: sa,
      total_shots: totalShots,
      avg_boost: d.boost_avg,
      avg_boost_time: d.boost_time_pct,
      avg_supersonic_time: d.supersonic_time_pct,
      avg_air_time: d.air_time_pct,
      avg_ground_time: d.ground_time_pct,
      avg_wall_time: d.wall_time_pct,
      avg_powerslide_time: d.powerslide_time_pct,
      avg_speed_kph: d.avg_speed_kph,
      player_score: d.player_score,
      demos_given: d.demos_given,
      demos_taken: d.demos_taken,
      saves: d.saves,
      overtime: d.overtime,
      crossbar_hits: d.crossbar_hits,
      boost_pills: d.boost_pills,
      boost_pads: d.boost_pads,
      touches: d.touches,
      car_touches: d.car_touches,
      assists: d.assists,
      total_goals: pgoals,
      total_matches: 1,
    };

    const actionsHtml = `<div class="actions" style="justify-content:flex-end;margin-top:14px;padding-top:10px;border-top:1px solid var(--border)">
      <button class="btn btn-ghost btn-sm" onclick='openEditMatch(${JSON.stringify({
        id: m.id,
        result: m.result,
        playlist: m.playlist || '',
        user_score: m.user_score,
        opponent_score: m.opponent_score,
        tags: m.tags || '',
      })})'>${ic('edit')} Edit Match</button>
      <button class="btn btn-danger btn-sm" onclick="deleteMatch(${m.id})">${ic('trash')} Delete Match</button>
    </div>`;

    popup.innerHTML = scoreboardHtml + timelineHtml + coachHtml + renderDeepBlocks(a) + actionsHtml;
  } catch (e) {
    popup.innerHTML = `<p style="color:var(--red)">${esc(e.message)}</p>`;
  }
}

function openEditMatch(m) {
  document.getElementById('edit-match-id').value = m.id;
  document.getElementById('edit-match-result').value = m.result || 'win';
  document.getElementById('edit-match-playlist').value = m.playlist || '';
  document.getElementById('edit-match-us').value = m.user_score ?? 0;
  document.getElementById('edit-match-opp').value = m.opponent_score ?? 0;
  document.getElementById('edit-match-tags').value = m.tags || '';
  document.getElementById('edit-match-modal').style.display = 'flex';
}
function closeEditMatch() {
  document.getElementById('edit-match-modal').style.display = 'none';
}
async function saveEditMatch() {
  const id = document.getElementById('edit-match-id').value;
  try {
    await api('/api/matches/' + id, {
      method: 'PATCH',
      body: JSON.stringify({
        result: document.getElementById('edit-match-result').value,
        playlist: document.getElementById('edit-match-playlist').value.trim(),
        user_score: Number(document.getElementById('edit-match-us').value),
        opponent_score: Number(document.getElementById('edit-match-opp').value),
        tags: document.getElementById('edit-match-tags').value.trim(),
      }),
    });
    closeEditMatch();
    showToast('Match updated');
    playlistsCache = [];
    loadActiveSession();
    if (document.getElementById('panel-history').classList.contains('active')) loadHistory();
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

async function deleteMatch(mid) {
  if (!(await askConfirm('Delete Match', 'Permanently delete this match and its telemetry?', 'Delete Match'))) return;
  try {
    await api('/api/matches/' + mid, { method: 'DELETE' });
    showToast('Match deleted');
    playlistsCache = [];
    loadActiveSession();
    if (document.getElementById('panel-history').classList.contains('active')) loadHistory();
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

async function endSession() {
  if (!activeSessionId) return;
  if (!(await askConfirm('End Session', 'Complete this active session and move it to History?', 'End Session'))) return;
  try {
    await api('/api/sessions/' + activeSessionId + '/end', { method: 'POST' });
    showToast('Session completed');
    activeSessionId = null;
    loadActiveSession();
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

// ===== HISTORY TAB =====
async function loadHistory() {
  const c = document.getElementById('history-content');
  c.innerHTML = '<div class="loading"><div class="spinner"></div>Loading sessions...</div>';
  olderMatchesOffset = 0;
  try {
    const all = await api('/api/sessions');
    const ss = historyMode === 'all' ? all : all.filter(s => (s.mode || 'solo').toLowerCase() === historyMode);

    const filterChips = [['all', 'All Modes'], ['solo', 'Solo'], ['duo', 'Duo']].map(([v, l]) =>
      `<button class="chip ${historyMode === v ? 'active' : ''}" onclick="historyMode='${v}';loadHistory()">${l}</button>`
    ).join('');

    if (!ss.length) {
      c.innerHTML = `<div class="filters">${filterChips}</div><div class="empty-state card"><h3>No sessions found</h3><p class="hint-text">Play a competitive match or change filter.</p></div>`;
      return;
    }

    const cards = ss.map(s => {
      const w = s.wins || 0, l = s.losses || 0, t = w + l, wr = t ? Math.round(w / t * 100) : 0;
      const gd = (s.goals_for || 0) - (s.goals_against || 0);
      const accent = t > 0 && w >= l ? 'var(--green)' : t > 0 ? 'var(--red)' : 'var(--blue)';
      const dots = (s.recent_results || []).map(r => `<span class="form-dot ${r}" style="width:18px;height:18px;font-size:.55rem">${r === 'win' ? 'W' : r === 'loss' ? 'L' : 'D'}</span>`).join('');
      const pls = (s.playlists || []).slice(0, 3).map(p => `<span class="tag">${esc(p)}</span>`).join('');
      return `<div class="card session-card" style="border-left:4px solid ${accent}" onclick="toggleSessionExpand(${s.id})">
        <div class="session-head">
          <div>
            <span style="font-weight:800;font-size:1rem">${formatDate(s.started_at)}</span>
            ${s.duration_sec > 60 ? `<span class="hint-text" style="margin-left:8px">· ${fmtDur(s.duration_sec)}</span>` : ''}
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
            ${pls}
            <span class="tag ${s.mode === 'duo' ? 'duo' : 'solo'}">${ic(s.mode === 'duo' ? 'users' : 'user')} ${s.mode === 'duo' ? ('Duo' + (s.friend_name ? ' · ' + esc(s.friend_name) : '')) : 'Solo'}</span>
            <span class="tag ${s.status === 'active' ? 'live' : ''}">${s.status === 'active' ? 'Live' : 'Done'}</span>
          </div>
        </div>
        <div class="session-meta" style="justify-content:space-between">
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
            <span class="tag"><b>${t}</b> matches</span>
            ${t ? `<span class="stat-pill g"><b>${w}W</b></span><span class="stat-pill r"><b>${l}L</b></span><span class="stat-pill b"><b>${wr}%</b></span><span class="stat-pill">GD <b>${gd > 0 ? '+' + gd : gd}</b></span>` : '<span class="hint-text">Empty session</span>'}
          </div>
          <div style="display:flex;gap:4px">${dots}</div>
        </div>
        <div class="session-expand" id="expand-${s.id}" onclick="event.stopPropagation()"></div>
      </div>`;
    }).join('');

    c.innerHTML = `<div class="filters">${filterChips}</div>${cards}
      <div style="text-align:center;margin-top:16px">
        <button class="btn btn-ghost" onclick="loadOlderMatches()">Load Older Match Summaries</button>
      </div>
      <div id="older-matches-results" style="margin-top:12px"></div>`;
  } catch (e) {
    c.innerHTML = `<div class="empty-state"><p>Error: ${esc(e.message)}</p></div>`;
  }
}

async function toggleSessionExpand(sid) {
  const e = document.getElementById('expand-' + sid);
  if (!e) return;
  if (e.classList.contains('open')) {
    e.classList.remove('open');
    e.innerHTML = '';
    return;
  }
  document.querySelectorAll('.session-expand.open').forEach(el => {
    el.classList.remove('open');
    el.innerHTML = '';
  });
  e.classList.add('open');
  e.innerHTML = '<div class="loading" style="padding:14px"><div class="spinner"></div></div>';
  try {
    const s = await api('/api/sessions/' + sid);
    const ms = s.matches || [];
    let h = `<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">`;
    h += ms.length ? ms.map((m, i) => matchRowHtml(m, i)).join('') : '<p class="hint-text" style="text-align:center;padding:8px">No matches</p>';
    h += `<div class="actions">
      <button class="btn btn-share btn-sm" onclick="shareSessionCard(${sid})">${ic('share')} Share Card</button>
      <button class="btn btn-ghost btn-sm" onclick="showCoachReport(${sid},'expand-coach-${sid}')">${ic('coach')} Coach Report</button>
      <button class="btn btn-danger btn-sm" onclick="deleteSession(${sid})">${ic('trash')} Delete Session</button>
    </div>
    <div id="expand-coach-${sid}"></div>
    <div id="session-deep-${sid}"></div></div>`;
    e.innerHTML = h;
    loadSessionDeepStats(sid, 'session-deep-' + sid);
  } catch (err) {
    e.innerHTML = `<p style="color:var(--red);padding:10px">${esc(err.message)}</p>`;
  }
}

async function loadSessionDeepStats(sid, elId) {
  const c = document.getElementById(elId || ('session-deep-' + sid));
  if (!c) return;
  try {
    const deep = await api('/api/sessions/' + sid + '/deep');
    const a = deep.aggregates || {};
    if (!a.total_matches) { c.innerHTML = ''; return; }
    c.innerHTML = `<div class="deep-section"><h3>Session Deep Telemetry</h3></div>` + renderDeepBlocks(a);
  } catch (e) { c.innerHTML = ''; }
}

async function deleteSession(sid) {
  if (!(await askConfirm('Delete Session', 'Permanently delete this entire session and all its matches?', 'Delete Session'))) return;
  try {
    await api('/api/sessions/' + sid, { method: 'DELETE' });
    showToast('Session deleted');
    loadHistory();
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

async function loadOlderMatches() {
  const c = document.getElementById('older-matches-results');
  try {
    const r = await api('/api/matches/summaries?offset=' + olderMatchesOffset + '&limit=50');
    const sums = r.summaries || [];
    if (!sums.length) {
      c.insertAdjacentHTML('beforeend', '<p class="hint-text" style="text-align:center;padding:10px">No more archived matches.</p>');
      return;
    }
    c.insertAdjacentHTML('beforeend', sums.map(s => {
      const accent = s.result === 'win' ? 'var(--green)' : s.result === 'draw' ? 'var(--muted)' : 'var(--red)';
      return `<div class="card" style="border-left:4px solid ${accent};padding:14px">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-weight:900;font-size:1.1rem">${s.user_score} – ${s.opponent_score}</span>
            <span class="${resultClass(s.result)}">${esc((s.result || '').toUpperCase())}</span>
            <span class="tag">${esc(s.playlist || 'Unknown')}</span>
            ${s.arena_name ? `<span class="tag">${esc(s.arena_name)}</span>` : ''}
          </div>
          <span class="hint-text">${relativeTime(s.played_at)}</span>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">${matchBadges(s)}</div>
      </div>`;
    }).join(''));
    olderMatchesOffset += sums.length;
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

// ===== ANALYTICS TAB =====
function _statsQueryString() {
  const q = new URLSearchParams();
  if (statsMode !== 'all') q.set('mode', statsMode);
  if (statsPlaylist !== 'all') q.set('playlist', statsPlaylist);
  if (statsDays) q.set('days', statsDays);
  if (statsLimit) q.set('limit', statsLimit);
  return q.toString() ? ('?' + q.toString()) : '';
}

async function loadStats() {
  const c = document.getElementById('stats-content');
  c.innerHTML = '<div class="loading"><div class="spinner"></div>Loading analytics...</div>';
  try {
    if (!playlistsCache.length) {
      try {
        const pl = await api('/api/stats/playlists');
        playlistsCache = pl.playlists || [];
      } catch (e) {}
    }
    const qs = _statsQueryString();
    const [s, deep, analytics] = await Promise.all([
      api('/api/stats' + qs),
      api('/api/stats/deep' + qs),
      api('/api/stats/analytics' + qs),
    ]);

    const chipsTime = [
      ['', '', 'All Time'],
      ['30', '', '30 Days'],
      ['7', '', '7 Days'],
      ['', '20', 'Last 20'],
    ].map(([d, l, lab]) => {
      const act = statsDays === d && statsLimit === l;
      return `<button class="chip ${act ? 'active' : ''}" onclick="statsDays='${d}';statsLimit='${l}';loadStats()">${lab}</button>`;
    }).join('');

    const chipsMode = [['all', 'All Modes'], ['solo', 'Solo'], ['duo', 'Duo']].map(([v, l]) =>
      `<button class="chip ${statsMode === v ? 'active' : ''}" onclick="statsMode='${v}';loadStats()">${l}</button>`
    ).join('');

    const chipsPl = [`<button class="chip ${statsPlaylist === 'all' ? 'active' : ''}" onclick="statsPlaylist='all';loadStats()">All Playlists</button>`]
      .concat(playlistsCache.map(p =>
        `<button class="chip ${statsPlaylist === p.playlist ? 'active' : ''}" data-pl="${esc(p.playlist)}" onclick="statsPlaylist=this.dataset.pl;loadStats()">${esc(p.playlist)} (${p.total})</button>`
      )).join('');

    const t = s.overall.total || 0;
    const headerFilters = `<div style="display:flex;justify-content:center;margin-bottom:12px">
        <button class="btn btn-ghost btn-sm" onclick="playlistsCache=[];loadStats()">${ic('refresh')} Refresh Stats</button>
      </div>
      <div class="filters">${chipsTime} · ${chipsMode}</div>
      <div class="filters">${chipsPl}</div>`;

    if (!t) {
      c.innerHTML = `${headerFilters}<div class="empty-state card"><h3>No matches match this filter</h3></div>`;
      return;
    }

    const owr = Math.round((s.overall.wins || 0) / t * 100);
    const swr = s.solo.total ? Math.round(s.solo.wins / s.solo.total * 100) : 0;
    const dwr = s.duo.total ? Math.round(s.duo.wins / s.duo.total * 100) : 0;

    // Reverse copy for display (oldest left -> newest right); keep original order for calcStreak
    const buildForm = rs => {
      const dots = rs.map(r => `<div class="form-dot ${r}">${r === 'win' ? 'W' : r === 'loss' ? 'L' : 'D'}</div>`);
      while (dots.length < 20) dots.push('<div class="form-dot placeholder">-</div>');
      return dots.join('');
    };
    const calcStreak = rs => {
      let n = 0;
      for (const r of (rs || [])) { if (r !== 'win') break; n++; }
      return n;
    };
    const soloHtml = buildForm((s.recent_solo || []).slice().reverse());
    const duoHtml = buildForm((s.recent_duo || []).slice().reverse());
    const ssStreak = calcStreak(s.recent_solo || []);
    const dsStreak = calcStreak(s.recent_duo || []);
    const stInfo = analytics.streaks || {};

    const duoFriendsHtml = (s.duo_by_friend && s.duo_by_friend.length)
      ? `<div class="card"><div class="section-title">${packIcon('people')} Duo Partner Leaderboard</div>
          ${s.duo_by_friend.map(f => {
            const fwr = f.total ? (f.wins / f.total * 100) : 0;
            return `<div class="hbar-row">
              <div class="hbar-head"><span><b>${esc(f.friend_name)}</b> <span class="hint-text">(${f.wins}W-${f.losses}L)</span></span><b>${fwr.toFixed(1)}%</b></div>
              <div class="hbar-track"><div class="hbar-fill" style="width:${fwr}%"></div></div>
            </div>`;
          }).join('')}
        </div>`
      : '';

    c.innerHTML = `${headerFilters}
      <div class="stats-grid">
        <div class="stat-card ${owr >= 50 ? 'win-card' : 'loss-card'}">
          <h4>${packIcon('trophy')} Filtered Winrate</h4>
          <div class="big-number">${owr}%</div>
          <div style="color:var(--soft);font-size:.82rem">${s.overall.wins || 0}W · ${s.overall.losses || 0}L · ${t} games</div>
          <div class="winrate-bar"><div class="winrate-fill" style="width:${owr}%"></div></div>
          <div class="hint-text" style="margin-top:8px">Best streak: <b>${stInfo.best_win || 0}W</b> · Current: <b>${stInfo.current_len || 0}${stInfo.current_type === 'win' ? 'W' : stInfo.current_type === 'loss' ? 'L' : ''}</b></div>
        </div>
        <div class="stat-card ${swr >= 50 ? 'win-card' : 'loss-card'}">
          <h4>${ic('user')} Solo Queue</h4>
          <div class="big-number">${swr}%</div>
          <div style="color:var(--soft);font-size:.82rem">${s.solo.wins || 0}W · ${s.solo.losses || 0}L</div>
          <div class="recent-form">${soloHtml}</div>
          ${ssStreak >= 3 ? `<div class="streak-badge hot">${ssStreak} W Streak</div>` : ''}
        </div>
        <div class="stat-card ${dwr >= 50 ? 'win-card' : 'loss-card'}">
          <h4>${ic('users')} Duo Queue</h4>
          <div class="big-number">${dwr}%</div>
          <div style="color:var(--soft);font-size:.82rem">${s.duo.wins || 0}W · ${s.duo.losses || 0}L</div>
          <div class="recent-form">${duoHtml}</div>
          ${dsStreak >= 3 ? `<div class="streak-badge hot">${dsStreak} W Streak</div>` : ''}
        </div>
      </div>

      <div class="analytics-grid">
        <div class="card">
          <div class="section-title">${packIcon('rocket')} Rolling 10-Game Winrate Trend</div>
          <div id="chart-wr-trend"></div>
        </div>
        <div class="card">
          <div class="section-title">${packIcon('speed')} Movement &amp; Recovery Profile</div>
          <div id="chart-movement"></div>
        </div>
        <div class="card">
          <div class="section-title">${packIcon('game')} Winrate by Playlist</div>
          <div id="chart-playlists"></div>
        </div>
        <div class="card">
          <div class="section-title">${packIcon('star')} Winrate by Arena</div>
          <div id="chart-arenas"></div>
        </div>
      </div>

      ${duoFriendsHtml}
      <div class="card" id="deep-stats-container"></div>`;

    renderWinrateTrendChart(document.getElementById('chart-wr-trend'), analytics.timeline || []);
    const agg = deep.aggregates || {};
    renderMovementStrip(document.getElementById('chart-movement'), agg);
    renderHorizontalBars(document.getElementById('chart-playlists'), analytics.playlists || [], 'playlist', 'No playlists recorded');
    renderHorizontalBars(document.getElementById('chart-arenas'), analytics.arenas || [], 'name', 'No arenas recorded');

    const dsc = document.getElementById('deep-stats-container');
    if (agg.total_matches) {
      dsc.innerHTML = `<div class="section-title">${packIcon('lightning')} Full Telemetry Breakdown (${agg.total_matches} matches)</div>` + renderDeepBlocks(agg);
    } else {
      dsc.innerHTML = '';
    }
  } catch (e) {
    c.innerHTML = `<div class="empty-state"><p>Error: ${esc(e.message)}</p></div>`;
  }
}

// ===== COACH 4.0 TAB =====
async function loadCoach() {
  const c = document.getElementById('coach-content');
  c.innerHTML = '<div class="loading"><div class="spinner"></div>Loading Coach 4.0...</div>';
  try {
    const [r, ss, ana] = await Promise.all([
      api('/api/coach/records'),
      api('/api/sessions'),
      api('/api/stats/analytics'),
    ]);
    const rec = r.records || {};
    const tm = rec.total_matches || 0;
    const withMatches = ss.filter(s => (s.wins || 0) + (s.losses || 0) > 0).slice(0, 10);

    if (!tm) {
      c.innerHTML = '<div class="empty-state card"><h3>Coach 4.0 is warming up</h3><p class="hint-text">Play at least one competitive match to unlock coaching reports.</p></div>';
      return;
    }

    const trophies = [
      { ico: 'football', label: 'Most Personal Goals', val: rec.most_goals?.value || 0, sub: rec.most_goals?.playlist },
      { ico: 'crown', label: 'Highest Match Score', val: rec.highest_score?.value || 0, sub: rec.highest_score?.playlist },
      { ico: 'rocket', label: 'Fastest Goal', val: rec.fastest_goal_kph?.value ? rec.fastest_goal_kph.value + ' km/h' : 0, sub: rec.fastest_goal_kph?.playlist },
      { ico: 'shield', label: 'Most Saves', val: rec.most_saves?.value || 0, sub: rec.most_saves?.playlist },
      { ico: 'fire', label: 'Most Demos', val: rec.most_demos?.value || 0, sub: rec.most_demos?.playlist },
      { ico: 'target', label: 'Most Shots', val: rec.most_shots?.value || 0, sub: rec.most_shots?.playlist },
      { ico: 'lightning', label: 'Top Avg Boost', val: rec.highest_boost_avg?.value ? rec.highest_boost_avg.value + '%' : 0, sub: rec.highest_boost_avg?.playlist },
      { ico: 'trophy', label: 'Longest Win Streak', val: rec.longest_win_streak?.value ? rec.longest_win_streak.value + 'W' : 0, sub: 'Career Peak' },
    ].filter(t => t.val);

    const wvl = ana.win_vs_loss || {};
    const wvlRows = (wvl.metrics || []).slice(0, 8).map(m => {
      const d = m.delta;
      const dStr = (d > 0 ? '+' : '') + d + (m.unit || '');
      return `<div class="wvl-row">
        <span style="color:var(--soft)">${esc(m.label)}</span>
        <div style="display:flex;justify-content:space-between;gap:12px">
          <span style="color:var(--green)">Win: <b>${m.win}${m.unit}</b></span>
          <span style="color:var(--red)">Loss: <b>${m.loss}${m.unit}</b></span>
        </div>
        <span style="text-align:right;font-weight:800;color:${d >= 0 ? 'var(--cyan)' : 'var(--orange)'}">${dStr}</span>
      </div>`;
    }).join('');
    const wvlTips = (wvl.insights || []).map(i => `<div class="tip ${i.severity || 'info'}"><span>${esc(i.text)}</span></div>`).join('');

    const sessionPick = withMatches.map((s, idx) =>
      `<button class="chip ${idx === 0 ? 'active' : ''}" onclick="document.querySelectorAll('#coach-sess-chips .chip').forEach(x=>x.classList.remove('active'));this.classList.add('active');showCoachReport(${s.id},'coach-report-root')">${formatDate(s.started_at)} · ${s.wins || 0}W-${s.losses || 0}L</button>`
    ).join('');

    c.innerHTML = `
      <div class="card">
        <div class="section-title">${packIcon('trophy')} Career Trophy Cabinet (${tm} matches · ${rec.total_wins || 0}W-${rec.total_losses || 0}L)</div>
        <div class="trophy-grid">
          ${trophies.map(t => `<div class="trophy-card">
            ${packIcon(t.ico, 'pack-ico-lg')}
            <div>
              <div class="trophy-val">${esc(t.val)}</div>
              <div class="trophy-lab">${esc(t.label)}</div>
              ${t.sub ? `<div class="trophy-sub">${esc(t.sub)}</div>` : ''}
            </div>
          </div>`).join('')}
        </div>
      </div>

      <div class="card">
        <div class="section-title">${packIcon('speed')} Win vs Loss Telemetry Diagnostic (${wvl.wins_count || 0} Wins vs ${wvl.losses_count || 0} Losses)</div>
        ${wvlTips}
        <div style="margin-top:10px">${wvlRows}</div>
      </div>

      <div class="card">
        <div class="section-title">${packIcon('ai')} Coach 4.0 — Session Deep Evaluation</div>
        <div class="filters" id="coach-sess-chips" style="justify-content:flex-start">${sessionPick || '<span class="hint-text">No sessions yet</span>'}</div>
        <div id="coach-report-root"></div>
      </div>`;

    if (withMatches.length) {
      showCoachReport(withMatches[0].id, 'coach-report-root');
    }
  } catch (e) {
    c.innerHTML = `<div class="empty-state"><p>Error: ${esc(e.message)}</p></div>`;
  }
}

function renderCoachReport(rep) {
  if (rep.error) return `<p style="color:var(--red)">${esc(rep.error)}</p>`;
  const gcol = gradeColor(rep.overall_grade);
  let h = `<div style="margin-top:12px;padding:16px;border-radius:14px;background:var(--tile);border:1px solid var(--border)">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px">
      <div>
        <div class="grade-pill" style="background:${gcol}">COACH ${esc(rep.overall_grade)} · ${rep.overall_score || 0}</div>
        <p style="margin-top:8px;color:var(--soft);font-size:.9rem">${esc(rep.summary || '')}</p>
      </div>
      <div class="tag">${rep.wins || 0}W-${rep.losses || 0}L · ${rep.match_count || 0} games · ${esc((rep.mode || '').toUpperCase())}</div>
    </div>
    <div class="coach-grid">
      <div class="card" style="margin:0;padding:14px;background:rgba(6,9,19,0.75)">
        <div style="font-size:.74rem;font-weight:800;color:var(--muted);text-transform:uppercase;text-align:center;margin-bottom:6px">5-Axis Performance Radar</div>
        <div class="coach-radar-mount"></div>
      </div>
      <div>`;

  (rep.players || []).forEach(p => {
    h += `<div style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <strong>${ic(p.role === 'you' ? 'user' : 'users')} ${esc(p.name)}</strong>
        <span class="grade-pill" style="background:${gradeColor(p.grade)};font-size:.76rem;padding:4px 10px">${esc(p.grade)} · ${p.score}</span>
      </div>
      <div class="cat-grid">${['scoring', 'defense', 'boost', 'movement', 'aggression'].filter(k => (p.categories || {})[k]).map(k => {
        const v = p.categories[k];
        return `<div class="cat">
          <div class="n">${esc(k)}</div>
          <div class="s">${v.score} <span class="${trendClass(v.trend)}">${trendIcon(v.trend)}</span></div>
          <div class="hint-text" style="font-size:.7rem;margin-top:3px">${esc(v.note || '')}</div>
        </div>`;
      }).join('')}</div>
      ${(p.tips || []).map(t => `<div class="tip ${t.severity || 'info'}"><span>${esc(t.icon || '•')}</span><span>${esc(t.text)}</span></div>`).join('')}
    </div>`;
  });

  (rep.session_tips || []).forEach(t => {
    h += `<div class="tip ${t.severity || 'info'}"><span>${esc(t.icon || '•')}</span><span>${esc(t.text)}</span></div>`;
  });
  h += `</div></div></div>`;
  return h;
}

async function showCoachReport(sid, targetId) {
  const id = targetId || 'session-coach-box';
  let box = document.getElementById(id);
  if (!box) return;
  box.innerHTML = '<div class="loading" style="padding:12px"><div class="spinner"></div>Analyzing session...</div>';
  try {
    const rep = await api('/api/coach/session/' + sid + '/report');
    box.innerHTML = renderCoachReport(rep);
    const radarEl = box.querySelector('.coach-radar-mount');
    if (radarEl && rep.radar) renderCoachRadar(radarEl, rep.radar);
  } catch (e) {
    box.innerHTML = `<p style="color:var(--red)">${esc(e.message)}</p>`;
  }
}

async function shareSessionCard(sid) {
  showToast('Rendering Overdrive session card...');
  try {
    const r = await fetch('/api/sessions/' + sid + '/card.png');
    if (!r.ok) throw new Error('Card render failed');
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `rl-session-${sid}.png`;
    a.click();
    window.open(url, '_blank');
    showToast('Session card ready for Discord!');
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

// ===== SETTINGS MODAL & MAINTENANCE =====
function switchSettingsTab(tab) {
  document.querySelectorAll('.mtab').forEach(b => b.classList.toggle('active', b.dataset.stab === tab));
  document.querySelectorAll('.stab-panel').forEach(p => p.classList.toggle('active', p.id === 'stab-' + tab));
  if (tab === 'diagnostics') loadDiagnostics();
}

function updateFilterVisibility() {
  const scope = document.querySelector('input[name="cfg-scope"]:checked')?.value || 'competitive';
  const box = document.getElementById('custom-filter-toggles');
  if (box) {
    box.style.opacity = scope === 'custom' ? '1' : '0.45';
    box.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.disabled = scope !== 'custom';
    });
  }
}

async function openSettings(tab = 'profile') {
  const m = document.getElementById('settings-modal');
  m.style.display = 'flex';
  switchSettingsTab(tab);
  try {
    const c = await api('/api/config');
    document.getElementById('cfg-player-name').value = c.name || '';
    document.getElementById('cfg-aliases').value = (c.aliases || []).join('\n');
    document.getElementById('cfg-friends').value = (c.friends || []).join('\n');
    const tr = c.tracking || {};
    const scope = tr.scope || 'competitive';
    const rad = document.querySelector(`input[name="cfg-scope"][value="${scope}"]`);
    if (rad) rad.checked = true;
    document.getElementById('cfg-inc-core').checked = tr.include_core_ranked !== false;
    document.getElementById('cfg-inc-extra').checked = tr.include_extra_ranked !== false;
    document.getElementById('cfg-inc-tourney').checked = tr.include_tournaments !== false;
    document.getElementById('cfg-inc-casual').checked = Boolean(tr.include_casual);
    document.getElementById('cfg-inc-private').checked = Boolean(tr.include_private);
    updateFilterVisibility();
  } catch (e) {}
  loadDiagnostics();
}

function closeSettings() {
  document.getElementById('settings-modal').style.display = 'none';
}

async function saveSettings() {
  const name = document.getElementById('cfg-player-name').value.trim();
  const aliases = document.getElementById('cfg-aliases').value.split('\n').map(x => x.trim()).filter(Boolean);
  const friends = document.getElementById('cfg-friends').value.split('\n').map(x => x.trim()).filter(Boolean);
  const scope = document.querySelector('input[name="cfg-scope"]:checked')?.value || 'competitive';
  const tracking = {
    scope,
    include_core_ranked: document.getElementById('cfg-inc-core').checked,
    include_extra_ranked: document.getElementById('cfg-inc-extra').checked,
    include_tournaments: document.getElementById('cfg-inc-tourney').checked,
    include_casual: document.getElementById('cfg-inc-casual').checked,
    include_private: document.getElementById('cfg-inc-private').checked,
  };
  try {
    await api('/api/config', {
      method: 'POST',
      body: JSON.stringify({ name, aliases, friends, tracking }),
    });
    showToast('Settings saved & live-reloaded');
    closeSettings();
    setTimeout(pollLiveOnce, 600);
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

async function loadDiagnostics() {
  const b = document.getElementById('rl-config-badge');
  const m = document.getElementById('rl-config-msg');
  const extra = document.getElementById('diag-extra');
  const logBox = document.getElementById('diag-log-tail');
  try {
    const d = await api('/api/diagnostics');
    const ini = d.ini || {};
    if (!ini.config_dir_found) {
      b.textContent = 'Not Found';
      b.className = 'tag warn';
      m.textContent = 'Rocket League Config folder not found under Documents\\My Games.';
    } else if (!ini.ini_exists) {
      b.textContent = 'Missing';
      b.className = 'tag warn';
      m.textContent = 'TAStatsAPI.ini missing — click Auto-Create / Repair INI.';
    } else if (!ini.ini_correct) {
      b.textContent = 'Broken Section';
      b.className = 'tag warn';
      m.textContent = 'TAStatsAPI.ini missing [TAGame.MatchStatsExporter_TA] or PacketSendRate=30 — click Auto-Create / Repair.';
    } else {
      b.textContent = ini.port_49123_open ? 'PORT OPEN' : 'INI OK';
      b.className = 'tag live';
      m.textContent = ini.ini_read_by_rl
        ? (ini.port_49123_open ? 'INI verified by RL and port 49123 is live!' : 'INI verified by RL. Launch Rocket League to open port 49123.')
        : 'INI written correctly — restart Rocket League once so RL reads it.';
    }
    const dbInfo = d.db || {};
    let ex = `DB: ${dbInfo.total_matches || 0} matches across ${dbInfo.total_sessions || 0} sessions`;
    if (dbInfo.non_competitive_count > 0) ex += ` (${dbInfo.non_competitive_count} non-competitive legacy rows detected)`;
    if ((ini.default_ini_issues || []).length) ex += ` · Warning: DefaultStatsAPI.ini issue in ${ini.default_ini_issues[0]}`;
    extra.textContent = ex;
    logBox.textContent = (d.log_tail || []).join('\n') || '(listener.log is empty)';
  } catch (e) {
    b.textContent = 'Error';
    m.textContent = e.message;
  }
}

async function createRlConfig() {
  try {
    const r = await api('/api/rl-config', { method: 'POST' });
    showToast(r.created ? 'TAStatsAPI.ini updated — restart Rocket League if running' : r.message);
    loadDiagnostics();
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

async function previewCleanup() {
  const badge = document.getElementById('cleanup-count-badge');
  const box = document.getElementById('cleanup-preview');
  const btn = document.getElementById('btn-run-cleanup');
  try {
    const r = await api('/api/maintenance/cleanup-non-competitive', { method: 'POST', body: JSON.stringify({ dry_run: true }) });
    badge.textContent = `${r.count} found`;
    if (!r.count) {
      box.textContent = 'Your database is already 100% clean Competitive matches!';
      btn.style.display = 'none';
    } else {
      btn.style.display = 'inline-flex';
      const sampleStr = (r.samples || []).slice(0, 6).map(x => `#${x.id} ${x.playlist || 'Unknown'} (${x.user_score}-${x.opponent_score})`).join(', ');
      box.textContent = `Found ${r.count} non-competitive/unknown matches: ${sampleStr}${r.count > 6 ? ' ...' : ''}`;
    }
  } catch (e) {
    box.textContent = 'Error: ' + e.message;
  }
}

async function runCleanup() {
  if (!(await askConfirm('Clean Database', 'Remove all non-competitive / Unknown legacy matches and resulting empty sessions? Tip: download a DB backup first.', 'Delete Non-Competitive'))) return;
  try {
    const r = await api('/api/maintenance/cleanup-non-competitive', { method: 'POST', body: JSON.stringify({ dry_run: false, delete_empty_sessions: true }) });
    showToast(`Deleted ${r.deleted_matches} matches & ${r.deleted_sessions} empty sessions`);
    playlistsCache = [];
    previewCleanup();
    loadActiveSession();
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

async function repairResultsNow() {
  try {
    const r = await api('/api/maintenance/repair-results', { method: 'POST' });
    showToast(r.repaired_count ? `Fixed ${r.repaired_count} inverted W/L rows` : 'All non-forfeit W/L results already match scores');
    loadActiveSession();
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

async function checkForUpdates() {
  const box = document.getElementById('update-results');
  const badge = document.getElementById('update-badge-modal');
  box.style.display = 'block';
  box.innerHTML = '<div class="loading" style="padding:8px"><div class="spinner"></div></div>';
  try {
    const d = await api('/api/check-update');
    if (!d.ok) { box.innerHTML = `<p style="color:var(--red)">${esc(d.error || 'Update check failed')}</p>`; return; }
    if (d.update_available) {
      if (badge) badge.textContent = 'v' + d.latest + ' available';
      box.innerHTML = `<div style="padding:10px;border:1px solid var(--orange);border-radius:10px;background:rgba(251,146,60,0.08)">
        <b style="color:var(--orange)">Update available: v${esc(d.current)} → v${esc(d.latest)}</b>
        <button class="btn btn-share btn-sm" style="margin-top:8px;width:100%;justify-content:center" onclick="performUpdate()">One-Click Update</button>
        <div id="update-progress" style="display:none;margin-top:8px"></div>
      </div>`;
    } else {
      if (badge) { badge.textContent = 'Up to date'; badge.className = 'tag live'; }
      box.innerHTML = `<p style="color:var(--green)">Running latest version (v${esc(d.current)})</p>`;
    }
  } catch (e) {
    box.innerHTML = `<p style="color:var(--red)">${esc(e.message)}</p>`;
  }
}

async function silentUpdateCheck() {
  try {
    const d = await api('/api/check-update');
    if (d.ok && d.update_available) {
      const b = document.getElementById('update-badge');
      if (b) { b.style.display = 'inline-block'; b.textContent = 'Update v' + d.latest; }
    }
  } catch (e) {}
}

async function performUpdate() {
  const prog = document.getElementById('update-progress');
  if (!prog) return;
  prog.style.display = 'block';
  prog.textContent = 'Downloading & applying update...';
  try {
    const r = await api('/api/update', { method: 'POST' });
    prog.textContent = r.ok ? r.message : ('Failed: ' + (r.error || ''));
    if (r.ok) showToast('Updated to v' + r.new_version);
  } catch (e) {
    prog.textContent = (e.message || '').includes('Failed to fetch') ? 'Restarting app...' : e.message;
  }
}

async function confirmExitTracker() {
  if (!(await askConfirm('Exit RL Tracker', 'Quit RL Tracker completely? Background TCP tracking and the web server will stop.', 'Quit Tracker'))) return;
  try { await api('/api/quit', { method: 'POST' }); } catch (e) {}
  showToast('Shutting down RL Tracker...');
  setTimeout(() => window.close(), 500);
}

// Modal backdrop & ESC handling
['settings-modal', 'edit-match-modal', 'confirm-modal'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('click', e => {
    if (e.target === el) {
      if (id === 'confirm-modal') closeConfirm(false);
      else el.style.display = 'none';
    }
  });
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeConfirm(false);
    closeEditMatch();
    closeSettings();
  }
});
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    pollLiveOnce();
    scheduleLivePoll();
  }
});

// Boot
loadActiveSession();
pollLiveOnce();
scheduleLivePoll();
silentUpdateCheck();
(async () => {
  try {
    const c = await api('/api/config');
    if (!c.name) setTimeout(() => { openSettings('profile'); showToast('Welcome! Enter your Rocket League nickname.'); }, 900);
  } catch (e) {}
})();
