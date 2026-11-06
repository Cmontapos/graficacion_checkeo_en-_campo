# Cambios

## 2026-11-06 · GasLab 2.0 en inglés
- **Qué:** a pedido del usuario, la 2.0 queda solo en inglés: pestañas, botones, ayudas ⓘ, avisos, mensajes de error del servidor, el arranque del APK y los archivos exportados. El Excel trae las hojas **Summary, Data, Charts, Route** con encabezados `Date and time (zona)` y `Elapsed (s)`. Los archivos de QGIS se llaman `_cloud.tif`, `_values.tif` y `_points.geojson`, y los de Google Earth `_route.kmz` y `_bars3d.kmz`. La versión 1 (`graficar.py`) sigue en español, pero su Excel también sale en inglés porque usa el mismo `make_excel()`. El código, los comentarios y el README siguen en español, y los nombres de columnas del CSV no cambian.
- **Dónde:** `web/index.html`, `web/app.js` (textos y `toLocaleString('en')`), `gaslab_web.py`, `kmz.py`, `mapa_calor.py` (`export_cloud`; en el GeoJSON, `fecha_utc` pasa a `time_utc`), `terreno.py`, `graficar.py` (`make_excel`, `read_excel` y los errores de carga) y `android/.../MainActivity.java`. Las opciones de la línea de comandos (`--puerto`, `--sin-navegador`, `--ventana`) no cambian.
- **Ojo:** los Excel exportados antes en español se siguen abriendo: `read_excel` busca la hoja `Data` o `Datos` y acepta `Date and time (…)`/`Fecha y hora (…)` y `Elapsed (s)`/`Transcurrido (s)`. La nueva prueba `test_old_spanish_excel_still_opens` lo cubre. Los números del KMZ usan punto decimal. Las 45 pruebas pasan, y en Brave headless ningún paso mostró textos en español ni errores de JS.

## 2026-11-06 · Análisis con Edición, recorrido en gris y esferas en el terreno
- **Qué:** a pedido del usuario:
  - Se quitan **↶ Anterior / Siguiente ↷**.
  - Con un tramo o recorrido elegido, el paso 1 muestra toda la medición: lo de fuera va en **gris** en la ruta, la altura, las gráficas de variables y la combinada. Las gráficas ya no quedan encerradas en el tramo: empiezan acercadas a él y **Restablecer zoom** vuelve a él. Los pasos 2 a 5 siguen usando solo el tramo.
  - Los pasos «Análisis» y «Límites» se juntan en **2 · Análisis**: botones con las variables marcadas, panel **Edición** a la izquierda (por ahora solo **Límites** de la variable que se ve, más «Comparar con original» y el conteo de ajustadas) y, en la gráfica, **+** para comparar con otra variable marcada en el eje derecho (por defecto **Ninguna**). Los pasos quedan: 1 Datos, 2 Análisis, 3 Mapa de calor, 4 Terreno 3D, 5 Excel.
  - En el terreno 3D cada muestra es una **esfera** en lugar de un cubo.
- **Dónde:** `web/app.js`:
  - Paso 1: `view1()` (zoom propio o el tramo), `splitByTramo()`, `draw()` y `drawAll()` con la traza gris; `refresh()` ya no manda el tramo; `loadRoute()` pide también la ruta completa (`state.routeFull`, `state.routeCurves`); se quitan `keepInside()` y el historial.
  - Paso 2: `enterAnalysis()`, `renderPick()`, `renderEdit()`, `renderCompare()` (`state.cmp`), `refreshBig()` con `yaxis2` y `bigAxes()`. Se quitan las filas «Dato | Máximo | Mínimo» y «+ Agregar límite».
  - Terreno: `drawPoints3d()` arma cada esfera con `SPHERE_SLICES` discos de `SPHERE_SIDES` lados, cada uno con su base y su tope (`b`, `h`) relativos al pie; `terrainPaint()` les suma la base.
  - `excelRange()` recorta la parte visible al tramo.
  - `gaslab_web.py`: en `series()`, las muestras ajustadas se cuentan dentro del tramo; antes se contaban en todo el archivo.
- **Ojo:**
  - Las esferas son discos apilados, porque MapLibre solo levanta prismas: hay 6 elementos por muestra en lugar de 1. Con 3774 muestras se probó sin errores.
  - La exportación a Google Earth del terreno no cambió.
  - Probado en Brave headless con `mediciones_16sep_gps_dron.csv` (recorrido con clics reales, gris en ruta y altura, límites y comparación con «+», terreno y Excel) y `Flight_Data_6_...` (Comparación de calibración y una sola variable, con «+» desactivado). La prueba `test_limits_saturate_without_dropping_samples` cubre el conteo dentro del tramo.

## 2026-11-06 · Recorrido con dos clics y Anterior / Siguiente
- **Qué:** en la fila Tramo del paso 1, **Elegir recorrido (2 clics)**: clic en el inicio y en el fin en cualquier gráfica del paso 1, y solo queda ese recorrido en la ruta, las gráficas, el análisis, los límites, los mapas y el Excel, igual que un tramo (no se borra nada). **↶ Anterior** y **Siguiente ↷** deshacen y rehacen cada cambio de recorrido (dos clics, lista, día y **Todo**), y los selectores de la fila vuelven a mostrar lo elegido.
- **Dónde:** `web/index.html` → `#pickrec`, `#tundo`, `#tredo`. `web/app.js` → `state.pick`, `showPick()`, `stopPick()`, `pickPoint()` (con `plotly_click` en `wire()`) y `pickMarks()`, que `cursor()` agrega a la línea del cursor; `state.history`/`state.hpos`, `setTramo(tramo, remember)`, `moveHistory()` y `showTramoBoxes()`. Los tramos de la lista guardan `k`, y los de día guardan `from`/`to`, para poder restaurar los selectores.
- **Ojo:** el clic se ajusta a la muestra más cercana. El recorrido es un tramo con `kind: 'pick'`, así que el servidor no cambia (`w0`/`w1`) y el nombre del Excel lleva `_rec_HHMM-HHMM`. El historial se reinicia al abrir otro archivo o cambiar de zona, porque los tiempos dependen de la zona. Al cambiar **Inactividad**, un tramo guardado de la lista se restaura con su rango aunque la lista ya no lo muestre. Probado en Brave headless con clics reales del mouse.

## 2026-11-06 · Gráfica con todas las variables y paso 2 «Análisis»
- **Qué:** en el paso 1, la primera gráfica de la derecha junta **todas las variables** marcadas, con **Normalizada | Valores reales** (normalizada: cada variable de 0 % a 100 % entre su mínimo y su máximo en lo visible, con el valor real al pasar el mouse). Los botones **Todas | variable…** dejan ver una sola variable, en grande, ocultando las demás. Nuevo paso **2 · Análisis**: dos variables en una gráfica, una con el eje izquierdo y otra con el derecho, cada eje con el color de su variable. Los demás pasos se corren: 3 Límites, 4 Mapa de calor, 5 Terreno 3D, 6 Excel.
- **Dónde:** `web/index.html` → `#solo`, `#norm`, `#allcard`/`#allchart` y `#step-analisis` (`#aleft`, `#aright`, `#acmp`). `web/app.js` → `renderSolo()`, `drawAll()` (usa los mismos datos que `refresh()` ya pide, sin un pedido extra) y `spanOf()` (lo visible sin margen; `yRange()` lo usa); `enterAnalysis()`, `refreshAnalysis()` y `sideAxis()`. Los pasos ahora tienen nombre (`data-step="datos|analisis|limites|calor|terreno|excel"`, `#step-…`, `state.step` es un texto) y `refreshStep()` refresca el paso abierto al cambiar tramo, calibración o GPS. El servidor no cambia (`/api/series` ya acepta dos variables).
- **Ojo:** la normalización es sobre lo visible, así que al acercar las curvas se reajustan (igual que el eje Y de las demás). La combinada solo aparece con dos o más variables y entra en el zoom y el cursor compartidos. En Comparación (calibración) la combinada lleva solo la versión calibrada. El análisis usa siempre valores sin límites. Probado en Brave headless con `mediciones_16sep_gps_dron.csv` y `Flight_Data_6_...` (zoom compartido, una sola variable, ejes del análisis, pasos 3–6 y tema). Al cambiar de paso, MapLibre registra el error `clearFadeHold` en la consola; también pasa con la versión anterior.

## 2026-11-06 · Límites opcionales en el Excel
- **Qué:** el paso 5 tiene la casilla **Aplicar los límites del paso 2**, apagada por defecto. Apagada, el Excel y su vista previa llevan los valores sin ajustar, como en el archivo original; marcada, se comportan como desde el 2026-11-05 (valores ajustados y límites en el título del Resumen). Junto a la casilla se indica qué variables se ajustan o que no hay límites escritos. Los límites siguen aplicándose siempre en las gráficas, el mapa de calor, el terreno, QGIS y Google Earth.
- **Dónde:** `web/index.html` → fila **Límites** del paso 5 (`#xlimits`, `#xlimnote`); `web/app.js` → `state.excel.limits`, y `excelQuery()` solo manda `limits` si está marcada. El servidor no cambia: sin `limits`, `excel_parts()` usa los valores originales.
- **Ojo:** volver a abrir en la app el Excel exportado ya funcionaba (hoja `Datos`, hora local → UTC). Se comprobó con `mediciones_16sep_gps_dron.csv` (GPS Ambos) y `Flight_Data_6_...`: mismas filas, horas y valores, y el selector del dron vuelve a aparecer. La casilla no se recuerda al recargar la página.

## 2026-11-05 · App de Android (APK)
- **Qué:** GasLab 2.0 como app de Android (`dist/GasLab.apk`, ~45 MB, Android 11+ ARM64). Es la misma interfaz y el mismo servidor de la PC: Python con Chaquopy y la página en un WebView. Abrir archivo usa el selector de Android, Guardar deja los archivos en Descargas, funciona la pantalla completa de las gráficas y Atrás deja la app en segundo plano sin perder el archivo.
- **Dónde:** `android/` (proyecto Gradle: `app/build.gradle`, `MainActivity.java`, `gaslab_android.py`), `make android`. En `web/app.js`, `saveFrom()` y el PNG del mapa usan `window.GasLabAndroid` cuando existe (en un WebView no hay descargas de `blob:`); en la PC no cambia nada. `gaslab_web.py` sirve `web/vendor/plotly.min.js` si está (la APK lo trae ahí y no necesita el paquete plotly).
- **Ojo:** la APK lleva numpy 1.26.2 y pandas 2.1.3 (las versiones de Chaquopy para Python 3.10), no las de la PC: `test_gaslab_web` pasa completo con esas versiones. El servidor se probó en la PC sin plotly, igual que en la APK. **No se ha probado en un dispositivo ni en un emulador** (la imagen del emulador está incompleta y no hay espacio en disco para bajarla).

## 2026-11-05 · Escala «Original | Lineal | Exponencial»
- **Qué:** el selector de divisiones del paso 3 tiene tres opciones. **Original** (por defecto) es la escala de antes, idéntica: divisiones del mismo ancho, y las que tienen menos del % mínimo de las muestras se unen a su vecina. Al elegirla, el % mínimo se pone en 5 %, como antes, y se puede cambiar. Al elegir **Lineal** o **Exponencial**, el % vuelve a 0 %; esas dos siguen igual.
- **Dónde:** `mapa_calor.adaptive_classes(spacing='original')` usa la misma llamada `np.histogram(bins, range)` de antes y `ORIGINAL_MIN_PCT = 5`; `mapa_calor.SPACINGS`; `gaslab_web.py` acepta `spacing=original` (también es el valor por defecto) y, sin `minpct`, usa 5 % en Original y 0 % en las demás; `web/app.js` → `syncMinPct()` pone el % inicial de cada escala.
- **Ojo:** se comparó con la versión del commit af9f702 en Flight_Data_6, mediciones.csv y el .dat de Miravalles: 117/117 escalas idénticas. Test: `test_original_is_the_old_scale`.

## 2026-11-05 · El Excel aplica los límites del paso 2
- **Qué:** el Excel exportaba las variables con los valores originales aunque hubiera límites en el paso 2. Ahora van ya ajustadas, igual que en el mapa de calor y el terreno: lo que pasa del máximo queda en el máximo y lo que baja del mínimo queda en el mínimo. Se ajustan las hojas Datos, Resumen y Gráficas, y también la vista previa. El título del Resumen indica los límites usados (p. ej. `· límites: co2_ppm máx 1000`), y la fila Contenido del paso 5 los menciona. La latitud, la longitud y la altura no se tocan.
- **Dónde:** `gaslab_web.py` → `Dataset.excel_parts(limits=)`, que usa `values()` en las variables marcadas; `excel()` y `excel_preview()` lo pasan (la vista previa también a `series()`), y `/api/excel` lee `limits` con `parse_limits()`. `web/app.js` → `excelQuery()` manda `limitsMap()` y `enterExcel()` lo muestra. Test: `test_excel_uses_the_limits_of_step_2`.

## 2026-11-04 · Desfase del paso 4: número primero, barra de ajuste fino
- El campo numérico del **Desfase** va primero y acepta cualquier valor (paso 0,1 m). La barra ya no va de −100 a 100 m: mueve ±5 m alrededor del número actual y, al soltarla, se recentra en el nuevo valor. Así se puede llegar lejos escribiendo y afinar con la barra.

## 2026-11-04 · Divisiones lineales o exponenciales; % mínimo en 0 % por defecto
- Paso 3, fila **Escala**: selector **Lineal | Exponencial** (con ⓘ) para las divisiones iniciales. Exponencial: cada división es un factor fijo más ancha que la anterior, y la última es 1000 veces la primera (`mapa_calor.initial_edges`, `EXP_DECADES = 3`). Funciona también con valores negativos o cero.
- El **% mínimo por división** empieza en 0 %: no se une ninguna división, así que en Lineal todas tienen el mismo ancho. El servidor también usa 0 % cuando no recibe el valor.
- La misma escala se usa en el paso 4, en el PNG, en el GeoTIFF + QGIS y en el KMZ (parámetro `spacing` de la API).

## 2026-11-04 · 3D más fluido
- **Qué:** el usuario dijo que el 3D "se pega". Mediciones en Brave headless con `mediciones_16sep_gps_dron.csv`, por cuadro:
  - Terreno con cubos: 129 ms. Sin cubos: 125 ms. Sin relieve: 31 ms. **Lo pesado es el relieve, no los cubos.**
  - Con `pixelRatio` 2: 432 ms. A 1×: 243 ms.
  - Además, cada movimiento de un deslizador rearmaba miles de prismas, y los cambios se encolaban.
- **Cambios** (todos en `web/app.js`):
  - **Resolución del terreno 3D:** se dibuja a 1× (`pixelRatio: min(dpr, 1)`). En pantallas con escala de Windows de 150–200 % es la mayor ganancia.
  - **Altura sin rearmar:** la altura de las barras (`r` × altura máxima) y la de los cubos (`alt − ground + desfase`, o el desfase pegado al terreno) son expresiones del mapa. Mover la altura máxima, el desfase o cambiar de modo ya no rearma la geometría.
  - **`latestOnly(map)`:** mientras el mapa procesa un cambio, los siguientes se juntan y solo se aplica el último, en lugar de encolarlos. `setFilter` se aplica solo si cambió el modo.
  - **Barras perezosas:** se arman solo en 3D, y el ancho se aplica con espera (`scheduleBars`). En 3D se apaga la capa invisible de muestras, que solo sirve para leer valores en 2D.
  - **Cubos del paso 4:** se rearman solo si el zoom cambió medio nivel o más, en vez de con cada zoom.
  - **`hoverValues()`:** como mucho una consulta del valor bajo el mouse por cuadro, y ninguna mientras el mapa se mueve o gira.
- **Ojo:** cambiar el tamaño de las teselas de relieve (512) o quitar el fundido de teselas no cambió nada medible. Quitar el relieve hace el 3D unas 4 veces más rápido; queda como opción a proponer.

## 2026-11-04 · KMZ del paso 3 según la vista; deslizador de desfase
- **Qué:** como pidió el usuario, el KMZ del paso 3 lleva lo que se ve: en **2D** la nube y en **3D** las barras. Las dos con la leyenda y la ruta. El del paso 4 sigue con las muestras de color a su altura. Ya no se mezclan muestras y barras encima de la nube, que en Google Earth web la tapaban (allá no hay capas ocultas). En el paso 4, el **Desfase** suma un deslizador de −100 a 100 m, sincronizado con el campo numérico.
- **Dónde:** `Dataset.kmz()` con `kind` `'heat'` (2D) o `'bars'` (3D, archivo `…_barras3d.kmz`). La ruta va visible en todos. `web/app.js` → `#hkmz` elige el kind según `state.heat.view`, y `#toffsetr`/`#toffset` se sincronizan.
- **Ojo:** el error "exceed the map's limit" al importar en la web es del proyecto (20 000 elementos en total), no del archivo; se resuelve con un proyecto nuevo. Test: `test_kmz_for_google_earth` (2D sin barras; 3D con 3 barras y sin nube).

## 2026-11-04 · KMZ sin TimeStamp ni ScreenOverlay
- **Qué:** el usuario probó en Google Earth en el navegador. Con **Data layer** todo salía amarillo y sin nube. Con **Map features** daba error: `Unsupported element: "TimeStamp"` en la ruta y `Unsupported element: "ScreenOverlay"` en la leyenda; la nube y los puntos de colores pasaban bien.
- **Cambios:**
  - La hora va en la descripción de cada punto, y en la de Inicio y Fin, en lugar de un `TimeStamp`.
  - La leyenda es un punto **«Leyenda»** en la esquina noroeste de los datos, con la tabla de colores. Ya no es una imagen fija en pantalla, y el KMZ ya no lleva `files/leyenda.png`. `kmz.legend_png()` se borró.
- **Ojo:** Google Earth Pro pierde la leyenda fija y la barra de tiempo, pero el mismo archivo sirve en los dos. El test verifica que no haya `TimeStamp` ni `ScreenOverlay`. Las barras 3D (`Polygon` extruido) y los puntos con altura `absolute` aún no se habían probado en la web: hay archivos de prueba en `CO2_georeferenciado/prueba_kmz/`.

## 2026-11-04 · KMZ compatible con Google Earth en el navegador
- **Qué:** un KMZ del mapa de calor se veía como "un montón de puntos amarillos". Tenía unos 12 800 elementos (muestras y barras ocultas), y Google Earth en el navegador importa como máximo 10 000 y no muestra leyendas fijas ([guía de importación KML](https://support.google.com/earth/community-guide/307322063/google-earth-kml-import-guide?hl=en)).
- **Cambios:**
  - Las muestras se reparten a lo largo del tramo hasta `MAX_FEATURES = 9000` elementos por KMZ: en el mapa de calor, mitad muestras y mitad barras.
  - El ícono de los puntos es el círculo blanco de Google (`kmz.ICON`), que se tiñe con el color de cada división, en lugar de uno dentro del KMZ.
  - La leyenda va también como tabla en la descripción de su carpeta.
- **Ojo:** el ícono se descarga de Google; Google Earth necesita internet de todas formas para la imagen satelital. En Google Earth Pro todo sigue igual: leyenda fija, capas ocultas, etc.

## 2026-11-04 · Alcance, enfriamiento y tamaño independientes
- **Qué:** como pidió el usuario, el **Alcance** ahora solo cambia hasta dónde se extiende la nube; los colores y la opacidad del centro no cambian. El **Enfriamiento** decide el tamaño de la zona de calor, en metros: con 1, el 60 % a 10 m; con 4, a 5 m. El **Tamaño** sigue siendo el detalle alrededor de cada muestra. Esto reemplaza la versión de más abajo, donde el enfriamiento se repartía según el alcance.
- **Dónde:** `mapa_calor.cloud()`. `COOL_SCALE_M = 10` m es la escala fija del enfriamiento (`exp(-cool·d²/2·10²)`, con d = metros a la muestra más cercana) y del promedio lejos de las muestras (segundo núcleo gaussiano de 10 m). El borde y la opacidad salen de la distancia a la muestra más cercana: opaca hasta la mitad del alcance y con un desvanecimiento suave (smoothstep) en la mitad exterior. Ya no hay dos caminos (alcance corto / largo): siempre es el mismo cálculo. `_distance_px(f, shift)` usa una celda gruesa fija (1/24 de la escala) alineada con la vista, así el resultado no depende del margen, que crece con el alcance.
- **Ojo:**
  - Con alcances cortos, el enfriamiento ahora es más suave que antes, porque ya no se mide en tamaños sino en metros (escala de 10 m).
  - La exportación (GeoTIFF/KMZ) calcula siempre los dos núcleos: unos 5 s para una imagen de 2500 px. En la app, menos de 1 s por vista normal.
  - Tests: `test_reach_only_extends_the_cloud_and_cooling_sets_the_heat_zone` (alcance 20 vs 40 m: el centro idéntico pixel a pixel; más enfriamiento, zona de calor más chica) y `test_cloud_cools_toward_the_sides` ajustado.

## 2026-11-04 · Nube de color más parejo
- **Qué:** con alcance largo, la nube era una línea fina con el color medido dentro de una franja azul plana de 30 m. Pasaba porque el enfriamiento dependía del Tamaño (1 m): el color llegaba al mínimo en 2–3 m y el resto de la nube quedaba de un solo color. Ahora el enfriamiento se reparte en todo el Alcance, y el color baja de a poco hasta el borde. El paso del valor de cada muestra al promedio de la zona también es más suave: va de ~2 a ~5 tamaños, en lugar de cambiar de golpe.
- **Dónde:** `mapa_calor.cloud()`: el enfriamiento usa `near` (gaussiana de ancho alcance / 2,5) en vez de la densidad del Tamaño, y `blend` va de densidad 0,1 a 1e-6, al cuadrado. Con el alcance de 2,5 tamaños `near` es la misma densidad de antes, así que ahí no cambia nada. Textos de ayuda (ⓘ) y README actualizados.
- **Ojo:** lejos de las muestras, el color es el promedio de las muestras cercanas (una estimación) que se va enfriando. Para ver menos color lejos: más enfriamiento o menos alcance.

## 2026-11-03 · Google Earth (.kmz) para todo lo que tiene mapa
- **Qué:** un botón **Google Earth (.kmz)** en la ruta del paso 1, en Guardar del paso 3 y en un nuevo Guardar del paso 4. Paso 1: la ruta. Paso 3: la nube, la leyenda, las muestras y las barras 3D (estas dos apagadas) y la ruta. Paso 4: las muestras a su altura (o pegadas al terreno) con el desfase, la leyenda y la ruta. Todos respetan el tramo, el GPS (en Ambos, la ruta con los dos), la señal, los límites y la escala.
- **Dónde:** `kmz.py` (nuevo) → `route_kml()`, `points_kml()`, `bars_kml()`, `overlay_kml()`/`overlay_png()`, `legend_png()` y `build()`. `gaslab_web.py` → `Dataset.route_segments()`, `kmz_routes()`, `kmz()` y `/api/kmz?kind=route|heat|terrain`. `web/app.js` → `kmzQuery()` y `saveFrom()`, una descarga común que ahora usa también el Excel.
- **Nube con alcance largo:** el borde de la nube (más de 4 tamaños) ahora sale de la **distancia a la muestra más cercana** (`mapa_calor._distance_px`: distancia euclidiana en dos pasadas sobre una cuadrícula gruesa). Antes salía de la suma de gaussianas, que a lo largo de una ruta con muchas muestras seguidas estiraba la nube a unos 47 m con 30 de alcance y la cortaba contra el borde de la imagen exportada. Ahora llega justo al alcance, en la app y en GeoTIFF/KMZ.
- **Ojo:**
  - La nube viene en Web Mercator y KML la estira en grados, así que `overlay_png()` remuestrea las filas a latitud lineal.
  - Las alturas van como `absolute`, que en Google Earth es sobre el nivel del mar (EGM96); la diferencia con el elipsoide del GPS se corrige con el desfase.
  - La fuente que trae Pillow no tiene el guion largo, así que la leyenda usa «a».
  - Test: `test_kmz_for_google_earth`. Probado en Brave headless: las tres descargas, con el tramo 2 y Ambos.

## 2026-11-03 · Terreno: desfase y pegado al relieve; nube de hasta 50 m; enfriamiento hasta 10
- **Qué:**
  - **Paso 4:** **Altura: Medida | Pegada al terreno** y **Desfase (m)**. El terreno 3D ya no exige columna de altura: sin ella, las muestras van pegadas al relieve.
  - **Paso 3:** **Alcance** ahora va en metros (1–50 m, 30 por defecto). Antes iba en veces el Tamaño, como máximo 4 (8 m con 2 m de tamaño).
  - **Enfriamiento:** de 0 a 10. Antes llegaba hasta 5.
- **Dónde:**
  - `mapa_calor.cloud()`: más allá de `CLOUD_SAFE_REACH` (4 tamaños) usa un segundo núcleo, de ancho alcance/2,5, para el borde y el valor de la cola. Para una muestra aislada da el mismo borde que la fórmula anterior, que sigue igual hasta 4 tamaños. La mezcla entre los dos promedios es suave, sin costura.
  - `_gauss_fft()` rellena con ceros hasta un tamaño de FFT rápido (factores 2, 3 y 5), calcula el pico con el núcleo separable y reutiliza la transformada para varios sigmas. Con esto, una vista de 2600 px pasa de 3,8 a 2,0 s con el alcance de siempre, y una de 30 m tarda 3,5 s (0,6 s en una vista de 1400 px).
  - La página manda `reach` = alcance en metros / tamaño. `Dataset.terrain()` acepta archivos sin altura (`altitude: None`).
  - `web/app.js`: `showTerrainMode()` (aviso de muestras bajo el relieve, recalculado con el desfase) y `drawPoints3d()`.
- **Ojo:** con 30 m y enfriamiento, alrededor de la ruta queda una franja azul (frío) de 30 m. Para verla menos tapada, baja la opacidad; con enfriamiento 0, la franja muestra el promedio de las muestras cercanas. Tests: `test_cloud_reach_up_to_30_m_with_a_small_size` y el caso sin altura en `test_terrain_puts_each_sample_above_ground`.

## 2026-11-03 · Tramos como en la versión 1, y tema claro/oscuro
- **Qué:** fila **Tramo** en el paso 1: **Inactividad > N s** + lista de tramos continuos, **Día de … a …** y **Todo**, como en la versión 1. El tramo limita todas las pestañas (gráficas, ruta, límites, mapa de calor, terreno, QGIS y Excel), y en el paso 1 las gráficas quedan encerradas en él. El paso 5 suma la opción **Tramo elegido**. Botón de **tema** (automático / claro / oscuro) en la cabecera.
- **Por qué el tema:** la app sigue el tema del sistema (`prefers-color-scheme`). En Windows con modo claro, la app de Windows se veía clara, y en Linux oscura. Ahora se puede forzar.
- **Dónde:** `gaslab_web.py` → `Dataset.tramos(zone, gap_s)` (`/api/tramos`) y `Dataset.window(zone, w0, w1)`. Todos los pedidos aceptan `w0`/`w1` (ms "de reloj" de la zona), y `series`, `route`, `heat_samples` (y con él `heat`, `terrain`, `heat_image` y `heat_zip`) reciben `window`. El Excel recibe el tramo como `start`/`end` y `tag` para el nombre. `web/app.js` → `loadTramos()`, `setTramo()`, `withTramo()`, `keepInside()` (encierra el paso 1) y `applyTheme()`/`redrawAll()`; Plotly guarda los colores al dibujar, así que cambiar el tema redibuja. `web/index.html` → `.tramobar`, `#theme` y un script en `<head>` que aplica el tema guardado antes de pintar.
- **Ojo:** los tramos se cortan con la hora UTC (pausas reales), y la lista y los días se muestran en la zona elegida; cambiar de zona quita el tramo. Con la zona en `UTC`, las horas de `Día de … a …` son UTC. Test: `test_tramos_like_version_1_limit_every_step`. Probado en Brave headless con `mediciones_16sep_gps_dron.csv`: 4 tramos con 60 s, el desplazamiento queda dentro del tramo y el tema cambia y se recuerda al recargar.

## 2026-11-03 · Paso 5: Excel con vista previa
- **Qué:** nueva pestaña **5 · Excel** que arma el libro de la versión 1 (Resumen, Datos, Gráficas y Ruta) con las variables marcadas, la versión en uso, el GPS elegido y la zona horaria. Ofrece **todo el archivo** o el **tramo visible del paso 1**, y antes de descargarlo muestra una vista previa con las hojas como pestañas abajo.
- **Dónde:** `gaslab_web.py` → `Dataset.excel_parts()` (lo común), `excel()` (bytes del .xlsx con `graficar.make_excel()`), `excel_preview()`, `/api/excel` y `/api/excel/preview`. `Handler.download()` y `attachment()` sirven la descarga y el .zip de QGIS con `filename*` UTF-8, para los nombres con acentos. `graficar.make_excel()` → parámetros nuevos `gps`, `also` y `route_name`; la versión 1 sigue igual. `web/app.js` → `enterExcel()`, `refreshExcel()` y `renderExcelSheet()`. `GasLab.spec` → `xlsxwriter` en `hiddenimports`.
- **Ojo:** la página descarga con `fetch` y un blob, así un error se muestra como aviso en lugar de bajar un archivo con el error. La vista previa colorea cada gráfica igual que Excel (paleta por orden de columna), que puede diferir del color de la misma variable en el paso 1. Tests: `test_excel_like_version_1_with_preview` y la descarga en `test_upload_and_series_over_http`.

## 2026-11-03 · Selector GPS sensor | Dron | Ambos
- **Qué:** si el archivo trae la posición del dron, la cabecera muestra **GPS sensor | Dron | Ambos**. La fuente elegida se usa en la ruta, el mapa de calor, el terreno 3D, QGIS y el Excel. En Ambos, la ruta muestra las dos con la distancia sensor–dron, y los mapas usan la del dron.
- **Dónde:** `gaslab_web.py` → `drone_columns()` (nombres flexibles), `distance_m()`, `Dataset.gps_columns(gps)` y `drone_info()` (en `info()['drone']`), y el parámetro `gps` en `route`, `heat_samples`, `heat`, `terrain`, `heat_image`, `heat_zip` y en las URLs. A diferencia de la calibración, no hay una segunda copia de los datos: el servidor guarda las dos posiciones y cada pedido dice cuál usar. `web/app.js` → `gpsMode`, `mapGps()`, `bothGps()` y `loadRoute()`, que en Ambos dibuja primero la ruta del sensor; `state.routeBase` corre los índices del resaltado y del cursor.
- **Ojo:** en `mediciones_16sep_gps_dron.csv`, 1149 de 3774 filas tienen posición del dron. La distancia al GPS del sensor tiene mediana 4,7 m, pero promedio 44,7 m y máximo 356 m: conviene revisar cuál de los dos es confiable en esos tramos. Test: `test_drone_gps_is_a_second_source_for_the_maps`.

## 2026-11-03 · Original | Calibrado | Comparación
- **Qué:** el switch Calibrado pasó a ser un selector de tres opciones. **Comparación** dibuja en las gráficas de los pasos 1 y 2 la versión calibrada (color) y la sin calibrar (gris punteado). En el encabezado de cada gráfica se ve la diferencia calibrado − sin calibrar del tramo visible (promedio y máxima). Los mapas usan el calibrado. Si el switch anterior estaba encendido (`'1'` guardado), se abre en Calibrado.
- **Dónde:** `gaslab_web.py` → `Dataset.series(other=)`, el parámetro `compare` de `/api/series` (id de la otra versión) y `cal_vars`; solo las variables con `_cal` llevan `compare` y `diff`. `web/app.js` → `calMode`, `compareId()`, `linesOf()` (el eje Y cubre las dos curvas) y `diffText()`. `web/index.html` y `web/app.css` → `.seg`.
- **Ojo:** al reducir los datos se guardan los extremos de **las dos** versiones (`np.union1d` de los dos `minmax`), así ninguna pierde picos. Con el selector visible, en pantallas de unos 1500 px o menos la zona horaria pasa a una segunda línea.

## 2026-11-03 · Switch Calibrado para columnas `_cal`
- **Qué:** cuando el archivo trae columnas `X` y `X_cal` (Flight_Data), la lista de variables muestra cada una una sola vez, sin las 21 `_cal` repetidas, y aparece el switch **Calibrado** en la cabecera para usar las originales o las calibradas en todos los pasos. Cambiarlo no pierde la selección, los límites ni el encuadre de los mapas, y la elección se recuerda en el navegador (`localStorage`) para los próximos archivos. Los archivos sin `_cal` no cambian.
- **Dónde:** `gaslab_web.py` → `calibration_pairs()`, `with_calibration()` y `load()`. El servidor guarda una segunda versión del archivo con id `<id>-cal`, con los mismos nombres de variables, y `info()` la anuncia como `cal_id`. `web/app.js` → `currentId()` y el evento del switch (`#cal`); el encuadre de los mapas se guarda con `state.info.id` para no reencuadrar al cambiar. `web/app.css` → `.switch` y una regla global `[hidden]`, porque `display` en `.zone` y `.switch` anulaba el atributo `hidden`.
- **Ojo:**
  - El original de una columna `_cal` pudo cambiar de nombre al cargar (`Latitude` → `latitud`), así que el emparejamiento prueba también `canonical_name()`.
  - En `Flight_Data_6_..._cal_n0.csv` las `_cal` son idénticas a las originales (calibración n0), así que el switch no cambia nada visible con ese archivo. Se probó con una copia donde `Sensor_2_ppm_Avg_cal` = 2 × original.
  - Tests: `test_calibrated_columns_are_a_second_version_with_the_same_names` y `test_old_files_leave_memory_together_with_their_calibrated_version`.

## 2026-11-02 · Abrir Excel (.xlsx)
- **Qué:** la 2.0 y la versión 1 abren `.xlsx` y `.xlsm` además de CSV. Se usa la hoja `Datos` si existe (la que exporta GasLab) o la hoja con más datos. Un `.xls` antiguo da un mensaje pidiendo guardarlo como `.xlsx` o `.csv`. El botón ahora dice **Abrir archivo…**.
- **Dónde:** `graficar.py` → `read_excel()` y `EXCEL_SUFFIXES`; `load_csv()` decide por la extensión y lo común pasó a `_prepare()`. `requirements.txt` → `openpyxl`. `GasLab.spec` → `openpyxl` en `hiddenimports`, porque pandas lo importa de forma dinámica y PyInstaller no lo ve. `web/index.html` → textos y `accept`.
- **Selector de hoja:** si el libro tiene más de una hoja con datos, aparece **Hoja: …** junto al nombre del archivo. Empieza en la hoja de siempre, y al cambiarla la página vuelve a enviar el archivo con el encabezado `X-Sheet` y lo abre como un archivo nuevo. Si esa hoja no se puede abrir (por ejemplo, porque no tiene columna de tiempo), se avisa y sigue abierta la anterior. Código: `read_excel(sheet=)` devuelve también la hoja usada y la lista de hojas, `load_csv(sheet=)` las deja en `frame.attrs` e `info()` las manda como `sheet` y `sheets`. En la página: `showSheets()` y `fileText()`.
- **Ojo:** en los libros que exporta GasLab, la columna `Fecha y hora (zona)` está en hora local. Se vuelve a pasar a UTC como `fecha_hora_utc` y se quita `Transcurrido (s)`. Las fechas de Excel sin zona se toman como UTC, igual que en el CSV. Tests: `test_excel_*` y `test_old_xls_gives_a_clear_error`.

## 2026-11-02 · Tabletas: pellizcar en las gráficas y tocar para ver el valor
- **Qué:** en las gráficas, pellizcar con dos dedos acerca o aleja alrededor de los dedos; las demás gráficas siguen igual que con la rueda. En el mapa de calor y el terreno 3D, tocar una muestra muestra su valor. Con mouse no cambia nada.
- **Dónde:** `web/app.js` → `pinchZoom(div, axes)`, que se usa en `wire()`, en la gráfica grande del paso 2 y en la ruta (con los ejes x e y). `showValue` en `createHeatMap()` y `createTerrainMap()` atiende `mousemove` y también `click`, que es como llega un toque.
- **Ojo:**
  - El segundo dedo no llega a Plotly (`stopPropagation` en captura). Si llegara, Plotly lo contaría como doble toque y reiniciaría la vista.
  - Al soltar se reaplica el rango del pellizco, porque Plotly cierra ahí el arrastre del primer dedo y podría volver al rango anterior.
  - `preventDefault` evita que el navegador agrande toda la página.
  - Se probó con Brave headless y toques simulados por CDP: separar los dedos 5× acercó 5×, la otra gráfica siguió y la página no se agrandó.

## 2026-11-02 · GasLab 2.0 como app de Windows
- **Qué:** `GasLab.exe` ahora es la 2.0: sin consola, abre su propia ventana (Edge o Chrome con `--app`) y se cierra sola al cerrarla. Sin Edge ni Chrome abre una pestaña del navegador predeterminado. `iniciar.bat` hace lo mismo desde el código. La versión 1 sale del ejecutable (sigue en `graficar.py`).
- **Dónde:** `GasLab.spec` (entrada `gaslab_web.py`, empaqueta `web/`, sin PyQt/pyqtgraph/folium/tkinter). `gaslab_web.py` → opción `--ventana` (activa en el `.exe`), `open_window()`, `app_browser()`, `Pages`, `close_when_unused()`, `/api/ping` y `/api/bye`. `web/app.js` avisa cada 30 s y se despide con `sendBeacon` en `pagehide`. `build_windows.bat` comprueba que se empaquetó `web/`, y el workflow corre también `test_gaslab_web.py`.
- **Ojo:**
  - Se apaga 5 s después de que se despide la última página (una recarga vuelve a avisar antes).
  - Una página que deja de avisar sin despedirse cuenta como cerrada a los 10 min, porque las ventanas en segundo plano solo avisan una vez por minuto.
  - Si ninguna página abre en 2 min, también se apaga, para no dejar un proceso invisible.
  - Se probó un build de PyInstaller en Linux (página, carga de CSV, zip de QGIS, cierre automático). El `.exe` en sí no se probó todavía en Windows.
  - Test: `test_pages_close_after_last_window_but_not_on_reload`.
- **Icono:** el átomo y la G del logo GasLAB de las placas (`PCBs GasLAB/Power Corrected/Logo.pretty/GasLAB.kicad_mod`), en azul oscuro sobre un cuadro blanco redondeado. Está en `gaslab.ico` (para el `.exe`) y en `web/icono.png` (favicon). En modo app, Edge usa el favicon como icono de la ventana y de la barra de tareas. El logo completo no se usó porque a 16–32 px no se lee.

## 2026-10-30 · Mapa de calor: alcance de la nube ajustable
- **Qué:** control **Alcance** (1–4 veces el Tamaño, 2,5 por defecto, con ⓘ y su equivalente en metros) en la fila Nube: hasta dónde se pinta cada muestra. Antes estaba fijo en ~2,5 veces el Tamaño. El núcleo y el enfriamiento siguen dependiendo del Tamaño; el alcance solo estira el borde que se desvanece.
- **Dónde:** `mapa_calor.py` → `cloud(reach=)` y `export_cloud(reach=)`, `CLOUD_REACH` y `CLOUD_MAX_REACH` (reemplazan a `CLOUD_CUT`). La transparencia usa la distancia equivalente escalada por `CLOUD_REACH / reach`, así que con 2,5 se ve igual que antes. `gaslab_web.py` → parámetro `reach` de `/api/heat/image` y `/api/heat.zip`. `web/app.js` → `heatQuery()`, `showOutputs()` e `INFO.reach`.
- **Ojo:** el máximo es 4 porque a esa distancia la densidad es ~3·10⁻⁴ del centro y el promedio ponderado de valores ya se vuelve inestable. Test: `test_cloud_reach_sets_how_far_it_is_painted`.

## 2026-10-30 · Mapa de calor: enfriamiento hacia los lados
- **Qué:** control **Enfriamiento** (0–5, 1 por defecto, con ⓘ) en la fila Nube. Cada muestra conserva su valor medido en el centro y, hacia los lados, su valor baja hacia el mínimo de la escala, así que el color pasa por las divisiones hasta azul. El control define la rapidez; con 0, la nube se ve como antes (mismo color y solo se desvanece).
- **Dónde:** `mapa_calor.py` → `cloud(cool=)` y `export_cloud(cool=)`: valor = mínimo + (valor − mínimo) · densidad^cool, con la densidad limitada a 1 (donde hay muestras seguidas no se enfría). `gaslab_web.py` → `heat_image()` y `heat_zip()`, parámetro `cool` de `/api/heat/image` y `/api/heat.zip`. `web/app.js` → `heatQuery()`, `showOutputs()` e `INFO.cool`.
- **Ojo:** el `_valores.tif` exportado lleva también el valor enfriado, para que coincida con los colores. Test: `test_cloud_cools_toward_the_sides`.

## 2026-10-30 · GasLab 2.0, paso 4: terreno 3D
- **Qué:** pestaña **4 · Terreno 3D**: relieve real (AWS Terrain Tiles) con Esri satélite, y cada muestra como un cubo pequeño a la altura que midió el GPS, con el color de su división (misma señal y escala del paso 3). Escala real, sin exagerar. Al pasar el mouse se ven el valor, la altura medida, la del terreno y la altura sobre el terreno. Un aviso indica la columna de altura usada y cuántas muestras quedaban bajo el relieve; esas se dibujan sobre el suelo. Sin opción de guardar, como se pidió.
- **Dónde:** `terreno.py` (nuevo: `elevation()` con interpolación bilineal y caché en `~/.cache/gaslab_tiles/terrarium`); `gaslab_web.py` → `Dataset.terrain()` y `/api/terrain`; `heat_samples()` devuelve también la altura. `web/app.js` → `enterTerrain()`, `createTerrainMap()`, `refreshTerrain()` y `drawPoints3d()`; `fillSignal()` comparte la señal entre los pasos 3 y 4, y `renderHeatTable(data, prefix)` sirve para las dos tablas.
- **Ojo:**
  - Se usa el zoom 13 del relieve porque algunas teselas del 14 vienen vacías (−32768).
  - `fitBounds` con inclinación y relieve deja la cámara en NaN, y MapLibre reajusta la cámara cuando el relieve termina de cargar. Por eso el encuadre se calcula en plano (`cameraForBounds`) y se repite en `idle`.
  - Los cubos se recalculan en cada `zoomend` para medir unos 7 píxeles con cualquier zoom.
  - Tests: `test_terrain_*`, con teselas simuladas (sin internet).

## 2026-10-30 · Mapa de calor: nube de 0,1–2 m, paleta intensa y ayudas ⓘ
- **Qué:** el tamaño de la nube va de 0,1 a 2 m (1 m por defecto) y la opacidad es del 95 % por defecto. La paleta es más intensa (`INTENSE_RAMP`, colores puros) y el centro de cada muestra es más opaco; se usa en la nube, la tabla, la leyenda, las barras 3D y QGIS. **Divisiones iniciales** y **% mínimo por división** quedan separados, cada uno con su botón ⓘ y una ventanita de explicación (se cierra con ✕, Esc o clic fuera).
- **Nube por zona visible:** con nubes tan pequeñas, una imagen de toda la ruta se veía pixelada al acercar. Ahora `/api/heat/image` calcula solo la zona visible a la resolución de la pantalla y se pide de nuevo al mover el mapa. Incluye un margen de 3 veces el tamaño de nube, para que las muestras justo fuera de la vista tiñan el borde. `/api/heat` ya no manda imagen: solo la escala, la tabla y las muestras.
- **Dónde:** `mapa_calor.py` → `INTENSE_RAMP`, `cloud(bounds=, res=)`; `gaslab_web.py` → `Dataset.heat_image()`, `MAX_IMAGE_PX`; `web/app.js` → `refreshCloud()`, `INFO` y `closeInfo()`.
- **Ojo:** el GeoTIFF exportado sigue cubriendo toda la ruta (hasta 2500 píxeles de lado), así que en rutas largas su píxel puede ser mayor que la nube; el nombre de la capa indica el tamaño del píxel. El `.qgz` se volvió a validar con PyQGIS.

## 2026-10-30 · GasLab 2.0, paso 3: mapa de calor 2D (nubes) y 3D (barras)
- **Qué:** pestaña **3 · Mapa de calor** para una sola señal (con los valores ajustados en Límites), con toda la configuración arriba y selector 2D/3D sobre Esri satélite.
  - **Escala adaptativa:** N divisiones iguales; las que tienen menos del % mínimo de muestras se unen a su vecina. Tabla de rango, muestras y % por división, recuadro con el rango completo y leyenda en el mapa.
  - **2D:** nube gaussiana por muestra, saturada en el punto, con tamaño (m) y opacidad.
  - **3D:** una barra por muestra, de altura proporcional al valor, con altura máxima y ancho ajustables.
  - **Guardar:** imagen PNG con la leyenda, y un .zip con dos GeoTIFF (nube RGBA y valores), los puntos en GeoJSON y el proyecto .qgz.
- **Dónde:** `mapa_calor.py` → `adaptive_classes()`, `cloud()` (suavizado por FFT, sin scipy), `write_rgba_geotiff()`, `_rgba_pipe()`, `_classes_pipe()` y `export_cloud()`. `write_qgis()` acepta un pipe propio por capa y clases propias para los puntos. `gaslab_web.py` → `Dataset.heat()`, `heat_zip()`, `/api/heat` y `/api/heat.zip`. `web/app.js` → `enterHeat()`, `refreshHeat()`, `drawHeat()`, `drawBars()` y `setHeatView()`. `web/vendor/maplibre-gl.*` (4.7.1).
- **Ojo:** el `.qgz` se validó con PyQGIS: las 5 capas son válidas, en EPSG:3857, y la escala es discreta con las mismas divisiones. El PNG necesita que Esri responda con CORS, y hoy lo hace. Tests: `test_adaptive_classes_*`, `test_cloud_*` y `test_heat_and_qgis_zip`.

## 2026-10-30 · GasLab 2.0: una sola selección de variables para todas las pestañas
- **Qué:** las filas de límites del paso 2 son exactamente las variables marcadas en el paso 1, y al revés: Todas, Típicos (CO₂ · SO₂ · H₂S) o Ninguna en el paso 1 se ven en el paso 2, y + Agregar límite, ✕ o cambiar el Dato en el paso 2 se ven en el paso 1. Sin variables, el paso 2 lo indica. El máximo y el mínimo escritos se recuerdan por variable.
- **Dónde:** `web/app.js` → `setSelected()` y `state.bounds` (reemplaza a `state.limits`); `showStep(1)` vuelve a dibujar la lista y las gráficas.

## 2026-10-28 · GasLab 2.0: botón Todas y movimiento como en la versión anterior
- **Qué:** botón **Todas** en la lista de variables. Las gráficas se desplazan arrastrando y hacen zoom con la rueda (antes, arrastrar dibujaba un recuadro de zoom). Mientras se mueve una gráfica, las demás la siguen en vivo, y el eje Y se ajusta al tramo visible. También aplica a la gráfica del paso 2.
- **Dónde:** `web/app.js` → `dragmode: 'pan'` en `baseLayout()`, `wire()`/`follow()` (evento `plotly_relayouting`), `yRange()`/`yAxis()` y `fetchWindow()`. Se pide al servidor el tramo visible más un ancho a cada lado, para poder desplazar sin huecos mientras llegan los datos con más detalle.

## 2026-10-28 · GasLab 2.0, paso 2: límites (saturación)
- **Qué:** pestañas en la cabecera (**1 · Datos**, **2 · Límites**). En el paso 2, filas `Dato | Máximo | Mínimo`: las muestras fuera del rango quedan en el límite, sin descartarse. Hay una fila por cada variable del paso 1 y un botón **+ Agregar límite**. Un campo vacío significa sin límite. Una gráfica grande con botones por variable, líneas de los límites, conteo de muestras ajustadas, **Comparar con original** y **Pantalla completa** (Esc sale).
- **Dónde:** `gaslab_web.py` → `Dataset.values()`, `parse_limits()`, `series(limits=, original=)` (parámetros `limits` en JSON y `original=1` de `/api/series`); `web/app.js` → `showStep()`, `syncLimitRows()`, `renderLimits()`, `renderPick()`, `refreshBig()`.
- **Ojo:** la reducción mín/máx se calcula sobre los datos originales y luego se ajusta, lo que da el mismo resultado porque recortar no cambia cuál es el mínimo o el máximo de cada grupo. Los límites se pierden al abrir otro CSV. Test: `test_limits_saturate_without_dropping_samples`.

## 2026-10-28 · GasLab 2.0: app en el navegador (rama `develop-2.0`)
- **Qué:** `gaslab_web.py` abre la app en el navegador: elegir el CSV con el administrador de archivos, lista de variables (CO₂, SO₂ y H₂S marcadas por defecto), ruta GPS sin fondo + altura contra la hora a la izquierda, variables contra la hora del día a la derecha, zona horaria (UTC por defecto). Zoom sincronizado, tramo resaltado en la ruta y cursor compartido.
- **Rendimiento:** reducción mín/máx por píxel en el servidor (`minmax()`) y nueva petición del tramo visible al hacer zoom (`/api/series?start=&end=`); la ruta se limita a 20.000 puntos (`/api/route`).
- **Dónde:** `gaslab_web.py` (servidor y API, reutiliza `load_csv`/`parse_time` de `graficar.py`); `web/index.html`, `web/app.css`, `web/app.js`. `iniciar.sh` y `make run` abren ahora la 2.0; `graficar.py` sigue con la v1.
- **Ojo:** las horas se pasan a Plotly como texto "de reloj" (`wall()` en `app.js`): con números, Plotly las corre según la zona horaria del navegador. Tests: `test_gaslab_web.py`. El ejecutable de Windows aún no incluye la 2.0.

## 2026-10-28 · Diagnóstico del empaquetado de Windows
- **Qué:** `build_windows.bat` valida el entorno `.venv` existente y lo recrea si no funciona en esta PC; detecta el Python de Microsoft Store antes de crear el entorno; al terminar comprueba que se haya incluido `python3XX.dll` y mantiene abierta la ventana para mostrar el resultado.
- **Errores guiados:** si falta Python, se detecta Microsoft Store o falta el DLL tras compilar, el script muestra el paso recomendado para corregirlo.
- **Documentación:** `README.md` incluye estos casos y recuerda copiar la carpeta `dist\GasLab\` completa.

## 2026-10-26 · Mapa de calor: modo Puntos y celdas desde 0,5 m
- **Qué:** selector **Puntos / Celdas** en la fila Mapa de calor. **Puntos** (por defecto) dibuja cada muestra en su coordenada con el color de su valor (los altos encima, tamaño en px, valor bajo el cursor). Celdas de **0,5 y 1 m** añadidas. El `.qgz` exportado trae ahora una **capa de puntos** (GeoJSON, renderer graduado de 20 clases, ordenado por valor) además de las celdas; queda encendida la del modo elegido. CLI: `--celdas`, `--tam-punto`.
- **Dónde:** `mapa_calor.py` → `_points_layer()`, `write_qgis(points=…)`, `export(mode=…, point_mm=…)`; `visor_qt.py` → `draw_heat_points()`, `cover_hover()`, `drawbox`/`sizebox`.
- **Ojo:** la XML de la capa vectorial se validó con PyQGIS (capa válida, 20 clases, orden por valor). Celdas más pequeñas que el error del GPS (1–3 m) no añaden detalle real.

## 2026-10-26 · Mapa de calor de una variable, georreferenciado (GeoTIFF + QGIS)
- **Qué:** la casilla **Cobertura** pasó a una fila **Mapa de calor** con **Valor** (Muestras = cobertura de antes, o cualquier variable numérica), **Promedio / Máximo / Percentil 95** por celda, celda de 2 a 250 m, **suavizado** gaussiano recortado a ~2 sigma de la ruta, **desfase** del sensor (s) y **rango válido**. **Exportar GeoTIFF/QGIS…** escribe `.tif` (EPSG:3857), `_puntos.geojson` y `.qgz` (OSM + Esri), con opción de agregar otro GeoTIFF debajo (p. ej. el mosaico térmico de TermoReferencia).
- **Cualquier CSV:** si no hay columnas de GPS con nombre conocido, el visor pregunta cuáles son latitud y longitud; en la CLI, `--lat`/`--lon`. Probado con `mediciones_16sep.csv`, `mediciones_16sep_gps_dron.csv` (`--gps-dron`) y `Flight_Data_6_Sensor_2_ppm_Avg_cal_n0.csv` (Campbell, `;` y coma decimal).
- **Dónde:** `mapa_calor.py` (nuevo: `grid()`, `lag_positions()`, `write_geotiff()`, `write_qgis()`, `export()`); `visor_qt.py` → `_build_heat_bar()`, `heat_inputs()`, `update_coverage()`, `cover_hover()`, `export_heat()`, `ask_gps_columns()`; `graficar.py` → `make_heatmap()` y opciones `--calor…`.
- **Sin dependencias pesadas:** GeoTIFF con Pillow (sin GDAL) y proyecto QGIS escribiendo el XML (sin PyQGIS ni pyproj; el CRS va con proj4 + authid). `Pillow` agregado a `requirements.txt`; `mapa_calor` a `GasLab.spec`.
- **Ojo:** en Flight_Data el CO₂ trae ceros y ~10 ppm al arrancar: usar mínimo válido ~300. Coordenadas en grados decimales (no NMEA ddmm.mmmm). Tests: `HeatMapTests`; el `.qgz` se validó abriéndolo con PyQGIS (capas válidas, EPSG:3857 y el mosaico térmico en EPSG:32633 alineado).

## 2026-10-19 · Exportar Excel del tramo; el tramo elegido encierra las gráficas
- **Qué:** botón **Exportar Excel…** en el visor rápido. Exporta las **variables marcadas** y las **muestras visibles**: el tramo (o día/horas) elegido, o solo la parte ampliada dentro de él. Antes de guardar muestra un resumen (muestras, inicio → fin, variables). El libro trae las hojas **Resumen** (mín/prom/máx con fórmulas), **Datos**, **Gráficas** (un gráfico nativo de Excel por variable, en 3 columnas) y **Ruta** (longitud contra latitud, sin fondo de mapa).
- **Tramo cerrado:** con un tramo, día u horas elegidos, las curvas solo contienen esas muestras y el zoom/desplazamiento no puede salir del tramo; **Restablecer zoom** vuelve al tramo completo, y las estadísticas y el cursor tampoco salen de él. **Todo** quita el límite.
- **Dónde:** `graficar.py` → `make_excel()`, `default_variables()`; `visor_qt.py` → `lock_plots()`, `span()`, `visible_idx()`, `reset_zoom()`, `export_excel()`.
- **Dependencia nueva:** `xlsxwriter` (en `requirements.txt` y `GasLab.spec`). Test: `test_excel_only_contains_the_given_rows`.

## 2026-10-15 · Ventana de tiempo que limita el mapa; arreglo del fondo del mapa
- **Qué:** nueva fila de la barra con **Inactividad > N s** + **Tramo** (tramos continuos), **Todo**, y en la fila siguiente **Día + de … a …** (hora de inicio y de fin del día elegido; reemplazó al rango manual con fecha completa y al selector de una sola hora). Elegir una ventana amplía las gráficas y limita el mapa (ruta, puntos, cobertura, encuadre) a esas muestras.
- **Dónde:** `visor_qt.py` → `compute_intervals()`, `on_interval()`, `fill_hours()`, `on_hour_from()`, `on_hour_to()`, `apply_hours()`, `apply_window()`, `clear_window()`, y `build_map()` (usa `self.window`).
- **Bug corregido:** el mapa no mostraba fondo (ni OSM ni satélite) porque al agregar el nivel máximo por proveedor (`PROVIDERS[...][3]`) `fetch_tile` seguía desempaquetando el proveedor en 3 valores y fallaba en silencio. Ahora usa `provider[:2]`.
- **Ojo:** los tramos y el rango manual usan la hora local de la zona elegida; no están en la vista web ni en la ventana de inicio; no hay test automático (probado a mano con `mediciones_16sep.csv`).

## 2026-10-14 · Día y hora, y tamaño de letra (visor rápido)
- **Qué:** los selectores **Día** y **Hora** (segunda fila de la barra) amplían las gráficas a un día u hora con muestras; **Letra** (8–28 pt, se guarda en QSettings) agranda toda la interfaz y las gráficas.
- **Dónde:** `visor_qt.py` → `Viewer.compute_days()`, `fill_hours()`, `on_day()`, `on_hour()` (sección `# ---------- day / hour ----------`) y `set_fontsize()` / `apply_font()`.
- Había reemplazado el selector de intervalos por huecos; volvió el 2026-10-15 junto con el rango manual (ver arriba).
- **Ojo:** día y hora salen de la columna de tiempo en hora local de la zona elegida; no están en la vista web ni en la ventana de inicio; no hay test automático.

## 2026-10-13 · CSV con bytes nulos
- `graficar.load_csv` quita los `\x00` (escritura interrumpida en SD/USB) y descarta las filas truncadas; un archivo de 0 bytes da un error claro.

## Antes
- Capa **Cobertura** (mapa de calor), fondos de mapa con nivel máximo por proveedor, vista web servida por `http://127.0.0.1` (OpenStreetMap bloquea tiles sin Referer), y empaquetado con PyInstaller/Makefile.
