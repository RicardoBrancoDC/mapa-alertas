from __future__ import annotations

import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any

from utils import BASE_DIR, DATA_DIR, feature_collection, write_geojson, write_json

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}

RSS_URL = os.getenv("RSS_URL", "https://idapfile.mdr.gov.br/idap/api/rss/cap")
HISTORY_PATH = Path(os.getenv("HISTORY_PATH", str(BASE_DIR / ".cache" / "historico_alertas_idap.json")))
WINDOW_HOURS = int(os.getenv("WINDOW_HOURS", "24"))
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "72"))
REQUEST_TIMEOUT_SEC = int(os.getenv("REQUEST_TIMEOUT_SEC", "45"))
LOCAL_TZ = timezone(timedelta(hours=-3))
CATALOG_PATH = DATA_DIR / "catalogo_camadas.json"

UF_PATTERN = re.compile(r"\b([A-Z]{2})\b")
UF_SET = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"
}


class AlertRecord(dict):
    pass


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone(LOCAL_TZ)


def safe_text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    txt = elem.text.strip()
    return txt or None


def first(elem: ET.Element, path: str, ns: dict[str, str]) -> ET.Element | None:
    return elem.find(path, ns)


def all_nodes(elem: ET.Element, path: str, ns: dict[str, str]) -> list[ET.Element]:
    return elem.findall(path, ns)


def parse_iso_any(value: str | None) -> datetime | None:
    if not value:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def calc_nivel(severity: str, urgency: str, certainty: str, response_type: str) -> str:
    s = (severity or "").strip()
    u = (urgency or "").strip()
    c = (certainty or "").strip()
    r = (response_type or "").strip()

    if s == "Extreme":
        if u == "Immediate" and c in {"Likely", "Observed"} and r in {"Evacuate", "Shelter", "Execute"}:
            return "Extremo"
        return "Severo"
    if s == "Severe":
        return "Alto"
    if s == "Moderate":
        return "Médio"
    if s == "Minor":
        return "Baixo"
    return "Indefinido"


def guess_uf(*values: str | None) -> str:
    for value in values:
        if not value:
            continue
        upper = value.upper()
        found = UF_PATTERN.findall(upper)
        for uf in found:
            if uf in UF_SET:
                return uf
    return ""


def parse_polygon_geometry(poly_str: str | None) -> dict[str, Any] | None:
    if not poly_str:
        return None
    pts: list[list[float]] = []
    for token in poly_str.strip().split():
        if "," not in token:
            continue
        lat_txt, lon_txt = token.split(",", 1)
        try:
            lat = float(lat_txt)
            lon = float(lon_txt)
        except Exception:
            continue
        pts.append([lon, lat])

    if len(pts) >= 3:
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        return {"type": "Polygon", "coordinates": [pts]}

    if len(pts) == 1:
        return {"type": "Point", "coordinates": pts[0]}

    if len(pts) == 2:
        center = [round((pts[0][0] + pts[1][0]) / 2, 6), round((pts[0][1] + pts[1][1]) / 2, 6)]
        return {"type": "Point", "coordinates": center}

    return None


def extract_cap_xml_from_entry(entry: ET.Element) -> ET.Element | None:
    content = first(entry, "atom:content", ATOM_NS)
    if content is None:
        return None

    for child in list(content):
        if child.tag.endswith("alert"):
            return child

    raw = (content.text or "").strip()
    if not raw:
        return None

    candidates = [raw, unescape(raw)]
    for candidate in candidates:
        try:
            root = ET.fromstring(candidate)
        except Exception:
            continue
        if root.tag.endswith("alert"):
            return root
    return None


def cap_get_parameter(info_elem: ET.Element, value_name: str) -> str | None:
    for p in all_nodes(info_elem, "cap:parameter", CAP_NS):
        vn = safe_text(first(p, "cap:valueName", CAP_NS))
        if vn and vn.strip().upper() == value_name.strip().upper():
            return safe_text(first(p, "cap:value", CAP_NS))
    return None


def extract_ibge(area_elem: ET.Element | None) -> str:
    if area_elem is None:
        return ""
    for gc in all_nodes(area_elem, "cap:geocode", CAP_NS):
        name = safe_text(first(gc, "cap:valueName", CAP_NS)) or ""
        value = safe_text(first(gc, "cap:value", CAP_NS)) or ""
        if "IBGE" in name.upper():
            return value.strip()
    return ""


def parse_entry(entry: ET.Element) -> AlertRecord | None:
    cap_alert = extract_cap_xml_from_entry(entry)
    if cap_alert is None:
        return None

    entry_id = safe_text(first(entry, "atom:id", ATOM_NS)) or "UNKNOWN"
    identifier = safe_text(first(cap_alert, "cap:identifier", CAP_NS)) or entry_id
    sender = safe_text(first(cap_alert, "cap:sender", CAP_NS))
    sent = safe_text(first(cap_alert, "cap:sent", CAP_NS))
    status_cap = safe_text(first(cap_alert, "cap:status", CAP_NS))
    msg_type = safe_text(first(cap_alert, "cap:msgType", CAP_NS))

    info = first(cap_alert, "cap:info", CAP_NS)
    if info is None:
        infos = all_nodes(cap_alert, "cap:info", CAP_NS)
        info = infos[0] if infos else None
    if info is None:
        return None

    category = safe_text(first(info, "cap:category", CAP_NS))
    event = safe_text(first(info, "cap:event", CAP_NS))
    response_type = safe_text(first(info, "cap:responseType", CAP_NS))
    urgency = safe_text(first(info, "cap:urgency", CAP_NS))
    severity = safe_text(first(info, "cap:severity", CAP_NS))
    certainty = safe_text(first(info, "cap:certainty", CAP_NS))
    onset = safe_text(first(info, "cap:onset", CAP_NS))
    expires = safe_text(first(info, "cap:expires", CAP_NS))
    sender_name = safe_text(first(info, "cap:senderName", CAP_NS))
    headline = safe_text(first(info, "cap:headline", CAP_NS))
    description = safe_text(first(info, "cap:description", CAP_NS))
    instruction = safe_text(first(info, "cap:instruction", CAP_NS))
    web = safe_text(first(info, "cap:web", CAP_NS))
    contact = safe_text(first(info, "cap:contact", CAP_NS))
    channel_list = cap_get_parameter(info, "CHANNEL-LIST")

    area = first(info, "cap:area", CAP_NS)
    area_desc = safe_text(first(area, "cap:areaDesc", CAP_NS)) if area is not None else None
    polygon_raw = safe_text(first(area, "cap:polygon", CAP_NS)) if area is not None else None
    ibge = extract_ibge(area)
    geometry = parse_polygon_geometry(polygon_raw)

    return AlertRecord(
        identifier=identifier,
        entry_id=entry_id,
        sender=sender,
        senderName=sender_name,
        sent=sent,
        status_cap=status_cap,
        msgType=msg_type,
        category=category,
        event=event,
        responseType=response_type,
        urgency=urgency,
        severity=severity,
        certainty=certainty,
        onset=onset,
        expires=expires,
        nivel=calc_nivel(severity or "", urgency or "", certainty or "", response_type or ""),
        headline=headline,
        description=description,
        instruction=instruction,
        web=web,
        contact=contact,
        channel_list=channel_list,
        areaDesc=area_desc,
        polygon_raw=polygon_raw,
        codibge=ibge,
        uf=guess_uf(area_desc, sender_name),
        geometry=geometry,
    )


def read_url_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/atom+xml,application/xml,text/xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        return resp.read()


def load_history(path: Path) -> list[AlertRecord]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    alerts: list[AlertRecord] = []
    for item in raw:
        if isinstance(item, dict):
            alerts.append(AlertRecord(item))
    return alerts


def save_history(path: Path, alerts: list[AlertRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_history(existing: list[AlertRecord], new_alerts: list[AlertRecord]) -> list[AlertRecord]:
    merged: dict[str, AlertRecord] = {}
    for alert in existing:
        key = (alert.get("entry_id") or alert.get("identifier") or "").strip()
        if key:
            merged[key] = alert
    for alert in new_alerts:
        key = (alert.get("entry_id") or alert.get("identifier") or "").strip()
        if key:
            merged[key] = alert
    def sort_key(alert: AlertRecord) -> datetime:
        return parse_iso_any(alert.get("onset")) or parse_iso_any(alert.get("sent")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    items = list(merged.values())
    items.sort(key=sort_key)
    return items


def filter_recent(alerts: list[AlertRecord], hours: int, ref_now: datetime) -> list[AlertRecord]:
    cutoff = ref_now.astimezone(timezone.utc) - timedelta(hours=hours)
    selected: list[AlertRecord] = []
    for alert in alerts:
        ref_dt = parse_iso_any(alert.get("onset")) or parse_iso_any(alert.get("sent"))
        if ref_dt is not None and ref_dt >= cutoff:
            selected.append(alert)
    return selected


def classify_runtime_status(alert: AlertRecord, ref_now: datetime) -> tuple[str, bool]:
    onset_dt = parse_iso_any(alert.get("onset")) or parse_iso_any(alert.get("sent"))
    expires_dt = parse_iso_any(alert.get("expires"))
    if onset_dt and onset_dt > ref_now:
        return "Futuro", False
    if expires_dt:
        return ("Ativo", True) if expires_dt >= ref_now else ("Inativo", False)
    return "Sem validade", True


def build_feature(alert: AlertRecord, runtime_status: str, is_active: bool, updated_at: str) -> dict[str, Any] | None:
    geometry = alert.get("geometry")
    if not geometry:
        return None

    title = alert.get("headline") or alert.get("event") or alert.get("senderName") or "Alerta IDAP"
    description_parts = []
    if alert.get("description"):
        description_parts.append(str(alert.get("description")))
    if alert.get("instruction"):
        description_parts.append(f"Instruções: {alert.get('instruction')}")

    return {
        "type": "Feature",
        "properties": {
            "id": alert.get("identifier") or alert.get("entry_id"),
            "title": title,
            "nome": title,
            "tipo": "IDAP",
            "categoria": alert.get("category") or "Met",
            "status": runtime_status,
            "status_cap": alert.get("status_cap") or "",
            "is_active": is_active,
            "municipio": alert.get("areaDesc") or "",
            "uf": alert.get("uf") or "",
            "codibge": alert.get("codibge") or "",
            "evento": alert.get("event") or "",
            "evento_tipo": alert.get("event") or "",
            "severidade": alert.get("nivel") or "Indefinido",
            "severity_group": str(alert.get("nivel") or "indefinido").lower().replace(" ", "_"),
            "urgency": alert.get("urgency") or "",
            "severity": alert.get("severity") or "",
            "certainty": alert.get("certainty") or "",
            "sender_name": alert.get("senderName") or "",
            "sender": alert.get("sender") or "",
            "channel_list": alert.get("channel_list") or "",
            "onset": alert.get("onset") or alert.get("sent") or "",
            "sent": alert.get("sent") or "",
            "expires": alert.get("expires") or "",
            "updated_at": updated_at,
            "descricao": "\n\n".join(description_parts).strip(),
            "link": alert.get("web") or RSS_URL,
            "fonte": RSS_URL,
        },
        "geometry": geometry,
    }


def update_catalog_timestamp(updated_at: str) -> None:
    if not CATALOG_PATH.exists():
        return
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    payload["generated_at"] = updated_at
    write_json("catalogo_camadas.json", payload)


def main() -> None:
    rss_bytes = read_url_bytes(RSS_URL)
    root = ET.fromstring(rss_bytes)
    entries = all_nodes(root, "atom:entry", ATOM_NS)

    feed_alerts: list[AlertRecord] = []
    for entry in entries:
        alert = parse_entry(entry)
        if alert is not None:
            feed_alerts.append(alert)

    ref_now = now_local()
    updated_at = ref_now.isoformat()

    history_before = load_history(HISTORY_PATH)
    history_merged = merge_history(history_before, feed_alerts)
    history_kept = filter_recent(history_merged, RETENTION_HOURS, ref_now)
    alerts_24h = filter_recent(history_kept, WINDOW_HOURS, ref_now)

    ativos: list[dict[str, Any]] = []
    inativos: list[dict[str, Any]] = []
    skipped_without_geometry = 0

    for alert in alerts_24h:
        runtime_status, is_active = classify_runtime_status(alert, ref_now)
        feature = build_feature(alert, runtime_status, is_active, updated_at)
        if feature is None:
            skipped_without_geometry += 1
            continue
        if is_active:
            ativos.append(feature)
        else:
            inativos.append(feature)

    save_history(HISTORY_PATH, history_kept)
    write_geojson("idap_ativos.geojson", feature_collection(ativos))
    write_geojson("idap_inativos.geojson", feature_collection(inativos))
    update_catalog_timestamp(updated_at)

    print(f"IDAP feed lido: {len(feed_alerts)} alertas parseados.")
    print(f"IDAP histórico preservado: {len(history_kept)} alertas.")
    print(f"IDAP últimas {WINDOW_HOURS}h: {len(alerts_24h)} alertas.")
    print(f"IDAP ativos gravados: {len(ativos)} feições.")
    print(f"IDAP inativos gravados: {len(inativos)} feições.")
    print(f"IDAP sem geometria aproveitável: {skipped_without_geometry} alertas.")


if __name__ == "__main__":
    main()
