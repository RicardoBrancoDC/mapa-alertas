import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_GEOJSON = DATA_DIR / 'cemaden_pluvio_estacoes.geojson'

URL = os.getenv(
    'CEMADEN_PLUVIO_WFS_URL',
    'https://gsc.cemaden.gov.br/geoserver/cemaden_dev/wfs'
    '?service=WFS'
    '&version=2.0.0'
    '&request=GetFeature'
    '&typeNames=cemaden_dev:view_pcds_pluviometrica_cemaden'
    '&outputFormat=application/json'
)
TIMEOUT = int(os.getenv('REQUEST_TIMEOUT_SEC', '30'))


def main() -> None:
    resp = requests.get(URL, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection':
        raise RuntimeError('Resposta inesperada do WFS do CEMADEN')

    features = data.get('features', [])
    for feature in features:
        props = feature.setdefault('properties', {})
        props['source'] = 'CEMADEN'
        props['camada'] = 'Estações Pluviométricas'
        props['title'] = props.get('nome') or 'Estação pluviométrica'
        props['severity_group'] = 'pluvio'

    OUT_GEOJSON.write_text(
        json.dumps(data, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8'
    )
    print(f'GeoJSON salvo em {OUT_GEOJSON} com {len(features)} feições')


if __name__ == '__main__':
    main()
