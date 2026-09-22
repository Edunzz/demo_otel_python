"""Servicio inventory (Flask + OpenTelemetry).

Responde GET /check?product=X con disponibilidad de stock.
Exporta trazas OTLP gRPC al OpenTelemetry Collector.
"""
import os
import random
import time

from flask import Flask, jsonify, request

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "inventory"
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

resource = Resource.create({"service.name": SERVICE_NAME, "service.version": "1.0.0"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(provider)

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

tracer = trace.get_tracer(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok", service=SERVICE_NAME)


@app.get("/check")
def check():
    product = request.args.get("product", "unknown")
    span = trace.get_current_span()
    span.set_attribute("inventory.product", product)

    # Simula consulta a base de datos
    with tracer.start_as_current_span("db-stock-lookup"):
        time.sleep(random.uniform(0.02, 0.15))

    # ~10% de errores para poder ver trazas con error en Zipkin
    if random.random() < 0.10:
        return jsonify(error="db timeout"), 500

    # ~20% sin stock
    available = random.random() > 0.20
    return jsonify(product=product, available=available)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
