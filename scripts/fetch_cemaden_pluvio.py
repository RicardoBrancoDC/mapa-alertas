import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_GEOJSON = DATA_DIR / 'cemaden_pluvio_estacoes.geojson'

WFS_URL = os.getenv(
    'CEMADEN_PLUVIO_WFS_URL',
    'https://gsc.cemaden.gov.br/geoserver/cemaden_dev/wfs'
    '?service=WFS'
    '&version=2.0.0'
    '&request=GetFeature'
    '&typeNames=cemaden_dev:view_pcds_pluviometrica_cemaden'
    '&outputFormat=application/json'
)
JSON_URLS = [
    part.strip()
    for part in os.getenv(
        'CEMADEN_PLUVIO_JSON_URLS',
        ','.join([
            'https://resources.cemaden.gov.br/dados/311_24.json?callback=estacoes',
            'https://resources.cemaden.gov.br/dados/327mi_24.json?callback=estacoes',
            'https://resources.cemaden.gov.br/dados/332_24.json?callback=estacoes',
            'https://resources.cemaden.gov.br/dados/333_24.json?callback=estacoes',
        ]),
    ).split(',')
    if part.strip()
]
TIMEOUT = int(os.getenv('REQUEST_TIMEOUT_SEC', '30'))


def parse_jsonp(text: str) -> Any:
    text = text.strip()
    if text.startswith('{') or text.startswith('['):
        return json.loads(text)
    start = text.find('(')
    end = text.rfind(')')
    if start == -1 or end == -1 or end <= start:
        raise ValueError('Resposta JSONP inválida')
    return json.loads(text[start + 1:end])


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_brasilia(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt_utc = datetime.strptime(value, '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=ZoneInfo('UTC'))
        dt_br = dt_utc.astimezone(ZoneInfo('America/Sao_Paulo'))
        return dt_br.strftime('%d/%m/%Y %H:%M:%S')
    except Exception:
        return value


def classify_pluvio(accumulated: float | None) -> tuple[str | None, str | None]:
    if accumulated is None:
        return None, None
    if accumulated < 10:
        return 'lt10', '#00d61f'
    if accumulated < 30:
        return '10a30', '#e0d400'
    if accumulated < 70:
        return '30a70', '#f4a300'
    return 'gt70', '#e64512'


def fetch_wfs() -> dict[str, Any]:
    response = requests.get(WFS_URL, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection':
        raise RuntimeError('Resposta inesperada do WFS do CEMADEN')
    return data


def fetch_json_sources() -> dict[str, dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}

    for url in JSON_URLS:
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        payload = parse_jsonp(response.text)
        if not isinstance(payload, list):
            continue

        for block in payload:
            if not isinstance(block, dict):
                continue
            updated_utc = block.get('atualizado')
            updated_brasilia = to_brasilia(updated_utc)
            stations = block.get('estacao', [])
            if not isinstance(stations, list):
                continue

            for station in stations:
                if not isinstance(station, dict):
                    continue
                code = station.get('codestacao')
                if not code:
                    continue
                accumulated = parse_float(station.get('acumulado'))
                bucket, color = classify_pluvio(accumulated)
                by_code[code] = {
                    'codestacao': code,
                    'idestacao': station.get('idestacao'),
                    'idmunicipio': station.get('idmunicipio'),
                    'idrede': station.get('idrede'),
                    'idtipoestacao': station.get('idtipoestacao'),
                    'nomeestacao': station.get('nomeestacao'),
                    'cidade': station.get('cidade'),
                    'uf': station.get('uf'),
                    'codibge': station.get('codibge'),
                    'latitude': parse_float(station.get('latitude')),
                    'longitude': parse_float(station.get('longitude')),
                    'tipoestacao': station.get('tipoestacao'),
                    'sigla': station.get('sigla'),
                    'nomerede': station.get('nomerede'),
                    'status': station.get('status'),
                    'acumulado': accumulated,
                    'atualizado_utc': updated_utc,
                    'atualizado_brasilia': updated_brasilia,
                    'faixa_pluvio': bucket,
                    'cor_pluvio': color,
                    'source_json_url': url,
                }
    return by_code


def build_feature_from_json(station: dict[str, Any]) -> dict[str, Any] | None:
    lat = station.get('latitude')
    lon = station.get('longitude')
    if lat is None or lon is None:
        return None
    return {
        'type': 'Feature',
        'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
        'properties': {
            'codestacao': station.get('codestacao'),
            'nome': station.get('nomeestacao') or 'Estação pluviométrica',
            'latitude': lat,
            'longitude': lon,
            'cidade': station.get('cidade'),
            'uf': station.get('uf'),
            'tipo': station.get('tipoestacao') or 'Pluviométrica',
            'tempo_inatividade': None,
        },
    }


def main() -> None:
    geojson = fetch_wfs()
    station_data = fetch_json_sources()

    original_features = geojson.get('features', [])
    filtered_features: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    for feature in original_features:
        props = feature.setdefault('properties', {})
        code = props.get('codestacao')
        extra = station_data.get(code)
        if not extra:
            continue
        if extra.get('acumulado') is None:
            continue

        props['source'] = 'CEMADEN'
        props['camada'] = 'Pluviômetros automáticos'
        props['title'] = props.get('nome') or extra.get('nomeestacao') or 'Estação pluviométrica'
        props['severity_group'] = extra.get('faixa_pluvio')
        props.update(extra)
        filtered_features.append(feature)
        seen_codes.add(code)

    for code, extra in station_data.items():
        if code in seen_codes or extra.get('acumulado') is None:
            continue
        feature = build_feature_from_json(extra)
        if not feature:
            continue
        props = feature['properties']
        props['source'] = 'CEMADEN'
        props['camada'] = 'Pluviômetros automáticos'
        props['title'] = props.get('nome') or 'Estação pluviométrica'
        props['severity_group'] = extra.get('faixa_pluvio')
        props.update(extra)
        filtered_features.append(feature)

    geojson['features'] = filtered_features
    geojson['totalFeatures'] = len(filtered_features)
    geojson['numberMatched'] = len(filtered_features)
    geojson['numberReturned'] = len(filtered_features)

    OUT_GEOJSON.write_text(
        json.dumps(geojson, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )
    print(
        f'GeoJSON salvo em {OUT_GEOJSON} com {len(filtered_features)} feições ' \
        f'(somente estações com acumulado disponível)'
    )


if __name__ == '__main__':
    main()
