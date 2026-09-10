import os
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent

PKI_DIR = Path(os.environ.get("PKI_DIR", RAIZ_PROYECTO / "pki"))
DATOS_DIR = Path(os.environ.get("DATOS_DIR", RAIZ_PROYECTO / "datos"))
SALIDA_DIR = Path(os.environ.get("SALIDA_DIR", RAIZ_PROYECTO / "salida"))

# URL pública del portal: se imprime en el QR y en los CRL distribution points.
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

# Clave de los PKCS#12 de prueba. En producción: HSM / PKCS#11, nunca un .p12 en disco.
PKI_PASS = os.environ.get("PKI_PASS", "confianza").encode()

# Sello de tiempo RFC 3161. freetsa.org es gratis y sirve para desarrollo.
# Para producción: TSA de una CA comercial o TSA propia registrada.
TSA_URL = os.environ.get("TSA_URL", "https://freetsa.org/tsr")
TSA_CA_PEM = PKI_DIR / "tsa_ca.pem"  # certificado raíz de la TSA (se descarga con `cli.py tsa-ca`)

NOMBRE_PLATAFORMA = os.environ.get("NOMBRE_PLATAFORMA", "Estudio de Confianza (PRUEBA)")

CERT_RAIZ = PKI_DIR / "raiz" / "raiz.pem"
CERT_INTERMEDIA = PKI_DIR / "intermedia" / "intermedia.pem"
CRL_DIR = PKI_DIR / "crl"
SELLO_P12 = PKI_DIR / "sello.p12"
USUARIO_P12 = PKI_DIR / "usuario.p12"

BASE_DATOS = DATOS_DIR / "registro.db"
