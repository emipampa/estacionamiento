"""Verificación: firmas embebidas (pyHanko) + registro de la plataforma."""
import io
from dataclasses import asdict, dataclass, field

from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature, validate_pdf_timestamp
from pyhanko_certvalidator import ValidationContext

from . import config, firmador
from .registro import Registro, sha256


@dataclass
class FirmaVerificada:
    campo: str
    firmante: str
    fecha_declarada: str | None
    integra: bool
    confiable: bool
    sello_tiempo_valido: bool | None
    nivel_modificacion: str | None
    resumen: str
    detalle: str


@dataclass
class ResultadoVerificacion:
    hash_sha256: str
    firmas: list[FirmaVerificada] = field(default_factory=list)
    sellos_documento: list[dict] = field(default_factory=list)
    registro: dict | None = None
    eventos: list[dict] = field(default_factory=list)

    @property
    def valido(self) -> bool:
        firmas_ok = bool(self.firmas) and all(f.integra and f.confiable for f in self.firmas)
        registrado = self.registro is not None and self.registro.get("estado") == "vigente"
        return firmas_ok and registrado

    def como_dict(self) -> dict:
        d = asdict(self)
        d["valido"] = self.valido
        return d


def contexto_verificacion() -> ValidationContext:
    return ValidationContext(
        trust_roots=firmador.certificados_confianza(),
        other_certs=[firmador._leer_cert(config.CERT_INTERMEDIA)],
        crls=firmador.crls_locales(),
        allow_fetching=False,
        revocation_mode="soft-fail",
    )


def verificar(pdf: bytes, registro: Registro | None = None) -> ResultadoVerificacion:
    resultado = ResultadoVerificacion(hash_sha256=sha256(pdf))
    vc = contexto_verificacion()
    lector = PdfFileReader(io.BytesIO(pdf))
    for emb in lector.embedded_signatures:
        if emb.sig_object_type == "/DocTimeStamp":
            # Sello de tiempo de documento (PAdES-LTA): se valida aparte y se informa como tal.
            estado = validate_pdf_timestamp(emb, validation_context=vc)
            resultado.sellos_documento.append(
                {"campo": emb.field_name, "valido": estado.valid and estado.trusted,
                 "momento": estado.timestamp.isoformat() if estado.timestamp else None,
                 "resumen": estado.summary()}
            )
            continue
        estado = validate_pdf_signature(emb, signer_validation_context=vc, ts_validation_context=vc)
        cn = emb.signer_cert.subject.native.get("common_name", "?")
        ts_ok = estado.timestamp_validity.valid if estado.timestamp_validity else None
        resultado.firmas.append(
            FirmaVerificada(
                campo=emb.field_name,
                firmante=cn,
                fecha_declarada=emb.self_reported_timestamp.isoformat() if emb.self_reported_timestamp else None,
                integra=estado.intact and estado.valid,
                confiable=estado.trusted,
                sello_tiempo_valido=ts_ok,
                nivel_modificacion=estado.modification_level.name if estado.modification_level else None,
                resumen=estado.summary(),
                detalle=estado.pretty_print_details(),
            )
        )
    if registro is not None:
        fila = registro.buscar_por_hash(resultado.hash_sha256)
        if fila:
            resultado.registro = fila
            resultado.eventos = registro.eventos(fila["id"])
    return resultado
