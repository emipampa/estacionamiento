# Estudio de Confianza: prototipo de firma y verificación de documentos

Prototipo de plataforma de tercero de confianza: un documento pasa por la plataforma,
lo firma el usuario con un certificado emitido por nuestra PKI, la plataforma le agrega
su sello con sello de tiempo y LTV, lo registra, y cualquiera puede verificarlo por QR
o subiendo el PDF.

Esto es la etapa "mes uno": todo funciona con una PKI de prueba. Más abajo está lo que
cambia para pasar a producción.

## Qué hace

- **Firma PAdES** con [pyHanko](https://pyhanko.readthedocs.io): firma del usuario más
  sello de plataforma, ambos visibles en el PDF, con sello de tiempo RFC 3161 y
  archivado a largo plazo (LTV/LTA) para que sigan validando cuando los certificados venzan.
- **Registro** SQLite con hash antes y después de firmar, firmante, fechas, estado
  (vigente/revocado) e historial de eventos.
- **Portal de verificación** (FastAPI): página del documento por ID (lo que abre el QR),
  verificación subiendo el PDF, descarga de la raíz para instalar en Acrobat, CRLs.
- **CLI** para generar, firmar, verificar y revocar.

## Arranque local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/setup_ca.sh            # PKI de prueba en pki/
.venv/bin/python cli.py tsa-ca   # raíz de la TSA gratuita (freetsa.org)
.venv/bin/python cli.py demo     # genera, firma, registra y verifica un documento
.venv/bin/uvicorn confianza.api:app --reload   # portal en http://localhost:8000
.venv/bin/python -m pytest       # tests sin red
```

`cli.py demo --sin-tsa` funciona sin conexión (sin sello de tiempo ni LTV).

Para ver la firma en Acrobat con tilde verde con la PKI de prueba, instalá `pki/raiz/raiz.pem`
como certificado de confianza (Preferencias > Firmas > Identidades y certificados de confianza).
Con un certificado AATL real ese paso desaparece.

Validación independiente con la CLI oficial de pyHanko:

```bash
.venv/bin/pyhanko sign validate --trust pki/raiz/raiz.pem --trust pki/tsa_ca.pem --trust-replace \
  --other-certs pki/intermedia/intermedia.pem --pretty-print salida/EC-XXXX.pdf
```

## Despliegue en el VPS

Primero un chequeo de sólo lectura, para ver qué hay corriendo y que nada choque:

```bash
curl -fsSL https://raw.githubusercontent.com/emipampa/estacionamiento/RAMA/deploy/chequear_vps.sh | bash
```

Después, con un dominio apuntando a la IP y los puertos 80 y 443 abiertos:

```bash
curl -fsSL https://raw.githubusercontent.com/emipampa/estacionamiento/RAMA/deploy/instalar_vps.sh \
  | bash -s -- https://github.com/emipampa/estacionamiento.git verificar.tudominio.com.ar RAMA
```

El instalador instala Python y Caddy, clona el repo en `/opt/confianza`, crea el usuario de
servicio, genera `.env` y la PKI, y deja el portal como servicio systemd detrás de Caddy con
HTTPS automático. Está pensado para no romper nada existente: se detiene si nginx o apache ya
usan el 80/443, no pisa un Caddyfile existente (agrega el sitio en `/etc/caddy/sites/`), hace
copia de seguridad de lo que modifica y valida Caddy antes de recargarlo. Si el puerto 8000
está ocupado, correrlo con `PUERTO=8010` (u otro).

Archivos: `deploy/confianza.service`, `deploy/Caddyfile`, `deploy/env.ejemplo`.

Importante: `BASE_URL` en `.env` tiene que ser la URL pública final **antes** de generar la PKI,
porque queda impresa en los certificados (puntos de distribución de CRL) y en los QR.

## API

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/verificar/{id}` | Estado del documento (HTML, o JSON con `?formato=json`) |
| POST | `/verificar` | Sube un PDF, valida firmas y busca el hash en el registro |
| POST | `/documentos` | Sube un PDF, lo firma, lo registra y lo devuelve firmado |
| POST | `/documentos/{id}/revocar` | Marca el documento como revocado |
| GET | `/ca/raiz.pem` | Raíz de la PKI |
| GET | `/crl/{nombre}.crl` | CRLs (raiz, intermedia) |

Documentación interactiva en `/docs`.

## Estructura

```
confianza/config.py       rutas, URL pública, TSA (todo por variables de entorno)
confianza/firmador.py     firma PAdES, sello de tiempo, LTV; acá se enchufa el HSM
confianza/verificador.py  validación con pyHanko + cruce con el registro
confianza/registro.py     SQLite: documentos y eventos
confianza/documento.py    PDF de ejemplo con QR
confianza/api.py          portal FastAPI
scripts/setup_ca.sh       PKI de prueba (raíz, intermedia, sello, usuario, CRLs)
deploy/                   systemd, Caddy, instalador del VPS
```

## Qué cambia para producción

1. **Claves fuera de disco.** Reemplazar `cargar_firmante` por un firmante PKCS#11
   (token o HSM) o remoto contra la API del proveedor. pyHanko trae `PKCS11Signer`.
2. **Sello AATL de organización** (SSL.com, GlobalSign) para que Acrobat valide sin
   instalar nada, y **certificado de persona jurídica de la ONTI** para validez local.
   Las dos firmas conviven en el mismo PDF.
3. **TSA comercial** en vez de freetsa.org.
4. **Identidad del usuario** en el alta: DNI, selfie, validación contra RENAPER. Hoy hay
   un único `usuario.p12` de prueba; cada usuario real tiene que tener su certificado.
5. **Autenticación** en `/documentos` y `/revocar`. Hoy están abiertos.
6. **Evidencia independiente:** anclar el hash de cada documento en OpenTimestamps.
7. **Base de datos** Postgres en lugar de SQLite cuando haya más de un proceso escribiendo.
8. **Políticas escritas:** cómo se verifica identidad, custodia de claves, retención de evidencia.
   Es lo primero que pide un cliente grande o un juez.

## Marco legal (Argentina)

Con la PKI propia, las firmas de usuarios son *firma electrónica* según la Ley 25.506, no
*firma digital*: valen, pero la carga de la prueba es de la plataforma; por eso importan
el registro, el sello de tiempo y la evidencia. Para operar formalmente mirar la figura de
Prestador de Servicios de Confianza (Decreto 182/2019) y consultar con un abogado.
