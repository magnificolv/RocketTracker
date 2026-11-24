/* RL Tracker v4.0 Overdrive — Zero-dependency SVG & Telemetry Chart Renderers */

function escChart(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderWinrateTrendChart(container, timeline) {
  if (!container) return;
  if (!timeline || timeline.length < 2) {
    container.innerHTML = '<p class="hint-text" style="padding:18px;text-align:center">Play at least 2 matches to plot your rolling winrate trend.</p>';
    return;
  }

  const W = 640, H = 200, padL = 36, padR = 16, padT = 16, padB = 26;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const n = timeline.length;

  const pts = timeline.map((m, i) => {
    const x = padL + (i / Math.max(n - 1, 1)) * plotW;
    const wr = Math.max(0, Math.min(100, Number(m.rolling_wr || 0)));
    const y = padT + plotH - (wr / 100) * plotH;
    return { x, y, wr, m };
  });

  const polyLine = pts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const areaPath = `M ${pts[0].x.toFixed(1)},${(padT + plotH).toFixed(1)} ` +
    pts.map(p => `L ${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') +
    ` L ${pts[pts.length - 1].x.toFixed(1)},${(padT + plotH).toFixed(1)} Z`;

  const gridLines = [25, 50, 75].map(pct => {
    const gy = padT + plotH - (pct / 100) * plotH;
    return `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" stroke="rgba(148,163,184,0.14)" stroke-dasharray="4 4"/>
            <text x="${padL - 6}" y="${gy + 3}" text-anchor="end" fill="#8b9bb4" font-size="10">${pct}%</text>`;
  }).join('');

  const dots = pts.map((p, i) => {
    const col = p.m.result === 'win' ? '#22c55e' : (p.m.result === 'loss' ? '#ef4444' : '#94a3b8');
    const title = `${p.m.result.toUpperCase()} ${p.m.user_score}-${p.m.opponent_score} · ${p.m.playlist} · Rolling WR ${p.wr}%`;
    return `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4.5" fill="${col}" stroke="#060913" stroke-width="1.5" data-idx="${i}">
              <title>${escChart(title)}</title>
            </circle>`;
  }).join('');

  container.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">
      <defs>
        <linearGradient id="wrAreaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.32"/>
          <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      ${gridLines}
      <path d="${areaPath}" fill="url(#wrAreaGrad)"/>
      <polyline points="${polyLine}" fill="none" stroke="#38bdf8" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
      ${dots}
      <text x="${padL}" y="${H - 6}" fill="#8b9bb4" font-size="10">Oldest (${n}g)</text>
      <text x="${W - padR}" y="${H - 6}" text-anchor="end" fill="#8b9bb4" font-size="10">Latest (${pts[n - 1].wr}%)</text>
    </svg>`;
}

function renderMovementStrip(container, agg) {
  if (!container || !agg) return;
  const g = Number(agg.avg_ground_time || 0);
  const a = Number(agg.avg_air_time || 0);
  const w = Number(agg.avg_wall_time || 0);
  const tot = g + a + w;
  const gp = tot > 0 ? (g / tot * 100) : 34;
  const ap = tot > 0 ? (a / tot * 100) : 33;
  const wp = tot > 0 ? (w / tot * 100) : 33;

  const sup = Number(agg.avg_supersonic_time || 0);
  const bst = Number(agg.avg_boost_time || 0);
  const pwr = Number(agg.avg_powerslide_time || 0);

  container.innerHTML = `
    <div style="font-size:.78rem;color:var(--soft);margin-bottom:4px">Surface Split (Ground / Air / Wall)</div>
    <div class="seg-bar">
      <div class="seg-ground" style="width:${gp.toFixed(1)}%" title="Ground ${g.toFixed(1)}%"></div>
      <div class="seg-air" style="width:${ap.toFixed(1)}%" title="Air ${a.toFixed(1)}%"></div>
      <div class="seg-wall" style="width:${wp.toFixed(1)}%" title="Wall ${w.toFixed(1)}%"></div>
    </div>
    <div class="seg-legend">
      <span><span class="seg-dot" style="background:var(--blue)"></span>Ground <b>${g.toFixed(1)}%</b></span>
      <span><span class="seg-dot" style="background:var(--cyan)"></span>Air <b>${a.toFixed(1)}%</b></span>
      <span><span class="seg-dot" style="background:var(--orange)"></span>Wall <b>${w.toFixed(1)}%</b></span>
    </div>
    <div style="margin-top:16px;display:grid;gap:10px">
      <div class="hbar-row" style="margin:0">
        <div class="hbar-head"><span>Supersonic Time</span><b>${sup.toFixed(1)}%</b></div>
        <div class="hbar-track"><div class="hbar-fill" style="width:${Math.min(sup * 2.5, 100)}%;background:linear-gradient(90deg,var(--orange),var(--gold))"></div></div>
      </div>
      <div class="hbar-row" style="margin:0">
        <div class="hbar-head"><span>Active Boosting</span><b>${bst.toFixed(1)}%</b></div>
        <div class="hbar-track"><div class="hbar-fill" style="width:${Math.min(bst * 2.5, 100)}%"></div></div>
      </div>
      <div class="hbar-row" style="margin:0">
        <div class="hbar-head"><span>Powerslide Usage</span><b>${pwr.toFixed(1)}%</b></div>
        <div class="hbar-track"><div class="hbar-fill" style="width:${Math.min(pwr * 8, 100)}%;background:linear-gradient(90deg,var(--violet),var(--cyan))"></div></div>
      </div>
    </div>`;
}

function renderCoachRadar(container, radar) {
  if (!container || !radar || !radar.labels) return;
  const labels = radar.labels;
  const sess = radar.session || [0, 0, 0, 0, 0];
  const base = radar.baseline || [0, 0, 0, 0, 0];
  const size = 320, cx = 160, cy = 164, R = 96;
  const count = labels.length;

  const pt = (idx, val) => {
    const ang = -Math.PI / 2 + (idx * 2 * Math.PI) / count;
    const r = (Math.max(0, Math.min(100, val)) / 100) * R;
    return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
  };

  const rings = [25, 50, 75, 100].map(lv => {
    const poly = labels.map((_, i) => pt(i, lv).map(v => v.toFixed(1)).join(',')).join(' ');
    return `<polygon points="${poly}" fill="none" stroke="rgba(148,163,184,0.18)" stroke-width="1"/>`;
  }).join('');

  const spokes = labels.map((_, i) => {
    const [x, y] = pt(i, 100);
    return `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(148,163,184,0.18)" stroke-width="1"/>`;
  }).join('');

  const basePoly = base.map((v, i) => pt(i, v).map(c => c.toFixed(1)).join(',')).join(' ');
  const sessPoly = sess.map((v, i) => pt(i, v).map(c => c.toFixed(1)).join(',')).join(' ');

  const labelEls = labels.map((lab, i) => {
    const [lx, ly] = pt(i, 128);
    const anchor = Math.abs(lx - cx) < 12 ? 'middle' : (lx > cx ? 'start' : 'end');
    return `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="${anchor}" fill="#cbd5e1" font-size="11" font-weight="700">${escChart(lab)} ${Math.round(sess[i] || 0)}</text>`;
  }).join('');

  const sessDots = sess.map((v, i) => {
    const [dx, dy] = pt(i, v);
    return `<circle cx="${dx.toFixed(1)}" cy="${dy.toFixed(1)}" r="4" fill="#22d3ee" stroke="#060913" stroke-width="1.5"/>`;
  }).join('');

  container.innerHTML = `
    <svg viewBox="0 0 ${size} ${size}" style="width:100%;max-width:320px;margin:0 auto;display:block">
      ${rings}
      ${spokes}
      <polygon points="${basePoly}" fill="rgba(167,139,250,0.12)" stroke="#a78bfa" stroke-width="1.5" stroke-dasharray="4 3"/>
      <polygon points="${sessPoly}" fill="rgba(34,211,238,0.22)" stroke="#22d3ee" stroke-width="2.2"/>
      ${sessDots}
      ${labelEls}
    </svg>
    <div style="display:flex;justify-content:center;gap:14px;font-size:.72rem;color:var(--muted);margin-top:4px">
      <span><span class="seg-dot" style="background:var(--cyan)"></span>Session</span>
      <span><span class="seg-dot" style="background:var(--violet)"></span>20-Game Baseline</span>
    </div>`;
}

function renderHorizontalBars(container, items, nameKey, emptyMsg) {
  if (!container) return;
  if (!items || !items.length) {
    container.innerHTML = `<p class="hint-text" style="padding:12px;text-align:center">${escChart(emptyMsg || 'No data yet')}</p>`;
    return;
  }
  container.innerHTML = items.map(it => {
    const wr = Number(it.winrate || 0);
    const col = wr >= 55 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : wr >= 45 ? 'linear-gradient(90deg,#38bdf8,#22d3ee)' : 'linear-gradient(90deg,#fb923c,#ef4444)';
    return `<div class="hbar-row">
      <div class="hbar-head">
        <span>${escChart(it[nameKey] || 'Unknown')} <span style="color:var(--muted);font-size:.72rem">(${it.wins || 0}W-${it.losses || 0}L)</span></span>
        <b>${wr.toFixed(1)}%</b>
      </div>
      <div class="hbar-track"><div class="hbar-fill" style="width:${Math.min(wr, 100)}%;background:${col}"></div></div>
    </div>`;
  }).join('');
}

function renderGoalTimeline(goals) {
  if (!goals || !goals.length) {
    return '<p class="hint-text" style="margin-bottom:10px">No goal events logged for this match.</p>';
  }
  return `<div class="goal-timeline">${goals.map(g => {
    const t = g.team_num === 0 ? 't0' : 't1';
    const rem = g.time_remaining_sec != null ? Number(g.time_remaining_sec) : null;
    const clockStr = g.is_overtime ? 'OT' : (rem != null ? `${Math.floor(rem / 60)}:${String(rem % 60).padStart(2, '0')}` : '');
    const spd = g.speed_kph ? ` · ${Number(g.speed_kph).toFixed(0)} km/h` : '';
    const ast = g.assister ? ` (ast ${escChart(g.assister)})` : '';
    return `<div class="goal-chip ${t}">
      <b>${escChart(g.scorer)}</b>${ast}
      <span style="color:var(--muted)">${clockStr}${spd}</span>
    </div>`;
  }).join('')}</div>`;
}
