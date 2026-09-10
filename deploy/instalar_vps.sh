#!/usr/bin/env bash
# Instalación en un VPS Debian/Ubuntu. Ejecutar como root:
#   bash deploy/instalar_vps.sh https://github.com/emipampa/estacionamiento.git verificar.tudominio.com.ar [rama]
#
# Diseñado para no romper lo que ya exista:
#  - se detiene si otro servidor web (nginx/apache) ya usa el puerto 80 o 443
#  - no pisa un Caddyfile existente: agrega el sitio en /etc/caddy/sites/
#  - hace copia de seguridad de todo archivo del sistema que modifica
#  - valida la configuración de Caddy antes de recargarla y la restaura si falla
#  - si el puerto 8000 está ocupado, usa otro (variable PUERTO)
set -euo pipefail
REPO="${1:?uso: instalar_vps.sh <url-repo> <dominio> [rama]}"
DOMINIO="${2:?uso: instalar_vps.sh <url-repo> <dominio> [rama]}"
RAMA="${3:-main}"
DEST=/opt/confianza
PUERTO="${PUERTO:-8000}"
SELLO=$(date +%Y%m%d-%H%M%S)

abortar() { echo "ERROR: $*" >&2; exit 1; }
respaldar() { [ -f "$1" ] && cp -a "$1" "$1.bak-$SELLO" && echo "  copia: $1.bak-$SELLO" || true; }
escucha() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q .; }
proceso_en() { ss -ltnpH "sport = :$1" 2>/dev/null | sed -n 's/.*users:(("\([^"]*\)".*/\1/p' | head -1; }

[ "$(id -u)" = 0 ] || abortar "ejecutar como root"
command -v apt-get >/dev/null || abortar "sólo Debian/Ubuntu"

echo "== Chequeos previos"
for p in 80 443; do
  if escucha "$p"; then
    quien=$(proceso_en "$p")
    [ "$quien" = caddy ] || abortar "el puerto $p ya lo usa '$quien'. No instalo Caddy encima. Configurá ese servidor como proxy a 127.0.0.1:$PUERTO o pedime que adapte el instalador."
  fi
done
if escucha "$PUERTO"; then
  quien=$(proceso_en "$PUERTO")
  if systemctl is-active --quiet confianza 2>/dev/null; then echo "  confianza ya corre en $PUERTO, se actualiza."
  else abortar "el puerto $PUERTO ya lo usa '$quien'. Volvé a correr con PUERTO=8010 (u otro libre)."; fi
fi
[ -d "$DEST" ] && [ ! -d "$DEST/.git" ] && abortar "$DEST existe y no es un clon del repo. Lo dejo como está."

echo "== Paquetes"
apt-get update -qq
apt-get install -y -qq python3 python3-venv git openssl curl gnupg apt-transport-https >/dev/null

if ! command -v caddy >/dev/null; then
  echo "== Instalando Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

echo "== Código en $DEST"
id -u confianza >/dev/null 2>&1 || useradd --system --home "$DEST" --shell /usr/sbin/nologin confianza
if [ ! -d "$DEST/.git" ]; then git clone -q --branch "$RAMA" "$REPO" "$DEST"; else git -C "$DEST" fetch -q origin "$RAMA" && git -C "$DEST" checkout -q "$RAMA" && git -C "$DEST" pull -q origin "$RAMA"; fi
cd "$DEST"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
mkdir -p datos salida

if [ ! -f .env ]; then
  sed "s#https://verificar.tudominio.com.ar#https://$DOMINIO#" deploy/env.ejemplo > .env
  sed -i "s#cambiar-esta-clave#$(openssl rand -hex 16)#" .env
  chmod 600 .env
fi
set -a; . ./.env; set +a
if [ ! -d pki ]; then
  echo "== PKI de prueba"
  BASE_URL="$BASE_URL" PKI_PASS="$PKI_PASS" ./scripts/setup_ca.sh >/dev/null
  .venv/bin/python cli.py tsa-ca || echo "  aviso: no se pudo bajar la raíz de la TSA (sin internet saliente?); reintentar con: cli.py tsa-ca"
fi
chown -R confianza:confianza "$DEST"
chmod 700 pki/raiz

echo "== Servicio systemd"
respaldar /etc/systemd/system/confianza.service
sed "s#--port 8000#--port $PUERTO#" deploy/confianza.service > /etc/systemd/system/confianza.service
systemctl daemon-reload
systemctl enable -q confianza
systemctl restart confianza
sleep 2
curl -fsS "http://127.0.0.1:$PUERTO/salud" >/dev/null || { journalctl -u confianza -n 30 --no-pager; abortar "el servicio no respondió en 127.0.0.1:$PUERTO"; }
echo "  servicio ok en 127.0.0.1:$PUERTO"

echo "== Caddy"
mkdir -p /etc/caddy/sites /var/log/caddy
sed -e "s#verificar.tudominio.com.ar#$DOMINIO#" -e "s#127.0.0.1:8000#127.0.0.1:$PUERTO#" deploy/Caddyfile > /etc/caddy/sites/confianza.caddy
respaldar /etc/caddy/Caddyfile
if [ ! -s /etc/caddy/Caddyfile ]; then
  echo "import /etc/caddy/sites/*.caddy" > /etc/caddy/Caddyfile
elif ! grep -q "import /etc/caddy/sites/\*.caddy" /etc/caddy/Caddyfile; then
  # Caddyfile existente (el de fábrica u otros sitios): sólo agrego el import, no toco lo demás
  printf "\nimport /etc/caddy/sites/*.caddy\n" >> /etc/caddy/Caddyfile
fi
if caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
  systemctl enable -q caddy; systemctl reload caddy 2>/dev/null || systemctl restart caddy
else
  caddy validate --config /etc/caddy/Caddyfile || true
  [ -f "/etc/caddy/Caddyfile.bak-$SELLO" ] && cp -a "/etc/caddy/Caddyfile.bak-$SELLO" /etc/caddy/Caddyfile
  abortar "la configuración de Caddy no validó; restauré la anterior. El servicio confianza sigue en 127.0.0.1:$PUERTO."
fi

echo
echo "Listo."
echo "  Salud:    curl https://$DOMINIO/salud   (el certificado HTTPS tarda unos segundos la primera vez)"
echo "  Demo:     cd $DEST && sudo -u confianza .venv/bin/python cli.py demo"
echo "  Logs:     journalctl -u confianza -f"
echo "  Copias de seguridad de lo modificado: *.bak-$SELLO"
