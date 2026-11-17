# Decisión de diseño (Puerta 0 del frontend)

- **Fecha:** 17 nov 2026
- **Eligió:** Andrés Ospina Silva
- **Opción elegida:** **B · Cordillera**
- **Lienzo en Claude Design:** https://claude.ai/artifact/4TRUmruCqwyUF6pBoWkBbu
  (tableros "B · Cordillera — Revisión docente" y "B · Cordillera — Inicio,
  informe, mapa y equipo"; las opciones A y C quedan en el mismo lienzo como
  referencia)
- **Brief:** `docs/diseno/brief.md`

## Opciones que se compararon

| Opción | Idea | Por qué no se eligió |
| --- | --- | --- |
| A · Cuaderno de laboratorio | Papel cuadriculado, la IA a lápiz y el docente en esfero rojo, sello de aprobado | La letra a mano (Caveat) se lee mal en celular y en bloques largos |
| **B · Cordillera** | El dominio como altura, de Manizales al Nevado del Ruiz; verde de la U y curvas de nivel | **Elegida** |
| C · Sala de control | Consola oscura 24×7, bandeja como cola de alertas, traza como registro de eventos | Tema oscuro: el informe en PDF necesitaría una versión aparte; se siente menos de la U |

## Por qué Cordillera

1. **Es de aquí.** Las alturas reales (Manizales 2 150 m, Nevado del Ruiz
   5 321 m) y el verde de la Universidad de Manizales hacen que no parezca una
   plantilla.
2. **Explica la nota sin palabras.** Los niveles de la rúbrica son escalones que
   suben; se ve de un vistazo dónde puso la IA el nivel y dónde lo dejó el
   docente.
3. **Fondo claro.** El contraste AA (RNF-11) y el PDF impreso del informe
   (RF-16) salen sin una segunda versión.
4. **Se cuenta fácil en la sustentación:** "este estudiante está a 4 100 m en
   agentes y a 2 150 m en manejo de errores".

## Indicación de Andrés para construir

> "Cordillera, pero recuerda hacerlo innovador, llamativo, optimizado, con buenas
> gráficas si es necesario."

Lo que eso significa en la construcción (no son opcionales):

### Llamativo e innovador

- **Encabezados con relieve.** Las curvas de nivel del encabezado no son una
  imagen: es un SVG con capas de verde que se desplazan un poco al hacer scroll
  (parallax suave). Se desactiva con `prefers-reduced-motion`.
- **Selector de nivel como escalones.** En la revisión docente el nivel es un
  grupo de 4 escalones de altura creciente. El de la IA va con borde punteado y
  la etiqueta "propuso la IA"; el del docente va relleno. Al cambiarlo, el
  escalón sube o baja con una transición corta y la nota se recalcula a la vista.
- **Nota como altímetro.** La nota final grande (Archivo 800, ancho 112 %) con un
  pequeño perfil que marca la preliminar y la final. Al recalcular, el número
  cuenta hasta el nuevo valor (máx. 400 ms).
- **Mapa mental por altura (Cytoscape.js).** Los temas se ubican en bandas
  horizontales según su nivel de dominio: Por fortalecer 2 150 m, Básico
  3 000 m, Medio 4 100 m, Alto 5 321 m; detrás, la silueta del nevado. Al tocar
  un tema se ilumina su ruta hasta los laboratorios donde se aplicó.
- **Informe como perfil de ascenso.** La evolución entre laboratorios es un
  perfil de montaña (área + línea) con la nota en cada cima. Se compara con el
  promedio de la cohorte como una línea punteada de "altitud media".
- **Inicio con el cerro.** Pantalla de inicio verde con curvas de nivel grandes y
  el formulario de ingreso sobre fondo blanco.
- Siguen prohibidos: degradados morados, chispitas, tarjetas con sombra
  genérica, "Powered by AI", fotos de stock.

### Buenas gráficas

- Una sola paleta para todas las gráficas (ver abajo); la de niveles siempre va
  con icono y texto, nunca solo color.
- Gráficas en SVG propio o con una librería liviana; ejes con texto de 12 px o
  más; cada gráfica con `role="img"` y `aria-label` que diga los datos.
- Gráficas del informe: perfil de ascenso (evolución), barras horizontales de
  dominio por tema con su altura, y tabla de notas. Todas deben imprimirse bien en
  el PDF (WeasyPrint).
- Gráfica de costos para el docente: tokens y USD por evaluación (RNF-14),
  como barras pequeñas en la bandeja y una serie en el panel de costos.

### Optimizado

- Cytoscape.js y las gráficas se cargan solo en las pantallas que las usan
  (`import()` dinámico); el inicio no las descarga.
- Fuentes de Google con `display=swap` y solo los pesos usados (Archivo 700/800
  y Source Sans 3 400/600/700).
- Meta de rendimiento en celular: LCP menor a 2,5 s y JavaScript inicial menor a
  200 KB comprimido. Se mide con Lighthouse antes del PR de cada pantalla.
- Animaciones solo con `transform` y `opacity`.

## Paleta

| Uso | Color | Nota |
| --- | --- | --- |
| Verde principal (botones, encabezado, nivel final) | `#0B5D3B` | Verde de la Universidad de Manizales, confirmado por Andrés el 17 nov 2026 |
| **Acento glaciar** (lo llamativo) | `#00B4D8` en rellenos, gráficas y sobre el verde · `#00739A` cuando es texto sobre fondo claro | El hielo de la cumbre del Nevado. Ver reglas abajo |
| Texto | `#15241C` | |
| Texto secundario | `#44564B` | AA sobre blanco y sobre `#F3F5F1` |
| Fondo de la app | `#F3F5F1` | Bruma de páramo |
| Superficies | `#FFFFFF` con borde `#C7D2CB` | Sin sombras |
| Verde claro (áreas, escalones sin elegir) | `#DCEBE3` / `#E7EEEA` | |
| Bordes de campos | `#8DA197` | |
| Cita encontrada | `#0B5D3B` + icono ✓ + "Encontrada" | |
| Cita no encontrada | `#B42318` sobre `#FDF0EF`, borde `#E5A29C` + icono ✗ + "No encontrada" | |
| Alerta de inyección | Texto `#8A4B00` sobre `#FFF4E0`, borde `#E0B36A` | Seria, no alarmista |

Niveles de dominio (mapa e informe): Alto ▲ `#0B5D3B` relleno · Medio ◆
`#DCEBE3` · Básico ● borde `#0B5D3B` · Por fortalecer ○ borde `#B42318`.

### Acento glaciar

Andrés confirmó el verde de la U y pidió un color más llamativo si lo había. El
verde se queda como color principal y se suma **un solo acento: azul glaciar**,
el hielo de la cumbre. Verde y azul glaciar juntos son la montaña con nieve, así
que el acento tiene sentido en la metáfora y no es un color suelto.

Dónde va (y solo ahí, para que siga llamando la atención):

- La **cumbre**: el casquete de nieve en las curvas de nivel del encabezado y del
  inicio, y la banda "Alto · 5 321 m" del mapa mental.
- La **ruta resaltada** del mapa mental cuando se toca un tema.
- El **escalón elegido** en la revisión docente: un borde o brillo glaciar al
  cambiar de nivel, mientras la nota se recalcula.
- La **línea de la nota final** en el altímetro y la serie del estudiante en el
  perfil de ascenso del informe (la cohorte va en gris punteado).
- El **anillo de foco** del teclado (`outline` de 3 px `#00739A`).

Dónde **no** va: estados (encontrada, no encontrada, alerta), botones
principales (siguen verdes) ni fondos grandes. Regla práctica: el glaciar no
pasa del 10 % de una pantalla.

Contraste comprobado: `#00739A` sobre blanco 5,4:1 (texto AA); `#00B4D8` sobre
`#0B5D3B` 3,2:1 (solo para formas, íconos y texto de 24 px o más).

## Tipografía

- **Títulos y números grandes:** Archivo, pesos 700 y 800, ancho 112-118 %
  (eje `wdth`), mayúsculas en el nombre de la plataforma.
- **Texto:** Source Sans 3, pesos 400, 600 y 700; tamaño base 16 px.
- **Código y citas de código:** monoespaciada del sistema (`ui-monospace,
  Consolas`), 13 px.

## Handoff

Hecho el 17 nov 2026. Los dos tableros de Cordillera quedaron en
`docs/diseno/cordillera/` (ver su `README.md`). No hizo falta *Export → Handoff
to Claude Code* en Claude Design: el lienzo lo armó Claude Code y ya tenía los
archivos fuente, así que se guardaron directo en el repo. Con eso se construye
con la skill `frontend-design`.

## Pendientes

1. **Al final del proyecto:** la página del equipo (pantalla 5). El equipo son
   **3 personas**, no 2 como dicen los bocetos: Andrés Ospina Silva, Santiago
   Arias Aguirre y Jerónimo Aristizabal. Faltan la foto de cada uno (retrato real,
   no de stock) y su rol. Mientras
   tanto la pantalla se construye con espacios marcados "[…]".
