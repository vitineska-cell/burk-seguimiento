#!/usr/bin/env python3
"""
Scraper de seguimiento BÜRK para Pickle Pro Tour (pickleprotour.com).

Qué hace:
1. Lee jugadores.json (torneo activo + lista de jugadores BÜRK).
2. Abre la pestaña "Grupos y Cuadros" del torneo.
3. Cada categoría tiene botones "GRUPO 1", "GRUPO 2"... que NO son enlaces:
   al pulsarlos, cargan la tabla de partidos dentro de la misma página
   (la URL no cambia). Por eso el script pulsa cada botón uno a uno con un
   navegador real (Playwright), lee la tabla que aparece, y vuelve atrás
   con el botón "Volver" para pasar al siguiente.
4. Filtra los partidos donde aparece alguno de los jugadores BÜRK.
5. Guarda todo en docs/resultados.json, que es lo que lee el panel web.

Historial:
- v1 intentaba buscar enlaces <a href="torneogrupo.aspx..."> - no existían,
  0 grupos encontrados en la primera ejecucion real (11/07/2026).
- v2 (esta version) simula los clics, basado en una captura real de la web
  que confirmo: los botones se llaman exactamente "GRUPO N", existe un
  boton "Volver", y el resultado tiene formatos como "21 - 0 WO Justificado".

Si esta version tambien falla, copia el log de GitHub Actions y peaselo a
Claude - cada intento deja mas informacion real sobre como es la web.
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

BOTON_GRUPO = re.compile(r"^GRUPO\s+\d+\s*$")
ENCABEZADO_PARTIDOS = re.compile(r"GRUPO\s+\d+\s*-\s*PARTIDOS", re.I)


def normalizar(texto: str) -> str:
    """Quita acentos/mayusculas para poder comparar nombres sin depender de tildes."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.lower().strip()


def cargar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def jugador_en_texto(nombre_jugador: str, texto_pareja: str) -> bool:
    return normalizar(nombre_jugador) in normalizar(texto_pareja)


def extraer_categoria_y_tabla_partidos(html: str) -> tuple[str, list[dict]]:
    """
    Dado el HTML de la vista de detalle de UN grupo (ya renderizada tras
    pulsar el boton "GRUPO N"), devuelve (etiqueta_categoria, partidos).

    Busca el texto "GRUPO N - PARTIDOS" y coge la tabla que viene justo
    despues (para no confundirla con la tabla de "GRUPO N - CLASIFICACION"
    que aparece mas abajo en la misma vista).
    """
    soup = BeautifulSoup(html, "html.parser")

    nodo_categoria = soup.find(string=re.compile(r"^\s*CATEGORIA\s", re.I))
    categoria = nodo_categoria.strip() if nodo_categoria else ""

    nodo_grupo = soup.find(string=ENCABEZADO_PARTIDOS)
    etiqueta = f"{nodo_grupo.strip()} · {categoria}" if nodo_grupo and categoria else (categoria or (nodo_grupo.strip() if nodo_grupo else ""))

    tabla = None
    if nodo_grupo:
        contenedor = nodo_grupo.find_parent()
        if contenedor:
            tabla = contenedor.find_next("table")
    if tabla is None:
        tabla = soup.find("table")  # Fallback si no se encontro el encabezado

    partidos = []
    if tabla:
        filas = tabla.find_all("tr")[1:]  # saltar cabecera (Jugador 1/2 o Pareja 1/2...)
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
    return etiqueta, partidos


def asegurar_vista_de_grupos(page, torneo_id: int) -> bool:
    """
    Comprueba que la pagina muestra el listado de botones GRUPO N. Si no
    (por ejemplo, un clic anterior fallo a mitad), recarga desde cero.
    Devuelve False si no consigue recuperar la vista.
    """
    try:
        page.get_by_text(BOTON_GRUPO).first.wait_for(state="visible", timeout=6000)
        return True
    except Exception:
        pass

    print("  Recargando: vista inesperada, recargando la pagina del torneo...")
    try:
        url = f"{BASE_URL}/torneo.aspx?id={torneo_id}"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.get_by_text("Grupos y Cuadros").first.click()
        page.get_by_text(BOTON_GRUPO).first.wait_for(state="visible", timeout=15000)
        return True
    except Exception as e:
        print(f"  No se pudo recuperar la vista de grupos: {e}")
        return False


def main() -> None:
    config = cargar_config()
    torneo_id = config["torneo_id"]
    torneo_nombre = config.get("torneo_nombre", "")
    jugadores = config["jugadores"]

    resultados = {nombre: {"partidos": []} for nombre in jugadores}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        url = f"{BASE_URL}/torneo.aspx?id={torneo_id}"
        print(f"Abriendo torneo id={torneo_id}...")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        print("Pulsando la pestana 'Grupos y Cuadros'...")
        page.get_by_text("Grupos y Cuadros").first.click()

        try:
            page.get_by_text(BOTON_GRUPO).first.wait_for(state="visible", timeout=15000)
        except Exception:
            print("No aparece ningun boton 'GRUPO N' tras pulsar la pestana.")
            print("La estructura de la web puede haber cambiado de nuevo.")
            total_grupos = 0
        else:
            total_grupos = page.get_by_text(BOTON_GRUPO).count()

        print(f"Detectados {total_grupos} boton(es) de grupo en todo el torneo.")

        procesados = 0
        errores = 0

        for i in range(total_grupos):
            if not asegurar_vista_de_grupos(page, torneo_id):
                print(f"Abortando en el grupo #{i + 1}/{total_grupos} - no se pudo recuperar la pagina.")
                break

            try:
                page.get_by_text(BOTON_GRUPO).nth(i).click()
                page.wait_for_selector(f"text=/{ENCABEZADO_PARTIDOS.pattern}/i", timeout=10000)

                categoria, partidos = extraer_categoria_y_tabla_partidos(page.content())

                encontrados_aqui = 0
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
                                "rival": rival,
                                "horario_pista": partido["horario_pista"],
                                "resultado": resultado_txt,
                                "jugado": resultado_txt.lower() not in ("sin resultado", "", "-"),
                            }
                        )
                        encontrados_aqui += 1

                procesados += 1
                if encontrados_aqui or procesados % 10 == 0:
                    print(f"  [{i + 1}/{total_grupos}] {categoria or '(sin categoria)'} - {encontrados_aqui} partido(s) BURK")

                page.get_by_text("Volver", exact=False).first.click()

            except Exception as e:
                errores += 1
                print(f"  Error en el grupo #{i + 1}/{total_grupos}: {e}")

        browser.close()

    print(f"\nGrupos procesados: {procesados}/{total_grupos} ({errores} error(es))")

    # Proximos partidos (sin resultado) primero, jugados despues.
    for datos in resultados.values():
        datos["partidos"].sort(key=lambda p: p["jugado"])

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
    print(f"Listo: {total} partido(s) encontrados para {len(jugadores)} jugadores BURK.")
    print(f"Guardado en {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
