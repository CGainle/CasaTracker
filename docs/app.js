/* ============================================================
   Casa Tracker · app.js
   ============================================================ */
(function () {
  'use strict';

  // ─── Storage keys ─────────────────────────────────────────────
  const SK = {
    seen: 'ct_seen_v1',
    lastFetchEtag: 'ct_etag_v1',
    lastListings: 'ct_listings_v1',
    knownIds: 'ct_known_v1',
    filters: 'ct_filters_v1',
  };

  // ─── Default filters ──────────────────────────────────────────
  const DEFAULT_FILTERS = {
    priceMin: 175000, priceMax: 250000,
    beds: 3, baths: 2, garage: 1,
    requirePB: true, noReciclar: true, withPriceOnly: false,
  };

  // ─── State ────────────────────────────────────────────────────
  const state = {
    listings: [],
    generated_at: null,
    stats: null,
    seenIds: new Set(JSON.parse(localStorage.getItem(SK.seen) || '[]')),
    knownIds: new Set(JSON.parse(localStorage.getItem(SK.knownIds) || '[]')),
    filters: { ...DEFAULT_FILTERS, ...JSON.parse(localStorage.getItem(SK.filters) || '{}') },
    zone: 'all',
    sort: 'new',
    selectedId: null,
    tab: 'list',
  };

  // ─── DOM helpers ──────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
  const fmt = (n) => n ? `USD ${n.toLocaleString('es-AR')}` : 'Precio a consultar';

  // ─── Filtering / sorting ──────────────────────────────────────
  function passesFilters(l) {
    const f = state.filters;
    if (f.withPriceOnly && !l.price) return false;
    if (l.price) {
      if (l.price < f.priceMin || l.price > f.priceMax) return false;
    }
    if (l.beds != null && l.beds < f.beds) return false;
    if (l.baths != null && l.baths < f.baths) return false;
    if (l.garage != null && l.garage < f.garage) return false;
    if (f.requirePB && (l.pb_bed === false || l.pb_bath === false)) {
      // si tiene flag explícito false rechazamos; si es null/undefined dejamos pasar
    }
    if (f.noReciclar && /reciclar|refaccionar|demoler/i.test((l.desc||'') + ' ' + (l.title||''))) return false;
    return true;
  }

  function applyZoneAndSort(list) {
    if (state.zone === 'castelar') list = list.filter(l => l.zona === 'Castelar Norte');
    else if (state.zone === 'ituzaingo') list = list.filter(l => l.zona === 'Ituzaingó Norte');
    list.sort((a, b) => {
      const aNew = !!a.is_new, bNew = !!b.is_new;
      if (aNew !== bNew) return aNew ? -1 : 1;
      if (state.sort === 'new') return new Date(b.added || 0) - new Date(a.added || 0);
      if (state.sort === 'pasc') {
        if (!a.price && !b.price) return 0;
        if (!a.price) return 1;
        if (!b.price) return -1;
        return a.price - b.price;
      }
      if (state.sort === 'pdesc') {
        if (!a.price && !b.price) return 0;
        if (!a.price) return 1;
        if (!b.price) return -1;
        return b.price - a.price;
      }
      return 0;
    });
    return list;
  }

  // ─── Render: cards ────────────────────────────────────────────
  function cardHtml(l) {
    const zClass = l.zona === 'Castelar Norte' ? 'cast' : 'itu';
    const seen = state.seenIds.has(l.id);
    const isNew = !!l.is_new && !seen;
    const cls = ['card', zClass, isNew && 'new', seen && 'seen', state.selectedId === l.id && 'selected'].filter(Boolean).join(' ');
    const imgBg = l.image
      ? `style="background-image:url('${esc(l.image)}')"`
      : '';
    const imgEmpty = l.image ? '' : '<div class="card-img-empty">🏠</div>';
    const badges = [];
    if (isNew) badges.push('<span class="badge badge-new">✦ Nuevo</span>');
    if (seen) badges.push('<span class="badge badge-seen">Visto</span>');
    const specs = [];
    if (l.beds) specs.push(`<span>🛏 ${l.beds} dorm.</span>`);
    if (l.baths) specs.push(`<span>🚿 ${l.baths} baños</span>`);
    if (l.garage) specs.push(`<span>🚗 ${l.garage} coch.</span>`);
    if (l.sup_cub) specs.push(`<span>📐 ${l.sup_cub}m²</span>`);
    const pills = [];
    if (l.pb_bed) pills.push('<span class="pill green">Dorm. PB</span>');
    if (l.pb_bath) pills.push('<span class="pill green">Baño PB</span>');
    if (l.state) pills.push(`<span class="pill ${l.state==='Excelente'?'green':l.state==='Muy Bueno'?'orange':''}">${esc(l.state)}</span>`);
    if (l.sup_total) pills.push(`<span class="pill">Lote ${l.sup_total}m²</span>`);

    return `
    <article class="${cls}" data-id="${esc(l.id)}">
      <div class="card-img" ${imgBg}>
        ${imgEmpty}
        <div class="card-badges">${badges.join('')}</div>
      </div>
      <div class="card-body">
        <span class="card-zone ${zClass}">📍 ${esc(l.zona)}</span>
        <h3 class="card-title">${esc(l.title || 'Casa en venta')}</h3>
        ${l.address ? `<p class="card-addr">${esc(l.address)}</p>` : ''}
        <p class="card-price ${l.price ? zClass : 'consult'}">${fmt(l.price)}</p>
        <div class="card-specs">${specs.join('')}</div>
        ${pills.length ? `<div class="card-pills">${pills.join('')}</div>` : ''}
        <div class="card-foot">
          <span class="card-portal">${esc(l.portal)} · ${esc(l.added || '')}</span>
          <a class="card-link ${zClass}" href="${esc(l.url)}" target="_blank" rel="noopener" data-noselect>Ver aviso ↗</a>
        </div>
      </div>
    </article>`;
  }

  function render() {
    // Filtros base + zona + sort
    let list = state.listings.filter(passesFilters);
    const visible = applyZoneAndSort(list);

    const castCount = list.filter(l => l.zona === 'Castelar Norte').length;
    const ituCount = list.filter(l => l.zona === 'Ituzaingó Norte').length;
    const newCount = list.filter(l => l.is_new && !state.seenIds.has(l.id)).length;

    // Header badge
    const badge = $('#new-badge');
    if (newCount > 0) {
      badge.hidden = false;
      $('#new-count').textContent = newCount;
    } else {
      badge.hidden = true;
    }

    // Stats
    $('#n-all').textContent = list.length;
    $('#n-cast').textContent = castCount;
    $('#n-itu').textContent = ituCount;
    $('#s-cast').textContent = castCount;
    $('#s-itu').textContent = ituCount;
    $('#s-new').textContent = newCount;

    // Cards
    const cards = $('#cards');
    cards.innerHTML = visible.map(cardHtml).join('');
    $('#empty').hidden = visible.length > 0;

    // Filter summary line
    const fs = state.filters;
    $('#filter-summary').textContent = `USD ${(fs.priceMin/1000)}k–${(fs.priceMax/1000)}k · ${fs.beds}+ dorm · ${fs.baths}+ baños`;

    renderMap(visible);
  }

  // ─── Map ──────────────────────────────────────────────────────
  let map = null, markers = [];
  function initMap() {
    if (map) return;
    if (typeof L === 'undefined') {
      console.warn('Leaflet no cargó');
      return;
    }
    const el = document.getElementById('map');
    if (!el) return;
    try {
      map = L.map(el, { zoomControl: false }).setView([-34.6470, -58.6610], 14);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OSM', maxZoom: 19,
      }).addTo(map);
      L.control.zoom({ position: 'bottomright' }).addTo(map);
      // Forzar resize después de mostrar
      setTimeout(() => map.invalidateSize(), 250);
    } catch (e) {
      console.error('Error iniciando mapa:', e);
    }
  }
  function renderMap(list) {
    if (!map) {
      initMap();
      if (!map) return;
    }
    try { map.invalidateSize(); } catch(_) {}
    markers.forEach(m => m.remove());
    markers = [];
    list.forEach(l => {
      if (!l.lat || !l.lng) return;
      const isNew = l.is_new && !state.seenIds.has(l.id);
      const color = isNew ? '#dc2626' : (l.zona === 'Castelar Norte' ? '#2563eb' : '#7c3aed');
      const icon = L.divIcon({
        className: '',
        iconSize: [30, 30], iconAnchor: [15, 30],
        html: `<div class="pin ${isNew?'new':''}" style="background:${color}"><span>$</span></div>`,
      });
      const popup = `
        <div style="width:230px">
          <b style="font-size:12px">${esc(l.title || 'Casa en venta')}</b><br>
          <span style="font-size:10px;color:#666">${esc(l.address || '')}</span><br>
          <span style="font-size:14px;font-weight:800;color:${color}">${fmt(l.price)}</span><br>
          <span style="font-size:10px;color:#555">🛏 ${l.beds||'-'} · 🚿 ${l.baths||'-'} · 🚗 ${l.garage||'-'}</span><br>
          <a href="${esc(l.url)}" target="_blank" style="display:block;margin-top:5px;background:${color};color:#fff;text-align:center;padding:4px;border-radius:5px;font-size:11px;font-weight:700;text-decoration:none">Ver aviso ↗</a>
        </div>`;
      const m = L.marker([l.lat, l.lng], { icon }).addTo(map).bindPopup(popup);
      m.on('click', () => {
        state.selectedId = l.id;
        markSeen(l.id);
        render();
      });
      markers.push(m);
    });
    // Si hay markers, ajustar zoom para encuadrar todos
    if (markers.length > 1) {
      try {
        const group = L.featureGroup(markers);
        map.fitBounds(group.getBounds().pad(0.15));
      } catch(_) {}
    }
  }

  // ─── Mark seen ────────────────────────────────────────────────
  function markSeen(id) {
    state.seenIds.add(id);
    localStorage.setItem(SK.seen, JSON.stringify([...state.seenIds]));
  }

  // ─── Fetch listings.json ──────────────────────────────────────
  async function fetchListings(force = false) {
    setStatus('loading', 'Buscando avisos…');
    const reloadBtn = $('#reload-btn');
    const icon = reloadBtn.querySelector('.reload-icon');
    icon.classList.add('spinning');
    reloadBtn.disabled = true;
    try {
      const url = './listings.json?ts=' + Date.now();  // bust cache
      const r = await fetch(url);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      state.listings = data.listings || [];
      state.generated_at = data.generated_at;
      state.stats = data.stats;
      $('#last-upd').textContent = (data.date || '—');

      // Persist for offline
      localStorage.setItem(SK.lastListings, JSON.stringify(data));

      // Compute new (vs known)
      const fresh = state.listings.filter(l => !state.knownIds.has(l.id)).length;
      // Update known set
      state.knownIds = new Set(state.listings.map(l => l.id));
      localStorage.setItem(SK.knownIds, JSON.stringify([...state.knownIds]));

      setStatus('done', `✅ ${state.listings.length} propiedades · ${fresh} ${fresh === 1 ? 'nueva' : 'nuevas'} desde tu última visita`);
      setTimeout(() => $('#status-bar').hidden = true, 3500);
    } catch (e) {
      console.error(e);
      // Try cached
      const cached = localStorage.getItem(SK.lastListings);
      if (cached) {
        try {
          const d = JSON.parse(cached);
          state.listings = d.listings || [];
          state.generated_at = d.generated_at;
          $('#last-upd').textContent = (d.date || '—');
          setStatus('error', `⚠ Sin conexión. Mostrando última versión guardada.`);
        } catch (_) {
          setStatus('error', `⚠ Error al cargar avisos. Verificá tu conexión.`);
        }
      } else {
        setStatus('error', `⚠ No se pudieron cargar avisos. ${e.message}`);
      }
    } finally {
      icon.classList.remove('spinning');
      reloadBtn.disabled = false;
      render();
    }
  }

  function setStatus(kind, msg) {
    const bar = $('#status-bar');
    bar.hidden = false;
    bar.className = 'status-bar ' + kind;
    bar.innerHTML = (kind === 'loading' ? '<span class="blink">⏳</span> ' : '') + msg;
  }

  // ─── Countdown to midnight ────────────────────────────────────
  function tickCountdown() {
    const now = new Date();
    const mn = new Date(now);
    mn.setDate(mn.getDate() + 1);
    mn.setHours(0, 0, 0, 0);
    const diff = mn - now;
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    $('#countdown').textContent = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    // Si llegamos a 00:00:00, refrescamos
    if (h === 0 && m === 0 && s === 0) {
      setTimeout(() => fetchListings(true), 2000);
    }
  }

  // ─── Event wiring ─────────────────────────────────────────────
  function bindEvents() {
    // Tabs mobile
    $$('.tab').forEach(t => {
      t.addEventListener('click', () => {
        $$('.tab').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        state.tab = t.dataset.tab;
        $$('.panel').forEach(p => p.classList.remove('active'));
        $('#panel-' + state.tab).classList.add('active');
        // resize map cuando se muestra
        if (state.tab === 'map' && map) setTimeout(() => map.invalidateSize(), 100);
      });
    });

    // Zone tabs
    $$('.ztab').forEach(t => {
      t.addEventListener('click', () => {
        $$('.ztab').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        state.zone = t.dataset.zone;
        render();
      });
    });

    // Sort
    $$('.sortb').forEach(t => {
      t.addEventListener('click', () => {
        $$('.sortb').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        state.sort = t.dataset.sort;
        render();
      });
    });

    // Card clicks (delegado, robusto)
    $('#cards').addEventListener('click', (e) => {
      // Si tocó el link "Ver aviso", dejarlo abrir normal
      const link = e.target.closest('a.card-link');
      if (link) {
        e.stopPropagation();
        return;
      }
      const card = e.target.closest('.card');
      if (!card) return;
      const id = card.dataset.id;
      const l = state.listings.find(x => x.id === id);
      if (!l) return;
      state.selectedId = id;
      markSeen(id);
      render();
      // Centrar mapa
      if (l.lat && l.lng && map) {
        try { map.invalidateSize(); } catch(_) {}
        map.setView([l.lat, l.lng], 16, { animate: true });
        const m = markers.find(mk => Math.abs(mk.getLatLng().lat - l.lat) < 0.0001);
        if (m) setTimeout(() => m.openPopup(), 300);
        // En mobile, cambiar a mapa
        if (window.innerWidth < 900) {
          $$('.tab').forEach(x => x.classList.remove('active'));
          document.querySelector('.tab[data-tab="map"]').classList.add('active');
          state.tab = 'map';
          $$('.panel').forEach(p => p.classList.remove('active'));
          $('#panel-map').classList.add('active');
          setTimeout(() => map.invalidateSize(), 150);
        }
      } else if (window.innerWidth < 900) {
        // Sin coords, abrir el aviso directo en mobile
        if (l.url) window.open(l.url, '_blank');
      }
    });

    // Reload button
    $('#reload-btn').addEventListener('click', () => fetchListings(true));

    // Filters
    $('#apply-filters').addEventListener('click', () => {
      state.filters = {
        priceMin: parseInt($('#f-price-min').value, 10) || 0,
        priceMax: parseInt($('#f-price-max').value, 10) || 99999999,
        beds: parseInt($('#f-beds').value, 10) || 0,
        baths: parseInt($('#f-baths').value, 10) || 0,
        garage: parseInt($('#f-garage').value, 10) || 0,
        requirePB: $('#f-pb').checked,
        noReciclar: $('#f-no-reciclar').checked,
        withPriceOnly: $('#f-with-price').checked,
      };
      localStorage.setItem(SK.filters, JSON.stringify(state.filters));
      render();
      $('.filters')?.removeAttribute('open');
      $('details.filters').open = false;
    });
    $('#reset-filters').addEventListener('click', () => {
      state.filters = { ...DEFAULT_FILTERS };
      hydrateFilterInputs();
      localStorage.removeItem(SK.filters);
      render();
    });
  }

  function hydrateFilterInputs() {
    $('#f-price-min').value = state.filters.priceMin;
    $('#f-price-max').value = state.filters.priceMax;
    $('#f-beds').value = state.filters.beds;
    $('#f-baths').value = state.filters.baths;
    $('#f-garage').value = state.filters.garage;
    $('#f-pb').checked = state.filters.requirePB;
    $('#f-no-reciclar').checked = state.filters.noReciclar;
    $('#f-with-price').checked = state.filters.withPriceOnly;
  }

  // ─── Init ─────────────────────────────────────────────────────
  function init() {
    bindEvents();
    hydrateFilterInputs();

    // Mobile: panel-list activo por defecto. Desktop: ambos visibles vía CSS.
    if (window.innerWidth < 900) {
      $('#panel-list').classList.add('active');
    } else {
      // Desktop: ambos visibles
      $('#panel-list').classList.add('active');
      $('#panel-map').classList.add('active');
    }

    // Show app
    $('#boot').style.display = 'none';
    $('#app').style.display = 'flex';

    // Init mapa después de mostrar el DOM (necesita medir tamaños)
    setTimeout(initMap, 100);

    fetchListings();
    setInterval(tickCountdown, 1000);
    tickCountdown();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
