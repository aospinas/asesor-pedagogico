# Rutas de la API y quién puede usarlas

Esta tabla sale de `app/api/rutas.py`, que es la fuente única del control de
acceso (OWASP A01). Si cambias una ruta allá, regenera la tabla con
`python -m app.api.rutas` y pégala aquí: la prueba `tests/test_rutas.py` falla
si la ruta, el rol o los requisitos no coinciden.

- **Pública:** se puede usar sin iniciar sesión.
- **Solo lo suyo:** el estudiante entra únicamente si el recurso es de él; el
  backend lo revisa en cada consulta.
- **Ya publicado:** al estudiante solo se le muestra lo que sale de evaluaciones
  que el docente ya publicó.
- Nadie puede borrar evaluaciones ni rúbricas, y ninguna ruta recibe una nota:
  la nota siempre la calcula `app/evaluador/nota.py`.

| Ruta | Para qué | Quién | Requisitos |
| --- | --- | --- | --- |
| `GET /salud` | Revisar que la app está arriba | Pública (sin sesión) | RNF-05 |
| `POST /api/sesion` | Iniciar sesión | Pública (sin sesión) | RF-01 |
| `GET /api/proyecto` | Página del proyecto y del equipo | Pública (sin sesión) | RF-18 |
| `GET /api/bitacora` | Bitácora de uso de IA | Pública (sin sesión) | RF-22 |
| `DELETE /api/sesion` | Cerrar sesión | Cualquiera con sesión | RF-01 |
| `GET /api/yo` | Ver mis datos y mi rol | Cualquiera con sesión | RF-01 |
| `PUT /api/yo/contrasena` | Cambiar mi contraseña | Cualquiera con sesión | RF-01 |
| `GET /api/usuarios` | Listar usuarios | Administrador | RF-02 |
| `POST /api/usuarios` | Crear un usuario | Administrador | RF-01, RF-02 |
| `PATCH /api/usuarios/{usuario_id}` | Editar, desactivar o cambiar el rol | Administrador | RF-02 |
| `POST /api/usuarios/{usuario_id}/clave-temporal` | Poner una clave temporal a quien olvidó la suya o quedó bloqueado | Administrador | RF-02 |
| `GET /api/estudiantes` | Listar estudiantes para abrir su portafolio o informe | Docente | RF-08 |
| `GET /api/cohortes` | Listar cohortes | Cualquiera con sesión | RF-03 |
| `POST /api/cohortes` | Crear una cohorte | Docente | RF-03 |
| `GET /api/laboratorios` | Listar laboratorios | Cualquiera con sesión | RF-03 |
| `POST /api/laboratorios` | Crear un laboratorio | Docente | RF-03 |
| `GET /api/laboratorios/{laboratorio_id}` | Ver un laboratorio | Cualquiera con sesión | RF-03 |
| `PATCH /api/laboratorios/{laboratorio_id}` | Editar un laboratorio | Docente | RF-03 |
| `GET /api/laboratorios/{laboratorio_id}/rubrica` | Ver la rúbrica vigente | Cualquiera con sesión | RF-04 |
| `POST /api/laboratorios/{laboratorio_id}/rubrica` | Cargar una rúbrica y convertirla con IA | Docente | RF-04, RF-05 |
| `PUT /api/laboratorios/{laboratorio_id}/rubrica` | Corregir la rúbrica (crea una versión nueva) | Docente | RF-05, RF-06 |
| `GET /api/laboratorios/{laboratorio_id}/rubrica/versiones` | Ver las versiones de la rúbrica | Docente | RF-06 |
| `POST /api/entregas` | Subir una entrega | Estudiante | RF-07 |
| `GET /api/mis-entregas` | Ver mis entregas | Estudiante | RF-08 |
| `GET /api/entregas/{entrega_id}` | Ver una entrega | Estudiante (solo lo suyo), Docente | RF-08 |
| `GET /api/laboratorios/{laboratorio_id}/entregas` | Ver las entregas de un laboratorio | Docente | RF-08 |
| `GET /api/evidencias/{evidencia_id}/enlace` | Pedir un enlace firmado que vence pronto para descargar un archivo | Estudiante (solo lo suyo), Docente | RNF-07 |
| `GET /api/portafolio/{estudiante_id}` | Ver el portafolio de un estudiante | Estudiante (solo lo suyo), Docente | RF-08 |
| `GET /api/evaluaciones` | Bandeja de evaluaciones por revisar | Docente | RF-14 |
| `POST /api/entregas/{entrega_id}/evaluaciones` | Lanzar la evaluación con IA | Docente | RF-09, RF-10, RF-11, RF-13 |
| `GET /api/evaluaciones/{evaluacion_id}` | Ver la evaluación completa | Docente | RF-14 |
| `POST /api/evaluaciones/{evaluacion_id}/ajustes` | Cambiar el nivel de un criterio (la nota se recalcula) | Docente | RF-14 |
| `PATCH /api/evaluaciones/{evaluacion_id}/retroalimentacion` | Editar la retroalimentación de un criterio | Docente | RF-14 |
| `POST /api/evaluaciones/{evaluacion_id}/aprobar` | Aprobar la evaluación | Docente | RF-14 |
| `POST /api/evaluaciones/{evaluacion_id}/publicar` | Publicar la evaluación | Docente | RF-14 |
| `GET /api/evaluaciones/{evaluacion_id}/traza` | Ver la traza | Docente, Administrador | RF-15, RNF-08 |
| `GET /api/evaluaciones/{evaluacion_id}/publicada` | Ver la evaluación ya publicada | Estudiante (solo lo suyo y ya publicado), Docente | RNF-09 |
| `GET /api/informe/{estudiante_id}` | Ver el informe integrado | Estudiante (solo lo suyo y ya publicado), Docente | RF-16 |
| `GET /api/informe/{estudiante_id}/pdf` | Descargar el informe en PDF | Estudiante (solo lo suyo y ya publicado), Docente | RF-16 |
| `GET /api/mapa/{estudiante_id}` | Ver el mapa mental | Estudiante (solo lo suyo y ya publicado), Docente | RF-17 |
| `GET /api/config-ia` | Ver el proveedor y el modelo de IA | Administrador | RF-19 |
| `PUT /api/config-ia` | Cambiar el proveedor y el modelo de IA | Administrador | RF-19 |
| `POST /api/config-ia/probar` | Probar la conexión con la IA | Administrador | RF-19 |
| `GET /api/costos` | Ver tokens y costo por evaluación | Administrador | RF-20 |
| `GET /api/auditoria` | Ver el registro de auditoría | Administrador | RF-15 |
