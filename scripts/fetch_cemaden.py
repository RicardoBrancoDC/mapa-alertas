from __future__ import annotations

from utils import feature_collection, write_geojson


def main() -> None:
    hidro = feature_collection([
        {
            "type": "Feature",
            "properties": {
                "title": "Alerta hidrológico",
                "tipo": "CEMADEN",
                "status": "Ativo",
                "is_active": True,
                "municipio": "São Paulo",
                "uf": "SP",
                "descricao": "Arquivo gerado pelo script base do CEMADEN.",
                "link": "https://painelalertas.cemaden.gov.br/wsAlertas2",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-46.6333, -23.5505],
            },
        }
    ])

    geo = feature_collection([
        {
            "type": "Feature",
            "properties": {
                "title": "Alerta geológico",
                "tipo": "CEMADEN",
                "status": "Ativo",
                "is_active": True,
                "municipio": "Nova Friburgo",
                "uf": "RJ",
                "descricao": "Arquivo gerado pelo script base do CEMADEN.",
                "link": "https://painelalertas.cemaden.gov.br/wsAlertas2",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-42.5310, -22.2817],
            },
        }
    ])

    write_geojson("cemaden_hidro.geojson", hidro)
    write_geojson("cemaden_geo.geojson", geo)
    print("Arquivos CEMADEN atualizados.")


if __name__ == "__main__":
    main()
