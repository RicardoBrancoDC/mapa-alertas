const BRAZIL_BOUNDS = L.latLngBounds(L.latLng(-33.9, -73.99), L.latLng(5.5, -28.8));
const state = { map: null, layers: {}, layerDefinitions: [] };

function formatDateTime(value) {
  if (!value) return 'Não informado';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' });
}
function normalize(value) { return String(value || '').trim().toLowerCase(); }

function computeIdapLevel(props) {
  const sev = normalize(props.severity || props.severidade);
  const urg = normalize(props.urgency || props.urgencia);
  const cer = normalize(props.certainty || props.confianca);
  const rt = normalize(props.responseType || props.acao_necessaria);
  const certaintyOk = cer === 'likely' || cer === 'observed' || cer === 'provável' || cer === 'provavel' || cer === 'observado';
  const responseOk = /shelter|evacuate|execute|abrigar|evacuar|executar/.test(rt);
  if (sev === 'minor' || sev === 'baixo') return 'Baixo';
  if (sev === 'moderate' || sev === 'médio' || sev === 'medio') return 'Médio';
  if (sev === 'severe' || sev === 'alto') return 'Alto';
  if (sev === 'extreme' || sev === 'extremo') {
    if (urg === 'immediate' && certaintyOk && responseOk) return 'Extremo';
    if (urg === 'expected' && certaintyOk && responseOk) return 'Severo';
    return 'Alto';
  }
  return props.nivel_calculado || props.nivel || 'Indefinido';
}
function idapLevelColor(level) {
  const n = normalize(level);
  if (n === 'baixo') return '#16A42F';
  if (n === 'médio' || n === 'medio') return '#EFCF19';
  if (n === 'alto') return '#EE6908';
  if (n === 'severo') return '#C60C0D';
  if (n === 'extremo') return '#7D39BD';
  return '#6a43d9';
}

function markerStyle(category, feature = null) {
  const styles = { idap_ativos: '#6a43d9', idap_inativos: '#8f96a3', inmet_alertas: '#ff8c00', cemaden_hidro: '#2474d2', cemaden_geo: '#8a5a3b', cemaden_pluvio_estacoes: '#1f78b4', sgb_estacoes: '#2f9e44' };
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
  return L.circleMarker(latlng, { radius: 7, color, weight: 2, fillColor: color, fillOpacity: 0.75 });
}

function popupHtml(feature, layerName) {
  const p = feature.properties || {};
  const title = p.nomeestacao || p.title || p.nome || layerName;

  if (p.codestacao && (p.tipo === 'Pluviométrica' || p.tipo_jsonp === 'Pluviométrica' || p.tipoestacao === 'Pluviométrica')) {
    const acumulado = p.acumulado ?? '-';
    const atualizado = p.atualizado_brasilia || (p.atualizado ? formatDateTime(p.atualizado) : '-');
    const inatividade = p.tempo_inatividade ?? '-';
    const idEstacao = p.idestacao || p.id_estacao || p.idEstacao;
    const uf = p.uf || '-';
    const graficoUrl = idEstacao && p.uf
      ? `https://resources.cemaden.gov.br/graficos/interativo/grafico_CEMADEN.php?idpcd=${idEstacao}&uf=${p.uf}`
      : null;
    const horarioUrl = idEstacao
      ? `https://mapservices.cemaden.gov.br/MapaInterativoWS/resources/horario/${idEstacao}/29`
      : null;

    return `
      <div class="popup-content">
        <h3>${title}</h3>
        <p><strong>Fonte:</strong> ${layerName}</p>
        <p><strong>Código:</strong> ${p.codestacao || '-'}</p>
        <p><strong>Cidade:</strong> ${p.cidade || '-'} / ${uf}</p>
        <p><strong>Tipo:</strong> ${p.tipo || p.tipo_jsonp || p.tipoestacao || '-'}</p>
        <p><strong>Acumulado 24h:</strong> ${acumulado} mm</p>
        <p><strong>Atualizado:</strong> ${atualizado}</p>
        <p><strong>Tempo de inatividade:</strong> ${inatividade}</p>
        ${graficoUrl ? `<p><a href="${graficoUrl}" target="_blank" rel="noopener noreferrer">📈 Abrir gráfico oficial do CEMADEN</a></p>` : ''}
        ${horarioUrl ? `<p><a href="${horarioUrl}" target="_blank" rel="noopener noreferrer">⏱ Ver dados horários em JSON</a></p>` : ''}
      </div>
    `;
  }

  return `<div class="popup-content"><h3>${title}</h3><p><strong>Fonte:</strong> ${layerName}</p></div>`;
}

function createGeoJsonLayer(definition, geojson) {
  return L.geoJSON(geojson, {
    style: feature => polygonStyle(feature, definition.id),
    pointToLayer: (feature, latlng) => pointToLayer(feature, latlng, definition.id),
    onEachFeature: (feature, layer) => {
      if (definition.id === 'idap_ativos' || definition.id === 'idap_inativos') {
        layer.on('click', () => openIdapModal(feature.properties, definition.id));
      } else {
        layer.bindPopup(popupHtml(feature, definition.name));
      }
    }
  });
}

async function fetchJson(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Falha ao carregar ${path}`);
  return response.json();
}
async function loadCatalog() { return fetchJson('data/catalogo_camadas.json'); }

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
      if (event.target.checked) layer.addTo(state.map);
      else state.map.removeLayer(layer);
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
    layer.eachLayer(() => { count += 1; });
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
    if (def.defaultVisible) layer.addTo(state.map);
  }
  renderLayerList();
  renderSummary();
}

function initMap() {
  state.map = L.map('map', { zoomControl: true, preferCanvas: true });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '&copy; OpenStreetMap contributors' }).addTo(state.map);
  state.map.fitBounds(BRAZIL_BOUNDS, { padding: [10, 10] });
  document.getElementById('reset-view').addEventListener('click', () => {
    state.map.fitBounds(BRAZIL_BOUNDS, { padding: [10, 10] });
  });
}

function truncateWithToggle(text, id, limit = 180) {
  const clean = String(text || '').trim();
  if (!clean) return '<p>Não informado</p>';
  if (clean.length <= limit) return `<p>${clean}</p>`;
  const short = clean.slice(0, limit) + '...';
  return `<div class="idap-truncated" data-target="${id}"><p class="short-text">${short}</p><p class="full-text" style="display:none;">${clean}</p><button class="toggle-more" data-target="${id}">Mais...</button></div>`;
}

function buildIdapCardHtml(props) {
  const level = computeIdapLevel(props);
  const headline = props.headline || props.sms || props.dca || 'Não informado';
  const description = props.description || props.descricao || 'Não informado';
  const instruction = props.instruction || props.recomendacoes || 'Não informado';
  const event = props.event || props.evento || props.title || 'ALERTA';
  const sender = props.sender_name || props.senderName || props.sender || props.orgao || 'Não informado';
  const urgency = props.urgency || props.urgencia || 'Não informado';
  const certainty = props.certainty || props.confianca || 'Não informado';
  const responseType = props.responseType || props.acao_necessaria || 'Não informado';

  return `
    <div class="idap-card-pill-wrap"><div class="idap-card-pill">ALERTA ${String(level).toUpperCase()}</div></div>
    <div class="idap-card-event">${event}</div>
    <div class="idap-card-box">
      <div class="idap-meta-row">
        <div class="idap-meta-line"><strong>Órgão:</strong><span>${sender}</span></div>
        <div class="idap-meta-line"><strong>Urgência:</strong><span>${urgency}</span><strong>Confiança:</strong><span>${certainty}</span></div>
        <div class="idap-meta-line"><strong>Ação Necessária:</strong><span>${responseType}</span></div>
      </div>
    </div>
    <div class="idap-small-grid">
      <div class="idap-small-card"><span class="label">Início:</span><span class="value">${formatDateTime(props.onset || props.inicio)}</span></div>
      <div class="idap-small-card"><span class="label">Validade:</span><span class="value">${formatDateTime(props.expires || props.validade)}</span></div>
    </div>
    <div class="idap-card-box"><h4>SMS/DCA:</h4><p>${headline}</p></div>
    <div class="idap-card-box"><h4>Descrição WhatsApp:</h4>${truncateWithToggle(description, 'desc')}</div>
    <div class="idap-card-box"><h4>Recomendações WhatsApp:</h4>${truncateWithToggle(instruction, 'instr')}</div>
    <div class="idap-card-actions"><button class="idap-back-btn" id="idap-back-btn">Voltar</button></div>
  `;
}

function wireModalToggles() {
  document.querySelectorAll('.toggle-more').forEach(btn => {
    btn.addEventListener('click', () => {
      const wrapper = btn.closest('.idap-truncated');
      if (!wrapper) return;
      const shortText = wrapper.querySelector('.short-text');
      const fullText = wrapper.querySelector('.full-text');
      const isOpen = fullText.style.display !== 'none';
      fullText.style.display = isOpen ? 'none' : 'block';
      shortText.style.display = isOpen ? 'block' : 'none';
      btn.textContent = isOpen ? 'Mais...' : 'Menos...';
    });
  });
  const backBtn = document.getElementById('idap-back-btn');
  if (backBtn) backBtn.addEventListener('click', closeIdapModal);
}

function openIdapModal(props) {
  const modal = document.getElementById('idap-modal');
  const card = document.getElementById('idap-modal-card');
  const content = document.getElementById('idap-modal-content');
  const level = computeIdapLevel(props);
  card.style.background = idapLevelColor(level);
  card.classList.toggle('level-medium', ['médio', 'medio'].includes(normalize(level)));
  content.innerHTML = buildIdapCardHtml(props);
  modal.classList.remove('hidden');
  modal.setAttribute('aria-hidden', 'false');
  wireModalToggles();
}

function closeIdapModal() {
  const modal = document.getElementById('idap-modal');
  modal.classList.add('hidden');
  modal.setAttribute('aria-hidden', 'true');
}

function initModal() {
  const closeBtn = document.getElementById('idap-modal-close');
  const modal = document.getElementById('idap-modal');
  closeBtn.addEventListener('click', closeIdapModal);
  modal.addEventListener('click', event => { if (event.target === modal) closeIdapModal(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeIdapModal(); });
}

initMap();
initModal();
loadLayers().catch(error => {
  console.error(error);
  document.getElementById('last-update').textContent = 'Erro ao carregar dados';
});
