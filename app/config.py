"""Ajustes de la app. Todo sale de variables de entorno (en el PC, del archivo .env)."""

import secrets
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRETO_MINIMO = 32


class Ajustes(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Lista cerrada: si ENTORNO queda mal escrito la app no arranca, en vez de
    # arrancar sin avisar en modo desarrollo (cookie sin HTTPS).
    entorno: Literal["desarrollo", "pruebas", "produccion"] = "desarrollo"
    database_url: str = ""
    jwt_secreto: str = ""
    origenes_permitidos: str = "http://localhost:5173"
    sesion_minutos: int = Field(default=480, ge=5, le=1440)
    bcrypt_rondas: int = Field(default=12, ge=4, le=15)

    @property
    def en_produccion(self) -> bool:
        return self.entorno == "produccion"

    @property
    def origenes(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.origenes_permitidos.split(",") if o.strip()]

    @model_validator(mode="after")
    def _revisar(self) -> Self:
        # SQLAlchemy necesita saber qué conector usar; Supabase entrega la dirección sin él.
        for prefijo in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefijo):
                self.database_url = "postgresql+psycopg://" + self.database_url[len(prefijo) :]

        if self.en_produccion:
            if len(self.jwt_secreto) < SECRETO_MINIMO:
                raise ValueError(
                    f"JWT_SECRETO debe tener al menos {SECRETO_MINIMO} caracteres en producción."
                )
            if not self.database_url:
                raise ValueError("Falta DATABASE_URL en producción.")
            if not self.origenes or any(not o.startswith("https://") for o in self.origenes):
                raise ValueError(
                    "En producción ORIGENES_PERMITIDOS debe ser la dirección https de la app (sin * ni http)."
                )
        elif not self.jwt_secreto:
            # En el PC, sin secreto, se inventa uno: las sesiones duran hasta que se reinicia la app.
            self.jwt_secreto = secrets.token_urlsafe(48)
        return self


@lru_cache
def ajustes() -> Ajustes:
    return Ajustes()
