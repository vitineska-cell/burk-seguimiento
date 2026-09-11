import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper_runner import (
    cargar_urls_en_paralelo,
    listado_cuadros_cargado,
    salida_tiene_cambios,
)


def test_placeholder_no_se_considera_cargado():
    html = """
    <div class="tab-lazy-content" data-panel="cuadros" data-id="2339" data-loaded="1">
      <div class="tab-loading-placeholder">Cargando...</div>
    </div>
    """
    assert listado_cuadros_cargado(html) is False


def test_listado_con_categoria_y_url_se_considera_cargado():
    html = """
    <div class="tab-lazy-content" data-panel="cuadros" data-id="2339" data-loaded="1">
      <div id="cuadros-todos">
        <div class="cuadros-categoria-block">
          <div class="cuadros-categoria-header">
            <a onclick="abrirCuadroVisor('torneogrupo.aspx?idT=2339&amp;g=908&amp;visor=0', 'Categoría')">
              Categoría
            </a>
          </div>
        </div>
      </div>
    </div>
    """
    assert listado_cuadros_cargado(html) is True


def test_no_publica_si_solo_cambian_fecha_o_diagnostico():
    anterior = {
        "torneo_id": 2339,
        "torneo_nombre": "A Coruña Open",
        "actualizado": "fecha anterior",
        "diagnostico": {"errores": 1},
        "jugadores": {"Víctor": {"partidos": []}},
    }
    nueva = {
        "torneo_id": 2339,
        "torneo_nombre": "A Coruña Open",
        "diagnostico": {"errores": 0},
        "jugadores": {"Víctor": {"partidos": []}},
    }
    assert salida_tiene_cambios(anterior, nueva) is False
    nueva["jugadores"]["Víctor"]["partidos"].append({"resultado": "21-18"})
    assert salida_tiene_cambios(anterior, nueva) is True


def test_carga_paralela_conserva_exitos_y_errores():
    def cargador(url):
        if url.endswith("/error"):
            raise RuntimeError("fallo controlado")
        return f"contenido:{url}"

    paginas, errores = cargar_urls_en_paralelo(
        ["https://ejemplo.test/uno", "https://ejemplo.test/error", "https://ejemplo.test/uno"],
        cargador=cargador,
        max_workers=2,
    )
    assert paginas == {"https://ejemplo.test/uno": "contenido:https://ejemplo.test/uno"}
    assert set(errores) == {"https://ejemplo.test/error"}


if __name__ == "__main__":
    test_placeholder_no_se_considera_cargado()
    test_listado_con_categoria_y_url_se_considera_cargado()
    test_no_publica_si_solo_cambian_fecha_o_diagnostico()
    test_carga_paralela_conserva_exitos_y_errores()
    print("Todos los tests del ejecutor v6 pasan.")
