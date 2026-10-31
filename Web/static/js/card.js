/* Atlas — the ivory card: the panel a marker opens — its portrait,
   its vitals, the service detail it drills into, and the minimise / expand /
   pull-back chrome. Lifted out of ui.js whole: the block
   referenced none of ui.js's other locals and everything outside reaches it
   through `A`, so nothing else moved. Registered in atlas.js right after ui.js. */

import { A, CFG, $, esc, host, glassAttrs, zoneById } from './config.js';
import { calendarPointerHTML } from './calendar.js';

const card = $('card');

/* One vital as parchment ink: label, the number now, and a week of history as
   an inline SVG sparkline. SVG over canvas so the strokes stay crisp at any
   zoom and the colours come from the stylesheet (`.cv-spark-line` etc.), not
   from values baked here — the theme owns its ink. Values clamp to 0–100:
   these are percentages, and one bad sample must not rescale the week. */
function sparkHTML(label, series, nowVal) {
  const pts = (series || []).filter((p) => Number.isFinite(p?.[1]));
  let svg = '';
  if (pts.length > 1) {
    const w = 160, h = 40;
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
    const xs = (t) => ((t - t0) / Math.max(1, t1 - t0)) * w;
    const ys = (v) => h - (Math.min(100, Math.max(0, v)) / 100) * h;
    const line = pts.map((p) => `${xs(p[0]).toFixed(1)},${ys(p[1]).toFixed(1)}`).join(' ');
    svg = `<svg class="cv-spark-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">` +
      `<polygon class="cv-spark-fill" points="0,${h} ${line} ${w},${h}"></polygon>` +
      `<polyline class="cv-spark-line" points="${line}"></polyline></svg>`;
  }
  const num = Number.isFinite(nowVal) ? `${Math.round(nowVal)}<em>%</em>` : '—';
  return `<div class="cv-spark" title="${esc(label)} over the last week">` +
    `<span class="cv-spark-label">${esc(label)}</span>` +
    `<span class="cv-spark-now">${num}</span>${svg}</div>`;
}

/* ── The ivory card ─────────────────────────────────── */
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // insecure-context fallback (plain http over the LAN)
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } finally { ta.remove(); }
  }
  A.showToast('The scroll’s path is copied to your clipboard.');
}

/* per-place emblem for the card portrait — the real product logo where a place
   IS a product (its OS / appliance / service), else a themed emoji, else kind. */
/* -> static/icons/<slug>.svg. A place names its own emblem with `logo` in the
   dataset; failing that the THEME's map (v1.48.0: `node_logos`, keyed by node
   id — which ids exist is one lab's business, not the app's). */
const LOGO_SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/;
const nodeLogo = (n) => {
  const own = String(n.logo || '');
  if (LOGO_SLUG.test(own)) return own;
  return CFG.THEME.nodeLogos?.[n.id] || '';
};

function setPortrait(n) {
  const slug = nodeLogo(n) || 'waypoints';   // waypoints = generic fallback
  $('card-portrait').innerHTML = `<img class="portrait-logo" src="static/icons/${slug}.svg" alt="">`;
}

A.openCard = function openCard(n) {
  setCardMinimized(false);   // a fresh selection always opens expanded
  const zone = zoneById(n.zone);
  const hue = zone ? zone.hue : '#C9A554';
  card.style.setProperty('--card-hue', hue);
  setPortrait(n);
  $('card-epi').textContent = zone
    ? `${zone.name} · ${n.role.split('·')[0].trim().toLowerCase()}`
    : n.role;
  $('card-name').textContent = n.name;
  $('card-lore').textContent = n.lore;

  const rows = [];
  if (n.ip && n.ip !== '—') rows.push(`<span>${esc(n.ip)}</span>`);
  if (n.hw) rows.push(`<span>${esc(n.hw)}</span>`);
  // K5 — "faith of the realm": 30-day uptime, only when the watchers are reporting
  const uptime = A.nodeUptime?.(n.id);
  if (uptime) rows.push(`<span class="card-uptime" title="30-day availability">${esc(uptime)}</span>`);
  // the patch survey (weekly, via Prometheus) — absent when the watchers can't see it
  const pi = A.signalsFeed?.nodes?.[n.id];
  if (pi && pi.patches_pending != null) {
    const age = pi.patch_surveyed ? (Date.now() / 1000 - pi.patch_surveyed) / 86400 : null;
    const stale = age != null && age > 8;
    const bits = [`${pi.patches_pending} updates await`];
    if (pi.patches_security > 0) bits.push(`${pi.patches_security} of them security`);
    if (pi.reboot_required > 0) bits.push('asks for a rebirth');
    rows.push(`<span class="card-patches${pi.patches_security > 0 || pi.reboot_required > 0 ? ' warn' : ''}${stale ? ' stale' : ''}"` +
      ` title="weekly patch survey${age != null ? ` · surveyed ${Math.round(age)}d ago` : ''}">${esc(bits.join(' · '))}${stale ? ' · survey is stale' : ''}</span>`);
  }
  // If this place is dark because something it depends on is dark, say so —
  // "it is down" is true but useless; "it is behind the hypervisor" is the
  // thing you act on (see Web/dependencies.py).
  const info = A.signalsFeed?.nodes?.[n.id];
  if (info?.cause) {
    const causeNode = A.DATA.nodes.find((x) => x.id === info.cause);
    const viaNode = info.via && info.via !== info.cause
      ? A.DATA.nodes.find((x) => x.id === info.via) : null;
    rows.push(`<span class="card-caused">${info.planned ? 'closed for work' : 'unreachable'} ` +
      `behind <strong>${esc(causeNode ? causeNode.name : info.cause)}</strong>` +
      (viaNode ? ` (via ${esc(viaNode.name)})` : '') + '</span>');
  }
  $('card-data').innerHTML = rows.join('');

  /* THE FORGE'S DAY (v1.40.0 → a scene in v1.42.0 → part of THE CALENDAR in
     v1.45.0): a place other rites ask for its model — the GPU box — says on its card
     what turns next and offers the door to THE CALENDAR, where the whole
     realm's day is drawn and this forge's lanes lead it. Hidden for every
     place nobody asks, so the card of a NAS is exactly the card it was. Intent
     only (the dataset's clocks), never the beats — the scene's own rows say
     whether each rite actually turned. */
  const forge = $('card-forge');
  if (forge) {
    const pointer = calendarPointerHTML(n, A.DATA.rites || []);
    forge.innerHTML = pointer;
    forge.hidden = !pointer;
    $('btn-card-forge')?.addEventListener('click', () => {
      A.closeAllScenes?.(); A.setSceneActive?.('calendar'); A.openCalendar?.();
    });
  }

  // service buttons — clicking one flips the card to a service-detail sub-view
  // (its parent host + live status + an open-in-new-tab button), never a raw jump
  const links = n.links || [];
  // leading bullet = live health (green up / red down / neutral when unwatched) —
  // one meaningful signal, not a different colour per service
  // vassals first: nodes that name this place as parent (the hypervisor's VMs, per
  // the NetBox virtualization model) — clicking one flies to it (2026-07-11)
  const vassals = A.DATA.nodes.filter(x => x.parent === n.id);
  const vassalHTML = vassals.length
    ? `<div class="card-vassals-head">its vassals</div>` +
      vassals.map(v =>
        `<button class="card-link card-vassal" data-go="${esc(v.id)}">` +
        `<span class="svc-health" data-node="${esc(v.id)}"></span>${esc(v.name)} ›</button>`
      ).join('')
    : '';
  // ⁘ THE CONSTELLATION — scatter this place's services onto the map as their
  // own dots so each one's roads can be read separately. One marker for a host
  // that runs seventeen things hides seventeen different network paths behind
  // one point; this is the button that opens it up (2026-07-31).
  // both labels are rendered; body.constellation in CSS decides which shows,
  // so neither this card nor world.js ever has to redraw the button to flip it.
  // Existence = own links + pass-throughs (A.serviceEntriesFor — the same list
  // the split rings), so a pure transit place like PANGOLIN still offers ⁘.
  const entries = A.serviceEntriesFor?.(n.id) || [];
  const splitHTML = entries.length
    ? `<button class="card-split" id="btn-card-split" title="Draw each service as its own dot, with the routes it uses">` +
      `<span class="cs-glyph" aria-hidden="true">⁘</span>` +
      `<span class="cs-off">SPLIT INTO ITS SERVICES</span>` +
      `<span class="cs-on">GATHER ITS SERVICES</span>` +
      `</button>`
    : '';
  // what crosses here — a road is known by its traffic. A transit place
  // (PANGOLIN, TAILSCALE, CLOUDFLARE) keeps no stall of its own, so its menu
  // was blank while the ⁘ split had plenty to scatter: the same pass-throughs
  // this reads (services whose `connects` names this place). One list for both,
  // so the card and the constellation can never disagree (world.js
  // serviceEntriesFor). Each row names its true host — the thing lives there,
  // it only *passes* through here (2026-08-03).
  const crossing = entries.filter((en) => en.passing);
  const crossHTML = crossing.length
    ? `<div class="card-vassals-head">what crosses here</div>` +
      crossing.map((en, i) =>
        `<button class="card-link card-cross" data-cross="${i}">` +
        `<span class="svc-health"${en.link.kuma ? ` data-kuma="${esc(en.link.kuma)}"` : ''}></span>` +
        `<span class="cross-label">${esc(en.link.label.toUpperCase())}</span>` +
        `<span class="cross-from">${esc(en.host.name)}</span> ›` +
        `</button>`
      ).join('')
    : '';
  $('card-links').innerHTML = vassalHTML + splitHTML + links.map((l, i) =>
    `<button class="card-link" data-svc="${i}">` +
    `<span class="svc-health"${l.kuma ? ` data-kuma="${esc(l.kuma)}"` : ''}></span>${esc(l.label.toUpperCase())} ›` +
    `</button>`
  ).join('') + crossHTML;
  $('card-links').querySelector('#btn-card-split')?.addEventListener('click', (e) => {
    e.stopPropagation();
    A.toggleConstellation?.(n.id);
  });
  for (const btn of $('card-links').querySelectorAll('.card-vassal')) {
    btn.addEventListener('click', (e) => { e.stopPropagation(); A.focusNode(btn.dataset.go); });
  }
  // vassal dots take the HOST feed (data-node), not the service feed
  const nodeFeed = A.signalsFeed?.nodes || {};
  for (const dot of $('card-links').querySelectorAll('.svc-health[data-node]')) {
    const st = nodeFeed[dot.dataset.node]?.state;
    if (st) dot.classList.add(A.svcHealthClass[st] || '');
  }
  for (const btn of $('card-links').querySelectorAll('.card-link[data-svc]')) {
    btn.addEventListener('click', (e) => { e.stopPropagation(); showServiceDetail(n, links[Number(btn.dataset.svc)]); });
  }
  // a pass-through flips to the service on its OWN host, not on this crossing —
  // the detail pane's "a service of X" has to name where the thing actually is
  for (const btn of $('card-links').querySelectorAll('.card-cross')) {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const en = crossing[Number(btn.dataset.cross)];
      if (en) showServiceDetail(en.host, en.link);
    });
  }
  A.paintServiceHealth?.(card);   // K4 — colour the new dots from the current feed

  // live vitals — the card draws its OWN pulse (v1.34.0). This used to be two
  // Grafana `/d-solo/` iframes, each booting the entire Grafana SPA to draw
  // one gauge — megabytes for two numbers, and the map's most-touched surface
  // depended on Grafana being warm (the 2026-08-30 cold-start evening made
  // that cost visible). Now the server asks Prometheus itself
  // (`/api/v2/vitals`, ATLAS_PROM_URL) and the card paints sparklines; the
  // Chronicle keeps Grafana for the rich dashboards, where the weight is
  // earned. No pulse (endpoint absent, host unknown to Prometheus, scribe
  // down) is a quiet absence — the section simply doesn't draw, never a fake
  // calm and never an error state.
  const vitals = $('card-vitals');
  vitals.innerHTML = ''; vitals.hidden = true;
  if (n.spark) {
    vitals.dataset.node = n.id;   // a slow answer must never paint a different card
    fetch(`api/v2/vitals/${encodeURIComponent(n.id)}`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((v) => {
        if (!v || vitals.dataset.node !== n.id) return;
        if (v.now?.cpu == null && v.now?.ram == null) return;
        vitals.innerHTML =
          `<div class="cv-head">the pulse of this place · a week</div>` +
          `<div class="cv-row">${sparkHTML('CPU', v.cpu, v.now?.cpu)}` +
          `${sparkHTML('RAM', v.ram, v.now?.ram)}</div>`;
        vitals.hidden = false;
      })
      .catch(() => {});
  }

  // the scroll: browsers won't follow file:// from http, so clicking copies the path
  const scrollEl = $('card-scroll');
  if (n.scroll) {
    // trim the display (drop the configured vault root + the .md) — the copy
    // keeps the full path. The root is a deployment value (ATLAS_SCROLL_ROOT),
    // not a constant: it used to be one particular person's drive letter.
    const root = CFG.SCROLL_ROOT.toLowerCase();
    const lower = n.scroll.toLowerCase();
    const shown = (root && lower.startsWith(root) ? n.scroll.slice(root.length) : n.scroll)
      .replace(/\.md$/i, '');
    scrollEl.innerHTML = `<button class="scroll-row" title="Copy the scroll's path">` +
      `<span class="scroll-glyph">📜</span><span class="scroll-path">${esc(shown)}</span></button>`;
    scrollEl.querySelector('.scroll-row').addEventListener('click', () => copyText(n.scroll));
    scrollEl.style.display = '';
  } else {
    scrollEl.innerHTML = '';
    scrollEl.style.display = 'none';
  }

  $('card-svc').hidden = true;   // always land on the node view
  card.classList.remove('svc-open');
  card.classList.add('visible');
  card.setAttribute('aria-hidden', 'false');
};

/* the state of a whole host, read from the live feed (for the "parent" line) */
const HEALTH_LABEL = { healthy: 'answering', degraded: 'faltering', down: 'gone dark', maintenance: 'under repair', slumbering: 'slumbering' };

/** flip the card to a single service's detail — its parent host, live status,
    and the outward jump. Back returns to the host. (When THE CONSTELLATION is
    open, highlightService finds the service's own scattered dot itself — the
    card never carries map geometry.) */
function showServiceDetail(node, link) {
  if (!link) return;
  const svc = $('card-svc');
  const svcState = A.signalsFeed?.services?.[link.kuma]?.state;
  const hostState = A.signalsFeed?.nodes?.[node.id]?.state;
  const st = svcState || hostState;
  const badge = st
    ? `<span class="svc-health ${A.svcHealthClass[st] || ''}" style="margin:0"></span>` +
      `<span class="csv-state-t">${esc(HEALTH_LABEL[st] || st)}</span>`
    : `<span class="csv-state-t dim">status unknown</span>`;
  const roleShort = (node.role || '').split('·')[0].trim();
  const zone = zoneById(node.zone);
  const where = node.ip && node.ip !== '—' ? node.ip : (node.hw || 'the map');
  /* What this service actually IS, when the dataset says so.
     The generated sentence below it — "Hosted on the app host, answering at
     198.51.100.21" — restates the epigraph two lines up and the mono host line at
     the foot of the pane, so a service that carries its own `desc` spends the
     paragraph on the one thing nothing else on screen can tell you. A service
     with no description keeps the old sentence rather than an empty pane:
     charting a new link should never require prose before it reads sensibly. */
  const desc = (link.desc || '').trim();
  svc.innerHTML =
    `<button class="csv-back" id="csv-back" title="Back to ${esc(node.name)}">‹ ${esc(node.name)}</button>` +
    `<div class="csv-epi">a service of ${esc(node.name)}${zone ? ' · ' + esc(zone.name) : ''}</div>` +
    `<h3 class="csv-name"><span class="ldot" style="background:${esc(link.hue)}"></span>${esc(link.label)}</h3>` +
    `<div class="csv-state">${badge}</div>` +
    `<p class="csv-desc">${desc
      ? esc(desc)
      : `Hosted on <strong>${esc(node.name)}</strong>${roleShort ? ` — ${esc(roleShort)}` : ''}, ` +
        `answering at ${esc(where)}. Follow the routes to its live metrics, or open it directly.`}</p>` +
    // ONE row of actions (2026-08-15): OPEN IT HERE with PATH and ROAD
    // beside it. They were four stacked buttons — VIEW ITS METRICS, VIEW IN
    // THE PATH, FOLLOW ITS ROAD — which made every service pane a third taller
    // than its content. The metrics button went entirely (the Chronicle is one
    // ☁ away and carries the same graphs); the other two kept their glyph and
    // lost their verbs, because next to OPEN IT HERE the ◈ already says "show
    // me" and the one word says where.
    `<div class="csv-actions">` +
      `<a class="csv-open" href="${esc(link.url)}" target="_blank" rel="noopener"` +
        `${glassAttrs(link.label, `a service of ${node.name}`, link.open_in)}>OPEN IT HERE ›</a>` +
      `<button class="csv-metrics" id="csv-path" title="Show it in TOPOLOGY — the tier diagram">◈ TOPOLOGY</button>` +
      // the map-side twin of PATH: the same road, drawn where you already are
      // instead of in the tier diagram (2026-08-11)
      `<button class="csv-metrics" id="csv-road" title="Follow its route on the map">◈ ROUTE</button>` +
    `</div>` +
    `<div class="csv-url">${esc(host(link.url))}</div>`;
  svc.querySelector('#csv-back').addEventListener('click', (e) => {
    e.stopPropagation();
    svc.hidden = true;
    card.classList.remove('svc-open');   // the node view takes its room back
  });
  svc.querySelector('#csv-path').addEventListener('click', (e) => {
    e.stopPropagation();
    A.closeCard?.();
    A.setSceneActive?.('path');
    // THE PATH, with this service's host haloed and its reach web lit
    // the road out wins over the unordered set, same precedence highlightService
    // uses — the two views must not disagree about what this service touches
    A.openPath?.(node.id, link.path || link.connects || node.reaches || [], link.label);
  });
  svc.querySelector('#csv-road').addEventListener('click', (e) => {
    e.stopPropagation();
    A.highlightService?.(node, link);   // draw it, now that it was asked for
  });
  svc.style.setProperty('--card-hue', link.hue || 'var(--gilt)');
  svc.hidden = false;
  /* the pane is a FLOW child now (atlas.css): this class folds the node view
     away so the card resizes to the SERVICE's content — the pane no longer
     inherits the host card's height and its blank space (2026-08-16) */
  card.classList.add('svc-open');
  /* Nothing is drawn here any more (2026-08-11: "move away from that
     being the default"). Opening a service used to narrow the web to it
     automatically, which made picking a service out of a ring the fourth way a
     single click put lines on the map unasked — after the network layer
     (v1.10.11), the host's own reach (v1.10.13) and the ring's service
     `connects` (v1.10.14).

     The road is still one gesture away, by either of the two routes that mean
     "show me this one": the ◈ FOLLOW ITS ROAD button above, or clicking a drawn
     road directly, which `focusService` handles because a click on a LINE is
     already an explicit request for that line. What is gone is the road you did
     not ask for. */
}
/* the constellation's dots flip the card the same way its buttons do */
A.showServiceDetail = showServiceDetail;

/* The edge case: when the pan clamp can't grant a focused dot the share
   left of the card, the card crosses to the left edge instead. focusNode (via
   A.focusAnchor) decides; this just wears the class — and every focus glide
   states a side, so the card crosses back on the next place that doesn't
   need it. */
/* The control band lives at the top in CSS now (2026-08-11), so there is
   nothing left to measure. The ResizeObserver + inline-offset machinery that
   slid it around the card is gone: the buttons never move, which is the point
   — a control you reach for should be in the same place every time. */
/* Which edge the card lands on — and, since 2026-08-25, which edge it ENTERS
   from: `--card-in` is per-side in atlas.css, so the class carries both.

   ⚑ The reflow is load-bearing, not a tic. Both callers (world.js focusNode
   and the constellation's auto-frame) set the side and then open the card in
   the SAME synchronous block, so the browser never recomputes style in
   between: a transition starting at that moment interpolates from the last
   value it actually painted. For a hidden card that is the PREVIOUS card's
   edge — so clicking a west place after an east one would slide the card in
   from the wrong side, and only on the first frame after a flip, which is
   precisely the kind of bug that gets called "sometimes it does it backwards".
   Reading `offsetWidth` forces the recalc so the hidden card is sitting behind
   its new edge before `.visible` lands.

   Only when it is HIDDEN: flipping a card that is already up is the `right`
   transition sliding it across the screen (2026-08-01), and a forced reflow
   there would be pure cost with nothing to correct — `.visible` pins
   `transform: none` throughout. */
A.setCardSide = (left) => {
  card.classList.toggle('card-left', !!left);
  if (!card.classList.contains('visible')) void card.offsetWidth;   // see above
};

A.closeCard = function closeCard() {
  card.classList.remove('visible');
  card.setAttribute('aria-hidden', 'true');

  // kill the vitals iframes — a hidden card's Grafana panels kept refreshing
  // every 30s forever (2026-07-11 perf pass)
  const vitals = $('card-vitals');
  if (vitals) { vitals.innerHTML = ''; vitals.hidden = true; }
  for (const mk of $('markers').children) mk.classList.remove('active');
  A.clearHighlight?.();   // drops the reach web AND gathers any split — one seam
};

// Is a card on screen? The Escape chain asks, so it can recentre on close
// exactly as the × does — but only when there was actually a card (or scene)
// to leave.
A.cardOpen = () => card.classList.contains('visible');

// closing the card with the × re-centers the survey (you were glided off-center to a node)
$('btn-card-close').addEventListener('click', () => { A.closeCard(); A.recenter?.(true); });

/* minimize (–) collapses the card to just its headline; the × still closes and a
   new selection reopens expanded (openCard resets it). (2026-07-20) */
/* (`rearmVitals` and the park-on-minimize loop lived here until v1.36.0.
   They parked and re-armed the card's two Grafana vitals iframes; the vitals
   have been native SVG since v1.34.0 and Grafana itself went 2026-09-03, so
   there was nothing left for them to park.) */
function setCardMinimized(on) {
  card.classList.toggle('minimized', on);
  const b = $('btn-card-min');
  if (b) { b.textContent = on ? '▢' : '–'; b.title = on ? 'Expand' : 'Minimize'; }
}
A.setCardMinimized = setCardMinimized;
$('btn-card-min')?.addEventListener('click', (e) => {
  e.stopPropagation();
  setCardMinimized(!card.classList.contains('minimized'));
});
/* a click on the collapsed card (anywhere but the × / – / ⊖) expands it again */
card.addEventListener('click', (e) => {
  if (!card.classList.contains('minimized')) return;
  if (e.target.closest('.card-close') || e.target.closest('.card-min')
      || e.target.closest('.card-out')) return;
  setCardMinimized(false);
});

/* ⊖ — pull back WITHOUT losing the place. The zoom buttons work on the middle
   of the screen, which drifts off whatever you were reading; this one zooms out
   around the selected marker so its roads come into frame and it stays put.
   Repeatable, and it dims itself once the whole table is on screen. (2026-07-31) */
$('btn-card-out')?.addEventListener('click', (e) => {
  e.stopPropagation();
  const at = A.pullBack?.();
  if (at === 'floor') A.showToast('The whole table is already in view.');
});
