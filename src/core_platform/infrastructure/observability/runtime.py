from __future__ import annotations

from dataclasses import dataclass

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from core_platform.infrastructure.observability.metrics import (
    InfrastructureMetrics,
    NoopInfrastructureMetrics,
    OpenTelemetryInfrastructureMetrics,
)
from core_platform.infrastructure.persistence.database import Database


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    enabled: bool
    service_name: str
    service_version: str
    environment: str
    otlp_endpoint: str
    trace_sample_ratio: float
    metric_export_interval_millis: int


class ObservabilityRuntime:
    """Owns OpenTelemetry providers and infrastructure instrumentation."""

    def __init__(
        self,
        config: ObservabilityConfig,
        *,
        span_exporter: SpanExporter | None = None,
        metric_reader: MetricReader | None = None,
    ) -> None:
        self._config = config
        self._tracer_provider: TracerProvider | None = None
        self._meter_provider: MeterProvider | None = None
        self._sqlalchemy_instrumentor: SQLAlchemyInstrumentor | None = None
        self._metrics: InfrastructureMetrics = NoopInfrastructureMetrics()
        self._shutdown = False

        if not config.enabled:
            return

        resource = Resource.create(
            {
                "service.name": config.service_name,
                "service.version": config.service_version,
                "deployment.environment.name": config.environment,
            }
        )

        tracer_provider = TracerProvider(
            resource=resource,
            sampler=ParentBased(TraceIdRatioBased(config.trace_sample_ratio)),
            shutdown_on_exit=False,
        )

        active_span_exporter = span_exporter
        if active_span_exporter is None:
            active_span_exporter = OTLPSpanExporter(
                endpoint=_signal_endpoint(config.otlp_endpoint, "v1/traces")
            )

        tracer_provider.add_span_processor(BatchSpanProcessor(active_span_exporter))

        active_metric_reader = metric_reader
        if active_metric_reader is None:
            active_metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=_signal_endpoint(config.otlp_endpoint, "v1/metrics")),
                export_interval_millis=config.metric_export_interval_millis,
            )

        meter_provider = MeterProvider(
            metric_readers=[active_metric_reader],
            resource=resource,
            shutdown_on_exit=False,
        )

        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._metrics = OpenTelemetryInfrastructureMetrics(meter_provider)

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def tracer_provider(self) -> TracerProvider | None:
        return self._tracer_provider

    @property
    def meter_provider(self) -> MeterProvider | None:
        return self._meter_provider

    @property
    def metrics(self) -> InfrastructureMetrics:
        return self._metrics

    def instrument_database(self, database: Database) -> None:
        if not self.enabled:
            return
        if self._shutdown:
            raise RuntimeError("Observability runtime is already shut down")
        if self._sqlalchemy_instrumentor is not None:
            raise RuntimeError("Database instrumentation is already installed")
        if self._tracer_provider is None or self._meter_provider is None:
            raise RuntimeError("Enabled observability runtime has no providers")

        instrumentor = SQLAlchemyInstrumentor()
        instrumentor.instrument(
            engine=database.instrumentation_engine,
            tracer_provider=self._tracer_provider,
            meter_provider=self._meter_provider,
        )
        self._sqlalchemy_instrumentor = instrumentor

        try:
            self._metrics.observe_database_pool(database)
        except BaseException:
            instrumentor.uninstrument()
            self._sqlalchemy_instrumentor = None
            raise

    def shutdown(self) -> None:
        if self._shutdown:
            return

        self._shutdown = True

        if self._sqlalchemy_instrumentor is not None:
            self._sqlalchemy_instrumentor.uninstrument()
            self._sqlalchemy_instrumentor = None

        if self._meter_provider is not None:
            self._meter_provider.shutdown()

        if self._tracer_provider is not None:
            self._tracer_provider.shutdown()


def _signal_endpoint(base_endpoint: str, signal_path: str) -> str:
    base = base_endpoint.rstrip("/")
    path = signal_path.lstrip("/")
    return f"{base}/{path}"
