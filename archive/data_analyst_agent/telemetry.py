"""OpenTelemetry instrumentation for data_analyst_agent."""
import os
from typing import Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.gcp.trace_exporter import CloudTraceSpanExporter
from opentelemetry.sdk.resources import Resource


def setup_telemetry(service_name: str = "data_analyst_agent") -> Optional[trace.Tracer]:
    """
    Set up OpenTelemetry tracing with GCP Cloud Trace exporter.
    
    Only activates if OTEL_ENABLED=true environment variable is set.
    
    Args:
        service_name: Service name for traces
    
    Returns:
        Tracer instance if enabled, None otherwise
    """
    if os.getenv("OTEL_ENABLED", "false").lower() != "true":
        return None
    
    # Create resource with service information
    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.getenv("APP_VERSION", "unknown")
    })
    
    provider = TracerProvider(resource=resource)
    
    # Use GCP Cloud Trace exporter (already installed)
    processor = BatchSpanProcessor(CloudTraceSpanExporter())
    provider.add_span_processor(processor)
    
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


# Default tracer instance (None if not enabled)
tracer = setup_telemetry()
