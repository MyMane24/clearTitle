import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import NoOpTracerProvider
from opentelemetry.instrumentation.celery import CeleryInstrumentor

_tracer_configured = False

def configure_tracing():
    global _tracer_configured
    if _tracer_configured:
        return
        
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            provider = TracerProvider()
            processor = SimpleSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            
            # Instrument Celery
            CeleryInstrumentor().instrument()
            _tracer_configured = True
        except Exception:
            # Fallback to no-op if grpc or otlp fails
            trace.set_tracer_provider(NoOpTracerProvider())
    else:
        trace.set_tracer_provider(NoOpTracerProvider())
    _tracer_configured = True

def get_tracer():
    return trace.get_tracer("cleartitle")
