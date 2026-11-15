# Lista OWASP del proyecto (solo lo que aplica)

Fuente: OWASP Top 10:2025 y OWASP Top 10 para aplicaciones con LLM 2025.
El detalle de por qué aplica cada uno está en `docs/srs.md`, sección 4.
El revisor de seguridad marca cada punto cuando el módulo que lo toca está listo.

## Web (OWASP Top 10:2025)

- [ ] **A01 Control de acceso:** cada consulta filtra por dueño y rol; IDs UUID; prueba de acceso cruzado entre dos estudiantes.
- [ ] **A02 Mala configuración:** sin debug en producción, CORS solo al dominio propio, `/docs` cerrado, cabeceras de seguridad.
- [ ] **A03 Cadena de suministro:** versiones fijadas en `requirements.txt`; `pip-audit` y `npm audit` en el CI.
- [ ] **A04 Criptografía:** contraseñas con bcrypt; secretos solo en variables de entorno.
- [ ] **A05 Inyección:** ORM con parámetros; nombres de archivo saneados.
- [ ] **A06 Diseño inseguro:** código del estudiante solo en el sandbox, sin secretos en su entorno.
- [ ] **A07 Autenticación:** 5 intentos y bloqueo de 5 min; contraseña mínima de 10 caracteres; sesión que vence.
- [ ] **A08 Integridad de datos:** ZIP sin rutas `../`; máximo 25 MB subido y 100 MB descomprimido; hash SHA-256.
- [ ] **A09 Registro y alertas:** tabla de auditoría con usuario, acción, valor anterior y nuevo.
- [ ] **A10 Condiciones excepcionales:** errores capturados; mensaje claro al usuario; detalle solo en logs.

## IA (OWASP Top 10 para LLM 2025)

- [ ] **LLM01 Inyección de prompt:** material dentro de `<entrega>`; filtro de frases; la IA no pone la nota.
- [ ] **LLM02 Fuga de información:** solo se envía lo necesario; opción Ollama local.
- [ ] **LLM05 Manejo de la salida:** validación con `app/esquemas.py` (`extra="forbid"`) y texto escapado.
- [ ] **LLM06 Exceso de autonomía:** la IA no tiene herramientas ni permisos; publicar es del docente.
- [ ] **LLM07 Fuga del prompt:** el prompt no guarda secretos.
- [ ] **LLM09 Desinformación:** verificación de citas (RF-12) y revisión docente.
- [ ] **LLM10 Consumo sin límite:** topes de páginas, tokens y evaluaciones por hora.

No aplican: LLM03 (modelos sin modificar de proveedores conocidos), LLM04 (no se entrena nada), LLM08 (no hay búsqueda vectorial).
