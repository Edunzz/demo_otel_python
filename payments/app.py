"""Servicio payments (Flask + OpenTelemetry).

Recibe pagos en POST /pay y valida stock llamando al servicio inventory.
Exporta trazas OTLP gRPC al OpenTelemetry Collector.
"""
import os
import random
import time

import requests
from flask import Flask, jsonify, request

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "payments"
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://localhost:5002")

# --- OpenTelemetry: provider + exportador OTLP gRPC ---
resource = Resource.create({"service.name": SERVICE_NAME, "service.version": "1.0.0"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(provider)

app = Flask(__name__)
# Auto-instrumentacion: cada request HTTP entrante/saliente genera spans
# y propaga el contexto (traceparent) hacia inventory.
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

tracer = trace.get_tracer(__name__)

PRODUCTS = {"pen": 10.0, "book": 25.0, "laptop": 999.0}


@app.get("/health")
def health():
    return jsonify(status="ok", service=SERVICE_NAME)


@app.post("/pay")
def pay():
    product = request.args.get("product") or random.choice(list(PRODUCTS))
    amount = PRODUCTS[product]

    span = trace.get_current_span()
    span.set_attribute("payment.product", product)
    span.set_attribute("payment.amount", amount)

    # Simula validacion antifraude
    with tracer.start_as_current_span("validate-payment"):
        time.sleep(random.uniform(0.01, 0.08))

    # Llamada al servicio inventory (el contexto de la traza viaja en headers)
    with tracer.start_as_current_span("check-stock") as check_span:
        resp = requests.get(f"{INVENTORY_URL}/check", params={"product": product}, timeout=5)
        check_span.set_attribute("inventory.http_status", resp.status_code)

    if resp.status_code != 200:
        return jsonify(status="error", detail="inventory unavailable"), 502

    stock = resp.json()
    if not stock.get("available"):
        return jsonify(status="rejected", reason="out of stock", product=product), 409

    with tracer.start_as_current_span("charge-card"):
        time.sleep(random.uniform(0.02, 0.12))

    return jsonify(status="paid", product=product, amount=amount)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
