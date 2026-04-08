from __future__ import annotations

from utils import feature_collection, write_geojson


def main() -> None:
    payload = feature_collection([
        {
            "type": "Feature",
            "properties": {
                "title": "Estação hidrológica SGB",
                "nome": "Estação de exemplo",
                "tipo": "SGB",
                "status": "Monitoramento",
                "is_active": True,
                "municipio": "Manaus",
                "uf": "AM",
                "descricao": "Arquivo gerado pelo script base do SGB.",
                "link": "https://www.sgb.gov.br/",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-60.025, -3.119],
            },
        }
    ])
    write_geojson("sgb_estacoes.geojson", payload)
    print("Arquivo SGB atualizado.")


if __name__ == "__main__":
    main()
