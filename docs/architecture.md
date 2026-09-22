# Arquitectura y diagrama de conexiones

![Arquitectura](architecture.png)

## Vista general

Cinco contenedores en una sola red de docker compose (`demo-otel-python`):

| Contenedor | Imagen / build | Puertos publicados | Descripción |
|---|---|---|---|
| `loadgen` | `./loadgen` (python:3.12-slim) | — | Loop que hace `POST /pay` cada 1-3 s (`INTERVAL_MAX`) |
| `payments` | `./payments` (python:3.12-slim) | `5001` | API Flask de pagos; valida stock en `inventory` |
| `inventory` | `./inventory` (python:3.12-slim) | `5002` (interno) | API Flask de stock; simula errores y falta de stock |
| `otel-collector` | `otel/opentelemetry-collector:0.111.0` | `4317`, `4318` | Recibe OTLP y exporta a Zipkin (`batch` 2 s) |
| `zipkin` | `openzipkin/zipkin:2` | `9411` | Almacena y visualiza trazas |

## Conexiones

### Flujo de negocio (HTTP)

```
loadgen --POST /pay?product=X--> payments:5001 --GET /check?product=X--> inventory:5002
```

1. `loadgen` abre el span raíz `generate-checkout` y llama a `payments`.
2. `payments` (span `POST /pay`) ejecuta los spans hijos `validate-payment` → `check-stock` (llamada HTTP a `inventory`) → `charge-card`.
3. `inventory` (span `GET /check`) ejecuta `db-stock-lookup`.
4. El contexto de traza viaja en el header `traceparent` entre servicios.

Respuestas posibles de `POST /pay`:

| Código | Significado |
|---|---|
| `200` | Pago realizado (`status: paid`) |
| `409` | Sin stock en inventory |
| `502` | inventory respondió error (10% simulado) |

### Flujo de telemetría (OTLP)

```
loadgen ─┐
payments ┼-- OTLP gRPC :4317 --> otel-collector --Zipkin API v2--> zipkin:9411
inventory┘
```

- Los tres servicios Python exportan spans con `OTLPSpanExporter` a `http://otel-collector:4317` (`OTEL_EXPORTER_OTLP_ENDPOINT`).
- El collector aplica `batch` (2 s) y exporta a `http://zipkin:9411/api/v2/spans`; además loguea un resumen con el exporter `debug` (`docker compose logs -f otel-collector`).
- El usuario abre la UI de Zipkin (`:9411`) y consulta las trazas.

## Variables de entorno

| Servicio | Variable | Valor por defecto (compose) |
|---|---|---|
| payments / inventory / loadgen | `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` |
| payments | `INVENTORY_URL` | `http://inventory:5002` |
| loadgen | `PAYMENTS_URL` | `http://payments:5001` |
| loadgen | `INTERVAL_MAX` | `3` (segundos máx. entre pagos) |

## Accesos al levantar

| Recurso | Local | GitHub Codespaces |
|---|---|---|
| Zipkin UI (trazas) | http://localhost:9411 | `https://<codespace>-9411.app.github.dev` (pestaña **PORTS**) |
| Payments API | http://localhost:5001 | `https://<codespace>-5001.app.github.dev` |
| OTLP gRPC / HTTP | `localhost:4317` / `4318` | internos |

`./start.sh` detecta si corre en un Codespace e imprime las URLs correctas.

## Editar el diagrama

- Fuente editable: [architecture.drawio](architecture.drawio) (o abrir directamente `architecture.drawio.png` en draw.io, trae el XML embebido).
- Fuente Mermaid: [architecture.mmd](architecture.mmd). Regenerar:

  ```bash
  drawio -x -f xml -o docs/architecture.drawio docs/architecture.mmd
  drawio -x -f png -o docs/architecture.png docs/architecture.drawio
  ```
