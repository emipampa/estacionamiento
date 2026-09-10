"""Firma PAdES con pyHanko: firma del usuario + sello de plataforma + sello de tiempo.

Modelo:
  1. El usuario firma (certificado emitido por la PKI de la plataforma).
  2. La plataforma agrega su sello de organización con sello de tiempo y,
     si hay TSA disponible, LTV/LTA para que la firma siga validando en el futuro.

Para pasar a producción se reemplaza `cargar_firmante` por un firmante PKCS#11
(token/HSM) o por un firmante remoto contra la API del proveedor. El resto no cambia.
"""
import io
import logging
from dataclasses import dataclass
from pathlib import Path

from asn1crypto import x509
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers
from pyhanko.sign.timestamps.requests_client import RequestsHTTPTimeStamper
from pyhanko.sign.signers.pdf_signer import PdfSignatureMetadata, PdfSigner
from pyhanko.stamp import TextStampStyle
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.fetchers.requests_fetchers import RequestsFetcherBackend

from . import config

log = logging.getLogger(__name__)


def _leer_cert(ruta: Path) -> x509.Certificate:
    from pyhanko.keys import load_cert_from_pemder

    return load_cert_from_pemder(str(ruta))


def certificados_confianza() -> list[x509.Certificate]:
    raices = [_leer_cert(config.CERT_RAIZ)]
    if config.TSA_CA_PEM.exists():
        raices.append(_leer_cert(config.TSA_CA_PEM))
    return raices


def crls_locales() -> list[bytes]:
    return [p.read_bytes() for p in sorted(config.CRL_DIR.glob("*.crl"))]


def contexto_validacion(permitir_descarga: bool = True) -> ValidationContext:
    """Contexto para reunir la información de revocación que se embebe (LTV)."""
    return ValidationContext(
        trust_roots=certificados_confianza(),
        other_certs=[_leer_cert(config.CERT_INTERMEDIA)],
        crls=crls_locales(),
        allow_fetching=permitir_descarga,  # para la cadena de la TSA
        fetcher_backend=RequestsFetcherBackend(per_request_timeout=20) if permitir_descarga else None,
        revocation_mode="soft-fail",
    )


def cargar_firmante(p12: Path, clave: bytes | None = None) -> signers.SimpleSigner:
    clave = clave if clave is not None else config.PKI_PASS
    firmante = signers.SimpleSigner.load_pkcs12(str(p12), passphrase=clave)
    if firmante is None:
        raise RuntimeError(f"No se pudo cargar {p12}")
    return firmante


def sellador_tiempo() -> RequestsHTTPTimeStamper | None:
    if not config.TSA_URL:
        return None
    # Cliente basado en `requests`: respeta HTTPS_PROXY y REQUESTS_CA_BUNDLE del entorno.
    return RequestsHTTPTimeStamper(config.TSA_URL, timeout=20)


@dataclass
class OpcionesFirma:
    campo: str
    razon: str
    pagina: int = 0
    caja: tuple[int, int, int, int] = (330, 60, 560, 120)  # puntos PDF, desde abajo-izquierda
    ltv: bool = True
    lta: bool = False
    con_tsa: bool = True


def firmar(pdf: bytes, firmante: signers.SimpleSigner, op: OpcionesFirma) -> bytes:
    """Agrega una firma PAdES visible al PDF y devuelve el PDF resultante."""
    w = IncrementalPdfFileWriter(io.BytesIO(pdf))
    tsa = sellador_tiempo() if op.con_tsa else None
    vc = contexto_validacion() if (op.ltv or op.lta) else None

    meta = PdfSignatureMetadata(
        field_name=op.campo,
        md_algorithm="sha256",
        subfilter=fields.SigSeedSubFilter.PADES,
        reason=op.razon,
        location="Argentina",
        embed_validation_info=bool(vc),
        use_pades_lta=op.lta and tsa is not None,
        validation_context=vc,
    )
    campo = fields.SigFieldSpec(sig_field_name=op.campo, on_page=op.pagina, box=op.caja)
    estilo = TextStampStyle(
        stamp_text="Firmado por: %(signer)s\nFecha: %(ts)s\nMotivo: " + op.razon,
        border_width=1,
    )
    firmador = PdfSigner(meta, signer=firmante, timestamper=tsa, stamp_style=estilo, new_field_spec=campo)
    salida = io.BytesIO()
    firmador.sign_pdf(w, output=salida)
    return salida.getvalue()


def firmar_documento(pdf: bytes, usuario_p12: Path, razon_usuario: str, con_tsa: bool = True) -> bytes:
    """Flujo completo: firma del usuario y después sello de la plataforma con LTA."""
    usuario = cargar_firmante(usuario_p12)
    paso1 = firmar(
        pdf,
        usuario,
        OpcionesFirma(campo="FirmaUsuario", razon=razon_usuario, caja=(60, 60, 290, 120),
                      ltv=con_tsa, con_tsa=con_tsa),
    )
    sello = cargar_firmante(config.SELLO_P12)
    paso2 = firmar(
        paso1,
        sello,
        OpcionesFirma(campo="SelloPlataforma", razon=f"Validado por {config.NOMBRE_PLATAFORMA}",
                      caja=(330, 60, 560, 120), ltv=con_tsa, lta=con_tsa, con_tsa=con_tsa),
    )
    return paso2
