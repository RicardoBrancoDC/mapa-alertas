import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    import geobr
    import geopandas as gpd
except Exception as e:
    raise RuntimeError(
        "Dependências ausentes. Instale geobr e geopandas no workflow."
    ) from e

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUT_ESTADOS = DATA_DIR / "cemaden_estados.geojson"
OUT_MUNICIPIOS = DATA_DIR / "cemaden_municipios.geojson"
OUT_ICONES = DATA_DIR / "cemaden_municipios_icones.geojson"
OUT_STATUS = DATA_DIR / "cemaden_status.json"

URL = os.getenv("CEMADEN_URL", "https://painelalertas.cemaden.gov.br/wsAlertas2")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SEC", "30"))

SEVERITY_MAP = {
    "muito alto": ("muito_alto", 3),
    "alto": ("alto", 2),
    "moderado": ("moderado", 1),
}

TYPE_MAP = {
    "hidrol": "hidro",
    "massa": "geo",
}

COLOR_MAP = {
    "muito_alto": "#cf3d32",
    "alto": "#ef8b1e",
    "moderado": "#d6b52b",
}

def severity_group(value: str) -> str:
    key = (value or "").strip().lower()
    return SEVERITY_MAP.get(key, ("moderado", 1))[0]


def severity_rank(value: str) -> int:
    key = (value or "").strip().lower()
    return SEVERITY_MAP.get(key, ("moderado", 1))[1]


def event_type(value: str) -> str:
    txt = (value or "").strip().lower()
    for marker, out in TYPE_MAP.items():
        if marker in txt:
            return out
    return "outro"


def normalize_codibge(value):
    txt = str(value or "").strip()
    if not txt or txt.lower() == "nan":
        return None
    digits = "".join(ch for ch in txt if ch.isdigit())
    if len(digits) >= 7:
        return digits[:7]
    return None


def fetch_alerts():
    response = requests.get(URL, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict):
        items = data.get("alertas", [])
        return items if isinstance(items, list) else []

    if isinstance(data, list):
        return data

    return []


def extract_open_alerts(raw_items):
    items = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for row in raw_items:
        status = str(row.get("status", "")).strip()
        if status != "1":
            continue

        nivel = row.get("nivel") or "Moderado"
        evento = row.get("evento") or ""
        codibge = normalize_codibge(row.get("codibge"))
        municipio = str(row.get("municipio") or "").strip()
        uf = str(row.get("uf") or "").strip().upper()

        items.append({
            "id": str(row.get("cod_alerta") or f"{codibge}-{evento}-{nivel}"),
            "municipio": municipio,
            "codibge": codibge,
            "uf": uf,
            "bacia": "",
            "tipo": event_type(evento),
            "tipo_raw": str(evento).strip(),
            "nivel_raw": str(nivel).strip(),
            "severity_group": severity_group(nivel),
            "severity_rank": severity_rank(nivel),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "created_at": str(row.get("datahoracriacao") or ""),
            "updated_at": str(row.get("ult_atualizacao") or now_iso),
        })
    return items


def load_municipios():
    gdf = geobr.read_municipality(code_muni="all", year=2020, simplified=True)
    cols = [c for c in gdf.columns if c in {"code_muni", "name_muni", "abbrev_state", "geometry"}]
    gdf = gdf[cols].copy()
    gdf["codibge"] = gdf["code_muni"].astype(str).str[:7]
    gdf["municipio_geo"] = gdf["name_muni"].astype(str)
    gdf["uf_geo"] = gdf["abbrev_state"].astype(str)
    return gdf[["codibge", "municipio_geo", "uf_geo", "geometry"]]


def load_estados():
    gdf = geobr.read_state(year=2020, simplified=True)
    cols = [c for c in gdf.columns if c in {"code_state", "abbrev_state", "name_state", "geometry"}]
    gdf = gdf[cols].copy()
    gdf["uf"] = gdf["abbrev_state"].astype(str)
    gdf["coduf"] = gdf["code_state"].astype(int).astype(str).str.zfill(2)
    return gdf[["uf", "coduf", "name_state", "geometry"]]


def empty_gdf(crs):
    return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)


def aggregate_municipios(alerts, muni_gdf):
    by_muni = defaultdict(list)
    for a in alerts:
        if a["codibge"]:
            by_muni[a["codibge"]].append(a)

    rows = []
    icon_rows = []

    for codibge, group in by_muni.items():
        sub = muni_gdf.loc[muni_gdf["codibge"] == codibge]
        if sub.empty:
            continue

        geom = sub.iloc[0].geometry
        top = max(group, key=lambda x: x["severity_rank"])
        tipos = sorted({x["tipo"] for x in group if x["tipo"] != "outro"})
        tem_hidro = "hidro" in tipos
        tem_geo = "geo" in tipos

        row = {
            "codibge": codibge,
            "municipio": sub.iloc[0]["municipio_geo"],
            "uf": sub.iloc[0]["uf_geo"],
            "total_alertas": len(group),
            "nivel_max": top["severity_group"],
            "nivel_max_label": top["nivel_raw"],
            "tem_hidro": tem_hidro,
            "tem_geo": tem_geo,
            "qtd_hidro": sum(1 for x in group if x["tipo"] == "hidro"),
            "qtd_geo": sum(1 for x in group if x["tipo"] == "geo"),
            "tipos": ", ".join(tipos) if tipos else "outro",
            "cor": COLOR_MAP[top["severity_group"]],
            "severity_group": top["severity_group"],
            "alertas": json.dumps(group, ensure_ascii=False),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "geometry": geom,
        }
        rows.append(row)

        rep = geom.representative_point()

        if tem_hidro:
            icon_rows.append({
                "tipo_icone": "hidro",
                "municipio": row["municipio"],
                "uf": row["uf"],
                "codibge": codibge,
                "nivel_max": row["nivel_max"],
                "severity_group": row["severity_group"],
                "total_alertas": row["total_alertas"],
                "geometry": rep,
            })

        if tem_geo:
            icon_rows.append({
                "tipo_icone": "geo",
                "municipio": row["municipio"],
                "uf": row["uf"],
                "codibge": codibge,
                "nivel_max": row["nivel_max"],
                "severity_group": row["severity_group"],
                "total_alertas": row["total_alertas"],
                "geometry": rep,
            })

    gdf_rows = gpd.GeoDataFrame(rows, geometry="geometry", crs=muni_gdf.crs) if rows else empty_gdf(muni_gdf.crs)
    gdf_icons = gpd.GeoDataFrame(icon_rows, geometry="geometry", crs=muni_gdf.crs) if icon_rows else empty_gdf(muni_gdf.crs)

    return gdf_rows, gdf_icons


def aggregate_estados(alerts, estados_gdf):
    by_uf = defaultdict(list)
    for a in alerts:
        if a["uf"]:
            by_uf[a["uf"]].append(a)

    rows = []
    for uf, group in by_uf.items():
        sub = estados_gdf.loc[estados_gdf["uf"] == uf]
        if sub.empty:
            continue

        geom = sub.iloc[0].geometry
        top = max(group, key=lambda x: x["severity_rank"])
        municipios = sorted({f'{x["municipio"]} - {x["uf"]}' for x in group if x["municipio"]})

        rows.append({
            "uf": uf,
            "estado": sub.iloc[0]["name_state"],
            "total_alertas": len(group),
            "municipios_com_alerta": len({x["codibge"] for x in group if x["codibge"]}),
            "nivel_max": top["severity_group"],
            "nivel_max_label": top["nivel_raw"],
            "qtd_hidro": sum(1 for x in group if x["tipo"] == "hidro"),
            "qtd_geo": sum(1 for x in group if x["tipo"] == "geo"),
            "severity_group": top["severity_group"],
            "cor": COLOR_MAP[top["severity_group"]],
            "municipios_lista": ", ".join(municipios[:40]),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "geometry": geom,
        })

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=estados_gdf.crs) if rows else empty_gdf(estados_gdf.crs)


def main():
    raw = fetch_alerts()
    alerts = extract_open_alerts(raw)

    muni_gdf = load_municipios()
    estados_gdf = load_estados()

    gdf_muni, gdf_icons = aggregate_municipios(alerts, muni_gdf)
    gdf_est = aggregate_estados(alerts, estados_gdf)

    gdf_est.to_file(OUT_ESTADOS, driver="GeoJSON")
    gdf_muni.to_file(OUT_MUNICIPIOS, driver="GeoJSON")
    gdf_icons.to_file(OUT_ICONES, driver="GeoJSON")

    OUT_STATUS.write_text(json.dumps({
        "status": "ok",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "alertas_abertos": len(alerts),
        "estados_com_alerta": int(len(gdf_est)),
        "municipios_com_alerta": int(len(gdf_muni)),
        "icones": int(len(gdf_icons)),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[CEMADEN] alertas abertos: {len(alerts)}")
    print(f"[CEMADEN] estados com alerta: {len(gdf_est)}")
    print(f"[CEMADEN] municípios com alerta: {len(gdf_muni)}")
    print(f"[CEMADEN] ícones: {len(gdf_icons)}")


if __name__ == "__main__":
    main()
