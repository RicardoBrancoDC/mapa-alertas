from __future__ import annotations

import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from utils import feature_collection, write_geojson

RSS_NSLESS_ITEM = "item"
CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
MUNI_CODE_RE = re.compile(r"\((\d{7})\)")


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

    if "<" not in text[:200] and "xml" not in content_type and "rss" not in content_type:
        preview = text[:120].replace("\n", " ").replace("\r", " ")
        raise ValueError(f"Resposta não parece XML em {url}: {preview}")

    return text


def text_or_none(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    txt = value.strip()
    try:
        return datetime.fromisoformat(txt)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(txt)
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


def parse_municipio_codes(parameters: dict[str, str]) -> list[str]:
    raw = parameters.get("Municipios", "")
    if not raw:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for code in MUNI_CODE_RE.findall(raw):
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return ordered


def load_municipal_seats(codes: list[str]) -> dict[str, tuple[float, float]]:
    if not codes:
        return {}

    try:
        from geobr import read_municipal_seat  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Dependência geobr não encontrada. Instale geobr no workflow para gerar a camada do INMET."
        ) from exc

    gdf = read_municipal_seat(code_muni="all", year=2010)

    lookup: dict[str, tuple[float, float]] = {}
    code_set = set(codes)
    for _, row in gdf.iterrows():
        code = str(row.get("code_muni", "")).strip()
        if code not in code_set:
            continue
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        lookup[code] = (float(geom.x), float(geom.y))
    return lookup


def parse_rss_items(rss_text: str) -> list[dict[str, str | None]]:
    root = ET.fromstring(rss_text)
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[dict[str, str | None]] = []
    for item in channel.findall(RSS_NSLESS_ITEM):
        items.append(
            {
                "title": text_or_none(item.find("title")),
                "link": text_or_none(item.find("link")),
                "guid": text_or_none(item.find("guid")),
                "pubDate": text_or_none(item.find("pubDate")),
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

    parameters = parse_parameters(info)
    municipio_codes = parse_municipio_codes(parameters)

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
        "municipio_codes": municipio_codes,
    }


def build_feature(
    rss_item: dict[str, Any],
    cap_data: dict[str, Any],
    seat_lookup: dict[str, tuple[float, float]],
    now: datetime,
) -> dict[str, Any] | None:
    coords = [seat_lookup[code] for code in cap_data["municipio_codes"] if code in seat_lookup]
    if not coords:
        return None

    expires_dt = parse_datetime(cap_data.get("expires"))
    is_active = bool(expires_dt and expires_dt >= now)
    severity_raw = cap_data.get("severity")
    severity_label = severity_pt_from_cap(severity_raw)

    properties = {
        "title": rss_item.get("title") or cap_data.get("headline") or cap_data.get("event") or "Alerta INMET",
        "tipo": "INMET",
        "status": "Ativo" if is_active else "Inativo",
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
        "municipios_total": len(cap_data["municipio_codes"]),
        "source": "https://apiprevmet3.inmet.gov.br/avisos/rss",
    }

    geometry = {
        "type": "MultiPoint",
        "coordinates": [[lon, lat] for lon, lat in coords],
    }

    return {"type": "Feature", "properties": properties, "geometry": geometry}


def main() -> None:
    rss_url = os.getenv("INMET_RSS_URL", "https://apiprevmet3.inmet.gov.br/avisos/rss")
    timeout = env_int("REQUEST_TIMEOUT_SEC", 45)
    max_items = env_int("INMET_MAX_ITEMS", 120)

    now = datetime.now(timezone.utc).astimezone()
    rss_text = fetch_text(rss_url, timeout=timeout)
    rss_items = parse_rss_items(rss_text)[:max_items]

    cap_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    all_codes: list[str] = []
    seen_codes: set[str] = set()

    skipped_cap = 0
    for item in rss_items:
        link = item.get("link")
        if not link:
            continue
        try:
            cap_xml = fetch_text(link, timeout=timeout)
            cap_data = parse_cap_alert(cap_xml)
        except Exception as exc:
            skipped_cap += 1
            print(f"[INMET] aviso ignorado em {link}: {exc}")
            continue
        cap_records.append((item, cap_data))
        for code in cap_data["municipio_codes"]:
            if code not in seen_codes:
                seen_codes.add(code)
                all_codes.append(code)

    seat_lookup = load_municipal_seats(all_codes)

    features: list[dict[str, Any]] = []
    skipped = 0
    for item, cap_data in cap_records:
        feature = build_feature(item, cap_data, seat_lookup, now)
        if feature is None:
            skipped += 1
            continue
        features.append(feature)

    payload = feature_collection(features)
    write_geojson("inmet_alertas.geojson", payload)
    print(
        f"Arquivo INMET atualizado com {len(features)} alertas, "
        f"{skipped} alertas sem geometria e {skipped_cap} CAPs ignorados."
    )


if __name__ == "__main__":
    main()
