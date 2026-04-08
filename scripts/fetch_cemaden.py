from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from utils import feature_collection, write_geojson

CEMADEN_URL = "https://painelalertas.cemaden.gov.br/wsAlertas2"
REQUEST_TIMEOUT_SEC = 30
LOCAL_TZ = timezone(timedelta(hours=-3))

LEVEL_COLORS = {
    "Muito Alto": "#d73027",
    "Alto": "#fc8d59",
    "Moderado": "#ffd54f",
}


def norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()



def norm_lower(value: Any) -> str:
    return norm(value).lower()



def http_get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)



def status_is_open(value: Any) -> bool:
    try:
        return int(value) == 1
    except Exception:
        return norm_lower(value) in {"1", "true", "aberto", "open"}



def normalize_level(value: Any) -> str:
    txt = norm_lower(value)
    if txt in {"muito alto", "muito_alto", "muitoalto"}:
        return "Muito Alto"
    if txt == "alto":
        return "Alto"
    if txt == "moderado":
        return "Moderado"
    return norm(value)



def evento_tipo_bruto(evento: Any) -> str:
    txt = norm(evento)
    if "-" in txt:
        return txt.split("-", 1)[0].strip()
    return txt



def tipo_evento(evento: Any) -> str | None:
    base = norm_lower(evento)
    if "hidrol" in base:
        return "hidrologico"
    if "massa" in base:
        return "geologico"
    return None



def parse_alert_dt(value: Any) -> datetime | None:
    txt = norm(value)
    if not txt:
        return None

    patterns = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y %H:%M:%S %Z",
        "%d-%m-%Y %H:%M:%S",
    ]

    for pattern in patterns:
        try:
            dt = datetime.strptime(txt, pattern)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    return None



def build_feature(alerta: dict[str, Any], categoria: str, updated_at: str) -> dict[str, Any] | None:
    nivel = normalize_level(alerta.get("nivel"))

    try:
        lat = float(alerta.get("latitude"))
        lon = float(alerta.get("longitude"))
    except Exception:
        return None

    created_dt = parse_alert_dt(alerta.get("datahoracriacao"))
    created_iso = created_dt.astimezone(LOCAL_TZ).isoformat() if created_dt else norm(alerta.get("datahoracriacao"))

    municipio = norm(alerta.get("municipio"))
    uf = norm(alerta.get("uf"))
    evento = norm(alerta.get("evento"))
    cod_alerta = norm(alerta.get("cod_alerta"))
    codibge = norm(alerta.get("codibge"))

    titulo = f"CEMADEN {categoria}"
    if municipio:
        titulo += f" - {municipio}"

    descricao = evento
    if cod_alerta:
        descricao = f"{evento}. Código do alerta: {cod_alerta}."

    return {
        "type": "Feature",
        "properties": {
            "id": cod_alerta,
            "title": titulo,
            "nome": titulo,
            "tipo": "CEMADEN",
            "categoria": categoria,
            "status": "Ativo",
            "is_active": True,
            "municipio": municipio,
            "uf": uf,
            "codibge": codibge,
            "evento": evento,
            "evento_tipo": evento_tipo_bruto(evento),
            "severidade": nivel,
            "severity_group": norm_lower(nivel).replace(" ", "_"),
            "cor": LEVEL_COLORS.get(nivel, "#2474d2" if categoria == "hidrológico" else "#8a5a3b"),
            "descricao": descricao,
            "onset": created_iso,
            "updated_at": updated_at,
            "link": CEMADEN_URL,
            "fonte": "https://painelalertas.cemaden.gov.br/wsAlertas2",
        },
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
    }



def split_open_alerts(alertas: list[dict[str, Any]], updated_at: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hidro: list[dict[str, Any]] = []
    geo: list[dict[str, Any]] = []

    for alerta in alertas:
        if not status_is_open(alerta.get("status")):
            continue

        categoria = tipo_evento(alerta.get("evento"))
        if categoria is None:
            continue

        pretty_category = "hidrológico" if categoria == "hidrologico" else "geológico"
        feature = build_feature(alerta, pretty_category, updated_at)
        if feature is None:
            continue

        if categoria == "hidrologico":
            hidro.append(feature)
        else:
            geo.append(feature)

    return hidro, geo



def main() -> None:
    data = http_get_json(CEMADEN_URL)
    atualizado = norm(data.get("atualizado"))
    alertas = data.get("alertas", []) or []

    updated_at = datetime.now(LOCAL_TZ).isoformat()
    if atualizado:
        dt_feed = parse_alert_dt(atualizado)
        if dt_feed:
            updated_at = dt_feed.astimezone(LOCAL_TZ).isoformat()

    hidro_features, geo_features = split_open_alerts(alertas, updated_at)

    write_geojson("cemaden_hidro.geojson", feature_collection(hidro_features))
    write_geojson("cemaden_geo.geojson", feature_collection(geo_features))

    print(f"CEMADEN hidrológico: {len(hidro_features)} feições gravadas.")
    print(f"CEMADEN geológico: {len(geo_features)} feições gravadas.")


if __name__ == "__main__":
    main()
