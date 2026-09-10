"""Portal de verificación y API de firma (FastAPI).

  GET  /                       página de inicio con formulario de verificación
  GET  /verificar/{id}         estado del documento (lo que abre el QR)
  POST /verificar              sube un PDF y devuelve el resultado de validación
  POST /documentos             sube un PDF, lo firma, lo registra y lo devuelve firmado
  POST /documentos/{id}/revocar
  GET  /crl/{nombre}.crl       CRLs de la PKI (para LTV y para Acrobat)
  GET  /ca/raiz.pem            raíz para instalar en Acrobat u otros validadores
  GET  /salud

Para producción: autenticación en /documentos, límites de tamaño, HTTPS con Caddy.
"""
import html
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from . import config, firmador, verificador
from .registro import Registro

app = FastAPI(title=config.NOMBRE_PLATAFORMA, docs_url="/docs")
MAX_BYTES = 20 * 1024 * 1024


def _registro() -> Registro:
    return Registro()


async def _leer_pdf(archivo: UploadFile) -> bytes:
    datos = await archivo.read()
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, "El archivo supera el máximo permitido")
    if not datos.startswith(b"%PDF"):
        raise HTTPException(400, "El archivo no es un PDF")
    return datos


ESTILO = """
<style>
 body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#222}
 .ok{color:#0a7a2f;font-weight:700}.mal{color:#b00020;font-weight:700}
 table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.4rem;text-align:left}
 code{background:#f4f4f4;padding:.1rem .3rem}
</style>
"""


def _pagina(titulo: str, cuerpo: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><title>{html.escape(titulo)}</title>{ESTILO}"
                        f"<h1>{html.escape(config.NOMBRE_PLATAFORMA)}</h1>{cuerpo}")


@app.get("/", response_class=HTMLResponse)
def inicio():
    return _pagina("Verificación", """
      <h2>Verificar un documento</h2>
      <form method="post" action="/verificar" enctype="multipart/form-data">
        <input type="file" name="archivo" accept="application/pdf" required>
        <button>Verificar</button>
      </form>
      <p>O escaneá el QR del documento. La raíz de nuestra PKI para instalar en Acrobat:
      <a href="/ca/raiz.pem">raiz.pem</a></p>""")


@app.get("/salud")
def salud():
    return {"ok": True, "plataforma": config.NOMBRE_PLATAFORMA}


@app.get("/ca/raiz.pem")
def raiz():
    return FileResponse(config.CERT_RAIZ, media_type="application/x-pem-file", filename="raiz.pem")


@app.get("/crl/{nombre}.crl")
def crl(nombre: str):
    ruta = config.CRL_DIR / f"{Path(nombre).name}.crl"
    if not ruta.exists():
        raise HTTPException(404)
    return Response(ruta.read_bytes(), media_type="application/pkix-crl")


@app.get("/verificar/{doc_id}")
def estado(doc_id: str, formato: str = "html"):
    reg = _registro()
    doc = reg.obtener(doc_id)
    if not doc:
        raise HTTPException(404, "Documento no registrado")
    datos = {"documento": doc, "eventos": reg.eventos(doc_id)}
    if formato == "json":
        return JSONResponse(datos)
    clase = "ok" if doc["estado"] == "vigente" else "mal"
    filas = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>" for k, v in doc.items())
    eventos = "".join(f"<li>{html.escape(e['momento'])} — {html.escape(e['tipo'])} {html.escape(e['detalle'] or '')}</li>"
                      for e in datos["eventos"])
    return _pagina(doc_id, f"""
      <h2>Documento {html.escape(doc_id)}: <span class="{clase}">{html.escape(doc['estado'].upper())}</span></h2>
      <table>{filas}</table>
      <h3>Historial</h3><ul>{eventos}</ul>
      <p>Para confirmar que el archivo que tenés es exactamente el registrado, subilo en
      <a href="/">la página de verificación</a>: se compara el hash SHA-256 y se validan las firmas.</p>""")


@app.post("/verificar")
async def verificar_archivo(archivo: UploadFile = File(...), formato: str = Form("html")):
    pdf = await _leer_pdf(archivo)
    # pyHanko usa asyncio.run internamente: hay que sacarlo del event loop del servidor.
    r = await run_in_threadpool(verificador.verificar, pdf, _registro())
    if formato == "json":
        return JSONResponse(r.como_dict())
    filas = "".join(
        f"<tr><td>{html.escape(f.campo)}</td><td>{html.escape(f.firmante)}</td>"
        f"<td class='{'ok' if f.integra else 'mal'}'>{'sí' if f.integra else 'NO'}</td>"
        f"<td class='{'ok' if f.confiable else 'mal'}'>{'sí' if f.confiable else 'NO'}</td>"
        f"<td>{f.sello_tiempo_valido}</td><td>{html.escape(f.nivel_modificacion or '')}</td></tr>"
        for f in r.firmas)
    registro = (f"<p>Registrado como <a href='/verificar/{r.registro['id']}'>{r.registro['id']}</a>, "
                f"estado <b>{html.escape(r.registro['estado'])}</b>.</p>") if r.registro else \
               "<p class='mal'>Este archivo no figura en nuestro registro.</p>"
    return _pagina("Resultado", f"""
      <h2>Resultado: <span class="{'ok' if r.valido else 'mal'}">{'VÁLIDO' if r.valido else 'NO VÁLIDO'}</span></h2>
      <p>SHA-256: <code>{r.hash_sha256}</code></p>
      <table><tr><th>Campo</th><th>Firmante</th><th>Íntegra</th><th>Confiable</th><th>Sello de tiempo</th><th>Modificaciones</th></tr>{filas}</table>
      {registro}<p><a href="/">Verificar otro</a></p>""")


@app.post("/documentos")
async def firmar_documento(archivo: UploadFile = File(...), titulo: str = Form(...), firmante: str = Form(...),
                           con_tsa: bool = Form(True)):
    pdf = await _leer_pdf(archivo)
    reg = _registro()
    doc_id = reg.crear(titulo, pdf, firmante)
    try:
        firmado = await run_in_threadpool(firmador.firmar_documento, pdf, config.USUARIO_P12,
                                          f"Firma de {firmante}", con_tsa)
    except Exception as e:  # noqa: BLE001
        reg.evento(doc_id, "error_firma", str(e))
        raise HTTPException(502, f"No se pudo firmar: {e}") from e
    reg.marcar_firmado(doc_id, firmado, detalle=f"tsa={'si' if con_tsa else 'no'}")
    return Response(firmado, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{doc_id}.pdf"', "X-Documento-Id": doc_id})


@app.post("/documentos/{doc_id}/revocar")
def revocar(doc_id: str, motivo: str = Form(...)):
    reg = _registro()
    if not reg.obtener(doc_id):
        raise HTTPException(404)
    reg.revocar(doc_id, motivo)
    return {"id": doc_id, "estado": "revocado"}
