"""Registro de documentos: lo que hace que ustedes sean el tercero de confianza.

Guarda, por documento, el hash antes y después de firmar, quién firmó, cuándo
y en qué estado está. Esto es lo que consulta el portal de verificación y lo
que se anclaría en OpenTimestamps o similar en una etapa siguiente.
"""
import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL,
    hash_original TEXT NOT NULL,
    hash_firmado TEXT,
    firmante TEXT NOT NULL,
    creado TEXT NOT NULL,
    firmado TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente'
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    documento_id TEXT NOT NULL REFERENCES documentos(id),
    momento TEXT NOT NULL,
    tipo TEXT NOT NULL,
    detalle TEXT
);
CREATE INDEX IF NOT EXISTS ix_hash_firmado ON documentos(hash_firmado);
"""


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def nuevo_id() -> str:
    # Corto, legible y con suficiente entropía para no poder adivinarse.
    return "EC-" + secrets.token_hex(6).upper()


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Registro:
    def __init__(self, ruta: Path | None = None):
        ruta = ruta or config.BASE_DATOS
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(ruta, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)

    def crear(self, titulo: str, pdf_original: bytes, firmante: str) -> str:
        doc_id = nuevo_id()
        self.con.execute(
            "INSERT INTO documentos (id, titulo, hash_original, firmante, creado) VALUES (?,?,?,?,?)",
            (doc_id, titulo, sha256(pdf_original), firmante, ahora()),
        )
        self.evento(doc_id, "creado", f"firmante={firmante}")
        return doc_id

    def marcar_firmado(self, doc_id: str, pdf_firmado: bytes, detalle: str = "") -> None:
        self.con.execute(
            "UPDATE documentos SET hash_firmado=?, firmado=?, estado='vigente' WHERE id=?",
            (sha256(pdf_firmado), ahora(), doc_id),
        )
        self.evento(doc_id, "firmado", detalle)

    def revocar(self, doc_id: str, motivo: str) -> None:
        self.con.execute("UPDATE documentos SET estado='revocado' WHERE id=?", (doc_id,))
        self.evento(doc_id, "revocado", motivo)

    def evento(self, doc_id: str, tipo: str, detalle: str = "") -> None:
        self.con.execute(
            "INSERT INTO eventos (documento_id, momento, tipo, detalle) VALUES (?,?,?,?)",
            (doc_id, ahora(), tipo, detalle),
        )
        self.con.commit()

    def obtener(self, doc_id: str) -> dict | None:
        fila = self.con.execute("SELECT * FROM documentos WHERE id=?", (doc_id,)).fetchone()
        return dict(fila) if fila else None

    def buscar_por_hash(self, hash_hex: str) -> dict | None:
        fila = self.con.execute(
            "SELECT * FROM documentos WHERE hash_firmado=? OR hash_original=?", (hash_hex, hash_hex)
        ).fetchone()
        return dict(fila) if fila else None

    def eventos(self, doc_id: str) -> list[dict]:
        filas = self.con.execute(
            "SELECT momento, tipo, detalle FROM eventos WHERE documento_id=? ORDER BY id", (doc_id,)
        ).fetchall()
        return [dict(f) for f in filas]
