 import json
import os
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUT_GEOJSON = DATA_DIR / "cemaden_pluvio_estacoes.geojson"

WFS_URL = os.getenv(
    "CEMADEN_PLUVIO_WFS_URL",
    "https://gsc.cemaden.gov.br/geoserver/cemaden_dev/wfs"
    "?service=WFS"
    "&version=2.0.0"
    "&request=GetFeature"
    "&typeNames=cemaden_dev:view_pcds_pluviometrica_cemaden"
    "&outputFormat=application/json",
)

# Você pode trocar depois por outro endpoint JSONP mais estável, se achar.
JSONP_URL = os.getenv(
    "CEMADEN_PLUVIO_JSONP_URL",
    "https://resources.cemaden.gov.br/dados/327mi_24.json?callback=estacoes",
)

TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SEC", "30"))


def extract_jsonp_payload(text: str) -> Any:
    """
    Extrai o JSON de uma resposta JSONP no formato:
    estacoes([...])
    """
    start = text.find("(")
    end = text.rfind(")")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Resposta JSONP inválida")
    return json.loads(text[start + 1:end])


def fetch_wfs_geojson() -> dict[str, Any]:
    response = requests.get(WFS_URL, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise RuntimeError("Resposta inesperada do WFS do CEMADEN")

    return data


def fetch_jsonp_station_data() -> dict[str, dict[str, Any]]:
    """
    Retorna um dicionário indexado por codestacao com dados complementares.
    """
    response = requests.get(JSONP_URL, timeout=TIMEOUT)
    response.raise_for_status()

    payload = extract_jsonp_payload(response.text)

    by_code: dict[str, dict[str, Any]] = {}

    # O formato observado é algo como:
    # [
    #   {
    #     "atualizado": "... UTC",
    #     "estacao": [{...}, {...}]
    #   }
    # ]
    if isinstance(payload, list):
        for block in payload:
            if not isinstance(block, dict):
                continue

            atualizado = block.get("atualizado")
            stations = block.get("estacao", [])
            if not isinstance(stations, list):
                continue

            for station in stations:
                if not isinstance(station, dict):
                    continue

                code = station.get("codestacao")
                if not code:
                    continue

                by_code[code] = {
                    "acumulado": station.get("acumulado"),
                    "atualizado": atualizado,
                    "status": station.get("status"),
                    "nome_jsonp": station.get("nomeestacao"),
                    "tipo_jsonp": station.get("tipoestacao"),
                    "sigla_rede": station.get("sigla"),
                    "nome_rede": station.get("nomerede"),
                    "codibge": station.get("codibge"),
                    "id_estacao": station.get("idestacao"),
                }

    return by_code


def merge_data(
    geojson: dict[str, Any], station_data: dict[str, dict[str, Any]]
) -> tuple[int, int]:
    """
    Faz a fusão por codestacao.
    Retorna:
    - total de feições
    - total de feições enriquecidas
    """
    features = geojson.get("features", [])
    if not isinstance(features, list):
        raise RuntimeError("GeoJSON sem lista de features")

    merged = 0

    for feature in features:
        if not isinstance(feature, dict):
            continue

        props = feature.setdefault("properties", {})
        if not isinstance(props, dict):
            continue

        code = props.get("codestacao")
        extra = station_data.get(code)

        # Padronizações úteis para o front
        props["source"] = "CEMADEN"
        props["camada"] = "Estações Pluviométricas"
        props["title"] = props.get("nome") or "Estação pluviométrica"

        # Flags simples para facilitar popup e estilo
        props["possui_dado_complementar"] = bool(extra)

        if extra:
            props.update(extra)
            merged += 1

    return len(features), merged


def main() -> None:
    geojson = fetch_wfs_geojson()

    try:
        station_data = fetch_jsonp_station_data()
    except Exception as exc:
        print(f"Aviso: falha ao obter JSONP complementar: {exc}")
        station_data = {}

    total_features, merged_features = merge_data(geojson, station_data)

    OUT_GEOJSON.write_text(
        json.dumps(geojson, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(
        f"GeoJSON salvo em {OUT_GEOJSON} com {total_features} feições "
        f"({merged_features} enriquecidas com dados complementares)"
    )


if __name__ == "__main__":
    main()
