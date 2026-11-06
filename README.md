# Graficación CSV de GasLab

Herramienta local para abrir CSV de mediciones, elegir variables y analizarlas con la ruta GPS. **GasLab 2.0** (`./iniciar.sh`) es una app en el navegador organizada en pasos: datos, límites, mapa de calor y terreno 3D. La **versión 1** (`.venv/bin/python graficar.py`) sigue disponible: una ventana para abrir el CSV y verlo en un visor rápido (pyqtgraph) o en el navegador (Plotly), con la ruta GPS sobre un mapa. Las dos son compatibles con los CSV de MicroGas Receptor, DJI, Simulado y Campbell (`Flight_Data`), y ninguna modifica el CSV original. También abren Excel (`.xlsx`/`.xlsm`): por defecto, la hoja `Datos` si existe (la que exporta GasLab, cuya fecha local se vuelve a pasar a UTC) o la hoja más grande. En la 2.0, si el libro tiene varias hojas con datos, aparece el selector **Hoja:** junto al nombre del archivo para abrir otra; cada hoja necesita su propia columna de tiempo. Los `.xls` antiguos hay que guardarlos antes como `.xlsx` o `.csv`.

## GasLab 2.0 (en desarrollo, rama `develop-2.0`)

`./iniciar.sh` (o `.venv/bin/python gaslab_web.py`) abre la app en el navegador, servida desde `http://127.0.0.1` (solo esta máquina). **Abrir archivo…** (CSV o Excel) usa el administrador de archivos del equipo (también se puede arrastrar el archivo a la página). Después aparecen:

- **Variables:** todas las columnas numéricas, con filtro. Por defecto se marcan **CO₂, SO₂ y H₂S** si el archivo los trae (se reconocen por nombre: `co2_ppm`, `CO2_Concentration_Avg`, `SO2 (ppm)`…; se ignoran columnas de temperatura, mV o RAW). Si falta alguno, se indica junto a la lista.
- **Izquierda:** la ruta GPS sin fondo de mapa (misma escala en metros en ambos ejes, inicio y fin marcados) y debajo la **altura contra la hora**.
- **Derecha:** una gráfica por variable contra la **hora del día** en la zona elegida.
- **Zona horaria** (arriba a la derecha): `UTC` por defecto; acepta cualquier zona IANA (`America/Costa_Rica`, `Europe/Rome`…).

**Todas** marca todas las variables. Las gráficas se mueven como en la versión anterior: **arrastrar desplaza** y **la rueda acerca o aleja**; el recuadro de zoom sigue disponible en la barra de cada gráfica. Mientras se mueve una, las demás la siguen en vivo; al soltar, el eje Y se ajusta al tramo visible. **Restablecer zoom** (o doble clic) vuelve a todo el archivo. El tramo visible se resalta en la ruta; al pasar el mouse se marca el mismo instante en todas las gráficas y en el mapa. Una pausa de más de 20 muestras (mínimo 10 s) corta la línea.

**Tramos** (fila debajo de las variables, como en la versión 1). Limitan **todas las pestañas** a una parte de la medición: gráficas, ruta, límites, mapa de calor, terreno 3D, QGIS y Excel.
- **Inactividad > N s + Tramo:** una pausa mayor a N segundos (1200 por defecto) entre dos muestras abre un tramo nuevo. La lista muestra cada tramo con inicio → fin, duración y muestras. En `mediciones_16sep` salen 2 tramos con 1200 s y 4 con 60 s.
- **Día + de … a …:** el día y las horas de inicio y fin; solo aparecen las horas con mediciones. Al elegir el día, por defecto va el día completo.
- **Todo** quita el límite. Con un tramo elegido, las gráficas quedan **encerradas** en él: al desplazarse no salen del tramo, y alejar o **Restablecer zoom** muestra el tramo completo. Las horas son de la zona elegida; cambiar de zona quita el tramo.

**Google Earth (.kmz):** todo lo que tiene mapa se puede abrir en Google Earth. Cada exportación usa el tramo, el GPS, la señal y la escala elegidos:
- **Paso 1**, botón en la tarjeta de la ruta: la ruta (con los dos GPS en Ambos), cortada en las pausas, con Inicio y Fin y su hora.
- **Paso 3**, en Guardar, según la vista: en **2D**, la nube como imagen sobre el mapa (igual a la de la app, con el mismo tamaño, opacidad, enfriamiento y alcance); en **3D**, las barras (con su altura máxima y ancho). Las dos llevan un punto **«Leyenda»** junto a los datos (al hacer clic muestra la tabla de colores) y la ruta.
- **Paso 4**, en Guardar: las muestras a su altura medida más el desfase (con una línea hasta el suelo), o pegadas al terreno según el modo elegido, más la leyenda y la ruta. El **Desfase** se escribe en el campo numérico, sin límite; al lado, una barra de ajuste fino lo mueve ±5 m y se recentra en el nuevo valor al soltarla.
- Google Earth usa su propio relieve y mide la altura sobre el nivel del mar con otro modelo (EGM96). Muchos GPS dan la altura sobre el elipsoide WGS84, que en Italia está unos 40–50 m más arriba. Si los puntos quedan enterrados o flotando, corrígelo con el **desfase** del paso 4.
- **Google Earth en el navegador** (earth.google.com): importa con **Map features**. Un proyecto admite 20 000 elementos en total; si da error al importar varios archivos, usa un proyecto nuevo. Con **Data layer** se ve todo amarillo, sin la nube. Map features rechaza los archivos con `TimeStamp` o `ScreenOverlay` y acepta hasta 10 000 elementos, así que el KMZ no los usa: la hora va en la descripción de cada punto, la leyenda es un punto y cada archivo lleva como máximo 9000 elementos (las muestras se reparten a lo largo del tramo).
- Se genera en `kmz.py`.

**Tema:** el botón ◐ / ☀ / ☾ al lado de la zona horaria cambia entre **automático** (el del sistema: en Windows, Configuración → Personalización → Colores, o la apariencia de Edge), **claro** y **oscuro**, como el Modo noche de la versión 1. Se recuerda al volver a abrir.

**Rendimiento:** el navegador nunca recibe el CSV completo. `gaslab_web.py` manda a cada gráfica el mínimo y el máximo por columna de píxeles (así no se pierden picos) y, al hacer zoom, vuelve a pedir solo el tramo visible con más detalle; la tarjeta de cada gráfica indica cuántos puntos se muestran. La ruta se limita a 20.000 puntos. Plotly se sirve desde el paquete instalado, por lo que la app no necesita internet.

**Plan de pasos (pestañas).** La 2.0 se organiza en pestañas que son los pasos de un análisis, en orden:
1. **Datos** (lo descrito arriba): abrir el CSV, elegir variables y zona horaria, revisar la ruta, la altura y las variables contra la hora.
2. **Límites (saturación):** filas `Dato: ____ | Máximo: ____ | Mínimo: ____`. Cada muestra por encima del máximo pasa a valer el máximo y cada una por debajo del mínimo pasa a valer el mínimo. Ninguna muestra se descarta.
   - La selección de variables es la misma en todas las pestañas: hay una fila por cada variable marcada en el paso 1. **+ Agregar límite** marca otra variable, ✕ la desmarca y cambiar el Dato cambia cuál está marcada; todo se refleja al volver al paso 1. Los valores escritos se recuerdan por variable aunque se desmarque.
   - Un campo vacío significa sin límite de ese lado. Se acepta coma decimal. Si el mínimo es mayor que el máximo, la fila se marca en rojo y no se aplica.
   - Debajo hay una gráfica grande con los datos ya ajustados. Los botones de arriba eligen la variable, y los límites se ven como líneas punteadas. Bajo la gráfica se indica cuántas muestras quedaron en cada límite.
   - **Comparar con original** muestra la curva sin ajustar en gris detrás de la ajustada. **Pantalla completa** amplía la gráfica; Esc sale.
   - Los pasos siguientes usan los valores ajustados: mapa de calor, terreno 3D, QGIS, Google Earth y Excel. En el servidor, `Dataset.values(nombre, límites)` devuelve la columna ya ajustada.

3. **Mapa de calor:** se analiza **una sola señal** a la vez, elegida entre las variables seleccionadas, con los valores ya ajustados en Límites. Toda la configuración está arriba:
   - **2D / 3D:** el selector cambia la vista sobre la imagen satelital de Esri. Solo el fondo necesita internet; sin conexión, la nube y las barras se ven igual sobre fondo oscuro.
   - **Escala:** **Divisiones iniciales** y **% mínimo por división** tienen cada uno un botón ⓘ que abre una ventanita con su explicación. El rango del mínimo al máximo registrado se divide en N divisiones iniciales según el selector **Lineal | Exponencial**: en Lineal todas tienen el mismo ancho; en Exponencial cada una es más ancha que la anterior por un factor fijo (finas cerca del mínimo, anchas hacia el máximo; la última es 1000 veces la primera). Cada división con menos del **% mínimo** de las muestras se une a su vecina con menos muestras, hasta que todas lleguen al mínimo. Así hay más divisiones (más colores) donde se concentran las muestras. Con 0 % (el valor por defecto) no se une ninguna: las divisiones quedan tal cual (en Lineal, todas del mismo ancho). La tabla muestra cada división con su rango, cantidad de muestras y %, y el recuadro superior muestra el rango completo de valores. El mapa lleva la misma leyenda.
   - **2D, nube:** cada muestra se dibuja saturada en su posición y se difumina alrededor con un núcleo gaussiano, con una paleta intensa (azul → cian → verde → amarillo → naranja → rojo, colores puros). **Tamaño** va de 0,1 a 2 m (1 m por defecto) y **Opacidad** (95 % por defecto) controla cuánto deja ver el satélite. **Enfriamiento** (0 a 10, 1 por defecto, con su botón ⓘ) decide el **tamaño de la zona de calor**: cada muestra tiene su color medido en el centro y se va "enfriando" hacia los lados, bajando hacia el mínimo de la escala (azul) según la distancia en metros. Con 1, a 10 m queda al 60 % de su valor sobre el mínimo; más alto = zona de calor más chica; 0 = el mismo color hasta el borde. La nube se recalcula para la zona visible a la resolución de la pantalla cada vez que se mueve el mapa, así que se ve nítida con cualquier zoom. **Alcance** (1 a 50 m, **30 m** por defecto, con ⓘ; entre paréntesis, en veces el Tamaño) es **solo hasta dónde se extiende** la nube: la mitad interior es opaca y la exterior se desvanece; más allá no se pinta nada. Cambiarlo no cambia los colores ni la opacidad del centro. Los tres controles son independientes: el **Tamaño** da el detalle alrededor de cada muestra, el **Enfriamiento** la zona de calor y el **Alcance** la extensión. Lejos de las muestras el valor es el promedio de las muestras cercanas (núcleo de 10 m), que es una estimación. Donde se cruzan nubes, el color es el promedio ponderado de las muestras cercanas. Al pasar el mouse se ve el valor de la muestra.
   - **3D, barras:** una barra por muestra, de altura proporcional al valor (**Altura máxima** para el valor más alto) y del color de su división. **Ancho** cambia el grosor. Clic derecho o Ctrl + arrastrar gira e inclina la vista.
   - **Guardar:** **Imagen PNG** guarda lo que se ve, con la leyenda. **GeoTIFF + QGIS (.zip)** descarga una carpeta con `<archivo>_<señal>_nube.tif` (RGBA, igual a la app), `_valores.tif` (Float32 con la escala por divisiones y el mismo enfriamiento), `_puntos.geojson` y `<archivo>_<señal>.qgz`. Al abrir el `.qgz`, la nube aparece encendida sobre Esri satélite, y los valores y las muestras quedan como capas apagadas. El GeoTIFF cubre toda la ruta con un máximo de 2500 píxeles de lado, así que en rutas largas su píxel puede ser mayor que la nube (por ejemplo, 1,1 m en un vuelo de 3 km); el nombre de la capa indica el tamaño del píxel. Se genera en `mapa_calor.py` (`adaptive_classes`, `cloud`, `export_cloud`).

4. **Terreno 3D:** relieve real con la imagen satelital encima. Cada muestra se dibuja como un punto (un cubo pequeño) flotando a la **altura que midió el GPS**, con el color de su concentración. Usa la misma señal, escala y colores del paso 3, y la misma tabla y leyenda. No exagera el relieve: todo va a escala real. Clic derecho o Ctrl + arrastrar gira e inclina la vista, y al pasar el mouse por un punto se ven su valor, la altura medida, la del terreno y la altura sobre el terreno.
   - **Relieve:** AWS Terrain Tiles (gratis, sin cuenta, unos 30 m de detalle), en el zoom 13 porque algunas teselas del 14 vienen vacías, por ejemplo sobre el cráter de Vulcano. Necesita internet la primera vez que se abre una zona; las teselas se guardan en `~/.cache/gaslab_tiles/terrarium`. `terreno.py` calcula la altura del terreno bajo cada muestra con la misma fuente que dibuja el mapa.
   - **Altura de la muestra:** la columna de altura del archivo (`altitud_m`…), tomada como altura sobre el nivel del mar. Las muestras que quedan bajo el relieve se dibujan sobre el suelo, y un aviso indica cuántas son y cuánto quedaban por debajo. En `Flight_Data` son 271, hasta 4,6 m, junto a la costa: está dentro de la precisión del GPS y del relieve.
   - **Altura: Medida | Pegada al terreno** y **Desfase (m)**: con **Medida**, cada muestra va a su altura medida más el desfase (negativo = más abajo), útil si el GPS o el barómetro miden con un error fijo. Con **Pegada al terreno**, todas las muestras van sobre el relieve y el desfase es su altura sobre él. Si el archivo no tiene columna de altura, se pegan al terreno. Se calcula en la página, sin volver a pedir datos.

5. **Excel:** arma el mismo libro que exportaba la versión 1 y muestra una **vista previa** antes de descargarlo, con las hojas como pestañas abajo, igual que en Excel:
   - **Resumen:** archivo, desde, hasta, duración, zona horaria y muestras, más el mínimo, promedio, máximo y muestras válidas de cada variable. En el Excel son fórmulas sobre la hoja Datos.
   - **Datos:** fecha y hora en la zona elegida, segundos transcurridos, las variables marcadas y la posición (latitud, longitud y altura). La vista previa muestra las primeras 30 filas y las últimas 3.
   - **Gráficas:** un gráfico nativo de Excel por variable. **Ruta:** longitud contra latitud, sin fondo de mapa.
   - **Tramo:** **Todo el archivo**, **Tramo elegido** (el de la fila Tramo del paso 1) o **Parte visible (paso 1)**. Por defecto se exporta la parte acercada si la hay, si no el tramo elegido, como en la versión 1. El nombre del archivo lleva el tramo (`_tramo2`, `_1609_12-13h`) y la fecha y hora de inicio.
   - El libro usa las variables marcadas, **con los límites del paso 2 aplicados** (el título del Resumen dice cuáles; la posición GPS va sin tocar), la versión en uso (original o calibrada; en Comparación, la calibrada), el GPS elegido y la zona horaria. **Descargar Excel** lo guarda en Descargas. Se arma con `graficar.make_excel()`, el mismo código de la versión 1.

La librería de mapas (MapLibre GL 4.7.1) está guardada en `web/vendor/`, así que la app no la descarga de internet.

Pruebas: `.venv/bin/python -m unittest test_gaslab_web.py`. La versión 1 (ventana Tkinter, visor Qt, CLI y mapas de calor) sigue disponible con `.venv/bin/python graficar.py` y se describe a continuación.

## Abrir la versión 1

Desde esta carpeta:

```bash
.venv/bin/python graficar.py
```

(`./iniciar.sh` y `make run` abren ahora la 2.0.) Pulsa **Abrir CSV**, selecciona una o varias variables (o **Seleccionar todas las variables**), ajusta la columna de tiempo si hace falta y abre el **Visor rápido (ventana)**, la **Vista interactiva (navegador)** o el **Mapa GPS…**. El eje X (fecha local, tiempo transcurrido o número de muestra) se cambia dentro de cada visor.

Zona predeterminada: `UTC`. Puedes cambiarla a otra zona IANA (por ejemplo `America/Costa_Rica`). Fechas ISO 8601 con zona respetan esa zona; fechas sin zona se interpretan como UTC. Para fechas numéricas, se detecta Unix s/ms/us/ns por magnitud; selecciona la unidad explícita si es necesario. Las filas pueden venir en cualquier orden siempre que el CSV tenga encabezado: al cargar se ordenan cronológicamente (en memoria) por la columna de tiempo elegida; las filas sin fecha válida quedan al final. Si la columna de tiempo no se puede leer, se conserva el orden del archivo. Se recomienda fecha ISO completa, no una columna que contenga solamente la hora.

El filtro **Solo muestras nuevas SEN66** usa `sen66_new_data == 1` en archivos DJI para excluir lecturas retenidas del registro a 10 Hz. En CSV sin esa columna no filtra nada. Por defecto se muestran todas las filas.

## Visor rápido (ventana, pyqtgraph)

Botón **Visor rápido (ventana)** o `.venv/bin/python graficar.py datos.csv --qt` (también `.venv/bin/python visor_qt.py datos.csv`). Ventana propia con el mapa OpenStreetMap o satélite Esri a la izquierda (los tiles se descargan según el zoom y se guardan en `~/.cache/gaslab_tiles`) y las gráficas a la derecha, con aceleración de dibujo para archivos grandes. Las gráficas se organizan en tres columnas y las filas adicionales se recorren con la barra lateral. Zoom y desplazamiento sincronizados, cursor compartido entre gráficas y mapa, tramo con zoom resaltado en la ruta, ruta coloreada por variable, mín/prom/máx del tramo visible, Y ajustada al tramo, lista de variables a la izquierda, **clic en una gráfica para ampliarla** (Esc o otro clic para volver), cambio de eje X, exportar PNG y **Modo noche** (interfaz oscura, líneas más claras y mapa oscurecido; se recuerda al reabrir). Al pasar el mouse por una gráfica aparece un cuadro con muestra, eje X, valor, latitud, longitud y altura. Requiere `pyqtgraph` y PyQt5 (ver `requirements.txt`). Sin internet el mapa no muestra fondo, pero sí la ruta.

**Tramos, día/hora y rango manual** (detalle en `CHANGELOG.md`). Se carga todo el archivo y se puede limitar a una ventana de tiempo de tres formas; la ventana ampla las gráficas **y limita el mapa** (ruta, puntos, cobertura y encuadre) a esas muestras:
- **Inactividad > N s + Tramo:** lista los tramos continuos; una pausa mayor a N s entre dos muestras abre un tramo nuevo (1200 s por defecto). Elegir un tramo lo aplica.
- **Día + de … a …:** eliges el día y la hora de inicio y la hora de fin (solo se ofrecen horas con mediciones; por ejemplo día 16/09, de 06:00 a 07:00). Al elegir un día, el rango por defecto es todo el día.
- **Todo:** quita la ventana. La ruta no une puntos separados por una pausa mayor a la inactividad.
Con un tramo elegido las gráficas quedan **encerradas** en él: no se puede hacer zoom ni desplazarse fuera del tramo (**Restablecer zoom** vuelve al tramo completo).

**Exportar Excel…** guarda un `.xlsx` con las variables marcadas y las muestras visibles (el tramo elegido o la parte ampliada dentro de él): hojas Resumen, Datos, Gráficas (gráficos nativos de Excel) y Ruta (latitud/longitud sin fondo de mapa). Antes de guardar muestra qué se va a exportar.

**Letra** cambia el tamaño del texto de toda la ventana (8 a 28 pt, se recuerda al reabrir).

**Mapa de calor (puntos, celdas o cobertura).** La fila **Mapa de calor** colorea el mapa según una variable. Con **Puntos** (por defecto) cada muestra se dibuja en su latitud/longitud con el color de su valor (escala azul → rojo; los valores altos quedan encima; tamaño ajustable en px y, al pasar el mouse, muestra el valor del punto). Con **Celdas** divide el mapa en celdas cuadradas (0,5 a 250 m) y colorea cada una. Con **Valor = Muestras (cobertura)** el color es el porcentaje de las muestras con GPS que cayó en la celda (más claro = zona más medida). Con **Valor = una variable** (CO₂, PM, temperatura… cualquier columna numérica) cada muestra se coloca en su latitud/longitud y la celda toma el **Promedio**, el **Máximo** o el **Percentil 95** de las muestras que caen en ella (escala azul → rojo, como el mapa de CO₂ de referencia). Opciones:
- **Celdas de 0,5–2 m:** el GPS tiene un error típico de 1–3 m, así que celdas más pequeñas que eso no ganan detalle real (se parecen a los puntos).
- **Suavizado** (1–3 celdas, solo celdas): reparte cada valor con un núcleo gaussiano; solo se dibuja hasta ~2 veces el suavizado desde la ruta, no se inventan valores lejos de lo medido.
- **Desfase** (s): retraso del sensor; el valor registrado en t se coloca donde estaba el equipo en t − desfase (sin él, los picos de CO₂ aparecen corridos hacia adelante en la ruta). Necesita columna de tiempo.
- **Válido de … a …:** valores fuera del rango se ignoran (p. ej. en `Flight_Data…csv` el CO₂ trae ceros y lecturas de ~10 ppm del arranque: usar mínimo 300).
- Respeta el tramo o día elegido. Al pasar el mouse por el mapa, la leyenda muestra el valor y las muestras de la celda.

**Exportar GeoTIFF/QGIS…** guarda la variable elegida como `<nombre>_puntos.geojson` (una entidad por muestra con su valor y fecha UTC), `<nombre>.tif` (las celdas: GeoTIFF Float32 en Web Mercator EPSG:3857, sin dato = -9999) y `<nombre>.qgz`: proyecto QGIS con la **capa de puntos** coloreada por valor (20 clases con leyenda, los altos encima) y la **capa de celdas**, sobre OpenStreetMap / Esri satélite. Queda encendida la que se estaba viendo (Puntos o Celdas); la otra se enciende en el panel de capas. Opcionalmente agrega debajo otro GeoTIFF, por ejemplo el mosaico térmico `temperatura_python.tif` de [TermoReferencia](../termoreferencia/README.md), con otra escala de colores. No necesita GDAL ni QGIS para generarse (`mapa_calor.py`, solo numpy y Pillow).

Si el CSV no trae columnas de GPS con un nombre conocido (`latitud`, `latitude`, `lat`…), al abrirlo el visor pregunta cuáles son la latitud y la longitud (en grados decimales).

## Vista interactiva (navegador)

Botón **Vista interactiva (navegador)** o `--web salida.html` en la CLI. Genera un HTML autónomo (Plotly con WebGL, incluido en el archivo) con el mapa a la izquierda y las gráficas a la derecha. Las gráficas se organizan en tres columnas; las filas adicionales se recorren con la barra lateral (en pantallas estrechas se adaptan a menos columnas). Funciones: zoom y desplazamiento sincronizados entre gráficas, cursor compartido (al pasar el mouse por una gráfica o por el mapa se marca ese instante en todo), el tramo con zoom se resalta en la ruta, ruta coloreada por una variable, mapa OpenStreetMap o satélite Esri, mín/prom/máx del tramo visible, ajuste automático del eje Y, activar/desactivar variables y ampliar una gráfica con clic en su título (Esc para volver). Solo los fondos del mapa necesitan internet. El botón de la ventana abre la vista desde un servidor local (`http://127.0.0.1`), porque OpenStreetMap bloquea los tiles pedidos sin Referer, y un HTML abierto como archivo no envía ninguno; por eso un HTML guardado con `--web` y abierto con doble clic arranca con el fondo satélite (el OSM puede salir bloqueado). El HTML contiene los datos del CSV. Requiere `plotly` (ver `requirements.txt`). Las filas se ordenan por la columna de tiempo, igual que en el visor rápido.

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

# Mapa de calor georreferenciado de una variable -> <csv>_<variable>.tif + _puntos.geojson + .qgz:
.venv/bin/python graficar.py mediciones_16sep.csv --calor co2_ppm --celda 5 --suavizado 1.5 --desfase 3

# CSV Campbell (Flight_Data), percentil 95, ignorando lecturas < 300 ppm y con el mosaico térmico debajo:
.venv/bin/python graficar.py Flight_Data_6_Sensor_2_ppm_Avg_cal_n0.csv --calor CO2_Concentration_Avg_cal --min 300 \
    --estadistico p95 --celda 4 --capa ../termoreferencia/resultados/vulcano-porto-levante_python/temperatura_python.tif

# Cualquier CSV con columnas de GPS de nombre no reconocido, o usando el GPS del dron:
.venv/bin/python graficar.py otro.csv --calor NO2 --lat Y_gps --lon X_gps
.venv/bin/python graficar.py mediciones_16sep_gps_dron.csv --calor co2_ppm --gps-dron
```

Opciones de `--calor`: `--calor-salida`, `--celda` (m, desde 0.5; 10), `--celdas` (abrir QGIS con las celdas encendidas en lugar de los puntos), `--tam-punto` (mm, 1.8), `--estadistico media|maximo|p95|muestras`, `--suavizado` (celdas, 1; 0 = sin suavizar), `--desfase` (s), `--min`/`--max` (rango válido), `--capa` (GeoTIFF extra, repetible), `--lat`/`--lon`, `--gps-dron`. Las coordenadas deben venir en grados decimales.

CSV separados por coma, punto y coma o tabulador: el separador se detecta automáticamente. Se admiten decimales con coma en columnas separadas por punto y coma. Las columnas vacías/no numéricas no se ofrecen como variables. Los nombres de columna de otros equipos se reconocen sin importar mayúsculas, acentos ni unidades entre paréntesis (`TIMESTAMP`, `Latitude`, `GPS_Lat`, `CO2 (ppm)`, `Temperature (°C)`…) y se renombran al nombre que usa la app; para añadir otro, agrégalo a `COLUMN_ALIASES` en `graficar.py`. Los valores `-2147483648`, `2147483647`, `-9999` y `-99999` (marcadores de "sin dato" de registradores como Campbell) se tratan como faltantes, y las coordenadas 0,0 (GPS sin señal) no se dibujan en la ruta. Los valores faltantes dejan huecos en las gráficas. Los errores se muestran en la ventana o terminal.

## Instalación desde cero

Python 3.10 o posterior con Tkinter. En Ubuntu, si falta Tkinter, instala el paquete `python3-tk`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./iniciar.sh                    # GasLab 2.0 en el navegador
.venv/bin/python graficar.py    # versión 1 (ventana Tkinter)
```

La 2.0 no necesita dependencias adicionales: Plotly se sirve desde el paquete instalado y MapLibre viene en `web/vendor/`.

El entorno preparado en esta máquina reutiliza pandas y PyQt5 ya instalados mediante `--system-site-packages`; las dependencias adicionales están dentro de `.venv`.

## Ejemplo y pruebas

Las pruebas usan datos **sintéticos** definidos en `test_graficar.py` (GPS, un hueco y un cambio de día en Costa Rica); no son una medición real. Las imágenes y el mapa de `ejemplos/` son de una versión anterior.

```bash
.venv/bin/python -m unittest -v test_graficar.py      # versión 1 y mapa_calor.py
.venv/bin/python -m unittest -v test_gaslab_web.py    # GasLab 2.0 (teselas de relieve simuladas, sin internet)
```

Referencias de los fondos: [Folium: capas de mapas](https://python-visualization.github.io/folium/v0.19.3/user_guide/raster_layers/tiles.html) y [Esri: atribución de mapas base](https://support.esri.com/en-us/knowledge-base/what-is-the-correct-way-to-cite-an-arcgis-online-basema-000012040).


## Incorporación y elección del archivo

El [manual MicroGas](../MicroGas/MANUAL_REPLICACION_DESDE_CERO.md) explica cómo obtener los CSV. Para una sesión larga del receptor usa **Archivos CSV → Exportar**: el botón del histórico solo exporta el buffer de hasta 7.200 muestras. El emisor y el receptor tienen 24 y 16 columnas respectivamente (incluida la altitud: `altura_m` al final en los CSV originales; el visor reconoce también `altitud_m`, `altitud` y `altura`); sus cantidades de filas no tienen por qué coincidir.

En CSV DJI selecciona `sen66_muestra_utc` y **Solo muestras nuevas** para estudiar lecturas; esa fecha es recepción en el control, no adquisición física en la Pi. Usa `fecha_hora_utc` sin filtro para estudiar el registro a ~10 Hz. En Receptor utiliza `fecha_hora_utc`. Los valores `payload_uptime_ms` son tiempo desde arranque y no deben interpretarse automáticamente como fechas Unix.

Conserva un CSV original sin modificar y guarda los resultados aparte. El programa ordena por la columna de tiempo seleccionada, pero no corrige coordenadas que saltan ni diferencia sesiones que no estén identificadas. Analiza vuelos por separado si no existe `session`.

## Guía de mantenimiento y diagnóstico

**GasLab 2.0:** `gaslab_web.py` es el servidor local y la API (`Dataset` carga el CSV con `load_csv`/`parse_time` de `graficar.py`, reduce cada serie a mín/máx por píxel, aplica los límites y prepara el mapa de calor y el terreno). La página está en `web/` (`index.html`, `app.css`, `app.js`; cada paso tiene su `enter…()` en `app.js`). `terreno.py` lee la altura del relieve (AWS Terrain Tiles). La escala adaptativa, la nube y la exportación GeoTIFF/QGIS están en `mapa_calor.py`. Al cambiarlos ejecuta `test_gaslab_web.py`; el `CHANGELOG.md` explica cada paso y sus detalles delicados.

**Versión 1:** el mapa de calor georreferenciado (rejilla, desfase, GeoTIFF, GeoJSON y proyecto QGIS) está en `mapa_calor.py`. `graficar.py` separa carga (`load_csv`), fechas (`parse_time`/`time_axis`), segmentos GPS (`gps_segments`), mapa (`make_map`), vista web (`make_viewer`), ventana de selección (`gui`) y CLI (`main`); el visor rápido está en `visor_qt.py`. Al cambiar fechas o columnas ejecuta `test_graficar.py` y comprueba un CSV de cada app. Los datos de prueba son sintéticos y no validan GPS real.

| Problema | Comprobación |
|---|---|
| No abre la ventana | Entorno `.venv`, Tkinter y sesión gráfica; sin escritorio usa `--web` o `--mapa` |
| No hay ruta | Coordenadas numéricas válidas; MicroGas Simulado desde 0.4.0 genera GPS sintético; archivos antiguos pueden no incluirlo |
| Hora desplazada | Zona IANA, UTC de entrada y unidad Unix elegida |
| Mapa sin fondo | Internet y servicios del navegador; el HTML necesita recursos externos |
| CSV no carga | Encabezado, separador y que no se haya convertido al guardarlo en una hoja de cálculo |
| No guarda resultados | Carpeta de destino existente y con permisos; la CLI no crea carpetas de salida |
| 2.0: no abre el navegador | `./iniciar.sh` muestra en la terminal la dirección `http://127.0.0.1:…`; ábrela a mano |
| `GasLab.exe` no abre ventana | Si no aparece en 2 minutos se cierra solo. Prueba `iniciar.bat` desde el código: la consola muestra la dirección y los errores |
| 2.0: mapa de calor o terreno sin satélite o sin relieve | Internet (Esri y AWS Terrain Tiles); sin conexión, la nube y las barras se ven sobre fondo oscuro, y el relieve solo aparece en zonas ya guardadas en `~/.cache/gaslab_tiles/terrarium` |

Las dependencias se instalan desde cero con los pasos anteriores; no copies `.venv` a otra máquina. Para reproducir una entrega registra también las versiones instaladas con `.venv/bin/python -m pip freeze`.


Marcadores del mapa: inicio 🏠 y fin ✈️ (cámbialos en `START_ICON` y `END_ICON` de `graficar.py`). En los cuadros de datos la altura se muestra como **Altitud**, después de latitud y longitud.

### Columnas calibradas (`_cal`)

Si el archivo trae columnas calibradas con el mismo nombre más `_cal` (Flight_Data: `Sensor_2_ppm_Avg` y `Sensor_2_ppm_Avg_cal`, `Latitude` y `Latitude_cal`…), la lista de variables muestra cada una **una sola vez** y aparece en la cabecera el selector **Original | Calibrado | Comparación**:
- **Original** usa las columnas sin `_cal` y **Calibrado** las `_cal`, en todos los pasos (gráficas, límites, mapa de calor, terreno 3D y exportación a QGIS).
- **Comparación** dibuja en cada gráfica (pasos 1 y 2) la versión calibrada y la sin calibrar (gris punteado), y en el encabezado muestra la diferencia calibrado − sin calibrar del tramo visible (promedio y máxima). Los mapas de los pasos 3 y 4 solo pueden pintar un valor por punto, así que usan el calibrado.

Cambiar de opción conserva las variables elegidas, los límites y la vista, y la app recuerda la elección para los próximos archivos.

### GPS del dron

Si el archivo trae también la posición del dron (`latitud_dron`/`longitud_dron`, `drone_lat`, `UAV Longitude`…: una columna con `dron`, `drone`, `uav` o `dji` en el nombre más `lat`/`lon`), aparece en la cabecera el selector **GPS sensor | Dron | Ambos**:
- **GPS sensor** usa `latitud`/`longitud` del archivo y **Dron** las del dron, en la ruta, el mapa de calor, el terreno 3D, QGIS y la hoja Ruta del Excel. Con el dron, las filas sin posición del dron quedan sin punto: no se rellenan con la del sensor.
- **Ambos** dibuja en la ruta del paso 1 la del dron (color) y la del sensor (gris punteado), e indica la distancia entre las dos donde hay ambas (mediana, promedio y máxima). Los pasos 3 y 4 usan la del dron, y el Excel lleva las dos posiciones en Datos.
- Altura en el terreno 3D con el dron: la absoluta del dron (`altitud_dron_m`, no la relativa al despegue); si el dron no trae altura, la del archivo.
- Las columnas de latitud y longitud del dron no salen en la lista de variables; las de altura y vuelo sí.

Igual que el de calibración, se recuerda para los próximos archivos y solo aparece si el archivo trae las dos posiciones. El CSV con las columnas del dron todavía hay que armarlo afuera (como `mediciones_16sep_gps_dron.csv`).

### Tabletas

En una tableta con Windows funciona igual (en Windows en ARM hace falta Windows 11; en "modo S" no se pueden abrir programas fuera de la Store). Con el dedo:
- **Gráficas:** un dedo desplaza y **pellizcar con dos dedos** acerca o aleja, como la rueda del mouse (las demás gráficas siguen igual). Tocar la línea muestra el valor; un doble toque devuelve la vista completa.
- **Mapa de calor y terreno 3D:** mover, pellizcar y girar o inclinar con dos dedos. **Tocar una muestra** muestra su valor, igual que al pasar el mouse.
- Arrastrar archivos a la página no funciona con el dedo: usa **Abrir archivo…**.

## Android (APK)

`GasLab.apk` es **GasLab 2.0** como app de Android (tabletas y teléfonos con Android 11 o más nuevo, procesador ARM de 64 bits, como la Lenovo Idea Tab Pro). Es la misma página y el mismo servidor Python de la PC: Python va dentro de la app ([Chaquopy](https://chaquo.com/chaquopy/)) y la página se muestra en un WebView a pantalla completa, sin barra de direcciones. Pesa unos 45 MB.

- **Instalar:** copiar `GasLab.apk` a la tableta (USB, Drive, correo…), abrirlo y aceptar *Instalar apps desconocidas* para la app con que se abrió. Para actualizar, se instala el nuevo encima: no se pierde nada.
- **Abrir archivo…** usa el selector de Android (Descargas, Drive, memoria USB…). **Guardar** (Excel, PNG, GeoTIFF + QGIS, KMZ) deja el archivo en **Descargas**; si ya existe, Android le agrega (1), (2)…
- **Atrás** sale de la pantalla completa; si no, deja GasLab en segundo plano sin perder el archivo abierto. Si Android cierra la app por falta de memoria, hay que abrir el archivo de nuevo.
- El tacto funciona como en las tabletas con Windows (ver *Tabletas*). El satélite y el relieve necesitan internet, igual que en la PC.

**Compilar:** `make android` (o `cd android && ./gradlew assembleRelease`) deja `dist/GasLab.apk`. Necesita Java 17, el SDK de Android (`android/local.properties` con `sdk.dir=…`, o la variable `ANDROID_HOME`), Python 3.10 en el PATH (Chaquopy lo usa para instalar los paquetes) y el `.venv` del proyecto (de ahí sale `plotly.min.js`). La primera vez descarga Gradle, Chaquopy y los paquetes de Android (numpy 1.26, pandas 2.1). No hay que copiar nada a mano: en cada compilación se toman los `.py` y `web/` del proyecto. Va firmada con la llave de depuración, así que se instala directo, pero no sirve para Play Store.

Archivos: `android/app/build.gradle` (qué se empaqueta), `android/app/src/main/java/cr/gaslab/app/MainActivity.java` (WebView, abrir y guardar archivos, pantalla completa) y `android/app/src/main/python/gaslab_android.py` (arranca el servidor en el puerto 47800). Para revisar la página en la tableta: conectar por USB con depuración activada y abrir `chrome://inspect` en Chrome de la PC.

## Ejecutable de Windows

`GasLab.exe` es **GasLab 2.0** como app de escritorio: no muestra consola, abre su propia ventana (Edge o Chrome en modo app, sin pestañas ni barra de direcciones; Edge viene con Windows 10 y 11) y se cierra sola unos segundos después de cerrar esa ventana. Si no encuentra Edge ni Chrome, abre una pestaña del navegador predeterminado. La versión 1 ya no va en el ejecutable; sigue disponible desde el código (`graficar.py`).

En Windows con Python 3.10 a 3.14 de 64 bits (de python.org): doble clic a `build_windows.bat` (o `pyinstaller --noconfirm GasLab.spec` tras instalar `requirements-build.txt`). El resultado queda en `dist\GasLab\`; esa carpeta completa se puede copiar a otro equipo y ejecutar `GasLab.exe` (conviene crear un acceso directo en el escritorio). En GitHub, el workflow *Build Windows* (pestaña Actions → Run workflow, o al subir una etiqueta `v*`) lo compila y lo publica como artefacto `GasLab-windows`.

Desde el código, en Windows: `iniciar.bat` (doble clic) abre la 2.0 en su ventana con el `.venv` del proyecto. `--ventana` hace lo mismo en cualquier sistema: `.venv/bin/python gaslab_web.py --ventana`.

Si el `.exe` dice *Failed to load Python DLL ... `_internal\python3XX.dll`* o `dist\GasLab\_internal` sale casi vacío: compila con Python de [python.org](https://www.python.org/downloads/), **no el de Microsoft Store** (PyInstaller no puede copiar su DLL), revisa que el antivirus no haya borrado archivos de `dist\` y copia siempre la carpeta `dist\GasLab\` completa. `build_windows.bat` detecta el Python de Store y un `.venv` inválido (lo rehace), y avisa si falta el DLL al terminar.

## Makefile

`make help` lista los objetivos: `make setup` (crea `.venv`), `make run` (abre GasLab 2.0 en el navegador), `make test` (corre `test_graficar.py` y `test_gaslab_web.py`), `make build` (genera `dist/GasLab/` con la 2.0; `GasLab.exe` en Windows), `make android` (genera `dist/GasLab.apk`) y `make clean`. En Windows hace falta GNU make (`choco install make` o `winget install ezwinports.make`); `build_windows.bat` sigue funcionando sin make.
