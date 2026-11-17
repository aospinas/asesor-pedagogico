# Decisiones técnicas

Una entrada por decisión: qué se decidió, por qué y qué se descartó.

## D-01 · Render + Supabase para desplegar gratis (13-nov-2026)

- **Decisión:** la app corre en Render (servicio web gratis con Docker) y los datos y archivos en Supabase (plan gratis).
- **Por qué:** cero costo, despliegue desde GitHub, PostgreSQL que el equipo ya conoce.
- **Descartado:** Hugging Face Spaces, porque crear un Space con Docker ya pide plan de pago.
- **Costo de la decisión:** Render se duerme a los 15 minutos sin visitas y tarda cerca de un minuto en despertar; Supabase se pausa tras una semana sin uso.

## D-02 · Python 3.15 (13-nov-2026)

- **Decisión:** usar Python 3.15, que es la versión que Andrés ya tiene instalada.
- **Prueba hecha:** todas las dependencias de `requirements-dev.txt` instalan con paquetes binarios para Python 3.15 en Windows y en Linux, y las pruebas pasan en 3.15 (26 ese día; 31 después de sumar las del flujo de Git).
- **Excepción:** PyYAML aún no tiene paquete para 3.15. Por eso `uvicorn` va sin `[standard]` y `bandit` solo se instala en 3.12; en 3.15 se corre con `uvx --python 3.12 bandit -r app -q`.
- **Plan B:** Python 3.12. Se probó igual: las dependencias instalan en Windows y Linux, las pruebas pasan y bandit no encuentra problemas. Para cambiar: `PYTHON_VERSION=3.12` en el `Dockerfile` y `py -3.12` en el PC. El CI corre en las dos versiones.

## D-03 · Un solo cliente de IA para tres proveedores (13-nov-2026)

- **Decisión:** SDK oficial de OpenAI cambiando la dirección base para OpenAI, Ollama y OpenRouter.
- **Por qué:** los tres aceptan el mismo formato de API; cambiar de proveedor es cambiar variables de entorno (RF-19).

## D-04 · La nota se calcula solo en el backend (13-nov-2026)

- **Decisión:** `app/evaluador/nota.py` es el único lugar que calcula notas; la salida de la IA no tiene campo de nota y `extra="forbid"` rechaza cualquier campo extra.
- **Por qué:** lo exige el enunciado (condición 2) y protege contra inyección de prompt.

## D-05 · Sandbox por proceso en la nube, Docker en local (13-nov-2026)

- **Decisión:** en Render el sandbox usa procesos con límites (`SANDBOX_MODE=proceso`); en local usa contenedores sin red (`SANDBOX_MODE=docker`).
- **Por qué:** Render gratis no permite Docker dentro del contenedor.
- **Nota de licencia:** Docker Desktop es gratis para uso personal y educativo, pero pide licencia paga en empresas grandes. Si el PC es de la empresa, revisar eso o usar Docker Engine dentro de WSL2, que es gratis.

## D-06 · El diseño se elige en Claude Design antes de programar (13-nov-2026)

- **Decisión:** el orquestador propone 3 direcciones en Claude Design, Andrés escoge una y se pasa a código con el handoff.
- **Por qué:** que la interfaz sea propia del equipo y no una plantilla genérica.

## D-07 · Docker en el PC para probar; CI y Render para confirmar y publicar (15-nov-2026)

- **Decisión:** Andrés tiene Docker en el PC. Claude Code prueba la imagen ahí con `/probar-imagen` antes de cada PR que la toque; el CI la vuelve a construir y probar en cada push, y Render la construye al desplegar con `render.yaml`.
- **Además:** PostgreSQL local con `docker compose up -d db` para desarrollo, y sandbox completo (`SANDBOX_MODE=docker`, contenedores sin red) en el PC.
- **Por qué:** los fallos de la imagen salen en minutos en el PC y no después del push; y el sandbox con contenedores es el que se muestra en la sustentación.
- **Lo que hace el humano:** solo la primera conexión de Render con el repo (New → Blueprint) y llenar las variables secretas.

## D-08 · Mythos 5.2 para lo crítico, Opus 5.5 para lo demás (15-nov-2026)

- **Decisión:** el proyecto corre por defecto en Claude Opus 5.5. Los módulos donde un error cuesta caro (contrato de esquemas, evaluador, sandbox, autenticación, pasada OWASP final) y los subagentes `revisor-seguridad` y `depurador` usan Claude Mythos 5.2. Detalle en `docs/modelos.md`.
- **Por qué:** Mythos 5.2 es el modelo más capaz al que tiene acceso el equipo y el más fuerte en seguridad, pero cuesta el doble por token que Opus 5.5; se usa donde más rinde.
- **Plan B:** Claude Fable 5.2, que es el mismo modelo con más protecciones, si Mythos no está disponible en Claude Code.

## D-09 · Flujo de Git con PR: Claude sube, Andrés hace el merge (15-nov-2026)

- **Decisión:** Andrés crea el repo. Claude Code trabaja en ramas `feat/<modulo>`, las sube y abre un PR. Andrés revisa el PR en GitHub, espera el CI en verde, hace el merge y luego `git pull`. Es el mismo flujo del proyecto SECOP TIC.
- **Por qué:** el merge del PR es la puerta humana final antes de producción, y queda registrada en GitHub como evidencia de la supervisión.
- **Cómo se hace cumplir:** el guardrail bloquea push a `main`, `gh pr merge` y merges locales de ramas.
- **Quién desarrolla:** todo el desarrollo lo lleva Andrés con Claude Code; Santiago Arias Aguirre figura como integrante del equipo.

## D-10 · La documentación de la API queda cerrada para todos (15-nov-2026)

- **Decisión:** `/docs` y `/redoc` de FastAPI quedan apagados para todos los roles. La lista de rutas se lee en `docs/api.md`.
- **Por qué:** el SRS (A02) decía "`/docs` solo para admin", pero cerrarla del todo es más simple y más seguro, y así ya estaban `app/main.py` y la lista OWASP.

## D-11 · Un solo nombre por estado de evaluación (15-nov-2026)

- **Decisión:** los estados son cinco y viven en `EstadoEvaluacion` de `app/esquemas.py`: en proceso, en revisión, revisión manual, aprobada y publicada.
- **Por qué:** el SRS usaba "Pendiente de revisión" y "En revisión" para lo mismo, y "Requiere revisión manual" y "Revisión manual" para lo mismo. Queda el nombre del diagrama de la sección 6.

## D-12 · Contrato de datos y tabla de rutas con rol (15-nov-2026)

- **Decisión:** `app/api/rutas.py` es la fuente única de qué rol usa cada ruta; `docs/api.md` es la misma tabla para leer y una prueba falla si no coinciden.
- **Usuarios:** los crea el administrador (`POST /api/usuarios`); no hay registro público. RF-01 dice "registro e inicio de sesión" y aquí "registro" se entiende como el alta que hace el administrador (RF-02).
- **Niveles ordenados (RF-05):** los valores de los niveles de un criterio deben ir de menor a mayor o de mayor a menor, sin repetirse.
- **Notas:** ningún modelo de entrada (IA, docente o estudiante) tiene campo de nota; solo aparecen en modelos que arma el backend.

## D-13 · Arreglos de la revisión del contrato (15-nov-2026)

Salieron de los dos revisores en la Puerta 2 del módulo contrato.

- **Dirección de la IA cerrada:** OpenAI y OpenRouter solo aceptan su dirección oficial; Ollama solo los equipos de la variable `OLLAMA_HOSTS_PERMITIDOS`. Así nadie puede hacer que el backend mande la llave a otro servidor.
- **Contraseñas:** máximo 72 bytes (límite de bcrypt), no se les recortan los espacios, y cada usuario cambia la suya en `PUT /api/yo/contrasena` para que el administrador no la conozca.
- **Correo:** se guarda en minúsculas.
- **Topes de tamaño:** textos y listas de la IA, de la rúbrica y del sandbox tienen máximo; los números no aceptan infinito.
- **Documentación de la API:** además de `/docs` y `/redoc`, se cierra `/openapi.json`.
- **Rutas:** `GET /api/estudiantes` para el docente y `/api/mis-entregas` en vez de `/api/entregas/mias`.

**Queda para el módulo que lo toca:**

| Módulo | Pendiente |
| --- | --- |
| auth | Marcar en la tabla de rutas las que son "solo si está publicada"; no guardar secretos en el detalle de la auditoría y tipar la IP; auditar cambios de rol |
| entregas | Modelos `LaboratorioEditar` y `Rubrica`; que el estudiante llegue desde su entrega a la evaluación publicada |
| revision | Que el docente pueda editar la justificación; publicar solo citas encontradas; decidir si el administrador ve la traza |
| proyecto | Modelo `IntegranteEquipo` sin correo para la página pública |

## D-14 · Cómo funciona el login (16-nov-2026)

Decisiones del módulo auth, aprobadas en su Puerta 1.

- **Sesión:** JWT en una cookie `httpOnly`, `SameSite=Lax`, de 8 horas (`SESION_MINUTOS`); en producción solo viaja por HTTPS. El rol se lee de la base en cada petición, nunca del navegador.
- **Primer administrador:** se crea con `python -m app.crear_admin`, que pide los datos por teclado. No hay claves en el repo.
- **Clave temporal:** la contraseña que pone el administrador es temporal; el usuario debe cambiarla al entrar antes de usar otra ruta. Al cambiarla se cierran sus otras sesiones.
- **Bloqueo:** 5 intentos fallidos bloquean la cuenta 5 minutos (dos columnas en `usuarios`), y hay un tope de 30 intentos de inicio de sesión por minuto por IP. **Limitación:** detrás del proxy de Render todos los usuarios pueden verse con la misma IP; se revisa en el primer despliegue.
- **Control de acceso:** cada ruta se registra con `app.api.seguridad.ruta`, que toma los roles de `app/api/rutas.py`. Una ruta que no esté en la tabla no deja arrancar la app.
- **Pruebas:** corren en SQLite en memoria (el CI no tiene PostgreSQL). Antes de cada PR que toque la base se corren también contra PostgreSQL con `PRUEBAS_DATABASE_URL`.
- **Migraciones:** Alembic en `migraciones/`. El contenedor corre `alembic upgrade head` al arrancar si existe `DATABASE_URL`.
- **Base local:** la dirección usa `127.0.0.1` y no `localhost`; en Windows `localhost` tardaba 30 segundos por conexión.
- **Cambia el SRS:** la tabla `usuarios` tiene cuatro columnas más que la sección 8 (`debe_cambiar_contrasena`, `intentos_fallidos`, `bloqueado_hasta`, `version_sesion`).

## D-15 · Arreglos de la revisión del login (16-nov-2026)

Salieron de los dos revisores en la Puerta 2 del módulo auth. Corrigen o precisan D-14.

- **Bloqueo por correo e IP (reemplaza las dos columnas de D-14):** los intentos se cuentan en la tabla `intentos_sesion`, por correo e IP, exista o no el correo. El intento se anota antes de revisar la clave y con la fila bloqueada en la base. Por qué: el revisor probó que con peticiones simultáneas se saltaba el tope; además así nadie le bloquea la cuenta a otro desde otra IP y la respuesta no revela qué correos existen.
- **Cerrar sesión invalida el token:** sube `version_sesion`, así que un token copiado deja de servir. Costo aceptado: se cierran también las sesiones de ese usuario en otros equipos. Desactivar a un usuario hace lo mismo.
- **Cambiar la contraseña tiene tope:** adivinar la clave actual usa el mismo contador; al quinto fallo se cierra la sesión.
- **Contraseña olvidada o cuenta bloqueada:** el administrador pone una clave temporal en `POST /api/usuarios/{usuario_id}/clave-temporal`. El usuario debe cambiarla al entrar; queda en la auditoría sin la clave. No hay recuperación por correo.
- **Siempre queda un administrador activo:** no se puede quitar el rol ni desactivar al último.
- **`ENTORNO` es una lista cerrada:** un valor mal escrito no deja arrancar. En producción `ORIGENES_PERMITIDOS` debe ser https y sin `*`.
- **Peticiones desde otro sitio:** las que cambian datos solo se aceptan si su origen está en `ORIGENES_PERMITIDOS`. En Render esa variable debe llevar la dirección https de la app.
- **Cookie:** en producción se llama `__Host-sesion`.
- **Auditoría:** también se registran los intentos con correos que no existen, los bloqueos y los accesos denegados por rol. El filtro de secretos usa nombres exactos.
- **Mensajes:** los errores de validación, el 404 y el 405 salen en español (`app/mensajes.py`).
- **Cambia el SRS:** hay una tabla más que en la sección 8 (`intentos_sesion`); `usuarios` suma `debe_cambiar_contrasena` y `version_sesion`; la columna `detalle_json` de `auditoria` se llama `detalle`.

**Queda para el primer despliegue en Render (`/desplegar`):**

| Pendiente | Por qué espera |
| --- | --- |
| Arrancar uvicorn con `--proxy-headers` limitado al proxy de Render | Sin eso, la IP del límite, del bloqueo y de la auditoría es la del proxy y todos comparten un solo cupo. Hay que ver en Render qué IP llega |
| Qué pasa si Supabase está dormido al arrancar | `alembic upgrade head` fallaría y el contenedor no sube. Opciones: reintentar unas veces o migrar como paso aparte |
| Cuenta de base de datos sin permiso de crear tablas para la app | Hoy la app usa la misma cuenta de las migraciones |

## D-16 · Rúbricas, cohortes y laboratorios (16-nov-2026)

- **Cohortes y laboratorios se construyen en el módulo rúbricas** y no en el de entregas: la rúbrica cuelga de un laboratorio y sin ellos no se puede probar. El módulo entregas queda con entregas y portafolio.
- **Cliente de IA mínimo antes del evaluador:** `app/ia/cliente.py` solo tiene `pedir_json` (pide un JSON y lo valida con el esquema). Lo necesita RF-04. El módulo evaluador (Mythos) lo amplía.
- **Sin `version_vigente_id`:** la versión vigente es la de número más alto. Por qué: con esa columna las tablas `rubricas` y `rubrica_versiones` se apuntan una a la otra y SQLite no lo soporta en las migraciones. Como cada cambio crea una versión nueva, la última siempre es la vigente. **Cambia el SRS (sección 8).**
- **`rubrica_versiones` guarda más que el SRS:** `origen` (json, pdf, docx, texto, editor), `archivo_sha256`, `prompt_version`, `modelo` y tokens. Sirve para la traza y para los costos.
- **Carga y corrección:** `POST .../rubrica` recibe un archivo (PDF, Word, texto o JSON; el tipo se decide por el contenido). El JSON entra sin IA. `PUT .../rubrica` recibe la estructura corregida del editor. Las dos crean una versión nueva.
- **Una rúbrica con errores se guarda** (para corregirla en el editor) pero `version_evaluable` no deja evaluar con ella (RF-05).
- **El estudiante solo ve la última versión válida**, nunca un borrador con errores.
- **Word sin lector de XML:** el texto del .docx se saca con expresiones regulares, así no hay entidades XML que atacar. Topes: 5 MB por archivo, 30 páginas, 10 MB descomprimido y 40.000 caracteres hacia la IA.
- **Cohortes:** no puede haber dos con el mismo nombre y periodo.

**Arreglos de la revisión (Puerta 2):**

- **Lo que convierte la IA lo confirma el docente:** una versión que sale de PDF, Word o texto queda `por_confirmar`. No sirve para evaluar ni la ve el estudiante hasta que el docente la revisa y la guarda desde el editor (`PUT`), que crea una versión nueva confirmada. No hay una ruta "confirmar": así ninguna versión se modifica. La IA propone, el docente aprueba.
- **El PDF se lee en un proceso aparte** con 15 s de tiempo y, en Linux, 400 MB de memoria. Un PDF bomba mata ese proceso y no la app. Probado con un PDF de 299 KB que se expande a 90 MB: en Linux se rechaza en 4 s.
- **Word:** la expresión que lee el texto ya no retrocede (antes un archivo de 216 bytes podía trabar el servidor) y el tope descomprimido baja a 2 MB. Un zip cifrado o dañado da un aviso y no un error 500.
- **Tope de 6 MB por petición** en el middleware, antes de leerla. FastAPI guarda los archivos en disco antes de revisar la sesión: sin esto, cualquiera podía llenar el disco. Si las entregas necesitan más, se sube con su propia decisión.
- **Máximo 10 conversiones con IA por docente por hora** (se cuentan en la auditoría como `rubrica_ia_pedida`, también las fallidas). Sin reintento automático.
- **La conexión a la base se suelta** antes de esperar a la IA.
- **Una rúbrica de más de 40.000 caracteres se rechaza** en vez de recortarse sin avisar.
- **Rúbricas incompletas:** el esquema acepta peso 0 y un solo nivel para que lo que convierte la IA se pueda guardar y corregir; `validar_rubrica` los marca como error. El prompt pide copiar los pesos tal cual, sin convertir puntos a porcentaje, para que un error de suma no se esconda. Se corrigió `interpretar_rubrica_v1` en vez de crear `_v2` porque nunca se había usado.
- **El estudiante recibe solo** número, estructura y fecha de la rúbrica.
- **Las versiones no se pueden editar ni borrar** tampoco desde el código: un evento de SQLAlchemy lo impide.
- **A Ollama nunca se le manda la llave.** Una respuesta cortada o un JSON muy anidado de la IA se rechazan.

## D-17 · Entregas, portafolio y almacén de archivos (16-nov-2026)

- **Almacén con dos opciones (`ALMACEN`):** `local` (una carpeta, para el PC y las pruebas) y `supabase` (Supabase Storage, bucket privado, para Render; el disco de Render se borra en cada despliegue). En producción la carpeta local no se acepta: subir una entrega responde 503 en vez de perder archivos. La app sigue arriba aunque Supabase no esté configurado.
- **La llave de Supabase solo va a `https://<ref>.supabase.co`**; cualquier otra dirección (o "pendiente") se rechaza antes de mandar nada.
- **Descarga solo con enlace firmado de 5 minutos (RNF-07).** En Supabase lo firma Supabase. En local lo firma la app (JWT con audiencia `archivo`, así nunca sirve como sesión) y se abre en la ruta pública nueva `GET /api/archivos/{token}`. El archivo se baja como adjunto, nunca se abre dentro de la app.
- **La ruta de cada archivo la arma el backend** (`entregas/<id>/<id>`); el nombre que manda el estudiante solo se muestra, limpio de rutas y caracteres raros.
- **Qué se extrae al subir (RF-09):** texto del PDF por página, árbol y texto de los archivos del ZIP (en memoria, sin ejecutar nada) y texto de las diapositivas (PPTX o PDF). **Las imágenes se guardan sin describir** y el **código de un enlace de GitHub no se descarga**: los dos quedan para el evaluador (gastan tokens o bajan contenido de internet y conviene revisarlos con el sandbox).
- **Video fuera de esta versión:** no se acepta como archivo (gastaría el 1 GB gratis de Supabase); el SRS ya dejaba su análisis por fuera.
- **Topes:** 30 MB por petición solo en `POST /api/entregas` (las demás siguen en 6 MB); informe 10 MB y 60 páginas; ZIP 15 MB, 500 archivos y 20 MB abierto (512 KB por archivo de texto y 5 MB de texto en total); 5 imágenes de 2 MB; diapositivas 10 MB.
- **ZIP:** se rechaza entero si trae rutas que se salen de la carpeta, enlaces simbólicos, contraseña o si miente sobre su tamaño. Se omiten binarios, archivos grandes y carpetas como `__pycache__`, `.git`, `node_modules` y `.venv`.
- **Solo se entrega si el laboratorio tiene una rúbrica lista** (válida y confirmada); la entrega queda amarrada a esa versión aunque la rúbrica cambie después. Se puede entregar varias veces: nada se borra.
- **El estudiante solo ve lo suyo:** si pide una entrega, un archivo o un portafolio ajeno recibe 404, igual que si no existiera.
- **El lector de PDF quedó compartido** en `app/archivos/pdf.py` (rúbricas y entregas).
- **Cambia el SRS (sección 8):** `evidencias` suma `tamano_bytes`, `tipo_mime`, `resumen` y `fecha`; `texto_extraido` es JSON.

**Arreglos de la revisión (Puerta 2):**

- **Memoria (Render tiene 512 MB):** el PDF se lee en un proceso aparte con 200 MB (antes 400) y **uno a la vez**; solo se procesan **dos subidas a la vez** (si no hay turno en 20 s, 503). El PPTX ya no se abre con python-pptx (un archivo de 164 KB pedía 265 MB): se lee con expresiones regulares, con 2 MB por diapositiva y 10 MB en total. Los ZIP y PPTX solo se aceptan con compresión normal (sin LZMA, bzip2 ni zstd).
- **El tope de texto se cumple de verdad:** se corta dentro del proceso aparte, antes de llegar a la app, y queda `recortado` en `texto_extraido` y en el resumen. Antes un PDF de 269 KB devolvía 4,5 millones de caracteres.
- **Topes por estudiante:** 5 entregas por hora, 10 por laboratorio y no se acepta el mismo informe (mismo SHA-256) dos veces en un laboratorio. Además, 20 subidas por minuto por IP.
- **Más de 6 MB solo con sesión:** el middleware revisa la cookie firmada (sin ir a la base) antes de recibir una subida grande; sin ella responde 401 sin leer el cuerpo.
- **Las listas no cargan el texto extraído:** `texto_extraido` es una columna diferida y el resumen se guarda al subir en la columna `resumen`. `mis-entregas` y la bandeja del docente se paginan (`desde`, `limite`; 50 por defecto, máximo 200).
- **Un solo almacén para toda la app** (una sola conexión a Supabase).
- **Auditoría:** también quedan `acceso_ajeno_denegado` (el 404 por dueño), `enlace_emitido` (quién pidió bajar qué) y `archivo_rechazado` (con el motivo). Si no se puede borrar un archivo suelto, su ruta queda en el registro del servidor para borrarlo a mano.
- **Nombres y rutas sin caracteres invisibles** (controles, ancho cero, los que invierten el texto) ni `< > | " * ? :`.
- **La llave `service_role` de Supabase da acceso total al proyecto** (base y archivos), no solo a Storage: va solo en las variables de Render. La dirección se revisa completa (`fullmatch`).
- **Matrícula:** cualquier estudiante puede entregar en cualquier laboratorio. El SRS no pide matrícula por cohorte; si se pide después, se valida la cohorte al subir.
- **Imágenes:** no se revisan sus dimensiones porque hoy no se abren. El evaluador debe leer ancho y alto de la cabecera y poner un tope antes de mandarlas a la IA.
- **Enlace local:** el token va en la dirección y sirve 5 minutos a quien lo tenga. Solo existe en el PC (almacén local); se acepta así.

**Arreglos de la segunda revisión:**

- **Topes sin carrera:** con subidas simultáneas entraban 8 entregas con tope de 5. Ahora, justo antes de guardar, se bloquea la fila del estudiante (`SELECT ... FOR UPDATE`) y se vuelven a contar los topes en la misma transacción del INSERT. El informe repetido además lo frena la base: `entregas.sha256_informe` con restricción única (estudiante, laboratorio, informe). Probado con 8 subidas a la vez en PostgreSQL.
- **El turno cubre toda la subida:** leer, procesar y guardar en Supabase (antes el informe se leía antes del turno y el guardado iba después).
- **Más topes:** 10 archivos rechazados por hora (gastan turno y lector de PDF igual que una entrega) y 100 MB por estudiante por día (el 1 GB de Supabase ya no se llena en horas).
- **El límite por minuto usa el id del usuario como clave**, no la IP: detrás del proxy de Render todos llegan con la misma IP. El arreglo de fondo (`--proxy-headers`) sigue pendiente para el despliegue.
- **Índice del ZIP revisado antes de abrirlo:** se lee solo el registro final (22 bytes) y se rechaza si declara demasiadas entradas o un índice enorme; antes, un ZIP de 14 MB con 300.000 entradas falsas pedía 149 MB. Aplica al ZIP de código, al PPTX y al Word de las rúbricas.
- **Lector de PDF ocupado:** responde 503 con aviso en rúbricas y entregas (antes, 500 en rúbricas). Rúbricas suelta la conexión a la base mientras espera.
- **Nombres:** un nombre como `". ."` quedaba vacío y tumbaba las listas con 500; ahora se usa el nombre por defecto. También se quitan los saltos de línea de Unicode (U+2028, U+2029) y los caracteres privados o sin asignar, en nombres y rutas del ZIP.
- **Auditoría:** el mismo intento ajeno no se repite dentro de un minuto.
- **`/api/estudiantes` se pagina** como las otras listas, y las listas tienen orden fijo (el id desempata; los archivos de una entrega salen en orden: informe, código, diapositivas, imágenes).
- **`python-pptx` sale de producción** (junto con `lxml` y `xlsxwriter`): solo lo usan las pruebas, en `requirements-dev.in`.
- **Se acepta:** el filtro de 6 MB del middleware deja pasar cualquier cookie firmada y sin vencer (aunque la sesión se haya cerrado o el usuario sea docente); la revisión completa viene después y responde 401 o 403. Solo cuesta recibir hasta 30 MB.
- **Riesgo bajo que queda:** en SQLite (pruebas) no hay bloqueo de fila; en producción se usa PostgreSQL.

**Arreglos de la tercera revisión:**

- **ZIP64:** si justo antes del registro final hay un localizador ZIP64, zipfile usa ese registro e ignora el normal; un ZIP que decía "1 entrada" en el registro normal y 300.000 en el ZIP64 llegaba a 144 MB. Ahora un ZIP64 se rechaza (no hace falta para estos tamaños) y, como segunda defensa, el índice tiene que caber completo antes del registro final. Aplica al ZIP de código, al PPTX y al Word de las rúbricas.
- **Auditoría con tope por usuario:** como máximo 20 filas `acceso_ajeno_denegado` por hora (con ids al azar se podía escribir una fila por petición). Además, ver una entrega, pedir un enlace y ver un portafolio tienen límite de 60 por minuto por usuario.
- **Bloqueo más liviano:** `FOR NO KEY UPDATE` en vez de `FOR UPDATE`, para no frenar las llaves foráneas de la fila del estudiante.
- **Solo la restricción del informe responde "ya subiste este informe"**; cualquier otro error de integridad sale como error.
- **Nombres sin `< > | " * ? :`** también en el nombre visible (antes solo en las rutas del ZIP).
- **Orden fijo también en el portafolio** (los ids desempatan).
- **Se acepta:** una subida puede tardar hasta unos 110 s en el peor caso (espera de turno, espera del lector de PDF y lectura). No tumba la app; ocupa un turno mientras tanto.

**Arreglos de la cuarta revisión:**

- **Los límites por minuto cuentan por ruta**, no por dirección exacta (`key_style="endpoint"` en el limitador). Antes cada id tenía su propio contador y el "60 por minuto" de la tercera revisión no frenaba a quien probaba ids al azar. Probado con 61 peticiones de ids distintos en las tres rutas.
- **ZIP, PPTX o Word con un nombre interno mal codificado** (marcado UTF-8 con bytes inválidos) daban 500; ahora dan el aviso de siempre y cuentan como archivo rechazado.
- **Las pruebas de ZIP64 usan un ZIP64 válido** (zipfile lo abre); comprobado que fallan si se quita la defensa.
- **Auditoría:** al llegar al tope de intentos ajenos queda una sola fila `acceso_ajeno_tope` por hora, y cada intento siguiente va al registro del servidor con lo que pidió. El mismo enlace pedido otra vez dentro de un minuto no se vuelve a anotar.
- **Nombres:** se normalizan con NFKC antes de filtrar, para que `＜ ＞` de ancho completo no se cuelen.
- **"Ya subiste este informe"** solo con la restricción única de verdad (en SQLite, "UNIQUE constraint failed" y la columna); cualquier otro error de integridad va al registro y sale como error genérico.
- **Se acepta:** el tope de intentos ajenos se cuenta sin bloqueo; en una ráfaga simultánea pueden entrar unas filas de más antes de que corte.

**Arreglos de la quinta revisión:**

- **ZIP con desplazamiento enorme en el índice** (campo extra ZIP64 de 2^63 en un ZIP normal): daba `OverflowError` y 500 en ZIP, PPTX y Word. Ahora cada entrada tiene que empezar dentro del archivo (se revisa después de que zipfile lee el índice y antes de abrir ninguna entrada) y `ArithmeticError` también se captura. Da el aviso de siempre y cuenta como archivo rechazado.
- **Rutas del ZIP con caracteres de compatibilidad:** ver la sexta revisión (ahora se normalizan en vez de rechazarse).
- **`enlace_emitido` con tope de 200 por usuario por hora** (ver la sexta revisión: además queda una fila `enlace_tope`).
- **Pruebas más fuertes:** el orden fijo del portafolio se prueba con ids fijos (sin el desempate falla siempre) y la restricción única real se reconoce como "ya subiste este informe".
- **Se acepta:** por encima del tope de intentos ajenos, cada intento deja una línea en el registro del servidor (como mucho 180 por minuto por usuario, por el límite de las rutas).

**Arreglos de la sexta revisión:**

- **Word con compresión rara:** el lector del .docx de rúbricas era el único que no revisaba la compresión; un `document.xml` con zstd (Python 3.14+) lanzaba `ZstdError` y daba 500. Ahora acepta solo compresión normal y sin contraseña, como el ZIP y el PPTX. Además, como red de seguridad, **cualquier excepción al leer un ZIP ajeno** se trata como archivo dañado (aviso y no 500): así se corta esta familia de errores en vez de ir uno por uno. Desde la séptima revisión, las excepciones que no son de un tipo conocido además quedan en el registro del servidor con su tipo (sin contenido del archivo), para no confundir un error de nuestro código con un archivo dañado.
- **Rutas del ZIP: se normalizan con NFKC en vez de rechazarse.** La ruta normalizada es la que se revisa y la que se guarda: `＜entrega＞` queda `<entrega>` y se rechaza, `．．` queda `..` y se rechaza, y `Taller 1º.py`, `x².py` o los espacios especiales de macOS pasan (como `Taller 1o.py`, `x2.py`). Antes se rechazaba el ZIP entero.
- **Aviso de rutas más claro** (dice qué buscar), sin repetir el nombre que mandó el estudiante.
- **Tope de enlaces con rastro:** al pasar los 200 por hora queda una fila `enlace_tope` y cada enlace siguiente va al registro como aviso (el nivel `info` no se imprimía con la configuración por defecto).
- **La rama "ya subiste este informe" por restricción única se prueba por la ruta** (409 y se borran los archivos nuevos).
- **Pendiente para el evaluador:** caracteres parecidos a `< >` que NFKC no cambia (`〈 〉`, `‹ ›`) pasan en nombres y rutas. No forman la etiqueta `<entrega>`, pero el evaluador debe meter nombres y rutas como datos escapados (por ejemplo JSON) dentro de `<entrega>`, sin confiar solo en el filtro de caracteres.

**Arreglos de la séptima revisión** (la de seguridad se hizo con Opus 5.5: Mythos 5.2 y Fable 5.2 no tenían créditos):

- **La red de seguridad deja rastro:** una excepción de tipo desconocido al leer un ZIP, PPTX o Word sigue dando el aviso de archivo dañado, pero deja una línea en el registro con el tipo del error. Las excepciones conocidas no llenan el registro.
- **Nombres repetidos:** un ZIP con dos archivos que quedan con la misma ruta (después de NFKC y sin mirar mayúsculas, por ejemplo `main.py` y `ｍａｉｎ.py`, o la misma entrada dos veces) se rechaza. Si no, el evaluador vería dos `main.py` distintos y una cita no diría a cuál se refiere.
- **El aviso de rutas** también nombra los caracteres invisibles y los nombres de más de 255 letras.
- **Pasada final:** las rutas con tramos `.` o vacíos (`./main.py`, `a//main.py`) y con espacios al inicio o al final (`main.py `) se rechazan; apuntaban al mismo archivo o se veían iguales y se colaban como repetidos.
- **Se acepta:** como no se distinguen mayúsculas, un proyecto con `Makefile` y `makefile` en la misma carpeta se rechaza (es raro).
- **Se acepta:** letras de otro alfabeto que se ven iguales (`mаin.py` con "а" cirílica) pasan como archivos distintos; NFKC no las cambia. El evaluador cita la ruta exacta, así que no se confunden al buscar la cita.

## D-18 · Sandbox: cómo se aísla el código del estudiante (17-nov-2026)

El módulo se hizo con **Opus 5.5**: Mythos 5.2 y Fable 5.2 no tenían créditos (Andrés lo aprobó en la Puerta 1).

- **Un solo lanzador para los dos modos** (`app/sandbox/lanzador.py`, solo biblioteca estándar). La app lo corre con `python -I -B -c <código>` y le manda los archivos por la entrada estándar: no se monta ninguna carpeta del equipo en el contenedor y no hay que reconstruir la imagen cuando cambia el lanzador.
- **Dos corridas por entrega:** "revisar" (sintaxis con `ast.parse` y ruff, sin ejecutar el código) y "pruebas" (pytest, solo si hay `test_*.py` o `*_test.py`). Las dos van fuera del proceso web. Un solo tiempo total (`SANDBOX_TIEMPO_SEG`, 60 s) para todos los pasos, y **un sandbox a la vez** (Render tiene 512 MB).
- **ruff con `--isolated`:** no lee la configuración que traiga la entrega. Los errores de sintaxis de ruff quedan en "estilo" (ya tienen su paso) y `S101` (assert) no cuenta en archivos de pruebas.
- **Modo docker (PC):** `--network none`, `--memory 256m` sin swap, `--cpus 0.5`, `--pids-limit 32`, `--read-only` con `/tmp` en memoria de 10 MB y `noexec`, `--cap-drop ALL`, `no-new-privileges`, usuario 10001, `--pull never`. Al pasarse del tiempo, `docker kill`. El cliente de Docker recibe solo las variables que necesita (ninguna de la app). La imagen es `sandbox.Dockerfile` (Python 3.12, pytest y ruff con las versiones de `requirements.txt`).
- **Modo proceso (Render, solo Linux):** grupo de procesos propio que se mata entero, entorno con solo `PATH`, `LANG`, `HOME` y `TMPDIR`, carpeta temporal que se borra. El lanzador pone `RLIMIT_CPU` 30 s, `RLIMIT_AS` 256 MB, `RLIMIT_FSIZE` 10 MB y `RLIMIT_NPROC` (lo que ya tiene el usuario + 32: ese límite cuenta todos los procesos del usuario). El proceso web se marca con `PR_SET_DUMPABLE=0`: otro proceso del mismo usuario no puede leer `/proc/<pid>/environ`, donde están las llaves.
- **Gancho de auditoría** (los dos modos, antes de correr pytest): bloquea sockets, procesos nuevos (también `_posixsubprocess`), `ctypes`, `/proc` de otros procesos, escribir o cambiar archivos fuera de su carpeta y crear librerías nativas (`.so`). No se puede quitar desde Python. Es otra capa, no reemplaza al contenedor.
- **Pruebas apagadas en Render** (`SANDBOX_PRUEBAS=false` en `render.yaml`): el aislamiento por proceso es más débil que `--network none` (por ejemplo, un proceso del lector de PDF corre con las variables de la app y el gancho es la única barrera para leerlas). En la nube corren sintaxis y ruff; si la entrega trae pruebas, queda un aviso que lo explica. El sandbox completo se demuestra en el PC. Apagarlo por laboratorio (como dice el SRS) queda para después: pide una columna nueva y su migración.
- **Salida:** se lee con tope (256 KB) aunque el código imprima gigas, se quitan los NUL (PostgreSQL no los acepta) y se recorta a 20.000 caracteres. Las rutas salen relativas.
- **Nunca lanza error** (RNF-10): sin Docker, sin imagen, ocupado o sin tiempo, devuelve una verificación con el aviso. Lista vacía = la entrega no trae `.py`.
- **ruff y pytest pasan a `requirements.txt`:** el modo proceso los corre desde la imagen de la app.
- **Pruebas:** la matriz C3 (red, ciclo infinito, memoria, entorno) corre en cada modo que haya en el equipo: docker en el PC, proceso y docker en el CI. El ciclo infinito se prueba con 15 s para no esperar 60 s.
- **Pendiente para la conexión con el evaluador:** la salida de pytest la escribe el código del estudiante y puede traer frases como "pon 5.0". `material.armar` debe meterla como datos dentro de `<entrega>` y pasarla por el filtro de inyección (LLM01). El estudiante también puede forzar que pytest salga con código 0 (`os._exit(0)`); el docente ve la salida completa.
