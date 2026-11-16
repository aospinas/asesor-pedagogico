# Bitácora de uso de IA

Lo pide el enunciado: herramientas, aportes, limitaciones y decisiones técnicas.
El orquestador agrega una fila por módulo con `/bitacora`; la columna
"Decisión humana" la escribe Andrés con sus palabras.

## Herramientas de IA del proyecto

| Herramienta | Fase | Para qué se usa | Limitación conocida |
| --- | --- | --- | --- |
| Claude (claude.ai) | Requisitos y diseño | Análisis del enunciado, SRS, arquitectura, kit inicial | Puede proponer servicios cuyos planes ya cambiaron; se verificó cada plan |
| Claude Design | Diseño de interfaz | Tres direcciones visuales y handoff a código | Hay que ajustar los diseños a lo que el backend sí entrega |
| Claude Code con Claude Mythos 5.2 | Módulos críticos, revisión de seguridad, depuración | Contrato, evaluador, sandbox, login; subagentes `revisor-seguridad` y `depurador` | Cuesta el doble por token que Opus 5.5; se reserva para lo crítico |
| Claude Code con Claude Opus 5.5 | Orquestación y módulos de menor riesgo | Rúbricas, portafolio, frontend, informe, mapa, documentación; subagente `revisor-calidad` | Necesita aprobación humana en cada puerta |
| OpenAI (API) | Dentro del producto | Evaluar criterios, interpretar rúbricas, describir imágenes | Costo por uso; puede inventar evidencias (por eso RF-12) |
| Ollama | Dentro del producto | Opción local y gratis | Más lento y menos preciso |

## Registro por módulo

| Fecha | Fase | Herramienta | Qué se le pidió | Qué aportó | Problema o limitación | Decisión humana |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-11-13 | Requisitos | Claude (claude.ai) | Analizar el enunciado y redactar el SRS con RF, RNF, casos de uso, OWASP y plan de un día | SRS, arquitectura, matriz de trazabilidad | Propuso Hugging Face Spaces y al verificar se vio que Docker ya es de pago; se cambió a Render | Todo gratis salvo OpenAI, un día, OWASP solo lo aplicable, diseño elegido en Claude Design |
| 2026-11-13 | Arranque | Claude (claude.ai) | Armar el kit del repo: CLAUDE.md, agentes, comandos, guardrails, CI, esquemas y cálculo de nota | Kit con 26 pruebas pasando en Python 3.15 | Supuso Python 3.12; se corrigió a 3.15 y se probó cada dependencia, dejando 3.12 como plan B probado. PyYAML no instala en 3.15, se ajustó uvicorn y bandit. No pudo construir la imagen Docker en su entorno, así que la prueba de Docker quedó en el CI | (completar) |
| 2026-11-15 | Arranque | Claude (claude.ai) | Repartir el trabajo entre Mythos 5.2 y Opus 5.5 | Tabla de modelos por tarea, subagente depurador, modelos fijos en los subagentes | Primero supuso que el equipo no tenía acceso a Mythos y propuso Fable 5.2; Andrés aclaró que sí tiene acceso y se cambió a Mythos, dejando Fable como plan B | (completar) |
| 2026-11-15 | Contrato | Claude Code con Claude Mythos 5.2 (subagentes `revisor-seguridad` con Mythos 5.2 y `revisor-calidad` con Opus 5.5) | Completar `app/esquemas.py` y hacer la tabla de rutas de la API con el rol de cada una | Modelos de usuarios, laboratorios, entregas, evaluaciones, revisión, informe y mapa; 44 rutas con rol en `app/api/rutas.py` y `docs/api.md`; 224 pruebas pasando | La primera versión tenía fallas que encontraron los revisores: la dirección de la IA aceptaba cualquier servidor (la llave podía salir), la contraseña aceptaba más de lo que soporta bcrypt, los niveles aceptaban infinito, no había topes de tamaño, faltaban esquemas de dos salidas de la IA y `/openapi.json` seguía público. Un validador de correo falló en la primera prueba y se corrigió. Los arreglos no pasaron por una segunda revisión. En el arranque, Claude Code no pudo abrir el PR: `gh` no estaba instalado y lo abrió Andrés | (completar) |
| 2026-11-16 | Auth | Claude Code con Claude Mythos 5.2 (subagentes `revisor-seguridad` con Mythos 5.2 y `revisor-calidad` con Opus 5.5) | Hacer el inicio de sesión, los roles, la gestión de usuarios y la auditoría (RF-01, RF-02, RF-22) | Sesión con cookie segura, control de rol en las 45 rutas desde una sola tabla, usuarios creados por el administrador, clave temporal, auditoría de cada cambio, tablas y migraciones, comando para el primer administrador; 376 pruebas pasando contra PostgreSQL y 375 en SQLite | La primera versión tenía fallas que encontró el revisor de seguridad: el bloqueo por intentos se podía saltar con peticiones al mismo tiempo (hallazgo alto), cualquiera podía bloquearle la cuenta a otro, cerrar sesión no invalidaba el token, cambiar la contraseña no tenía tope de intentos, se podía dejar el sistema sin administrador y `ENTORNO` mal escrito arrancaba en modo desarrollo. Se rehízo el bloqueo y se cambió la migración. Los arreglos no pasaron por una segunda revisión. La prueba de acceso al principio solo veía `/salud` y no avisaba; las pruebas contra PostgreSQL se colgaban por usar `localhost` (se cambió a `127.0.0.1`). Claude Code no puede leer `.env` ni abrir el PR (sin `gh`): eso lo hace Andrés. Quedó pendiente para el despliegue la IP real detrás del proxy de Render | (completar) |

## Reflexión final

Responder al cerrar el proyecto, con ejemplos reales de esta bitácora:

- ¿Qué parte hizo mejor la IA y cuál tuvieron que corregir más?
- ¿Qué hallazgo de los revisores evitó un error serio?
- ¿Qué decisión técnica tomaron ustedes en contra de lo que propuso la IA, y por qué?
- ¿Cuánto costó en tokens evaluar los laboratorios reales?
