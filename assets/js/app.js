const BRAZIL_BOUNDS = L.latLngBounds(
  L.latLng(-33.9, -73.99),
  L.latLng(5.5, -28.8)
);

const state = {
  map: null,
  layers: {},
  layerDefinitions: []
};

function formatDateTime(value) {
  if (!value) return 'Não informado';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: 'America/Sao_Paulo'
  });
}

function markerStyle(category, feature = null) {
  const styles = {
    idap_ativos: '#6a43d9',
    idap_inativos: '#8f96a3',
    inmet_alertas: '#ff8c00',
    cemaden_hidro: '#2474d2',
    cemaden_geo: '#8a5a3b',
    sgb_estacoes: '#2f9e44'
  };

  const severity = feature?.properties?.severity_group || '';

  if (category === 'cemaden_hidro' || category === 'cemaden_geo') {
    if (severity === 'muito_alto') return '#d73027';
    if (severity === 'alto') return '#fc8d59';
    if (severity === 'moderado') return '#ffd54f';
  }

  if (category === 'sgb_estacoes') {
    if (severity === 'alerta') return '#d73027';
    if (severity === 'atencao') return '#ffd54f';
    if (severity === 'sem_transmissao') return '#8f96a3';
    if (severity === 'normal') return '#2f9e44';
    return '#1f78b4';
  }

  return styles[category] || '#1f2a44';
}

function polygonStyle(feature, category) {
  const severity = feature.properties?.severity_group || '';
  if (category === 'inmet_alertas') {
    if (severity === 'grande_perigo') return { color: '#ff0000', weight: 2, fillOpacity: 0.18 };
    if (severity === 'perigo') return { color: '#ff8c00', weight: 2, fillOpacity: 0.16 };
    return { color: '#ffff00', weight: 2, fillOpacity: 0.14 };
  }
  const color = markerStyle(category, feature);
  return { color, weight: 2, fillOpacity: 0.14 };
}

function pointToLayer(feature, latlng, category) {
  const color = markerStyle(category, feature);
  return L.circleMarker(latlng, {
    radius: 7,
    color,
    weight: 2,
    fillColor: color,
    fillOpacity: 0.75
  });
}

function popupBadge(label, value, tone = 'neutral') {
  if (!value) return '';
  return `<span class="popup-badge ${tone}">${label}: ${value}</span>`;
}

function popupHtml(feature, layerName) {
  const p = feature.properties || {};
  const severityTone = (p.severity_group || '').toLowerCase();
  const statusTone = p.is_active ? 'ativo' : 'inativo';
  const title = p.title || p.nome || layerName;
  const eventName = p.evento || p.evento_tipo || '';
  const areaName = [p.municipio, p.uf].filter(Boolean).join(' - ');
  const headline = p.headline || '';
  const description = p.descricao || '';
  const instruction = p.instruction || '';
  const sender = p.sender_name || p.sender || '';
  const channels = p.channel_list || '';

  return `
    <div class="popup-content popup-card">
      <div class="popup-topline">${layerName}</div>
      <h3>${title}</h3>
      <div class="popup-badges">
        ${popupBadge('Status', p.status || (p.is_active ? 'Ativo' : 'Inativo'), statusTone)}
        ${popupBadge('Nível', p.severidade, severityTone)}
        ${popupBadge('Tipo', p.tipo)}
        ${popupBadge('Categoria', p.categoria)}
      </div>

      ${headline ? `<div class="popup-section"><div class="popup-label">Headline</div><div class="popup-text highlight">${headline}</div></div>` : ''}
      ${eventName ? `<div class="popup-section"><div class="popup-label">Evento</div><div class="popup-text">${eventName}</div></div>` : ''}
      ${areaName ? `<div class="popup-section"><div class="popup-label">Área</div><div class="popup-text">${areaName}</div></div>` : ''}
      ${p.bacia ? `<div class="popup-section"><div class="popup-label">Bacia</div><div class="popup-text">${p.bacia}</div></div>` : ''}
      ${p.municipios_total ? `<div class="popup-section"><div class="popup-label">Municípios afetados</div><div class="popup-text">${p.municipios_total}</div></div>` : ''}

      <div class="popup-grid">
        ${p.codibge ? `<div><span class="popup-label">IBGE</span><span class="popup-value">${p.codibge}</span></div>` : ''}
        ${p.sigla_pm ? `<div><span class="popup-label">Sigla</span><span class="popup-value">${p.sigla_pm}</span></div>` : ''}
        ${p.onset ? `<div><span class="popup-label">Início</span><span class="popup-value">${formatDateTime(p.onset)}</span></div>` : ''}
        ${p.expires ? `<div><span class="popup-label">Expira</span><span class="popup-value">${formatDateTime(p.expires)}</span></div>` : ''}
        ${p.updated_at ? `<div><span class="popup-label">Atualizado</span><span class="popup-value">${formatDateTime(p.updated_at)}</span></div>` : ''}
      </div>

      ${sender ? `<div class="popup-section"><div class="popup-label">Emissor</div><div class="popup-text">${sender}</div></div>` : ''}
      ${channels ? `<div class="popup-section"><div class="popup-label">Canais</div><div class="popup-text">${channels}</div></div>` : ''}
      ${description ? `<div class="popup-section"><div class="popup-label">Descrição</div><div class="popup-text">${description}</div></div>` : ''}
      ${instruction ? `<div class="popup-section"><div class="popup-label">Instrução</div><div class="popup-text">${instruction}</div></div>` : ''}
      ${p.municipios ? `<div class="popup-section"><div class="popup-label">Lista de municípios</div><div class="popup-text">${p.municipios}</div></div>` : ''}
      ${p.link ? `<div class="popup-actions"><a href="${p.link}" target="_blank" rel="noopener noreferrer">Abrir fonte</a></div>` : ''}
    </div>
  `;
}

function createGeoJsonLayer(definition, geojson) {
  return L.geoJSON(geojson, {
    style: feature => polygonStyle(feature, definition.id),
    pointToLayer: (feature, latlng) => pointToLayer(feature, latlng, definition.id),
    onEachFeature: (feature, layer) => {
      layer.bindPopup(popupHtml(feature, definition.name));
    }
  });
}

async function fetchJson(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Falha ao carregar ${path}`);
  return response.json();
}

async function loadCatalog() {
  return fetchJson('data/catalogo_camadas.json');
}

function renderLayerList() {
  const container = document.getElementById('layer-list');
  container.innerHTML = '';

  state.layerDefinitions.forEach(def => {
    const item = document.createElement('div');
    item.className = 'layer-item';

    const label = document.createElement('label');

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = def.defaultVisible;
    checkbox.dataset.layerId = def.id;

    const dot = document.createElement('span');
    dot.className = 'layer-dot';
    dot.style.background = def.color;

    const text = document.createElement('span');
    text.textContent = def.name;

    checkbox.addEventListener('change', event => {
      const layer = state.layers[event.target.dataset.layerId];
      if (!layer) return;
      if (event.target.checked) {
        layer.addTo(state.map);
      } else {
        state.map.removeLayer(layer);
      }
    });

    label.appendChild(checkbox);
    label.appendChild(dot);
    label.appendChild(text);
    item.appendChild(label);
    container.appendChild(item);
  });
}

function renderSummary() {
  const summary = document.getElementById('summary');
  summary.innerHTML = '';

  state.layerDefinitions.forEach(def => {
    const layer = state.layers[def.id];
    let count = 0;
    layer.eachLayer(() => {
      count += 1;
    });

    const card = document.createElement('div');
    card.className = 'summary-card';
    card.innerHTML = `<strong>${count}</strong><span>${def.name}</span>`;
    summary.appendChild(card);
  });
}

async function loadLayers() {
  const catalog = await loadCatalog();
  state.layerDefinitions = catalog.layers;
  document.getElementById('last-update').textContent = formatDateTime(catalog.generated_at);

  for (const def of state.layerDefinitions) {
    const geojson = await fetchJson(def.file);
    const layer = createGeoJsonLayer(def, geojson);
    state.layers[def.id] = layer;
    if (def.defaultVisible) {
      layer.addTo(state.map);
    }
  }

  renderLayerList();
  renderSummary();
}

function initMap() {
  state.map = L.map('map', {
    zoomControl: true,
    preferCanvas: true
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(state.map);

  state.map.fitBounds(BRAZIL_BOUNDS, {
    padding: [10, 10]
  });

  document.getElementById('reset-view').addEventListener('click', () => {
    state.map.fitBounds(BRAZIL_BOUNDS, {
      padding: [10, 10]
    });
  });
}

initMap();
loadLayers().catch(error => {
  console.error(error);
  document.getElementById('last-update').textContent = 'Erro ao carregar dados';
});
