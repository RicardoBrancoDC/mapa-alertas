from __future__ import annotations

import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import DATA_DIR, feature_collection, write_geojson, write_json

CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}


class RateLimitError(Exception):
    pass


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        return int(value)
    except ValueError:
        return default


def fetch_text(url: str, timeout: int = 45) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "mapa-alertas/1.0 (+https://github.com)",
            "Accept": "application/rss+xml, application/xml, text/xml, application/cap+xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        content_type = (response.headers.get("Content-Type") or "").lower()
        encoding = response.headers.get_content_charset() or "utf-8"

    try:
        text = raw.decode(encoding, errors="strict")
    except Exception:
        text = raw.decode("utf-8", errors="replace")

    text = text.lstrip("\ufeff\n\r\t ")
    if not text:
        raise ValueError(f"Resposta vazia em {url}")

    lower_text = text.lower()
    if "limite de requisições" in lower_text or "limite de requisicoes" in lower_text:
        raise RateLimitError(f"Limite de requisições atingido em {url}")

    if "<" not in text[:200] and "xml" not in content_type and "rss" not in content_type:
        preview = text[:120].replace("\n", " ").replace("\r", " ")
        raise ValueError(f"Resposta não parece XML em {url}: {preview}")

    return text


def fetch_text_with_retry(url: str, timeout: int = 45, retries: int = 3, backoff_sec: float = 8.0) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fetch_text(url, timeout=timeout)
        except RateLimitError as exc:
            last_exc = exc
            if attempt == retries:
                break
            sleep_for = backoff_sec * attempt
            print(f"[INMET] limite de requisições em {url}. Nova tentativa em {sleep_for:.1f}s.")
            time.sleep(sleep_for)
        except Exception as exc:
            last_exc = exc
            if attempt == retries:
                break
            sleep_for = min(3.0 * attempt, 10.0)
            print(f"[INMET] falha temporária em {url}: {exc}. Nova tentativa em {sleep_for:.1f}s.")
            time.sleep(sleep_for)
    assert last_exc is not None
    raise last_exc


def text_or_none(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except Exception:
        return None


def severity_pt_from_cap(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "extreme":
        return "Grande Perigo"
    if normalized == "severe":
        return "Perigo"
    if normalized == "moderate":
        return "Perigo Potencial"
    return value or "Não informado"


def severity_group(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"extreme", "grande perigo"}:
        return "grande_perigo"
    if normalized in {"severe", "perigo"}:
        return "perigo"
    return "perigo_potencial"


def parse_parameters(info: ET.Element) -> dict[str, str]:
    params: dict[str, str] = {}
    for parameter in info.findall("cap:parameter", CAP_NS):
        key = text_or_none(parameter.find("cap:valueName", CAP_NS))
        value = text_or_none(parameter.find("cap:value", CAP_NS))
        if key:
            params[key] = value or ""
    return params


def cap_polygon_to_coords(polygon_text: str | None) -> list[list[list[float]]] | None:
    txt = (polygon_text or "").strip()
    if not txt:
        return None

    pts: list[list[float]] = []
    for pair in txt.split():
        parts = pair.split(",")
        if len(parts) != 2:
            continue
        try:
            lat = float(parts[0])
            lon = float(parts[1])
        except ValueError:
            continue
        pts.append([lon, lat])

    if len(pts) < 3:
        return None

    if pts[0] != pts[-1]:
        pts.append(pts[0])

    return [pts]


def parse_rss_items(rss_text: str) -> list[dict[str, str | None]]:
    root = ET.fromstring(rss_text)
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[dict[str, str | None]] = []
    for item in channel.findall("item"):
        items.append(
            {
                "title": text_or_none(item.find("title")),
                "link": text_or_none(item.find("link")),
                "guid": text_or_none(item.find("guid")),
                "pubDate": text_or_none(item.find("pubDate")),
                "description": text_or_none(item.find("description")),
            }
        )
    return items


def parse_cap_alert(xml_text: str) -> dict[str, Any]:
    xml_text = (xml_text or "").lstrip("\ufeff\n\r\t ")
    if not xml_text:
        raise ValueError("CAP vazio.")

    root = ET.fromstring(xml_text)
    info = root.find("cap:info", CAP_NS)
    if info is None:
        raise ValueError("CAP do INMET sem bloco <info>.")

    areas = []
    for area in info.findall("cap:area", CAP_NS):
        area_desc = text_or_none(area.find("cap:areaDesc", CAP_NS))
        polygon_text = text_or_none(area.find("cap:polygon", CAP_NS))
        coords = cap_polygon_to_coords(polygon_text)
        geocodes = {}
        for geocode in area.findall("cap:geocode", CAP_NS):
            key = text_or_none(geocode.find("cap:valueName", CAP_NS))
            value = text_or_none(geocode.find("cap:value", CAP_NS))
            if key:
                geocodes[key] = value or ""
        areas.append(
            {
                "area_desc": area_desc,
                "polygon": polygon_text,
                "coords": coords,
                "geocodes": geocodes,
            }
        )

    parameters = parse_parameters(info)

    return {
        "identifier": text_or_none(root.find("cap:identifier", CAP_NS)),
        "sender": text_or_none(root.find("cap:sender", CAP_NS)),
        "sent": text_or_none(root.find("cap:sent", CAP_NS)),
        "status": text_or_none(root.find("cap:status", CAP_NS)),
        "msg_type": text_or_none(root.find("cap:msgType", CAP_NS)),
        "scope": text_or_none(root.find("cap:scope", CAP_NS)),
        "language": text_or_none(info.find("cap:language", CAP_NS)),
        "category": text_or_none(info.find("cap:category", CAP_NS)),
        "event": text_or_none(info.find("cap:event", CAP_NS)),
        "response_type": text_or_none(info.find("cap:responseType", CAP_NS)),
        "urgency": text_or_none(info.find("cap:urgency", CAP_NS)),
        "severity": text_or_none(info.find("cap:severity", CAP_NS)),
        "certainty": text_or_none(info.find("cap:certainty", CAP_NS)),
        "onset": text_or_none(info.find("cap:onset", CAP_NS)),
        "expires": text_or_none(info.find("cap:expires", CAP_NS)),
        "sender_name": text_or_none(info.find("cap:senderName", CAP_NS)),
        "headline": text_or_none(info.find("cap:headline", CAP_NS)),
        "description": text_or_none(info.find("cap:description", CAP_NS)),
        "instruction": text_or_none(info.find("cap:instruction", CAP_NS)),
        "web": text_or_none(info.find("cap:web", CAP_NS)),
        "contact": text_or_none(info.find("cap:contact", CAP_NS)),
        "parameters": parameters,
        "areas": areas,
    }


def build_features(rss_item: dict[str, Any], cap_data: dict[str, Any], now: datetime, time_filter: str = "today") -> list[dict[str, Any]]:
    onset_dt = parse_datetime(cap_data.get("onset"))
    expires_dt = parse_datetime(cap_data.get("expires"))
    if not expires_dt:
        return []

    # Descarta tudo que já expirou.
    if expires_dt <= now:
        return []

    status_tempo = "hoje"
    if onset_dt and onset_dt > now:
        status_tempo = "futuro"

    # Comportamento padrão do painel: mostrar apenas os avisos em vigência agora.
    # Se quiser incluir futuros também, use INMET_TIME_FILTER=valid.
    if time_filter == "today" and status_tempo != "hoje":
        return []

    is_active = status_tempo == "hoje"
    severity_raw = cap_data.get("severity")
    severity_label = severity_pt_from_cap(severity_raw)

    common_props = {
        "title": rss_item.get("title") or cap_data.get("headline") or cap_data.get("event") or "Alerta INMET",
        "tipo": "INMET",
        "status": "Ativo" if is_active else "Futuro",
        "status_tempo": status_tempo,
        "is_active": is_active,
        "severidade": severity_label,
        "severity_group": severity_group(severity_raw),
        "evento": cap_data.get("event"),
        "categoria": cap_data.get("category"),
        "headline": cap_data.get("headline"),
        "descricao": cap_data.get("description"),
        "instruction": cap_data.get("instruction"),
        "sender": cap_data.get("sender"),
        "sender_name": cap_data.get("sender_name"),
        "onset": cap_data.get("onset"),
        "expires": cap_data.get("expires"),
        "sent": cap_data.get("sent"),
        "urgency": cap_data.get("urgency"),
        "certainty": cap_data.get("certainty"),
        "response_type": cap_data.get("response_type"),
        "updated_at": now.isoformat(),
        "link": cap_data.get("web") or rss_item.get("link"),
        "source_rss_link": rss_item.get("link"),
        "guid": rss_item.get("guid"),
        "identifier": cap_data.get("identifier"),
        "color_risk": cap_data["parameters"].get("ColorRisk"),
        "municipios": cap_data["parameters"].get("Municipios"),
        "source": "https://apiprevmet3.inmet.gov.br/avisos/rss",
    }

    features: list[dict[str, Any]] = []
    areas = cap_data.get("areas") or []
    for idx, area in enumerate(areas):
        coords = area.get("coords")
        if not coords:
            continue
        props = dict(common_props)
        props.update(
            {
                "area_desc": area.get("area_desc"),
                "area_index": idx,
                "geocodes": area.get("geocodes") or {},
                "polygon_raw": area.get("polygon"),
            }
        )
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Polygon", "coordinates": coords},
            }
        )
    return features


def write_status(payload: dict[str, Any]) -> None:
    write_json("inmet_status.json", payload)


def existing_geojson_exists() -> bool:
    return (DATA_DIR / "inmet_alertas.geojson").exists()


def main() -> None:
    rss_url = os.getenv("INMET_RSS_URL", "https://apiprevmet3.inmet.gov.br/avisos/rss")
    timeout = env_int("REQUEST_TIMEOUT_SEC", 45)
    max_items = env_int("INMET_MAX_ITEMS", 120)
    retries = env_int("INMET_RSS_RETRIES", 4)
    backoff_sec = float(os.getenv("INMET_BACKOFF_SEC", "10").strip() or "10")
    cap_retries = env_int("INMET_CAP_RETRIES", 2)
    cap_backoff_sec = float(os.getenv("INMET_CAP_BACKOFF_SEC", "4").strip() or "4")
    time_filter = (os.getenv("INMET_TIME_FILTER", "today").strip().lower() or "today")

    now = datetime.now(timezone.utc).astimezone()

    try:
        rss_text = fetch_text_with_retry(rss_url, timeout=timeout, retries=retries, backoff_sec=backoff_sec)
    except RateLimitError as exc:
        message = str(exc)
        if existing_geojson_exists():
            print(f"[INMET] {message}. Mantendo camada anterior sem falhar o workflow.")
            write_status(
                {
                    "updated_at": now.isoformat(),
                    "status": "rate_limited",
                    "message": message,
                    "used_cached_geojson": True,
                }
            )
            return
        raise

    rss_items = parse_rss_items(rss_text)[:max_items]

    features: list[dict[str, Any]] = []
    skipped_cap = 0
    without_geometry = 0

    for item in rss_items:
        link = item.get("guid") or item.get("link")
        if not link:
            continue
        try:
            cap_xml = fetch_text_with_retry(link, timeout=timeout, retries=cap_retries, backoff_sec=cap_backoff_sec)
            cap_data = parse_cap_alert(cap_xml)
        except RateLimitError as exc:
            skipped_cap += 1
            print(f"[INMET] CAP ignorado por limite de requisições em {link}: {exc}")
            continue
        except Exception as exc:
            skipped_cap += 1
            print(f"[INMET] aviso ignorado em {link}: {exc}")
            continue

        built = build_features(item, cap_data, now, time_filter=time_filter)
        if not built:
            without_geometry += 1
            continue
        features.extend(built)

    payload = feature_collection(features)
    write_geojson("inmet_alertas.geojson", payload)
    write_status(
        {
            "updated_at": now.isoformat(),
            "status": "ok",
            "time_filter": time_filter,
            "alerts_total": len(features),
            "alerts_without_geometry": without_geometry,
            "caps_ignored": skipped_cap,
            "rss_items_total": len(rss_items),
        }
    )
    print(
        f"Arquivo INMET atualizado com {len(features)} geometrias, "
        f"{without_geometry} alertas sem polígono e {skipped_cap} CAPs ignorados."
    )


if __name__ == "__main__":
    main()
