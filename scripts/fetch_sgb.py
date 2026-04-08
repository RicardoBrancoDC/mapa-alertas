from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen

from utils import feature_collection, write_geojson

SGB_URL = "https://www.sgb.gov.br/sace/sace_nivel/api_estacoes_situacao.php"
TIMEOUT = 60


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_status(value: str) -> str:
    raw = normalize_text(value)
    lowered = raw.casefold()

    if "alerta" in lowered:
        return "alerta"
    if "aten" in lowered:
        return "atencao"
    if "sem transmiss" in lowered:
        return "sem_transmissao"
    if "normal" in lowered:
        return "normal"
    return "outro"


def is_active_status(group: str) -> bool:
    return group in {"atencao", "alerta"}


def to_float(value: Any) -> float | None:
    text = normalize_text(value).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_payload() -> list[dict[str, Any]]:
    req = Request(
        SGB_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(req, timeout=TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        raw = response.read().decode(charset, errors="replace")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Resposta do SGB não veio em lista JSON.")
    return data


def build_feature(item: dict[str, Any]) -> dict[str, Any] | None:
    lat = to_float(item.get("latitude"))
    lon = to_float(item.get("longitude"))
    if lat is None or lon is None:
        return None

    nome_alerta = normalize_text(item.get("nome_alerta"))
    status_group = normalize_status(nome_alerta)
    nome_pm = normalize_text(item.get("nome_pm"))
    sigla_pm = normalize_text(item.get("sigla_pm"))
    nome_bacia = normalize_text(item.get("nome_bacia"))

    title_parts = [part for part in [nome_pm, nome_alerta] if part]
    title = " | ".join(title_parts) if title_parts else "Estação hidrológica SGB"

    return {
        "type": "Feature",
        "properties": {
            "title": title,
            "nome": nome_pm,
            "sigla_pm": sigla_pm,
            "tipo": "SGB",
            "categoria": "Estação hidrológica",
            "status": nome_alerta or "Não informado",
            "severity_group": status_group,
            "is_active": is_active_status(status_group),
            "bacia": nome_bacia,
            "descricao": f"Bacia: {nome_bacia}" if nome_bacia else "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "link": SGB_URL,
        },
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
    }


def main() -> None:
    payload = fetch_payload()
    features = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        feature = build_feature(item)
        if feature is not None:
            features.append(feature)

    write_geojson("sgb_estacoes.geojson", feature_collection(features))
    print(f"Arquivo SGB atualizado com {len(features)} estações.")


if __name__ == "__main__":
    main()
