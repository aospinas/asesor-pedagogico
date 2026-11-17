# Esta imagen se prueba en el PC con /probar-imagen, la vuelve a probar el CI
# y la construye Render al publicar.
# Plan B: si algo falla en 3.15, cambia esta línea a 3.12 (también está probada).
# (El ARG va antes del primer FROM para que lo vea la etapa de Python.)
ARG PYTHON_VERSION=3.15

# Etapa 1: el frontend (React). Solo queda la carpeta dist; Node no va en la imagen final.
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:${PYTHON_VERSION}-slim

# Librerías del sistema que necesita WeasyPrint para generar el informe en PDF
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# OWASP A02/A06: la app no corre como root
RUN useradd --create-home --uid 10001 app
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY prompts ./prompts
COPY --from=web /web/dist ./frontend/dist
COPY alembic.ini .
COPY migraciones ./migraciones

USER app
ENV PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000

# Render entrega el puerto en la variable PORT.
# Si hay base de datos configurada, primero se aplican las migraciones pendientes;
# si una migración falla, la app no arranca (mejor eso que arrancar con tablas viejas).
CMD ["sh", "-c", "{ [ -z \"$DATABASE_URL\" ] || alembic upgrade head; } && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
