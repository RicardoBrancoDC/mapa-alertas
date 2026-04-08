import json
import os
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUT_GEOJSON = DATA_DIR / "inmet_alertas.geojson"
OUT_STATUS = DATA_DIR / "inmet_status.json"

CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}


def now_sp() -> datetime:
    return datetime.now(timezone(timedelta(hours=-3)))


def fetch_text(url: str, timeout: int = 30, retries: int = 2, sleep_sec: float = 4.0) -> str:
    headers = {
        "User-Agent": "mapa-alertas/1.0 (+GitHub Actions)",
        "Accept": "application/xml,text/xml,application/rss+xml,*/*",
    }

    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers=headers)
            text = (resp.text or "").strip()
            if "Você atingiu o limite de requisições" in text:
                raise RuntimeError(f"Limite de requisições atingido em {url}")
            resp.raise_for_status()
            return text
        except Exception as e:
            last_error = e
            if attempt < retries:
                print(f"[INMET] tentativa {attempt + 1} falhou em {url}: {e}. Nova tentativa em {sleep_sec:.1f}s.")
                time.sleep(sleep_sec)
            else:
                raise last_error
    raise RuntimeError(f"Falha inesperada ao buscar {url}")


def write_geojson(features: List[Dict[str, Any]]) -> None:
    fc = {"type": "FeatureCollection", "features": features}
    OUT_GEOJSON.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")


def write_status(payload: Dict[str, Any]) -> None:
    OUT_STATUS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def text_or_none(el: Optional[ET.Element]) -> Optional[str]:
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t or None


def parse_pubdate(pub_date: str) -> Optional[datetime]:
    try:
        return parsedate_to_datetime(pub_date)
    except Exception:
        return None


def same_local_date(dt: datetime, ref: datetime) -> bool:
    try:
        dt_local = dt.astimezone(ref.tzinfo)
    except Exception:
        dt_local = dt
    return dt_local.date() == ref.date()


def parse_cap_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def normalize_level(headline: str, severity_text: str, colorrisk: str) -> str:
    h = (headline or "").lower()
    s = (severity_text or "").lower()
    c = (colorrisk or "").lower()

    if "grande perigo" in h or "grande perigo" in s or c == "#ff0000":
        return "Grande Perigo"
    if "perigo potencial" in h or "perigo potencial" in s or c in {"#fffe00", "#ffff00"}:
        return "Perigo Potencial"
    if "perigo" in h or "perigo" in s or c == "#ffa500":
        return "Perigo"
    return severity_text or "Perigo Potencial"


def inmet_group(level: str) -> str:
    l = (level or "").strip().lower()
    if l == "grande perigo":
        return "grande_perigo"
    if l == "perigo":
        return "perigo"
    return "perigo_potencial"


def cap_polygon_to_geojson_coords(polygon_str: str) -> Optional[List[List[List[float]]]]:
    s = (polygon_str or "").strip()
    if not s:
        return None

    pts = []
    for pair in s.split():
        parts = pair.split(",")
        if len(parts) != 2:
            continue
        try:
            lat = float(parts[0])
            lon = float(parts[1])
        except Exception:
            continue
        pts.append([lon, lat])

    if len(pts) < 3:
        return None

    if pts[0] != pts[-1]:
        pts.append(pts[0])

    return [pts]


def read_cap(url: str, timeout: int) -> Optional[Dict[str, Any]]:
    try:
        xml_text = fetch_text(url, timeout=timeout, retries=1, sleep_sec=4.0)
    except RuntimeError as e:
        if "Limite de requisições" in str(e):
            print(f"[INMET] CAP ignorado por limite de requisições em {url}: {e}")
            return None
        raise

    xml_text = xml_text.lstrip("\ufeff\r\n\t ")
    if not xml_text.startswith("<"):
        print(f"[INMET] CAP ignorado, resposta não parece XML em {url}")
        return None

    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print(f"[INMET] CAP ignorado por erro de parse em {url}: {e}")
        return None

    info = root.find("cap:info", CAP_NS)
    if info is None:
        return None

    areas = info.findall("cap:area", CAP_NS)
    polygons = []
    area_descs = []
    for area in areas:
        area_desc = text_or_none(area.find("cap:areaDesc", CAP_NS)) or ""
        area_descs.append(area_desc)
        polygon_raw = text_or_none(area.find("cap:polygon", CAP_NS))
        coords = cap_polygon_to_geojson_coords(polygon_raw or "")
        if coords:
            polygons.append({"areaDesc": area_desc, "coords": coords})

    if not polygons:
        return None

    parameters = {}
    for p in info.findall("cap:parameter", CAP_NS):
        name = text_or_none(p.find("cap:valueName", CAP_NS)) or ""
        value = text_or_none(p.find("cap:value", CAP_NS)) or ""
        if name:
            parameters[name] = value

    return {
        "identifier": text_or_none(root.find("cap:identifier", CAP_NS)),
        "sender": text_or_none(root.find("cap:sender", CAP_NS)),
        "sent": text_or_none(root.find("cap:sent", CAP_NS)),
        "status": text_or_none(root.find("cap:status", CAP_NS)),
        "msgType": text_or_none(root.find("cap:msgType", CAP_NS)),
        "scope": text_or_none(root.find("cap:scope", CAP_NS)),
        "language": text_or_none(info.find("cap:language", CAP_NS)),
        "category": text_or_none(info.find("cap:category", CAP_NS)),
        "event": text_or_none(info.find("cap:event", CAP_NS)),
        "responseType": text_or_none(info.find("cap:responseType", CAP_NS)),
        "urgency": text_or_none(info.find("cap:urgency", CAP_NS)),
        "severity": text_or_none(info.find("cap:severity", CAP_NS)),
        "certainty": text_or_none(info.find("cap:certainty", CAP_NS)),
        "onset": text_or_none(info.find("cap:onset", CAP_NS)),
        "expires": text_or_none(info.find("cap:expires", CAP_NS)),
        "senderName": text_or_none(info.find("cap:senderName", CAP_NS)),
        "headline": text_or_none(info.find("cap:headline", CAP_NS)),
        "description": text_or_none(info.find("cap:description", CAP_NS)),
        "instruction": text_or_none(info.find("cap:instruction", CAP_NS)),
        "web": text_or_none(info.find("cap:web", CAP_NS)),
        "contact": text_or_none(info.find("cap:contact", CAP_NS)),
        "parameters": parameters,
        "areas": polygons,
        "areaDescs": [x for x in area_descs if x],
    }


def current_time_filter(onset_dt: Optional[datetime], expires_dt: Optional[datetime], mode: str, ref_now: datetime) -> Optional[str]:
    if not expires_dt:
        return None
    if expires_dt <= ref_now:
        return None

    if mode == "today":
        if onset_dt and onset_dt > ref_now:
            return None
        return "hoje"

    if onset_dt and onset_dt > ref_now:
        return "futuro"
    return "hoje"


def parse_rss_items(xml_text: str) -> List[Dict[str, str]]:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    for item in channel.findall("item"):
        title = text_or_none(item.find("title")) or ""
        link = text_or_none(item.find("link")) or ""
        guid = text_or_none(item.find("guid")) or ""
        pub_date = text_or_none(item.find("pubDate")) or ""
        description = text_or_none(item.find("description")) or ""
        items.append({
            "title": title,
            "link": link,
            "guid": guid,
            "pubDate": pub_date,
            "description": description,
        })
    return items


def main() -> None:
    rss_url = os.getenv("INMET_RSS_URL", "https://apiprevmet3.inmet.gov.br/avisos/rss")
    timeout = int(os.getenv("REQUEST_TIMEOUT_SEC", "30"))
    time_filter = os.getenv("INMET_TIME_FILTER", "today").strip().lower()
    ref_now = now_sp()

    try:
        rss_text = fetch_text(rss_url, timeout=timeout, retries=2, sleep_sec=4.0)
    except RuntimeError as e:
        if "Limite de requisições" in str(e):
            print(f"[INMET] Limite de requisições no RSS. Mantendo camada anterior sem falhar.")
            if not OUT_GEOJSON.exists():
                write_geojson([])
            write_status({
                "status": "rate_limited_rss",
                "updated_at": ref_now.isoformat(),
                "rss_url": rss_url,
            })
            return
        raise

    items = parse_rss_items(rss_text)

    items_today = []
    for item in items:
        dt = parse_pubdate(item.get("pubDate", ""))
        if dt and same_local_date(dt, ref_now):
            items_today.append(item)

    features: List[Dict[str, Any]] = []
    caps_lidos = 0
    caps_ignorados_rate_limit = 0

    for item in items_today:
        cap_url = item.get("link") or item.get("guid")
        if not cap_url:
            continue

        cap = read_cap(cap_url, timeout=timeout)
        if cap is None:
            caps_ignorados_rate_limit += 1
            continue

        caps_lidos += 1

        onset_dt = parse_cap_datetime(cap.get("onset"))
        expires_dt = parse_cap_datetime(cap.get("expires"))
        status_tempo = current_time_filter(onset_dt, expires_dt, time_filter, ref_now)
        if status_tempo is None:
            continue

        level = normalize_level(
            cap.get("headline") or item.get("title") or "",
            cap.get("severity") or "",
            (cap.get("parameters") or {}).get("ColorRisk", "")
        )

        for idx, area in enumerate(cap.get("areas", []), start=1):
            features.append({
                "type": "Feature",
                "properties": {
                    "fonte": "INMET",
                    "id": f"{cap.get('identifier') or cap_url}::{idx}",
                    "identifier": cap.get("identifier"),
                    "titulo": item.get("title"),
                    "event": cap.get("event"),
                    "severity": cap.get("severity"),
                    "nivel": level,
                    "nivel_grupo": inmet_group(level),
                    "status_tempo": status_tempo,
                    "onset": cap.get("onset"),
                    "expires": cap.get("expires"),
                    "sent": cap.get("sent"),
                    "pubDate": item.get("pubDate"),
                    "sender": cap.get("sender"),
                    "senderName": cap.get("senderName"),
                    "responseType": cap.get("responseType"),
                    "urgency": cap.get("urgency"),
                    "certainty": cap.get("certainty"),
                    "headline": cap.get("headline"),
                    "description": cap.get("description"),
                    "instruction": cap.get("instruction"),
                    "web": cap.get("web"),
                    "contact": cap.get("contact"),
                    "areaDesc": area.get("areaDesc"),
                    "areas": cap.get("areaDescs", []),
                    "link": cap_url,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": area["coords"],
                },
            })

    write_geojson(features)
    write_status({
        "status": "ok",
        "updated_at": ref_now.isoformat(),
        "rss_url": rss_url,
        "rss_items_total": len(items),
        "rss_items_pubdate_hoje": len(items_today),
        "caps_lidos": caps_lidos,
        "caps_ignorados_rate_limit": caps_ignorados_rate_limit,
        "features": len(features),
        "time_filter": time_filter,
    })

    print(f"[INMET] RSS total: {len(items)}")
    print(f"[INMET] Itens com pubDate de hoje: {len(items_today)}")
    print(f"[INMET] CAPs lidos: {caps_lidos}")
    print(f"[INMET] Features geradas: {len(features)}")


if __name__ == "__main__":
    main()
