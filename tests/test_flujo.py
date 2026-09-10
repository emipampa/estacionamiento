"""Flujo completo sin red: PKI de prueba, firma sin TSA, verificación, alteración y portal."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def entorno(tmp_path_factory):
    base = tmp_path_factory.mktemp("confianza")
    pki, datos = base / "pki", base / "datos"
    subprocess.run([str(RAIZ / "scripts/setup_ca.sh")], check=True, env={**os.environ, "PKI_DIR": str(pki)},
                   stdout=subprocess.DEVNULL)
    os.environ.update({"PKI_DIR": str(pki), "DATOS_DIR": str(datos), "SALIDA_DIR": str(base / "salida"), "TSA_URL": ""})
    for m in [m for m in sys.modules if m.startswith("confianza")]:
        del sys.modules[m]
    return base


def test_firma_y_verificacion(entorno):
    from confianza import config, documento, firmador, verificador
    from confianza.registro import Registro

    reg = Registro()
    doc_id = reg.crear("Prueba", b"", "Juan Perez")
    pdf = documento.pdf_ejemplo(doc_id, "Prueba", "Cuerpo\nde prueba", "Juan Perez")
    firmado = firmador.firmar_documento(pdf, config.USUARIO_P12, "Prueba", con_tsa=False)
    reg.marcar_firmado(doc_id, firmado)

    r = verificador.verificar(firmado, reg)
    assert [f.campo for f in r.firmas] == ["FirmaUsuario", "SelloPlataforma"]
    assert all(f.integra and f.confiable for f in r.firmas)
    assert r.registro["id"] == doc_id and r.valido

    alterado = bytearray(firmado)
    i = alterado.find(b"stream\n") + 50
    alterado[i] = ord("A") if alterado[i] != ord("A") else ord("B")
    r2 = verificador.verificar(bytes(alterado), reg)
    assert not r2.valido and not any(f.integra for f in r2.firmas)

    reg.revocar(doc_id, "prueba")
    assert not verificador.verificar(firmado, reg).valido


def test_portal(entorno):
    from fastapi.testclient import TestClient

    from confianza import documento
    from confianza.api import app

    c = TestClient(app)
    assert c.get("/salud").json()["ok"]
    pdf = documento.pdf_ejemplo("EC-TEST", "Prueba", "Cuerpo", "Juan Perez")
    resp = c.post("/documentos", files={"archivo": ("a.pdf", pdf, "application/pdf")},
                  data={"titulo": "Prueba", "firmante": "Juan Perez", "con_tsa": "false"})
    assert resp.status_code == 200, resp.text
    doc_id = resp.headers["X-Documento-Id"]
    assert c.get(f"/verificar/{doc_id}?formato=json").json()["documento"]["estado"] == "vigente"
    ver = c.post("/verificar", files={"archivo": ("a.pdf", resp.content, "application/pdf")}, data={"formato": "json"}).json()
    assert ver["valido"] and len(ver["firmas"]) == 2
    assert c.get("/crl/intermedia.crl").status_code == 200
    assert c.get("/ca/raiz.pem").status_code == 200
    assert c.post(f"/documentos/{doc_id}/revocar", data={"motivo": "prueba"}).json()["estado"] == "revocado"
