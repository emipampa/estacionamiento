#!/usr/bin/env bash
# PKI de PRUEBA para desarrollo. Genera:
#   pki/raiz/          CA raíz (offline en producción)
#   pki/intermedia/    CA intermedia que emite los certificados operativos
#   pki/sello.p12      certificado de sello de la plataforma (persona jurídica)
#   pki/usuario.p12    certificado de un usuario firmante (persona física)
#   pki/crl/           CRLs que sirve el portal para LTV
#
# En producción la raíz se guarda fuera de línea y las claves operativas
# viven en un HSM. Este script sólo sirve para desarrollar el flujo.
set -euo pipefail

PKI="${PKI_DIR:-pki}"
BASE_URL="${BASE_URL:-http://localhost:8000}"
PASS="${PKI_PASS:-confianza}"
ORG="${ORG_NOMBRE:-Estudio de Confianza (PRUEBA)}"
DIAS_RAIZ=3650
DIAS_INTER=1825
DIAS_CERT=730

if [ -d "$PKI" ]; then
  echo "Ya existe $PKI. Borralo si querés regenerar la PKI de prueba." >&2
  exit 1
fi
mkdir -p "$PKI"/{raiz,intermedia,crl}

ext_file() {
  # $1 = archivo destino, $2 = tipo (ca|sello|usuario)
  local f="$1" tipo="$2"
  case "$tipo" in
    ca)
      cat > "$f" <<EOC
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid:always
crlDistributionPoints=URI:$BASE_URL/crl/raiz.crl
EOC
      ;;
    sello|usuario)
      cat > "$f" <<EOC
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,nonRepudiation
extendedKeyUsage=emailProtection,1.2.840.113583.1.1.5
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
crlDistributionPoints=URI:$BASE_URL/crl/intermedia.crl
EOC
      ;;
  esac
}

echo "== CA raíz"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out "$PKI/raiz/raiz.key" 2>/dev/null
openssl req -x509 -new -key "$PKI/raiz/raiz.key" -sha256 -days $DIAS_RAIZ \
  -subj "/C=AR/O=$ORG/CN=$ORG - CA Raiz" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" \
  -out "$PKI/raiz/raiz.pem"

echo "== CA intermedia"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$PKI/intermedia/intermedia.key" 2>/dev/null
openssl req -new -key "$PKI/intermedia/intermedia.key" -sha256 \
  -subj "/C=AR/O=$ORG/CN=$ORG - CA Intermedia" -out "$PKI/intermedia/intermedia.csr"
ext_file "$PKI/intermedia/ext.cnf" ca
openssl x509 -req -in "$PKI/intermedia/intermedia.csr" -CA "$PKI/raiz/raiz.pem" -CAkey "$PKI/raiz/raiz.key" \
  -CAcreateserial -days $DIAS_INTER -sha256 -extfile "$PKI/intermedia/ext.cnf" -out "$PKI/intermedia/intermedia.pem" 2>/dev/null
cat "$PKI/intermedia/intermedia.pem" "$PKI/raiz/raiz.pem" > "$PKI/cadena.pem"

emitir() {
  # $1 = nombre de archivo, $2 = tipo, $3 = subject
  local nombre="$1" tipo="$2" subj="$3"
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$PKI/$nombre.key" 2>/dev/null
  openssl req -new -key "$PKI/$nombre.key" -sha256 -subj "$subj" -out "$PKI/$nombre.csr"
  ext_file "$PKI/$nombre.ext.cnf" "$tipo"
  openssl x509 -req -in "$PKI/$nombre.csr" -CA "$PKI/intermedia/intermedia.pem" -CAkey "$PKI/intermedia/intermedia.key" \
    -CAcreateserial -days $DIAS_CERT -sha256 -extfile "$PKI/$nombre.ext.cnf" -out "$PKI/$nombre.pem" 2>/dev/null
  openssl pkcs12 -export -inkey "$PKI/$nombre.key" -in "$PKI/$nombre.pem" -certfile "$PKI/cadena.pem" \
    -passout "pass:$PASS" -out "$PKI/$nombre.p12"
  rm -f "$PKI/$nombre.csr" "$PKI/$nombre.ext.cnf"
}

echo "== Sello de la plataforma"
emitir sello sello "/C=AR/O=$ORG/CN=$ORG - Sello de plataforma"
echo "== Usuario de prueba"
emitir usuario usuario "/C=AR/O=$ORG/OU=Usuarios verificados/CN=Juan Perez/serialNumber=DNI 12345678"

echo "== CRLs (vacías)"
crl() {
  # $1 = nombre, $2 = cert, $3 = key
  local dir="$PKI/crl/.$1"
  mkdir -p "$dir"; : > "$dir/index.txt"; echo 01 > "$dir/crlnumber"
  cat > "$dir/ca.cnf" <<EOC
[ca]
default_ca=CA_default
[CA_default]
database=$dir/index.txt
crlnumber=$dir/crlnumber
default_md=sha256
default_crl_days=30
EOC
  openssl ca -config "$dir/ca.cnf" -gencrl -cert "$2" -keyfile "$3" -out "$PKI/crl/$1.crl.pem" 2>/dev/null
  openssl crl -in "$PKI/crl/$1.crl.pem" -outform DER -out "$PKI/crl/$1.crl"
}
crl raiz "$PKI/raiz/raiz.pem" "$PKI/raiz/raiz.key"
crl intermedia "$PKI/intermedia/intermedia.pem" "$PKI/intermedia/intermedia.key"

chmod 600 "$PKI"/raiz/raiz.key "$PKI"/intermedia/intermedia.key "$PKI"/*.key
echo
echo "PKI de prueba lista en $PKI/"
echo "  Raíz para instalar en Acrobat/otros:  $PKI/raiz/raiz.pem"
echo "  Sello de plataforma:                  $PKI/sello.p12   (clave: $PASS)"
echo "  Usuario de prueba:                    $PKI/usuario.p12 (clave: $PASS)"
