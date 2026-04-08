from __future__ import annotations

from datetime import datetime, timezone

from utils import feature_collection, write_geojson


def build_demo_payload() -> tuple[dict, dict]:
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()

    ativos = feature_collection([
        {
            "type": "Feature",
            "properties": {
                "title": "Chuvas intensas em Petrópolis",
                "tipo": "IDAP",
                "status": "Ativo",
                "is_active": True,
                "municipio": "Petrópolis",
                "uf": "RJ",
                "onset": now_iso,
                "expires": now_iso,
                "descricao": "Arquivo gerado pelo script base de IDAP.",
                "link": "https://idapfile.mdr.gov.br/idap/api/rss/cap",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-43.1782, -22.5098],
            },
        }
    ])

    inativos = feature_collection([
        {
            "type": "Feature",
            "properties": {
                "title": "Alerta encerrado em Belo Horizonte",
                "tipo": "IDAP",
                "status": "Inativo",
                "is_active": False,
                "municipio": "Belo Horizonte",
                "uf": "MG",
                "onset": now_iso,
                "expires": now_iso,
                "descricao": "Arquivo gerado pelo script base de IDAP.",
                "link": "https://idapfile.mdr.gov.br/idap/api/rss/cap",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-43.9386, -19.9208],
            },
        }
    ])

    return ativos, inativos


def main() -> None:
    ativos, inativos = build_demo_payload()
    write_geojson("idap_ativos.geojson", ativos)
    write_geojson("idap_inativos.geojson", inativos)
    print("Arquivos IDAP atualizados.")


if __name__ == "__main__":
    main()
