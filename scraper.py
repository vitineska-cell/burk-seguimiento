#!/usr/bin/env python3
"""
Scraper de seguimiento BÜRK para Pickle Pro Tour (pickleprotour.com).

Qué hace:
1. Lee jugadores.json (torneo activo + lista de jugadores BÜRK).
2. Abre la pestaña "Grupos y Cuadros" del torneo (se carga con JavaScript,
   por eso usamos un navegador real -Playwright- en vez de un simple fetch).
3. Visita cada grupo encontrado y extrae la tabla de partidos (esa parte SÍ
   es HTML normal, no hace falta JavaScript para leerla).
4. Filtra los partidos donde aparece alguno de los jugadores BÜRK.
5. Guarda todo en docs/resultados.json, que es lo que lee el panel web.

Nota para Víctor / futuras sesiones con Claude:
El paso 2 (encontrar los grupos) es la parte más frágil, porque depende de
cómo pickleprotour.com organiza esa pestaña internamente y no se pudo
probar en vivo antes de la primera ejecución real. Si el workflow de
GitHub Actions falla o encuentra 0 grupos, copia el log de "Actions" y
pégaselo a Claude: con eso se ajusta en minutos.
"""

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://pickleprotour.com"
ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "jugadores.json"
OUTPUT_PATH = ROOT / "docs" / "resultados.json"


def normalizar(texto: str) -> str:
    """Quita acentos/mayúsculas para poder comparar nombres sin depender de tildes."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.lower().strip()


def cargar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def encontrar_urls_de_grupo(page, torneo_id: int) -> list[str]:
    """
    Abre la pestaña 'Grupos y Cuadros' (JavaScript) y devuelve todas las URLs
    tipo torneogrupo.aspx?... encontradas en la página ya renderizada.
    """
    url = f"{BASE_URL}/torneo.aspx?id={torneo_id}&tab=panel-cuadros"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)

    try:
        page.wait_for_selector("a[href*='torneogrupo.aspx']", timeout=15000)
    except Exception:
        print("⚠️  No aparecieron enlaces a grupos tras esperar 15s.")
        print("   La estructura de la web puede haber cambiado.")
        print("   URL comprobada:", url)
        return []

    hrefs = page.eval_on_selector_all(
        "a[href*='torneogrupo.aspx']", "els => els.map(e => e.href)"
    )
    return sorted(set(hrefs))


def extraer_partidos_de_grupo(html: str, torneo_nombre: str = "") -> tuple[str, list[dict]]:
    """
    Dado el HTML de una página torneogrupo.aspx, devuelve (categoria, partidos).
    El título de la página tiene el formato:
      "{Torneo} GRUPO {N} {categoría completa} | Pickle Pro Tour"
    """
    soup = BeautifulSoup(html, "html.parser")

    titulo = soup.title.get_text(strip=True) if soup.title else ""
    categoria = titulo.split("|")[0].strip()
    if torneo_nombre and categoria.startswith(torneo_nombre):
        categoria = categoria[len(torneo_nombre):].strip()

    partidos = []
    tabla = soup.find("table")
    if tabla:
        filas = tabla.find_all("tr")[1:]  # saltar cabecera (Pareja 1 / Pareja 2 / ...)
        for fila in filas:
            celdas = [c.get_text(strip=True) for c in fila.find_all("td")]
            if len(celdas) >= 4:
                partidos.append(
                    {
                        "pareja1": celdas[0],
                        "pareja2": celdas[1],
                        "horario_pista": celdas[2],
                        "resultado": celdas[3],
                    }
                )
    return categoria, partidos


def jugador_en_texto(nombre_jugador: str, texto_pareja: str) -> bool:
    return normalizar(nombre_jugador) in normalizar(texto_pareja)


def procesar_grupo(html: str, jugadores: list[str], url: str, torneo_nombre: str, resultados: dict) -> None:
    categoria, partidos = extraer_partidos_de_grupo(html, torneo_nombre)
    for partido in partidos:
        for nombre in jugadores:
            en_p1 = jugador_en_texto(nombre, partido["pareja1"])
            en_p2 = jugador_en_texto(nombre, partido["pareja2"])
            if not (en_p1 or en_p2):
                continue
            rival = partido["pareja2"] if en_p1 else partido["pareja1"]
            resultado_txt = partido["resultado"].strip()
            resultados[nombre]["partidos"].append(
                {
                    "categoria": categoria,
                    "url_grupo": url,
                    "rival": rival,
                    "horario_pista": partido["horario_pista"],
                    "resultado": resultado_txt,
                    "jugado": resultado_txt.lower() not in ("sin resultado", "", "-"),
                }
            )


def main() -> None:
    config = cargar_config()
    torneo_id = config["torneo_id"]
    torneo_nombre = config.get("torneo_nombre", "")
    jugadores = config["jugadores"]

    resultados = {nombre: {"partidos": []} for nombre in jugadores}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        print(f"Buscando grupos del torneo id={torneo_id}...")
        urls_grupo = encontrar_urls_de_grupo(page, torneo_id)
        print(f"  {len(urls_grupo)} grupo(s) encontrados.")

        for i, url in enumerate(urls_grupo, 1):
            print(f"  [{i}/{len(urls_grupo)}] {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            procesar_grupo(html, jugadores, url, torneo_nombre, resultados)

        browser.close()

    # Separar próximos partidos (sin resultado) de los ya jugados, y ordenar
    # para que cada jugador muestre primero lo pendiente.
    for nombre, datos in resultados.items():
        datos["partidos"].sort(key=lambda p: p["jugado"])  # False (pendiente) antes que True

    salida = {
        "torneo_id": torneo_id,
        "torneo_nombre": torneo_nombre,
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "jugadores": resultados,
    }

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    total = sum(len(v["partidos"]) for v in resultados.values())
    print(f"\nListo: {total} partido(s) encontrados para {len(jugadores)} jugadores BÜRK.")
    print(f"Guardado en {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
