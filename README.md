# Seguimiento BÜRK · Pickle Pro Tour

Panel para ver de un vistazo los partidos de los jugadores patrocinados por
BÜRK en cada torneo del Pickle Pro Tour: fase de grupos, cuadro eliminatorio,
logros, resultados, próximo partido (día, hora o estado, pista y rival) y
enlace directo a la información oficial.

---

## 🚀 Puesta en marcha (solo la primera vez)

### 1. Crear el repositorio

1. Entra en [github.com/new](https://github.com/new)
2. Nombre del repositorio: `burk-seguimiento` (o el que prefieras)
3. Marca la opción **Public** (necesario para que GitHub Pages sea gratis)
4. Pulsa **Create repository**

### 2. Subir estos ficheros

1. En la página del repositorio recién creado, pulsa **uploading an existing file**
2. Arrastra **todos** los ficheros y carpetas de este proyecto (manteniendo la
   estructura de carpetas: `.github/`, `docs/`, `tests/`, etc.)
3. Pulsa **Commit changes**

### 3. Activar GitHub Pages (el panel visual)

1. En el repositorio, ve a **Settings → Pages**
2. En "Branch", selecciona `main` y la carpeta `/docs`
3. Pulsa **Save**
4. Espera 1-2 minutos. Tu panel estará en algo como:
   `https://tu-usuario.github.io/burk-seguimiento/`
   (GitHub te muestra la URL exacta en esa misma pantalla)

### 4. Ejecutar el scraper por primera vez

1. Ve a la pestaña **Actions** del repositorio
2. Si aparece un aviso pidiendo habilitar Actions, acéptalo
3. Click en **Actualizar resultados BÜRK** (en la lista de la izquierda)
4. Click en el botón **Run workflow** → **Run workflow** (botón verde)
5. Espera 1-2 minutos y refresca la página del panel (paso 3)

---

## 🔁 Uso normal cada torneo

**Antes del torneo:**
Edita `jugadores.json` directamente en GitHub (ábrelo, pulsa el icono del
lápiz ✏️), añade el torneo a la lista `torneos` con su ID, nombre y fechas, y
revisa la lista de jugadores. El ID del torneo está en su URL:
`pickleprotour.com/torneo.aspx?id=XXXX` ← ese número.

**Durante el fin de semana:**
Dentro de las fechas `actualizacion_desde` y `actualizacion_hasta`, GitHub
selecciona automáticamente el torneo y solicita un nuevo barrido **cada 5 minutos**
mediante una cadena de ejecuciones, con cron de respaldo. El cron comprueba si
ya hay una cadena reciente para evitar ciclos duplicados. Los intervalos
dependen también de la cola de GitHub Actions y de la web de Pickle Pro Tour,
por lo que no constituyen una garantía de tiempo real.

**Barcelona Open 2026 (ID 2341):** ventana desde el 12 de octubre a las
21:00 hasta el 19 de octubre a las 12:00 (hora peninsular). Se adelantó el
inicio cuando estuvieron publicados los grupos el 12 de octubre, sin esperar
al primer día de competición (16 de octubre). El panel muestra partidos
programados aunque aún no se hayan disputado.

Fuera de las ventanas no se consulta Pickle Pro Tour. Las modificaciones
`push` ejecutan las pruebas aunque el torneo esté inactivo. También puedes
forzar una actualización desde **Actions → Actualizar resultados BÜRK →
Run workflow**. El panel comprueba cada 60 segundos si hay nuevos datos.

---

## 🗂️ Qué hace cada fichero

| Fichero | Para qué sirve |
|---|---|
| `jugadores.json` | **El único que edita Víctor.** Torneo activo + lista de jugadores BÜRK. |
| `scraper.py` | Lee grupos, cuadros eliminatorios y orden de juego en pickleprotour.com. |
| `docs/index.html` | El panel visual (lo que ves en el navegador). |
| `docs/resultados.json` | Los datos que genera el scraper; los lee `index.html`. |
| `.github/workflows/actualizar.yml` | Define el botón "Run workflow". |
| `tests/` | Pruebas internas del código, no hace falta tocarlas. |
| `vista_previa.html` | Ejemplo visual con datos ficticios (no forma parte del panel real). |

---

## Comprobación y recuperación de resultados

El visor distingue **Último cambio detectado** (datos deportivos) de **Última
comprobación correcta** (consulta de las fuentes). `docs/estado.json` se publica
en cada ciclo incluso si no cambia ningún marcador. Si una consulta falla,
el visor avisa; también avisa tras 15 minutos sin comprobación dentro de la
ventana del torneo. Un fallo no se presenta como ausencia de resultados.

La extracción combina grupos, cuadros y orden de juego. Los alias se vinculan
por los identificadores oficiales de jugador (por ejemplo, Mercedes Cascales
y Merche Cascales Campos). Se conservan esos alias durante el mismo torneo.
Un cruce con categoría ambigua se registra como incidencia, con enlace a la
fuente, y no detiene la actualización de los demás. Los resultados confirmados
se conservan con aviso si una fuente desaparece o vuelve a mostrar pendientes.
Una corrección oficial con marcador sí puede sustituir un resultado anterior.
Los marcadores en curso no se cuentan como victorias ni derrotas.

Las fuentes HTML de cada barrido y las incidencias se guardan en el artefacto
`diagnostico-scraper` de GitHub Actions durante siete días. El diagnóstico usa
las descargas guardadas, sin depender de Playwright. Si se modifica el código
durante un barrido, ese barrido no puede sobrescribir los datos de la corrección.

Pruebas locales y en CI:

```bash
python tests/run_all.py
node tests/test_panel.cjs
```

La regresión de Barcelona del 17/10/2026 incluye HTML real de grupos, cuadro y
orden de juego de Bárbara: victoria 21–7 y semifinal 12–21 / 10–21. Las pruebas
cubren además alias, ambigüedades, caídas de fuentes, conservación/corrección de
resultados, marcadores en curso, comprobaciones sin cambios y avisos del visor.
La frecuencia solicitada sigue siendo cinco minutos; la cola de GitHub y la
publicación oficial pueden introducir retrasos, que ahora quedan visibles.

---

## 🔮 Próximos pasos posibles

- **Bot de Telegram**: aviso automático al grupo del equipo cuando un
  jugador BÜRK termina un partido.
- **Monitorización externa** del calendario de GitHub Actions como respaldo
  adicional frente a retrasos de GitHub (pendiente de valorar).

No construidos todavía — se añaden cuando el panel esté validado con datos
reales del primer torneo.
