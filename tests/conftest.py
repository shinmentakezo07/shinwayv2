import logging
import structlog


def pytest_configure(config):
    """Configure structlog to emit through stdlib logging so pytest's caplog works."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    logging.getLogger().setLevel(logging.DEBUG)
