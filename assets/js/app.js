const BRAZIL_BOUNDS = L.latLngBounds(L.latLng(-33.9, -73.99), L.latLng(5.5, -28.8));
const state = { map: null, layers: {}, layerDefinitions: [], layerVisibility: {} };

function formatDateTime(value) {
  if (!value) return 'Não informado';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' });
}
function normalize(value) { return String(value || '').trim().toLowerCase(); }
function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
function formatRain(value) {
  if (value == null || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toFixed(1).replace(/\.0$/, '');
}

function cemadenSeverityColor(value) {
  const severity = normalize(value);
  if (severity === 'muito_alto') return '#d73027';
  if (severity === 'alto') return '#fc8d59';
  if (severity === 'moderado') return '#ffd54f';
  return '#d6b52b';
}

function isCemadenInternalLayerId(id) {
  return id === 'cemaden_estados' || id === 'cemaden_municipios' || id === 'cemaden_municipios_icones';
}

function getDisplayLayerDefs() {
  return state.layerDefinitions.filter(def => !def.internalOnly);
}

function getCemadenActiveMode() {
  const zoom = state.map ? state.map.getZoom() : 4;
  if (zoom < 6) return 'estados';
  if (zoom < 8) return 'municipios';
  return 'municipios_icones';
}

function setLayerOnMap(layerId, shouldShow) {
  const layer = state.layers[layerId];
  if (!layer || !state.map) return;
  if (shouldShow) {
    if (!state.map.hasLayer(layer)) layer.addTo(state.map);
  } else if (state.map.hasLayer(layer)) {
    state.map.removeLayer(layer);
  }
}

function updateCemadenAlertasByZoom() {
  if (!state.map) return;
  const enabled = !!state.layerVisibility.cemaden_alertas;
  const mode = getCemadenActiveMode();

  setLayerOnMap('cemaden_estados', enabled && mode === 'estados');
  setLayerOnMap('cemaden_municipios', enabled && (mode === 'municipios' || mode === 'municipios_icones'));
  setLayerOnMap('cemaden_municipios_icones', enabled && mode === 'municipios_icones');
}

function syncLayerVisibilityToMap() {
  getDisplayLayerDefs().forEach(def => {
    if (def.id === 'cemaden_alertas') return;
    setLayerOnMap(def.id, !!state.layerVisibility[def.id]);
  });
  updateCemadenAlertasByZoom();
}

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
  if (category === 'cemaden_pluvio_estacoes') {
    const acumulado = feature?.properties?.acumulado;
    if (acumulado == null) return '#8f8f8f';
    if (acumulado < 10) return '#32d74b';
    if (acumulado < 30) return '#e0d400';
    if (acumulado < 70) return '#f4a300';
    return '#e64512';
  }

  if (category === 'cemaden_estados' || category === 'cemaden_municipios' || category === 'cemaden_municipios_icones') {
    return feature?.properties?.cor || cemadenSeverityColor(feature?.properties?.severity_group);
  }

  const styles = { idap_ativos: '#6a43d9', idap_inativos: '#8f96a3', inmet_alertas: '#ff8c00', sgb_estacoes: '#2f9e44' };
  const severity = feature?.properties?.severity_group || '';
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

  if (category === 'cemaden_pluvio_estacoes') {
    const acumulado = feature?.properties?.acumulado;
    const valor = acumulado == null ? '' : formatRain(acumulado);
    const textColor = acumulado != null && acumulado >= 30 ? '#fff' : '#111';

    const icon = L.divIcon({
      className: 'cemaden-pluvio-marker-wrapper',
      html: `
        <div class="cemaden-pluvio-marker" style="background:${color}; color:${textColor};">
          <span>${escapeHtml(valor)}</span>
        </div>
      `,
      iconSize: [28, 28],
      iconAnchor: [14, 14]
    });

    return L.marker(latlng, { icon });
  }

  if (category === 'cemaden_municipios_icones') {
    const tipo = normalize(feature?.properties?.tipo_icone);
    const glyph = tipo === 'geo' ? '⛰' : '≋';
    const icon = L.divIcon({
      className: 'cemaden-alert-icon-wrapper',
      html: `<div class="cemaden-alert-icon" style="background:${color};"><span>${glyph}</span></div>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13]
    });
    return L.marker(latlng, { icon });
  }

  return L.circleMarker(latlng, { radius: 7, color, weight: 2, fillColor: color, fillOpacity: 0.75 });
}

function popupHtml(feature, layerName) {
  const p = feature.properties || {};
  const title = p.nomeestacao || p.title || p.nome || layerName;

  if (p.codestacao && (p.tipo === 'Pluviométrica' || p.tipo_jsonp === 'Pluviométrica' || p.tipoestacao === 'Pluviométrica')) {
    const acumulado = formatRain(p.acumulado);
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
      <div class="popup-content cemaden-popup-content">
        <h3>${escapeHtml(title)}</h3>
        <p><strong>Fonte:</strong> ${escapeHtml(layerName)}</p>
        <p><strong>Código:</strong> ${escapeHtml(p.codestacao || '-')}</p>
        <p><strong>Cidade:</strong> ${escapeHtml(p.cidade || '-')} / ${escapeHtml(uf)}</p>
        <p><strong>Tipo:</strong> ${escapeHtml(p.tipo || p.tipo_jsonp || p.tipoestacao || '-')}</p>
        <p><strong>Acumulado 24h:</strong> ${escapeHtml(acumulado)} mm</p>
        <p><strong>Atualizado:</strong> ${escapeHtml(atualizado)}</p>
        <p><strong>Tempo de inatividade:</strong> ${escapeHtml(String(inatividade))}</p>
        <div class="cemaden-popup-actions">
          ${horarioUrl ? `<button type="button" class="cemaden-hourly-btn" data-hourly-url="${escapeHtml(horarioUrl)}" data-title="${escapeHtml(title)}" data-codestacao="${escapeHtml(p.codestacao || '')}" data-cidade="${escapeHtml(p.cidade || '')}" data-uf="${escapeHtml(uf)}" data-acumulado="${escapeHtml(acumulado)}" data-atualizado="${escapeHtml(atualizado)}">⏱ Ver chuva por hora</button>` : ''}
          ${graficoUrl ? `<a class="cemaden-popup-link" href="${escapeHtml(graficoUrl)}" target="_blank" rel="noopener noreferrer">📈 Gráfico oficial</a>` : ''}
          ${horarioUrl ? `<a class="cemaden-popup-link" href="${escapeHtml(horarioUrl)}" target="_blank" rel="noopener noreferrer">{} JSON</a>` : ''}
        </div>
      </div>
    `;
  }

  if (p.estado) {
    return `
      <div class="popup-content">
        <h3>${escapeHtml(p.estado)} (${escapeHtml(p.uf || '-')})</h3>
        <p><strong>Nível máximo:</strong> ${escapeHtml(p.nivel_max_label || p.nivel_max || '-')}</p>
        <p><strong>Total de alertas:</strong> ${escapeHtml(String(p.total_alertas ?? '-'))}</p>
        <p><strong>Municípios com alerta:</strong> ${escapeHtml(String(p.municipios_com_alerta ?? '-'))}</p>
        <p><strong>Tipos:</strong> Hidrológico ${escapeHtml(String(p.qtd_hidro ?? 0))} · Geológico ${escapeHtml(String(p.qtd_geo ?? 0))}</p>
        <p><strong>Atualizado:</strong> ${escapeHtml(formatDateTime(p.updated_at))}</p>
      </div>
    `;
  }

  if (p.municipio && (p.total_alertas != null || Array.isArray(p.alertas))) {
    const alertaPrincipal = Array.isArray(p.alertas) && p.alertas.length ? p.alertas[0] : null;
    const tipoLabel = alertaPrincipal?.tipo_raw || p.tipos || '-';
    return `
      <div class="popup-content">
        <h3>${escapeHtml(p.municipio)} / ${escapeHtml(p.uf || '-')}</h3>
        <p><strong>Nível máximo:</strong> ${escapeHtml(p.nivel_max_label || p.nivel_max || '-')}</p>
        <p><strong>Total de alertas:</strong> ${escapeHtml(String(p.total_alertas ?? '-'))}</p>
        <p><strong>Tipo principal:</strong> ${escapeHtml(tipoLabel)}</p>
        <p><strong>Tipos:</strong> Hidrológico ${escapeHtml(String(p.qtd_hidro ?? 0))} · Geológico ${escapeHtml(String(p.qtd_geo ?? 0))}</p>
        <p><strong>Atualizado:</strong> ${escapeHtml(formatDateTime(p.updated_at || alertaPrincipal?.updated_at))}</p>
      </div>
    `;
  }

  return `<div class="popup-content"><h3>${escapeHtml(title)}</h3><p><strong>Fonte:</strong> ${escapeHtml(layerName)}</p></div>`;
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

      if ((definition.id === 'cemaden_estados' || definition.id === 'cemaden_municipios') && feature?.properties?.total_alertas != null) {
        layer.bindTooltip(String(feature.properties.total_alertas), {
          permanent: true,
          direction: 'center',
          className: `cemaden-count-tooltip ${definition.id === 'cemaden_estados' ? 'is-state' : 'is-municipio'}`,
          opacity: 1
        });
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
  getDisplayLayerDefs().forEach(def => {
    const item = document.createElement('div');
    item.className = 'layer-item';
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = !!state.layerVisibility[def.id];
    checkbox.dataset.layerId = def.id;
    const dot = document.createElement('span');
    dot.className = 'layer-dot';
    dot.style.background = def.color;
    const text = document.createElement('span');
    text.textContent = def.name;
    checkbox.addEventListener('change', event => {
      const id = event.target.dataset.layerId;
      state.layerVisibility[id] = event.target.checked;
      syncLayerVisibilityToMap();
      renderSummary();
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
  getDisplayLayerDefs().forEach(def => {
    let count = 0;
    if (def.id === 'cemaden_alertas') {
      if (state.layerVisibility.cemaden_alertas) {
        const mode = getCemadenActiveMode();
        const targetId = mode === 'estados' ? 'cemaden_estados' : 'cemaden_municipios';
        const layer = state.layers[targetId];
        if (layer) layer.eachLayer(() => { count += 1; });
      }
    } else {
      const layer = state.layers[def.id];
      if (layer && state.layerVisibility[def.id]) layer.eachLayer(() => { count += 1; });
    }
    const card = document.createElement('div');
    card.className = 'summary-card';
    card.innerHTML = `<strong>${count}</strong><span>${escapeHtml(def.summaryLabel || def.name)}</span>`;
    summary.appendChild(card);
  });
}

async function loadLayers() {
  const catalog = await loadCatalog();
  state.layerDefinitions = catalog.layers;
  document.getElementById('last-update').textContent = formatDateTime(catalog.generated_at);

  for (const def of state.layerDefinitions) {
    state.layerVisibility[def.id] = !!def.defaultVisible;

    if (!def.file) {
      continue;
    }

    const geojson = await fetchJson(def.file);
    const layer = createGeoJsonLayer(def, geojson);
    state.layers[def.id] = layer;
  }

  renderLayerList();
  syncLayerVisibilityToMap();
  renderSummary();

  state.map.on('zoomend', () => {
    updateCemadenAlertasByZoom();
    renderSummary();
  });
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

function buildHourlyRows(data) {
  const datas = Array.isArray(data?.datas) ? data.datas : [];
  const horarios = Array.isArray(data?.horarios) ? data.horarios : [];
  const acumulados = Array.isArray(data?.acumulados) ? data.acumulados : [];

  return datas.map((dataLabel, rowIndex) => {
    const row = Array.isArray(acumulados[rowIndex]) ? acumulados[rowIndex] : [];
    const cells = horarios.map((hora, colIndex) => {
      const value = row[colIndex];
      return `<td>${escapeHtml(formatRain(value))}</td>`;
    }).join('');
    return `<tr><th scope="row">${escapeHtml(dataLabel)}</th>${cells}</tr>`;
  }).join('');
}

function flattenHourlyData(data) {
  const datas = Array.isArray(data?.datas) ? data.datas : [];
  const horarios = Array.isArray(data?.horarios) ? data.horarios : [];
  const acumulados = Array.isArray(data?.acumulados) ? data.acumulados : [];
  const points = [];

  datas.forEach((dataLabel, rowIndex) => {
    const row = Array.isArray(acumulados[rowIndex]) ? acumulados[rowIndex] : [];
    horarios.forEach((hora, colIndex) => {
      const value = row[colIndex];
      if (value != null) {
        points.push({ data: dataLabel, hora, valor: Number(value) });
      }
    });
  });

  return points;
}

function buildRecentHourlyCards(data) {
  const points = flattenHourlyData(data).slice(-12);
  if (!points.length) return '<p class="cemaden-empty">Sem dados horários disponíveis.</p>';
  const max = Math.max(...points.map(p => p.valor), 0.1);
  return `
    <div class="cemaden-hourly-bars">
      ${points.map(point => {
        const height = Math.max(10, Math.round((point.valor / max) * 72));
        return `
          <div class="cemaden-hourly-bar-item">
            <div class="cemaden-hourly-bar-value">${escapeHtml(formatRain(point.valor))}</div>
            <div class="cemaden-hourly-bar" style="height:${height}px"></div>
            <div class="cemaden-hourly-bar-hour">${escapeHtml(point.hora)}</div>
            <div class="cemaden-hourly-bar-date">${escapeHtml(point.data.slice(0, 5))}</div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function buildHourlyModalHtml(data, meta = {}) {
  const est = data?.estacao || {};
  const nome = meta.title || est.nome || 'Pluviômetro';
  const cidade = meta.cidade || est?.idMunicipio?.cidade || 'Não informado';
  const uf = meta.uf || est?.idMunicipio?.uf || '—';
  const codestacao = meta.codestacao || est.codEstacao || '—';
  const acumulado = meta.acumulado || '—';
  const tabelaLinhas = buildHourlyRows(data);
  const horarios = Array.isArray(data?.horarios) ? data.horarios : [];
  const headerCols = horarios.map(hora => `<th>${escapeHtml(hora)}</th>`).join('');
  const graficoUrl = est?.idEstacao && uf !== '—'
    ? `https://resources.cemaden.gov.br/graficos/interativo/grafico_CEMADEN.php?idpcd=${est.idEstacao}&uf=${uf}`
    : null;

  return `
    <div class="cemaden-hourly-header">
      <div>
        <h3>${escapeHtml(nome)}</h3>
        <p>${escapeHtml(cidade)} / ${escapeHtml(uf)} · ${escapeHtml(codestacao)}</p>
      </div>
      <div class="cemaden-hourly-badge">24h: ${escapeHtml(acumulado)} mm</div>
    </div>

    <div class="cemaden-hourly-section">
      <h4>Últimas leituras com dado</h4>
      ${buildRecentHourlyCards(data)}
    </div>

    <div class="cemaden-hourly-section">
      <h4>Tabela horária</h4>
      <div class="cemaden-hourly-table-wrap">
        <table class="cemaden-hourly-table">
          <thead>
            <tr><th>Data</th>${headerCols}</tr>
          </thead>
          <tbody>
            ${tabelaLinhas}
          </tbody>
        </table>
      </div>
    </div>

    <div class="cemaden-hourly-footer">
      ${graficoUrl ? `<a href="${escapeHtml(graficoUrl)}" target="_blank" rel="noopener noreferrer">📈 Abrir gráfico oficial</a>` : ''}
      <a href="${escapeHtml(meta.url || '')}" target="_blank" rel="noopener noreferrer">{} Abrir JSON bruto</a>
    </div>
  `;
}

function ensureCemadenHourlyModal() {
  if (document.getElementById('cemaden-hourly-modal')) return;

  const style = document.createElement('style');
  style.textContent = `
    .cemaden-pluvio-marker-wrapper { background: transparent; border: none; }
    .cemaden-pluvio-marker { width: 28px; height: 28px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 1px 4px rgba(0,0,0,.35); display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; line-height:1; }
    .cemaden-pluvio-marker span { display:block; transform: translateY(.5px); }
    .cemaden-popup-actions { display:flex; flex-direction:column; gap:8px; margin-top:10px; }
    .cemaden-hourly-btn { border:none; border-radius:10px; background:#0ea5e9; color:#fff; padding:8px 10px; font-weight:600; cursor:pointer; }
    .cemaden-popup-link { color:#0f3b7a; text-decoration:none; font-weight:600; }
    .cemaden-popup-link:hover { text-decoration:underline; }
    .cemaden-hourly-modal.hidden { display:none; }
    .cemaden-hourly-modal { position:fixed; inset:0; background:rgba(15,23,42,.55); z-index:5000; display:flex; align-items:center; justify-content:center; padding:20px; }
    .cemaden-hourly-card { width:min(1100px, 96vw); max-height:88vh; overflow:auto; background:#fff; border-radius:18px; box-shadow:0 20px 60px rgba(0,0,0,.25); }
    .cemaden-hourly-topbar { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:16px 20px; border-bottom:1px solid #e5e7eb; position:sticky; top:0; background:#fff; z-index:2; }
    .cemaden-hourly-topbar h2 { margin:0; font-size:1.2rem; }
    .cemaden-hourly-close { border:none; background:#eef2ff; color:#1e3a8a; width:36px; height:36px; border-radius:999px; font-size:20px; cursor:pointer; }
    .cemaden-hourly-content { padding:18px 20px 22px; }
    .cemaden-hourly-loading, .cemaden-hourly-error, .cemaden-empty { padding:16px; border-radius:12px; background:#f8fafc; margin:0; }
    .cemaden-hourly-error { background:#fef2f2; color:#991b1b; }
    .cemaden-hourly-header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:18px; }
    .cemaden-hourly-header h3 { margin:0 0 6px; font-size:1.15rem; }
    .cemaden-hourly-header p { margin:0; color:#475569; }
    .cemaden-hourly-badge { background:#eff6ff; color:#1d4ed8; border-radius:999px; padding:8px 12px; font-weight:700; white-space:nowrap; }
    .cemaden-hourly-section { margin-top:18px; }
    .cemaden-hourly-section h4 { margin:0 0 10px; }
    .cemaden-hourly-bars { display:flex; align-items:flex-end; gap:10px; overflow-x:auto; padding:8px 0; }
    .cemaden-hourly-bar-item { min-width:48px; text-align:center; }
    .cemaden-hourly-bar-value { font-size:.78rem; margin-bottom:6px; color:#0f172a; }
    .cemaden-hourly-bar { width:28px; margin:0 auto 6px; border-radius:8px 8px 4px 4px; background:linear-gradient(180deg,#38bdf8,#2563eb); }
    .cemaden-hourly-bar-hour { font-size:.75rem; font-weight:700; }
    .cemaden-hourly-bar-date { font-size:.68rem; color:#64748b; }
    .cemaden-hourly-table-wrap { overflow:auto; border:1px solid #e5e7eb; border-radius:12px; }
    .cemaden-hourly-table { border-collapse:collapse; width:max-content; min-width:100%; font-size:.84rem; }
    .cemaden-hourly-table th, .cemaden-hourly-table td { border-bottom:1px solid #e5e7eb; border-right:1px solid #e5e7eb; padding:6px 8px; text-align:center; }
    .cemaden-hourly-table thead th { position:sticky; top:0; background:#f8fafc; z-index:1; }
    .cemaden-hourly-table tbody th { position:sticky; left:0; background:#f8fafc; text-align:left; z-index:1; }
    .cemaden-hourly-footer { display:flex; gap:16px; flex-wrap:wrap; margin-top:18px; }
    .cemaden-hourly-footer a { color:#0f3b7a; text-decoration:none; font-weight:600; }
    .cemaden-hourly-footer a:hover { text-decoration:underline; }
    @media (max-width: 720px) {
      .cemaden-hourly-header { flex-direction:column; }
      .cemaden-hourly-badge { white-space:normal; }
      .cemaden-hourly-topbar { padding:14px 16px; }
      .cemaden-hourly-content { padding:16px; }
    }
  `;
  document.head.appendChild(style);

  const modal = document.createElement('div');
  modal.id = 'cemaden-hourly-modal';
  modal.className = 'cemaden-hourly-modal hidden';
  modal.setAttribute('aria-hidden', 'true');
  modal.innerHTML = `
    <div class="cemaden-hourly-card" role="dialog" aria-modal="true" aria-labelledby="cemaden-hourly-title">
      <div class="cemaden-hourly-topbar">
        <h2 id="cemaden-hourly-title">Chuva por hora do CEMADEN</h2>
        <button type="button" class="cemaden-hourly-close" id="cemaden-hourly-modal-close" aria-label="Fechar">×</button>
      </div>
      <div class="cemaden-hourly-content" id="cemaden-hourly-content"></div>
    </div>
  `;
  document.body.appendChild(modal);
}

function closeCemadenHourlyModal() {
  const modal = document.getElementById('cemaden-hourly-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.setAttribute('aria-hidden', 'true');
}

async function openCemadenHourlyModal(meta) {
  ensureCemadenHourlyModal();
  const modal = document.getElementById('cemaden-hourly-modal');
  const content = document.getElementById('cemaden-hourly-content');
  modal.classList.remove('hidden');
  modal.setAttribute('aria-hidden', 'false');
  content.innerHTML = '<p class="cemaden-hourly-loading">Carregando dados horários...</p>';

  try {
    const response = await fetch(meta.url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Falha ao carregar dados horários (${response.status})`);
    const data = await response.json();
    content.innerHTML = buildHourlyModalHtml(data, meta);
  } catch (error) {
    content.innerHTML = `<p class="cemaden-hourly-error">Não foi possível carregar os dados horários. ${escapeHtml(error.message || 'Erro desconhecido.')}</p>`;
  }
}

function initCemadenHourlyModal() {
  ensureCemadenHourlyModal();
  document.addEventListener('click', event => {
    const trigger = event.target.closest('.cemaden-hourly-btn');
    if (trigger) {
      event.preventDefault();
      openCemadenHourlyModal({
        url: trigger.dataset.hourlyUrl,
        title: trigger.dataset.title,
        codestacao: trigger.dataset.codestacao,
        cidade: trigger.dataset.cidade,
        uf: trigger.dataset.uf,
        acumulado: trigger.dataset.acumulado,
        atualizado: trigger.dataset.atualizado
      });
      return;
    }

    if (event.target.id === 'cemaden-hourly-modal-close') {
      closeCemadenHourlyModal();
      return;
    }

    const modal = document.getElementById('cemaden-hourly-modal');
    if (modal && event.target === modal) {
      closeCemadenHourlyModal();
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeCemadenHourlyModal();
  });
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
initCemadenHourlyModal();
loadLayers().catch(error => {
  console.error(error);
  document.getElementById('last-update').textContent = 'Erro ao carregar dados';
});
