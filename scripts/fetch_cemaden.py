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
    raise RuntimeError("Dependências ausentes. Instale geobr e geopandas no workflow.") from e

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUT_ESTADOS = DATA_DIR / "cemaden_estados.geojson"
OUT_MUNICIPIOS = DATA_DIR / "cemaden_municipios.geojson"
OUT_ICONES = DATA_DIR / "cemaden_municipios_icones.geojson"
OUT_STATUS = DATA_DIR / "cemaden_status.json"

URL = os.getenv("CEMADEN_URL", "https://painelalertas.cemaden.gov.br/wsAlertas2")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SEC", "30"))

SEVERITY_MAP = {"muito alto": ("muito_alto", 3), "alto": ("alto", 2), "moderado": ("moderado", 1)}
TYPE_MAP = {"hidrol": "hidro", "massa": "geo"}
COLOR_MAP = {"muito_alto": "#cf3d32", "alto": "#ef8b1e", "moderado": "#d6b52b"}
STATE_CODE_TO_UF = {11:"RO",12:"AC",13:"AM",14:"RR",15:"PA",16:"AP",17:"TO",21:"MA",22:"PI",23:"CE",24:"RN",25:"PB",26:"PE",27:"AL",28:"SE",29:"BA",31:"MG",32:"ES",33:"RJ",35:"SP",41:"PR",42:"SC",43:"RS",50:"MS",51:"MT",52:"GO",53:"DF"}

def severity_group(value):
    return SEVERITY_MAP.get((value or "").strip().lower(), ("moderado", 1))[0]

def severity_rank(value):
    return SEVERITY_MAP.get((value or "").strip().lower(), ("moderado", 1))[1]

def event_type(value):
    txt = (value or "").strip().lower()
    for marker, out in TYPE_MAP.items():
        if marker in txt:
            return out
    return "outro"

def normalize_codibge(value):
    txt = str(value or "").strip()
    digits = "".join(ch for ch in txt if ch.isdigit())
    return digits[:7] if len(digits) >= 7 else None

def fetch_alerts():
    r = requests.get(URL, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []

def extract_open_alerts(raw_items):
    items = []
    now = datetime.now(timezone.utc).isoformat()
    for row in raw_items:
        if str(row.get("status", "")).strip() != "1":
            continue
        nivel = row.get("nome_alerta") or row.get("nivel") or row.get("grau") or "Moderado"
        tipo_base = row.get("tipo") or row.get("tipo_alerta") or row.get("evento") or row.get("descricao") or row.get("nome_alerta") or ""
        codibge = normalize_codibge(row.get("codibge")) or normalize_codibge(row.get("cod_municipio")) or normalize_codibge(row.get("ibge"))
        uf = str(row.get("uf") or row.get("sigla_uf") or "").strip().upper()
        if not uf and codibge:
            uf = STATE_CODE_TO_UF.get(int(codibge[:2]), "")
        items.append({
            "id": str(row.get("id") or row.get("cod_alerta") or f"{codibge}-{tipo_base}-{nivel}"),
            "municipio": str(row.get("nome_pm") or row.get("municipio") or row.get("nome") or "").strip(),
            "codibge": codibge,
            "uf": uf,
            "bacia": str(row.get("nome_bacia") or "").strip(),
            "tipo": event_type(tipo_base),
            "tipo_raw": str(tipo_base).strip(),
            "nivel_raw": str(nivel).strip(),
            "severity_group": severity_group(nivel),
            "severity_rank": severity_rank(nivel),
            "updated_at": now,
        })
    return items

def load_municipios():
    gdf = geobr.read_municipality(code_muni="all", year=2020, simplified=True)
    gdf["codibge"] = gdf["code_muni"].astype(str).str[:7]
    gdf["municipio_geo"] = gdf["name_muni"].astype(str)
    gdf["uf_geo"] = gdf["abbrev_state"].astype(str)
    return gdf[["codibge", "municipio_geo", "uf_geo", "geometry"]]

def load_estados():
    gdf = geobr.read_state(year=2020, simplified=True)
    gdf["uf"] = gdf["abbrev_state"].astype(str)
    gdf["coduf"] = gdf["code_state"].astype(int).astype(str).str.zfill(2)
    return gdf[["uf", "coduf", "name_state", "geometry"]]

def aggregate_municipios(alerts, muni_gdf):
    by_muni = defaultdict(list)
    for a in alerts:
        if a["codibge"]:
            by_muni[a["codibge"]].append(a)
    rows, icon_rows = [], []
    for codibge, group in by_muni.items():
        sub = muni_gdf.loc[muni_gdf["codibge"] == codibge]
        if sub.empty:
            continue
        geom = sub.iloc[0].geometry
        top = max(group, key=lambda x: x["severity_rank"])
        tipos = sorted({x["tipo"] for x in group if x["tipo"] != "outro"})
        tem_hidro = "hidro" in tipos
        tem_geo = "geo" in tipos
        row = {"codibge": codibge, "municipio": sub.iloc[0]["municipio_geo"], "uf": sub.iloc[0]["uf_geo"],
               "total_alertas": len(group), "nivel_max": top["severity_group"], "nivel_max_label": top["nivel_raw"],
               "tem_hidro": tem_hidro, "tem_geo": tem_geo, "qtd_hidro": sum(1 for x in group if x["tipo"] == "hidro"),
               "qtd_geo": sum(1 for x in group if x["tipo"] == "geo"), "tipos": ", ".join(tipos) if tipos else "outro",
               "cor": COLOR_MAP[top["severity_group"]], "severity_group": top["severity_group"],
               "alertas": json.dumps(group, ensure_ascii=False), "updated_at": datetime.now(timezone.utc).isoformat()}
        rows.append({**row, "geometry": geom})
        rep = geom.representative_point()
        if tem_hidro:
            icon_rows.append({"tipo_icone": "hidro", "municipio": row["municipio"], "uf": row["uf"], "codibge": codibge,
                              "nivel_max": row["nivel_max"], "severity_group": row["severity_group"], "total_alertas": row["total_alertas"], "geometry": rep})
        if tem_geo:
            icon_rows.append({"tipo_icone": "geo", "municipio": row["municipio"], "uf": row["uf"], "codibge": codibge,
                              "nivel_max": row["nivel_max"], "severity_group": row["severity_group"], "total_alertas": row["total_alertas"], "geometry": rep})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=muni_gdf.crs), gpd.GeoDataFrame(icon_rows, geometry="geometry", crs=muni_gdf.crs)

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
        top = max(group, key=lambda x: x["severity_rank"])
        municipios = sorted({f'{x["municipio"]} - {x["uf"]}' for x in group if x["municipio"]})
        rows.append({"uf": uf, "estado": sub.iloc[0]["name_state"], "total_alertas": len(group),
                     "municipios_com_alerta": len({x["codibge"] for x in group if x["codibge"]}),
                     "nivel_max": top["severity_group"], "nivel_max_label": top["nivel_raw"],
                     "qtd_hidro": sum(1 for x in group if x["tipo"] == "hidro"),
                     "qtd_geo": sum(1 for x in group if x["tipo"] == "geo"),
                     "severity_group": top["severity_group"], "cor": COLOR_MAP[top["severity_group"]],
                     "municipios_lista": ", ".join(municipios[:40]), "updated_at": datetime.now(timezone.utc).isoformat(),
                     "geometry": sub.iloc[0].geometry})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=estados_gdf.crs)

def main():
    alerts = extract_open_alerts(fetch_alerts())
    muni_gdf = load_municipios()
    estados_gdf = load_estados()
    gdf_muni, gdf_icons = aggregate_municipios(alerts, muni_gdf)
    gdf_est = aggregate_estados(alerts, estados_gdf)
    if gdf_est.empty: gdf_est = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=estados_gdf.crs)
    if gdf_muni.empty: gdf_muni = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=muni_gdf.crs)
    if gdf_icons.empty: gdf_icons = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=muni_gdf.crs)
    gdf_est.to_file(OUT_ESTADOS, driver="GeoJSON")
    gdf_muni.to_file(OUT_MUNICIPIOS, driver="GeoJSON")
    gdf_icons.to_file(OUT_ICONES, driver="GeoJSON")
    OUT_STATUS.write_text(json.dumps({"status":"ok","updated_at":datetime.now(timezone.utc).isoformat(),"alertas_abertos":len(alerts),
                                      "estados_com_alerta":0 if gdf_est.empty else int(len(gdf_est)),
                                      "municipios_com_alerta":0 if gdf_muni.empty else int(len(gdf_muni)),
                                      "icones":0 if gdf_icons.empty else int(len(gdf_icons))}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[CEMADEN] alertas abertos: {len(alerts)}")
    print(f"[CEMADEN] estados com alerta: {0 if gdf_est.empty else len(gdf_est)}")
    print(f"[CEMADEN] municípios com alerta: {0 if gdf_muni.empty else len(gdf_muni)}")
    print(f"[CEMADEN] ícones: {0 if gdf_icons.empty else len(gdf_icons)}")

if __name__ == "__main__":
    main()
