"""Tabla de rutas de la API y qué rol puede usar cada una (OWASP A01).

Es la fuente única del control de acceso: el módulo de login la hace cumplir y
`docs/api.md` la muestra para leer. Aquí solo hay datos y la función que
arma esa tabla; el control de acceso de verdad lo hace el módulo de login.

- `publica=True`: se puede usar sin sesión.
- `solo_dueno=True`: el estudiante solo entra si el recurso es suyo; el backend
  lo revisa en cada consulta. A los demás roles no les aplica.
- `solo_publicado=True`: al estudiante solo se le muestra lo que sale de
  evaluaciones ya publicadas (RNF-09).
"""

from dataclasses import dataclass

from app.esquemas import Rol

E, D, A = Rol.ESTUDIANTE, Rol.DOCENTE, Rol.ADMINISTRADOR
TODOS = frozenset({E, D, A})
NADIE: frozenset[Rol] = frozenset()


@dataclass(frozen=True)
class Ruta:
    metodo: str
    ruta: str
    roles: frozenset[Rol]
    descripcion: str
    rf: tuple[str, ...] = ()
    publica: bool = False
    solo_dueno: bool = False
    solo_publicado: bool = False


def _r(
    metodo, ruta, roles, descripcion, rf=(), *, publica=False, solo_dueno=False, solo_publicado=False
) -> Ruta:
    return Ruta(metodo, ruta, frozenset(roles), descripcion, tuple(rf), publica, solo_dueno, solo_publicado)


RUTAS: tuple[Ruta, ...] = (
    # --- Públicas ---
    _r("GET", "/salud", NADIE, "Revisar que la app está arriba", ["RNF-05"], publica=True),
    _r("POST", "/api/sesion", NADIE, "Iniciar sesión", ["RF-01"], publica=True),
    _r("GET", "/api/proyecto", NADIE, "Página del proyecto y del equipo", ["RF-18"], publica=True),
    _r("GET", "/api/bitacora", NADIE, "Bitácora de uso de IA", ["RF-22"], publica=True),
    # --- Sesión ---
    _r("DELETE", "/api/sesion", TODOS, "Cerrar sesión", ["RF-01"]),
    _r("GET", "/api/yo", TODOS, "Ver mis datos y mi rol", ["RF-01"]),
    _r("PUT", "/api/yo/contrasena", TODOS, "Cambiar mi contraseña", ["RF-01"]),
    # --- Usuarios ---
    _r("GET", "/api/usuarios", [A], "Listar usuarios", ["RF-02"]),
    _r("POST", "/api/usuarios", [A], "Crear un usuario", ["RF-01", "RF-02"]),
    _r("PATCH", "/api/usuarios/{usuario_id}", [A], "Editar, desactivar o cambiar el rol", ["RF-02"]),
    _r(
        "POST",
        "/api/usuarios/{usuario_id}/clave-temporal",
        [A],
        "Poner una clave temporal a quien olvidó la suya o quedó bloqueado",
        ["RF-02"],
    ),
    _r("GET", "/api/estudiantes", [D], "Listar estudiantes para abrir su portafolio o informe", ["RF-08"]),
    # --- Cohortes y laboratorios ---
    _r("GET", "/api/cohortes", TODOS, "Listar cohortes", ["RF-03"]),
    _r("POST", "/api/cohortes", [D], "Crear una cohorte", ["RF-03"]),
    _r("GET", "/api/laboratorios", TODOS, "Listar laboratorios", ["RF-03"]),
    _r("POST", "/api/laboratorios", [D], "Crear un laboratorio", ["RF-03"]),
    _r("GET", "/api/laboratorios/{laboratorio_id}", TODOS, "Ver un laboratorio", ["RF-03"]),
    _r("PATCH", "/api/laboratorios/{laboratorio_id}", [D], "Editar un laboratorio", ["RF-03"]),
    # --- Rúbricas ---
    _r("GET", "/api/laboratorios/{laboratorio_id}/rubrica", TODOS, "Ver la rúbrica vigente", ["RF-04"]),
    _r(
        "POST",
        "/api/laboratorios/{laboratorio_id}/rubrica",
        [D],
        "Cargar una rúbrica y convertirla con IA",
        ["RF-04", "RF-05"],
    ),
    _r(
        "PUT",
        "/api/laboratorios/{laboratorio_id}/rubrica",
        [D],
        "Corregir la rúbrica (crea una versión nueva)",
        ["RF-05", "RF-06"],
    ),
    _r(
        "GET",
        "/api/laboratorios/{laboratorio_id}/rubrica/versiones",
        [D],
        "Ver las versiones de la rúbrica",
        ["RF-06"],
    ),
    # --- Entregas y portafolio ---
    _r("POST", "/api/entregas", [E], "Subir una entrega", ["RF-07"]),
    _r("GET", "/api/mis-entregas", [E], "Ver mis entregas", ["RF-08"]),
    _r("GET", "/api/entregas/{entrega_id}", [E, D], "Ver una entrega", ["RF-08"], solo_dueno=True),
    _r(
        "GET",
        "/api/laboratorios/{laboratorio_id}/entregas",
        [D],
        "Ver las entregas de un laboratorio",
        ["RF-08"],
    ),
    _r(
        "GET",
        "/api/evidencias/{evidencia_id}/enlace",
        [E, D],
        "Pedir un enlace firmado que vence pronto para descargar un archivo",
        ["RNF-07"],
        solo_dueno=True,
    ),
    _r(
        "GET",
        "/api/portafolio/{estudiante_id}",
        [E, D],
        "Ver el portafolio de un estudiante",
        ["RF-08"],
        solo_dueno=True,
    ),
    # --- Evaluaciones ---
    _r("GET", "/api/evaluaciones", [D], "Bandeja de evaluaciones por revisar", ["RF-14"]),
    _r(
        "POST",
        "/api/entregas/{entrega_id}/evaluaciones",
        [D],
        "Lanzar la evaluación con IA",
        ["RF-09", "RF-10", "RF-11", "RF-13"],
    ),
    _r("GET", "/api/evaluaciones/{evaluacion_id}", [D], "Ver la evaluación completa", ["RF-14"]),
    _r(
        "POST",
        "/api/evaluaciones/{evaluacion_id}/ajustes",
        [D],
        "Cambiar el nivel de un criterio (la nota se recalcula)",
        ["RF-14"],
    ),
    _r(
        "PATCH",
        "/api/evaluaciones/{evaluacion_id}/retroalimentacion",
        [D],
        "Editar la retroalimentación de un criterio",
        ["RF-14"],
    ),
    _r("POST", "/api/evaluaciones/{evaluacion_id}/aprobar", [D], "Aprobar la evaluación", ["RF-14"]),
    _r("POST", "/api/evaluaciones/{evaluacion_id}/publicar", [D], "Publicar la evaluación", ["RF-14"]),
    _r("GET", "/api/evaluaciones/{evaluacion_id}/traza", [D, A], "Ver la traza", ["RF-15", "RNF-08"]),
    _r(
        "GET",
        "/api/evaluaciones/{evaluacion_id}/publicada",
        [E, D],
        "Ver la evaluación ya publicada",
        ["RNF-09"],
        solo_dueno=True,
        solo_publicado=True,
    ),
    # --- Informe y mapa mental ---
    _r(
        "GET",
        "/api/informe/{estudiante_id}",
        [E, D],
        "Ver el informe integrado",
        ["RF-16"],
        solo_dueno=True,
        solo_publicado=True,
    ),
    _r(
        "GET",
        "/api/informe/{estudiante_id}/pdf",
        [E, D],
        "Descargar el informe en PDF",
        ["RF-16"],
        solo_dueno=True,
        solo_publicado=True,
    ),
    _r(
        "GET",
        "/api/mapa/{estudiante_id}",
        [E, D],
        "Ver el mapa mental",
        ["RF-17"],
        solo_dueno=True,
        solo_publicado=True,
    ),
    # --- Configuración de IA, costos y auditoría ---
    _r("GET", "/api/config-ia", [A], "Ver el proveedor y el modelo de IA", ["RF-19"]),
    _r("PUT", "/api/config-ia", [A], "Cambiar el proveedor y el modelo de IA", ["RF-19"]),
    _r("POST", "/api/config-ia/probar", [A], "Probar la conexión con la IA", ["RF-19"]),
    _r("GET", "/api/costos", [A], "Ver tokens y costo por evaluación", ["RF-20"]),
    _r("GET", "/api/auditoria", [A], "Ver el registro de auditoría", ["RF-15"]),
)

_NOMBRES = {E: "Estudiante", D: "Docente", A: "Administrador"}


def quien(ruta: Ruta) -> str:
    """Texto de la columna "Quién" de docs/api.md."""
    if ruta.publica:
        return "Pública (sin sesión)"
    if ruta.roles == TODOS:
        return "Cualquiera con sesión"
    nombres = []
    for rol in (E, D, A):
        if rol in ruta.roles:
            suyo = ""
            if rol is E and ruta.solo_dueno:
                suyo = " (solo lo suyo y ya publicado)" if ruta.solo_publicado else " (solo lo suyo)"
            nombres.append(_NOMBRES[rol] + suyo)
    return ", ".join(nombres)


def tabla_markdown() -> str:
    """La tabla de docs/api.md. Para regenerarla: python -m app.api.rutas"""
    filas = ["| Ruta | Para qué | Quién | Requisitos |", "| --- | --- | --- | --- |"]
    filas += [f"| `{r.metodo} {r.ruta}` | {r.descripcion} | {quien(r)} | {', '.join(r.rf)} |" for r in RUTAS]
    return "\n".join(filas)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print(tabla_markdown())
