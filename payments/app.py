"""Servicio payments (Flask + OpenTelemetry).

Recibe pagos en POST /pay y valida stock llamando al servicio inventory.
Exporta trazas OTLP gRPC al OpenTelemetry Collector y métricas OTLP al Collector (que las reenvía a Grafana LGTM).
"""
import os
import random
import time

import requests
from flask import Flask, jsonify, request

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

SERVICE_NAME = "payments"
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://localhost:5002")

resource = Resource.create({"service.name": SERVICE_NAME, "service.version": "1.0.0"})

# --- Trazas: OTLP gRPC ---
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# --- Métricas: OTLP gRPC al Collector cada 10 s ---
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=OTLP_ENDPOINT, insecure=True),
    export_interval_millis=10_000,
)
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))
meter = metrics.get_meter(__name__)

PRODUCTS = {"pen": 10.0, "book": 25.0, "laptop": 999.0}
_start_time = time.time()
_simulated_stock = {p: 100 for p in PRODUCTS}

# 1) Counter (síncrono, solo sube): pagos procesados
payments_counter = meter.create_counter(
    "payments.processed", unit="{payment}", description="Pagos procesados por estado"
)

# 2) UpDownCounter (síncrono, sube y baja): pagos en curso
inflight_payments = meter.create_up_down_counter(
    "payments.inflight", unit="{payment}", description="Pagos en procesamiento"
)

# 3) Histogram (síncrono, distribución): monto de pagos
amount_histogram = meter.create_histogram(
    "payments.amount", unit="USD", description="Distribución de montos pagados"
)

# 4) Gauge (síncrono, último valor) - requiere opentelemetry-sdk >= 1.23
last_amount_gauge = meter.create_gauge(
    "payments.last_amount", unit="USD", description="Último monto procesado"
)


# 5) ObservableCounter (asíncrono, monotónico): uptime del servicio
def uptime_callback(options: CallbackOptions):
    yield Observation(time.time() - _start_time)

meter.create_observable_counter(
    "payments.uptime", callbacks=[uptime_callback], unit="s", description="Segundos activo"
)


# 6) ObservableUpDownCounter (asíncrono, sube y baja): stock simulado
def stock_callback(options: CallbackOptions):
    for product, qty in _simulated_stock.items():
        yield Observation(qty, {"payment.product": product})

meter.create_observable_up_down_counter(
    "payments.simulated_stock", callbacks=[stock_callback], unit="{item}",
    description="Stock simulado por producto",
)


# 7) ObservableGauge (asíncrono, valor instantáneo): carga simulada de CPU
def cpu_callback(options: CallbackOptions):
    yield Observation(random.uniform(0.1, 0.9))

meter.create_observable_gauge(
    "payments.cpu_load", callbacks=[cpu_callback], unit="1", description="Carga simulada"
)

app = Flask(__name__)
# Auto-instrumentación: cada request HTTP entrante/saliente genera spans
# y propaga el contexto (traceparent) hacia inventory.
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()


@app.get("/health")
def health():
    return jsonify(status="ok", service=SERVICE_NAME)


@app.post("/pay")
def pay():
    product = request.args.get("product") or random.choice(list(PRODUCTS))
    amount = PRODUCTS[product]
    attrs = {"payment.product": product}

    span = trace.get_current_span()
    span.set_attribute("payment.product", product)
    span.set_attribute("payment.amount", amount)

    inflight_payments.add(1, attrs)
    try:
        # Simula validación antifraude (falla 1 de cada 10)
        with tracer.start_as_current_span("validate-payment") as validation_span:
            time.sleep(random.uniform(0.01, 0.08))
            divisor = 0 if random.randint(1, 10) == 1 else 1
            try:
                _ = 1 / divisor
            except Exception as exc:
                validation_span.record_exception(exc)
                validation_span.set_status(
                    Status(StatusCode.ERROR, description=f"{type(exc).__name__}: {exc}")
                )
                validation_span.set_attribute(
                    "error.type", f"{type(exc).__module__}.{type(exc).__name__}"
                )
                payments_counter.add(1, {**attrs, "payment.status": "validation_error"})

        # Llamada al servicio inventory (el contexto viaja en headers)
        with tracer.start_as_current_span("check-stock") as check_span:
            resp = requests.get(f"{INVENTORY_URL}/check", params={"product": product}, timeout=5)
            check_span.set_attribute("inventory.http_status", resp.status_code)

        if resp.status_code != 200:
            payments_counter.add(1, {**attrs, "payment.status": "error"})
            return jsonify(status="error", detail="inventory unavailable"), 502

        stock = resp.json()
        if not stock.get("available"):
            status = "rejected"
            span.set_attribute("payment.status", status)
            payments_counter.add(1, {**attrs, "payment.status": status})
            return jsonify(status=status, reason="out of stock", product=product), 409

        with tracer.start_as_current_span("charge-card"):
            time.sleep(random.uniform(0.02, 0.12))

        status = "paid"
        span.set_attribute("payment.status", status)
        payments_counter.add(1, {**attrs, "payment.status": status})
        amount_histogram.record(amount, attrs)
        last_amount_gauge.set(amount, attrs)
        _simulated_stock[product] = max(0, _simulated_stock[product] - 1)
        return jsonify(status=status, product=product, amount=amount)
    finally:
        inflight_payments.add(-1, attrs)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
