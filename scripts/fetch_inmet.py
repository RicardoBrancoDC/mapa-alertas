from __future__ import annotations

from datetime import datetime, timezone

from utils import feature_collection, write_geojson


def main() -> None:
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    payload = feature_collection([
        {
            "type": "Feature",
            "properties": {
                "title": "Perigo potencial de chuva",
                "tipo": "INMET",
                "status": "Ativo",
                "is_active": True,
                "severidade": "Perigo Potencial",
                "severity_group": "perigo_potencial",
                "uf": "SP",
                "updated_at": now_iso,
                "descricao": "Arquivo gerado pelo script base do INMET.",
                "link": "https://alertas2.inmet.gov.br/",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-47.2, -23.0],
                    [-46.2, -23.0],
                    [-46.2, -22.2],
                    [-47.2, -22.2],
                    [-47.2, -23.0],
                ]],
            },
        }
    ])
    write_geojson("inmet_alertas.geojson", payload)
    print("Arquivo INMET atualizado.")


if __name__ == "__main__":
    main()
