# Imagen del sandbox (SANDBOX_MODE=docker, D-18). Solo trae Python, pytest y ruff:
# el código del lanzador lo manda la app en cada corrida, así que no hay que
# reconstruir la imagen cuando cambia app/sandbox/lanzador.py.
#
# Crear en el PC (una vez, y cada vez que cambie requirements-sandbox.txt):
#   docker build -t asesor-sandbox:1 -f sandbox.Dockerfile .
#
# Los límites (sin red, memoria, CPU, procesos, solo lectura) los pone `docker run`
# en app/sandbox/ejecutar.py, no esta imagen.
FROM python:3.12-slim

COPY requirements-sandbox.txt /tmp/requirements-sandbox.txt
RUN pip install --no-cache-dir -r /tmp/requirements-sandbox.txt && rm /tmp/requirements-sandbox.txt

# Usuario sin privilegios (el mismo uid que pasa `docker run --user`)
RUN useradd --no-create-home --uid 10001 sandbox
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /tmp
