#!/usr/bin/env bash
# Instalación en un VPS Debian/Ubuntu limpio. Ejecutar como root:
#   bash deploy/instalar_vps.sh https://github.com/emipampa/estacionamiento.git verificar.tudominio.com.ar
set -euo pipefail
REPO="${1:?uso: instalar_vps.sh <url-repo> <dominio>}"
DOMINIO="${2:?uso: instalar_vps.sh <url-repo> <dominio>}"
DEST=/opt/confianza

apt-get update -qq
apt-get install -y -qq python3 python3-venv git openssl debian-keyring debian-archive-keyring apt-transport-https curl >/dev/null

# Caddy (HTTPS automático)
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

id -u confianza >/dev/null 2>&1 || useradd --system --home "$DEST" --shell /usr/sbin/nologin confianza
if [ ! -d "$DEST/.git" ]; then git clone "$REPO" "$DEST"; else git -C "$DEST" pull; fi
cd "$DEST"
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
mkdir -p datos salida

if [ ! -f .env ]; then
  sed "s#https://verificar.tudominio.com.ar#https://$DOMINIO#" deploy/env.ejemplo > .env
  sed -i "s#cambiar-esta-clave#$(openssl rand -hex 16)#" .env
fi
set -a; . ./.env; set +a
if [ ! -d pki ]; then
  BASE_URL="$BASE_URL" PKI_PASS="$PKI_PASS" ./scripts/setup_ca.sh
  .venv/bin/python cli.py tsa-ca
fi
chown -R confianza:confianza "$DEST"
chmod 700 pki/raiz

cp deploy/confianza.service /etc/systemd/system/confianza.service
sed "s#verificar.tudominio.com.ar#$DOMINIO#" deploy/Caddyfile > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now confianza
systemctl reload caddy || systemctl restart caddy

echo
echo "Listo. Probá: curl https://$DOMINIO/salud"
echo "Demo:        cd $DEST && sudo -u confianza .venv/bin/python cli.py demo"
