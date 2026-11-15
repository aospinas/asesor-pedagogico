# Esta imagen se prueba en el PC con /probar-imagen, la vuelve a probar el CI
# y la construye Render al publicar.
# Plan B: si algo falla en 3.15, cambia esta línea a 3.12 (también está probada).
ARG PYTHON_VERSION=3.15
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

USER app
ENV PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000

# Render entrega el puerto en la variable PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
