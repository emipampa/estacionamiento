#!/usr/bin/env python3
"""Línea de comandos del prototipo.

  python cli.py tsa-ca                  descarga el certificado raíz de la TSA (una vez)
  python cli.py demo [--sin-tsa]        genera, firma y verifica un documento de ejemplo
  python cli.py firmar entrada.pdf --titulo "..." --firmante "..." [--sin-tsa]
  python cli.py verificar archivo.pdf
  python cli.py revocar EC-XXXX --motivo "..."
"""
import argparse
import sys
import urllib.request
from pathlib import Path

from confianza import config, documento, firmador, verificador
from confianza.registro import Registro


def cmd_tsa_ca(_):
    url = "https://freetsa.org/files/cacert.pem"
    config.TSA_CA_PEM.parent.mkdir(parents=True, exist_ok=True)
    config.TSA_CA_PEM.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    print(f"Guardado {config.TSA_CA_PEM}")


def _firmar_y_registrar(pdf: bytes, titulo: str, firmante: str, con_tsa: bool) -> tuple[str, bytes]:
    reg = Registro()
    doc_id = reg.crear(titulo, pdf, firmante)
    firmado = firmador.firmar_documento(pdf, config.USUARIO_P12, razon_usuario=f"Firma de {firmante}", con_tsa=con_tsa)
    reg.marcar_firmado(doc_id, firmado, detalle=f"tsa={'si' if con_tsa else 'no'}")
    return doc_id, firmado


def cmd_demo(args):
    reg = Registro()
    doc_id = reg.crear("Certificado de garantía (DEMO)", b"", "Juan Perez")
    pdf = documento.pdf_ejemplo(
        doc_id,
        "Certificado de garantía",
        "El presente documento certifica que el firmante asume la garantía\n"
        "descripta a continuación, validada por la plataforma.\n\n"
        "Objeto: contrato de locación, calle Falsa 123.\nMonto: $ 1.000.000.\nVigencia: 12 meses.",
        "Juan Perez (DNI 12345678)",
    )
    firmado = firmador.firmar_documento(pdf, config.USUARIO_P12, "Acepto la garantía", con_tsa=not args.sin_tsa)
    reg.marcar_firmado(doc_id, firmado, detalle=f"tsa={'no' if args.sin_tsa else 'si'}")
    config.SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    destino = config.SALIDA_DIR / f"{doc_id}.pdf"
    destino.write_bytes(firmado)
    print(f"Documento {doc_id} firmado -> {destino}")
    print(f"Verificación pública: {config.BASE_URL}/verificar/{doc_id}\n")
    _imprimir(verificador.verificar(firmado, reg))


def cmd_firmar(args):
    pdf = Path(args.pdf).read_bytes()
    doc_id, firmado = _firmar_y_registrar(pdf, args.titulo, args.firmante, not args.sin_tsa)
    config.SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    destino = config.SALIDA_DIR / f"{doc_id}.pdf"
    destino.write_bytes(firmado)
    print(f"Documento {doc_id} firmado -> {destino}")


def cmd_verificar(args):
    _imprimir(verificador.verificar(Path(args.pdf).read_bytes(), Registro()))


def cmd_revocar(args):
    reg = Registro()
    if not reg.obtener(args.id):
        sys.exit(f"No existe {args.id}")
    reg.revocar(args.id, args.motivo)
    print(f"{args.id} revocado")


def _imprimir(r):
    print(f"SHA-256: {r.hash_sha256}")
    for f in r.firmas:
        estado = "OK" if (f.integra and f.confiable) else "FALLA"
        print(f"[{estado}] {f.campo}: {f.firmante} | íntegra={f.integra} confiable={f.confiable} "
              f"sello_tiempo={f.sello_tiempo_valido} modif={f.nivel_modificacion}")
        print("      " + f.resumen)
    for sd in r.sellos_documento:
        print(f"[{'OK' if sd['valido'] else 'FALLA'}] {sd['campo']}: sello de tiempo de documento {sd['momento']}")
    if r.registro:
        print(f"Registro: {r.registro['id']} estado={r.registro['estado']} firmado={r.registro['firmado']}")
    else:
        print("Registro: el documento NO figura en el registro de la plataforma")
    print("RESULTADO:", "VÁLIDO" if r.valido else "NO VÁLIDO")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tsa-ca").set_defaults(fn=cmd_tsa_ca)
    d = sub.add_parser("demo"); d.add_argument("--sin-tsa", action="store_true"); d.set_defaults(fn=cmd_demo)
    f = sub.add_parser("firmar"); f.add_argument("pdf"); f.add_argument("--titulo", required=True)
    f.add_argument("--firmante", required=True); f.add_argument("--sin-tsa", action="store_true"); f.set_defaults(fn=cmd_firmar)
    v = sub.add_parser("verificar"); v.add_argument("pdf"); v.set_defaults(fn=cmd_verificar)
    r = sub.add_parser("revocar"); r.add_argument("id"); r.add_argument("--motivo", required=True); r.set_defaults(fn=cmd_revocar)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
