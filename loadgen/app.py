"""Generador de carga.

Hace POST /pay al servicio payments en un loop con pausa aleatoria.
Esta instrumentado para que la traza en Zipkin empiece aqui
(loadgen -> payments -> inventory en una sola traza distribuida).
"""
import os
import random
import time

import requests

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "loadgen"
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
PAYMENTS_URL = os.getenv("PAYMENTS_URL", "http://localhost:5001")
INTERVAL_MAX = float(os.getenv("INTERVAL_MAX", "3"))

resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(provider)

RequestsInstrumentor().instrument()
tracer = trace.get_tracer(__name__)

PRODUCTS = ["pen", "book", "laptop"]


def main():
    print(f"loadgen -> {PAYMENTS_URL}/pay (cada 1-{INTERVAL_MAX}s)", flush=True)
    while True:
        product = random.choice(PRODUCTS)
        with tracer.start_as_current_span("generate-checkout") as span:
            span.set_attribute("cart.product", product)
            try:
                resp = requests.post(
                    f"{PAYMENTS_URL}/pay", params={"product": product}, timeout=5
                )
                print(f"POST /pay product={product} -> {resp.status_code}", flush=True)
            except requests.RequestException as exc:
                print(f"error llamando a payments: {exc}", flush=True)
        time.sleep(random.uniform(1, INTERVAL_MAX))


if __name__ == "__main__":
    main()
