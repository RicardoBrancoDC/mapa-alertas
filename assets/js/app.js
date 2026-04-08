const BRAZIL_BOUNDS = L.latLngBounds(
  L.latLng(-33.9, -73.99),
  L.latLng(5.5, -28.8)
);

const state = {
  map: null,
  layers: {},
  layerDefinitions: [],
  activeFilter: 'all'
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
    inmet_alertas: '#ef8b1e',
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

  return styles[category] || '#1f2a44';
}

function polygonStyle(feature, category) {
  const severity = feature.properties?.severity_group || '';
  if (category === 'inmet_alertas') {
    if (severity === 'grande_perigo') return { color: '#cf3d32', weight: 2, fillOpacity: 0.18 };
    if (severity === 'perigo') return { color: '#ef8b1e', weight: 2, fillOpacity: 0.16 };
    return { color: '#d6b52b', weight: 2, fillOpacity: 0.14 };
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

function popupHtml(feature, layerName) {
  const p = feature.properties || {};
  return `
    <div class="popup-content">
      <h3>${p.title || p.nome || layerName}</h3>
      <p><strong>Camada:</strong> ${layerName}</p>
      ${p.tipo ? `<p><strong>Tipo:</strong> ${p.tipo}</p>` : ''}
      ${p.categoria ? `<p><strong>Categoria:</strong> ${p.categoria}</p>` : ''}
      ${p.status ? `<p><strong>Status:</strong> ${p.status}</p>` : ''}
      ${p.severidade ? `<p><strong>Nível:</strong> ${p.severidade}</p>` : ''}
      ${p.evento_tipo ? `<p><strong>Evento:</strong> ${p.evento_tipo}</p>` : ''}
      ${p.municipio ? `<p><strong>Município:</strong> ${p.municipio}</p>` : ''}
      ${p.uf ? `<p><strong>UF:</strong> ${p.uf}</p>` : ''}
      ${p.codibge ? `<p><strong>Código IBGE:</strong> ${p.codibge}</p>` : ''}
      ${p.onset ? `<p><strong>Criação:</strong> ${formatDateTime(p.onset)}</p>` : ''}
      ${p.expires ? `<p><strong>Expira:</strong> ${formatDateTime(p.expires)}</p>` : ''}
      ${p.updated_at ? `<p><strong>Atualizado em:</strong> ${formatDateTime(p.updated_at)}</p>` : ''}
      ${p.descricao ? `<p><strong>Descrição:</strong> ${p.descricao}</p>` : ''}
      ${p.link ? `<p><a href="${p.link}" target="_blank" rel="noopener noreferrer">Abrir fonte</a></p>` : ''}
    </div>
  `;
}

function passesFilter(feature) {
  if (state.activeFilter === 'all') return true;
  const isActive = Boolean(feature.properties?.is_active);
  if (state.activeFilter === 'active') return isActive;
  if (state.activeFilter === 'inactive') return !isActive;
  return true;
}

function createGeoJsonLayer(definition, geojson) {
  return L.geoJSON(geojson, {
    filter: passesFilter,
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

function rebuildLayers() {
  state.layerDefinitions.forEach(def => {
    const wasVisible = state.map.hasLayer(state.layers[def.id]);
    state.map.removeLayer(state.layers[def.id]);
  });

  loadLayers().catch(error => {
    console.error(error);
    document.getElementById('last-update').textContent = 'Erro ao carregar dados';
  });
}

function setupFilterButtons() {
  document.querySelectorAll('.chip').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach(btn => btn.classList.remove('active'));
      button.classList.add('active');
      state.activeFilter = button.dataset.filter;
      state.layers = {};
      rebuildLayers();
    });
  });
}

function initMap() {
  state.map = L.map('map', {
    zoomControl: true,
    preferCanvas: true
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(state.map);

  state.map.fitBounds(BRAZIL_BOUNDS);

  document.getElementById('reset-view').addEventListener('click', () => {
    state.map.fitBounds(BRAZIL_BOUNDS);
  });

  setupFilterButtons();
  loadLayers().catch(error => {
    console.error(error);
    document.getElementById('last-update').textContent = 'Erro ao carregar dados';
  });
}

window.addEventListener('DOMContentLoaded', initMap);
