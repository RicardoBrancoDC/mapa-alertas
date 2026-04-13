from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUT_GEOJSON = DATA_DIR / "inmet_precipitacao.geojson"
OUT_STATUS = DATA_DIR / "inmet_precipitacao_status.json"

MAP_URL = os.getenv("INMET_MAP_URL", "https://mapas.inmet.gov.br/")
ENTIDADES_URL = os.getenv("INMET_ENTIDADES_URL", "https://apimapas.inmet.gov.br/entidades")
MIN_RAIN_MM = float(os.getenv("INMET_PRECIP_MIN_MM", "1"))
TIMEOUT_SEC = int(os.getenv("REQUEST_TIMEOUT_SEC", "30"))
ENTITY_MODE = os.getenv("INMET_PRECIP_ENTITY_MODE", "all").strip().lower()
HEADLESS = os.getenv("INMET_PLAYWRIGHT_HEADLESS", "true").strip().lower() != "false"

BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://mapas.inmet.gov.br",
    "Referer": "https://mapas.inmet.gov.br/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_all_entity_ids() -> list[str]:
    r = requests.get(ENTIDADES_URL, headers=BROWSER_HEADERS, timeout=TIMEOUT_SEC)
    r.raise_for_status()
    payload = r.json()
    ids: list[str] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("value") is not None:
                ids.append(str(item["value"]))
    return ids


def parse_json_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Resposta não veio em JSON válido: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Resposta JSON inesperada da camada de precipitação do INMET.")
    return data


def click_buscar(page) -> None:
    candidates = [
        page.get_by_role("button", name="Buscar"),
        page.get_by_text("Buscar", exact=True),
        page.locator("button:has-text('Buscar')"),
        page.locator("input[type='button'][value='Buscar']"),
        page.locator("input[type='submit'][value='Buscar']"),
        page.locator("text=Buscar"),
    ]

    last_error: Exception | None = None

    for locator in candidates:
        try:
            locator.first.wait_for(state="visible", timeout=10000)
            locator.first.scroll_into_view_if_needed(timeout=5000)
            locator.first.click(timeout=10000, force=True)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    raise RuntimeError(f"Não foi possível clicar no botão Buscar: {last_error}")


def run_browser_capture() -> tuple[dict[str, Any], dict[str, Any]]:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1600, "height": 1200},
        )
        page = context.new_page()

        page.goto(MAP_URL, wait_until="networkidle", timeout=TIMEOUT_SEC * 1000)
        page.wait_for_timeout(8000)

        # garante que a página estabilizou
        try:
            page.locator("body").wait_for(state="visible", timeout=10000)
        except Exception:
            pass

        def trigger_search() -> tuple[dict[str, Any], dict[str, Any]]:
            with page.expect_response(
                lambda r: "apimapas.inmet.gov.br/dados" in r.url and r.request.method.upper() == "POST",
                timeout=TIMEOUT_SEC * 1000,
            ) as response_info:
                click_buscar(page)

            response = response_info.value
            request = response.request
            post_data = request.post_data or "{}"
            payload = json.loads(post_data)
            data = parse_json_text(response.text())
            return payload, data

        last_error: Exception | None = None
        payload: dict[str, Any] | None = None
        data: dict[str, Any] | None = None

        for _ in range(3):
            try:
                payload, data = trigger_search()
                if isinstance(data.get("estacoes"), list):
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                page.wait_for_timeout(3000)

        if payload is None or data is None:
            browser.close()
            raise RuntimeError(f"Não foi possível capturar a requisição /dados do INMET: {last_error}")

        if ENTITY_MODE == "all":
            try:
                all_ids = get_all_entity_ids()
                if all_ids:
                    payload_all = dict(payload)
                    payload_all["entidade"] = all_ids

                    fetch_result = page.evaluate(
                        """
                        async (payload) => {
                          const response = await fetch('https://apimapas.inmet.gov.br/dados', {
                            method: 'POST',
                            headers: {
                              'Accept': 'application/json, text/plain, */*',
                              'Content-Type': 'application/json'
                            },
                            body: JSON.stringify(payload)
                          });
                          return {
                            status: response.status,
                            text: await response.text()
                          };
                        }
                        """,
                        payload_all,
                    )

                    candidate = parse_json_text(fetch_result.get("text", ""))
                    if isinstance(candidate.get("estacoes"), list) and candidate["estacoes"]:
                        payload = payload_all
                        data = candidate
            except Exception as exc:  # noqa: BLE001
                print(f"[INMET PRECIP] Falha ao expandir para todas as entidades, usando resposta padrão: {exc}")

        browser.close()
        return payload, data


def classify_bucket(value: float) -> str:
    if value < 10:
        return "1a10"
    if value < 30:
        return "10a30"
    return "gt30"


def bucket_color(value: float, original_color: str | None) -> str:
    color = (original_color or "").strip()
    if color:
        return color
    if value < 10:
        return "#ffae00"
    if value < 30:
        return "#2f9e44"
    return "#2474d2"


def build_feature(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        value = float(item.get("valor", 0))
        lat = float(item["latitude"])
        lon = float(item["longitude"])
    except Exception:
        return None

    if value <= MIN_RAIN_MM:
        return None

    color = bucket_color(value, item.get("cor"))
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "title": item.get("nome") or item.get("codigo") or "Estação INMET",
            "codigo": item.get("codigo"),
            "nome": item.get("nome"),
            "estado": item.get("estado"),
            "regiao": item.get("regiao"),
            "latitude": lat,
            "longitude": lon,
            "valor": value,
            "valor_mm": value,
            "cor": color,
            "bucket": classify_bucket(value),
            "source": "INMET",
            "categoria": "Precipitação horária",
            "updated_at": now_iso(),
        },
    }


def main() -> None:
    payload, data = run_browser_capture()
    stations = data.get("estacoes")
    if not isinstance(stations, list):
        raise RuntimeError("Resposta do INMET não trouxe a lista de estações.")

    features = []
    for item in stations:
        if not isinstance(item, dict):
            continue
        feature = build_feature(item)
        if feature is not None:
            features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    OUT_GEOJSON.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_STATUS.write_text(
        json.dumps(
            {
                "generated_at": now_iso(),
                "source": "INMET mapas",
                "min_rain_mm": MIN_RAIN_MM,
                "entity_mode": ENTITY_MODE,
                "query_payload": payload,
                "total_returned": len(stations),
                "total_filtered": len(features),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[INMET PRECIP] {len(features)} estações com chuva > {MIN_RAIN_MM} mm salvas em {OUT_GEOJSON}.")


if __name__ == "__main__":
    main()
