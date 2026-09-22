#!/usr/bin/env bash
# Levanta la demo y muestra las URLs de acceso (local y GitHub Codespaces).
set -e

docker compose up --build -d

echo ""
echo "=============================================================="
echo " Demo OTel Python levantada. Servicios:"
echo "=============================================================="

if [ -n "$CODESPACE_NAME" ]; then
  DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  echo " Zipkin UI (trazas) : https://${CODESPACE_NAME}-9411.${DOMAIN}"
  echo " Payments API       : https://${CODESPACE_NAME}-5001.${DOMAIN}"
  echo ""
  echo " Tip: abre la pestana PORTS de VS Code y haz clic en el"
  echo " icono del globo junto al puerto 9411 para abrir Zipkin."
else
  echo " Zipkin UI (trazas) : http://localhost:9411"
  echo " Payments API       : http://localhost:5001"
fi

echo ""
echo " Probar un pago manual:"
echo "   curl -X POST http://localhost:5001/pay?product=book"
echo ""
echo " Ver logs:"
echo "   docker compose logs -f loadgen"
echo "   docker compose logs -f otel-collector"
echo "=============================================================="
