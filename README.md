# Graficación CSV de GasLab

Primera versión local: una ventana sencilla para abrir CSV, seleccionar variables y verlas en un visor rápido (pyqtgraph) o en el navegador (Plotly), con la ruta GPS sobre un mapa. Compatible con los CSV de MicroGas Receptor, DJI y Simulado. No modifica el CSV original.

## Abrir

Desde esta carpeta:

```bash
./iniciar.sh
```

O ejecuta `.venv/bin/python graficar.py`. Pulsa **Abrir CSV**, selecciona una o varias variables (o **Seleccionar todas las variables**), ajusta la columna de tiempo si hace falta y abre el **Visor rápido (ventana)**, la **Vista interactiva (navegador)** o el **Mapa GPS…**. El eje X (fecha local, tiempo transcurrido o número de muestra) se cambia dentro de cada visor.

Zona predeterminada: `America/Costa_Rica`. Puedes cambiarla a `UTC` u otra zona IANA. Fechas ISO 8601 con zona respetan esa zona; fechas sin zona se interpretan como UTC. Para fechas numéricas, se detecta Unix s/ms/us/ns por magnitud; selecciona la unidad explícita si es necesario. Las filas pueden venir en cualquier orden siempre que el CSV tenga encabezado: al cargar se ordenan cronológicamente (en memoria) por la columna de tiempo elegida; las filas sin fecha válida quedan al final. Si la columna de tiempo no se puede leer, se conserva el orden del archivo. Se recomienda fecha ISO completa, no una columna que contenga solamente la hora.

El filtro **Solo muestras nuevas SEN66** usa `sen66_new_data == 1` en archivos DJI para excluir lecturas retenidas del registro a 10 Hz. En CSV sin esa columna no filtra nada. Por defecto se muestran todas las filas.

## Visor rápido (ventana, pyqtgraph)

Botón **Visor rápido (ventana)** o `.venv/bin/python graficar.py datos.csv --qt` (también `.venv/bin/python visor_qt.py datos.csv`). Ventana propia con el mapa OpenStreetMap o satélite Esri a la izquierda (los tiles se descargan según el zoom y se guardan en `~/.cache/gaslab_tiles`) y las gráficas a la derecha, con aceleración de dibujo para archivos grandes. Las gráficas se organizan en tres columnas y las filas adicionales se recorren con la barra lateral. Zoom y desplazamiento sincronizados, cursor compartido entre gráficas y mapa, tramo con zoom resaltado en la ruta, ruta coloreada por variable, mín/prom/máx del tramo visible, Y ajustada al tramo, lista de variables a la izquierda, **clic en una gráfica para ampliarla** (Esc o otro clic para volver), cambio de eje X, exportar PNG y **Modo noche** (interfaz oscura, líneas más claras y mapa oscurecido; se recuerda al reabrir). Al pasar el mouse por una gráfica aparece un cuadro con muestra, eje X, valor, latitud, longitud y altura. Requiere `pyqtgraph` y PyQt5 (ver `requirements.txt`). Sin internet el mapa no muestra fondo, pero sí la ruta.

## Vista interactiva (navegador)

Botón **Vista interactiva (navegador)** o `--web salida.html` en la CLI. Genera un HTML autónomo (Plotly con WebGL, incluido en el archivo) con el mapa a la izquierda y las gráficas a la derecha. Las gráficas se organizan en tres columnas; las filas adicionales se recorren con la barra lateral (en pantallas estrechas se adaptan a menos columnas). Funciones: zoom y desplazamiento sincronizados entre gráficas, cursor compartido (al pasar el mouse por una gráfica o por el mapa se marca ese instante en todo), el tramo con zoom se resalta en la ruta, ruta coloreada por una variable, mapa OpenStreetMap o satélite Esri, mín/prom/máx del tramo visible, ajuste automático del eje Y, activar/desactivar variables y ampliar una gráfica con clic en su título (Esc para volver). Solo los fondos del mapa necesitan internet. El HTML contiene los datos del CSV. Requiere `plotly` (ver `requirements.txt`). Las filas se ordenan por la columna de tiempo, igual que en el visor rápido.

## Ruta y satélite

- **Mapa GPS**: guarda un HTML y lo abre en el navegador, con OpenStreetMap como fondo inicial y una capa satelital Esri alternativa. Toca los puntos amarillos para consultar hora, CO₂ y GPS. Puedes ampliar y mover el mapa.
- El mapa necesita internet para cargar las bibliotecas y los fondos. El CSV se procesa localmente; el HTML contiene las coordenadas, por lo que compartirlo comparte esos datos.
- Las filas sin coordenadas válidas cortan la ruta; tampoco se unen sesiones distintas cuando existe la columna `session`. No se inventan ubicaciones ni se filtran saltos GPS válidos. Los CSV simulados sin GPS sí se pueden graficar, pero no generan rutas.
- Se conserva toda la ruta. Para no saturar el navegador, se muestran hasta aproximadamente 2.000 puntos consultables; el mapa informa la cantidad. En archivos grandes, generar el mapa puede tardar.
- Los fondos son servicios externos: su disponibilidad, cobertura y resolución dependen del proveedor. Se conserva la atribución del proveedor suministrada por Folium/xyzservices.

## Línea de comandos

```bash
# Visor rápido (ventana) con el CSV; --y elige las variables iniciales:
.venv/bin/python graficar.py datos.csv --y co2_ppm temperatura_c humedad_pct

# Vista interactiva en HTML y mapa satelital:
.venv/bin/python graficar.py datos.csv --web vista.html --mapa ruta.html

# CSV DJI, solo muestras nuevas y hora de recepción SEN66 en el control:
.venv/bin/python graficar.py datos.csv --solo-nuevas --tiempo sen66_muestra_utc

# Otra columna de tiempo numérico (milisegundos Unix):
.venv/bin/python graficar.py datos.csv --tiempo received_at_ms --unidad ms
```

CSV separados por coma, punto y coma o tabulador: el separador se detecta automáticamente. Se admiten decimales con coma en columnas separadas por punto y coma. Las columnas vacías/no numéricas no se ofrecen como variables. Los valores faltantes dejan huecos en las gráficas. Los errores se muestran en la ventana o terminal.

## Instalación desde cero

Python 3.10 o posterior con Tkinter. En Ubuntu, si falta Tkinter, instala el paquete `python3-tk`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./iniciar.sh
```

El entorno preparado en esta máquina reutiliza pandas y PyQt5 ya instalados mediante `--system-site-packages`; las dependencias adicionales están dentro de `.venv`.

## Ejemplo y pruebas

Las pruebas usan datos **sintéticos** definidos en `test_graficar.py` (GPS, un hueco y un cambio de día en Costa Rica); no son una medición real. Las imágenes y el mapa de `ejemplos/` son de una versión anterior.

```bash
.venv/bin/python -m unittest -v test_graficar.py
```

Referencias de los fondos: [Folium: capas de mapas](https://python-visualization.github.io/folium/v0.19.3/user_guide/raster_layers/tiles.html) y [Esri: atribución de mapas base](https://support.esri.com/en-us/knowledge-base/what-is-the-correct-way-to-cite-an-arcgis-online-basema-000012040).


## Incorporación y elección del archivo

El [manual MicroGas](../MicroGas/MANUAL_REPLICACION_DESDE_CERO.md) explica cómo obtener los CSV. Para una sesión larga del receptor usa **Archivos CSV → Exportar**: el botón del histórico solo exporta el buffer de hasta 7.200 muestras. El emisor y el receptor tienen 24 y 16 columnas respectivamente (incluida la altitud: `altura_m` al final en los CSV originales; el visor reconoce también `altitud_m`, `altitud` y `altura`); sus cantidades de filas no tienen por qué coincidir.

En CSV DJI selecciona `sen66_muestra_utc` y **Solo muestras nuevas** para estudiar lecturas; esa fecha es recepción en el control, no adquisición física en la Pi. Usa `fecha_hora_utc` sin filtro para estudiar el registro a ~10 Hz. En Receptor utiliza `fecha_hora_utc`. Los valores `payload_uptime_ms` son tiempo desde arranque y no deben interpretarse automáticamente como fechas Unix.

Conserva un CSV original sin modificar y guarda los resultados aparte. El programa ordena por la columna de tiempo seleccionada, pero no corrige coordenadas que saltan ni diferencia sesiones que no estén identificadas. Analiza vuelos por separado si no existe `session`.

## Guía de mantenimiento y diagnóstico

`graficar.py` separa carga (`load_csv`), fechas (`parse_time`/`time_axis`), segmentos GPS (`gps_segments`), mapa (`make_map`), vista web (`make_viewer`), ventana de selección (`gui`) y CLI (`main`); el visor rápido está en `visor_qt.py`. Al cambiar fechas o columnas ejecuta `test_graficar.py` y comprueba un CSV de cada app. Los datos de prueba son sintéticos y no validan GPS real.

| Problema | Comprobación |
|---|---|
| No abre la ventana | Entorno `.venv`, Tkinter y sesión gráfica; sin escritorio usa `--web` o `--mapa` |
| No hay ruta | Coordenadas numéricas válidas; MicroGas Simulado desde 0.4.0 genera GPS sintético; archivos antiguos pueden no incluirlo |
| Hora desplazada | Zona IANA, UTC de entrada y unidad Unix elegida |
| Mapa sin fondo | Internet y servicios del navegador; el HTML necesita recursos externos |
| CSV no carga | Encabezado, separador y que no se haya convertido al guardarlo en una hoja de cálculo |
| No guarda resultados | Carpeta de destino existente y con permisos; la CLI no crea carpetas de salida |

Las dependencias se instalan desde cero con los pasos anteriores; no copies `.venv` a otra máquina. Para reproducir una entrega registra también las versiones instaladas con `.venv/bin/python -m pip freeze`.


Marcadores del mapa: inicio 🏠 y fin ✈️ (cámbialos en `START_ICON` y `END_ICON` de `graficar.py`). En los cuadros de datos la altura se muestra como **Altitud**, después de latitud y longitud.

## Ejecutable de Windows

En Windows con Python 3.10+: doble clic a `build_windows.bat` (o `pyinstaller --noconfirm GasLab.spec` tras instalar `requirements-build.txt`). El resultado queda en `dist\GasLab\`; esa carpeta completa se puede copiar a otro equipo y ejecutar `GasLab.exe`. En GitHub, el workflow *Build Windows* (pestaña Actions → Run workflow, o al subir una etiqueta `v*`) lo compila y lo publica como artefacto `GasLab-windows`. El visor rápido se abre relanzando el mismo ejecutable con `--visor-qt`.

## Makefile

`make help` lista los objetivos: `make setup` (crea `.venv`), `make run`, `make test`, `make build` (genera `dist/GasLab/`) y `make clean`. En Windows hace falta GNU make (`choco install make` o `winget install ezwinports.make`); `build_windows.bat` sigue funcionando sin make.
