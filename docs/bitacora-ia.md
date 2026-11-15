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

## Reflexión final

Responder al cerrar el proyecto, con ejemplos reales de esta bitácora:

- ¿Qué parte hizo mejor la IA y cuál tuvieron que corregir más?
- ¿Qué hallazgo de los revisores evitó un error serio?
- ¿Qué decisión técnica tomaron ustedes en contra de lo que propuso la IA, y por qué?
- ¿Cuánto costó en tokens evaluar los laboratorios reales?
