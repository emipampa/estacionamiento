#!/usr/bin/env bash
# Chequeo de SOLO LECTURA antes de instalar. No cambia nada.
# Uso (como root en el VPS):  bash chequear_vps.sh
set -u
echo "== Sistema"; (. /etc/os-release && echo "$PRETTY_NAME"); uname -r; uptime
echo; echo "== Disco y memoria"; df -h / | tail -1; free -h | head -2
echo; echo "== Puertos escuchando (80, 443, 8000 son los que usa la plataforma)"
ss -ltnp 2>/dev/null | awk 'NR==1 || /:(80|443|8000|22|5565) /'
echo; echo "== Servidores web / proxies instalados"
for s in caddy nginx apache2 httpd traefik docker; do
  if command -v "$s" >/dev/null 2>&1; then printf "  %-8s instalado" "$s"; systemctl is-active --quiet "$s" 2>/dev/null && echo "  (ACTIVO)" || echo "  (inactivo)"; fi
done
[ -f /etc/caddy/Caddyfile ] && { echo; echo "== /etc/caddy/Caddyfile existente:"; sed 's/^/   /' /etc/caddy/Caddyfile; }
echo; echo "== Servicios systemd que podrían chocar"
systemctl list-units --type=service --state=running --no-legend 2>/dev/null | grep -Ei "confianza|caddy|nginx|apache|docker|uvicorn|gunicorn" || echo "  ninguno"
echo; echo "== Python"; python3 --version 2>&1; python3 -c "import venv" 2>/dev/null && echo "  venv ok" || echo "  FALTA python3-venv"
echo; echo "== Firewall"; (command -v ufw >/dev/null && ufw status | head -5) || echo "  ufw no instalado (revisar iptables/panel del proveedor)"
echo; echo "== Ya existe /opt/confianza?"; [ -d /opt/confianza ] && ls -la /opt/confianza | head || echo "  no"
