"""Keep dependency diagnostics from exposing the document being parsed."""

import logging


def configure_sensitive_dependency_logging() -> None:
    """Suppress pypdf messages, which can include raw bytes from an upload."""

    parser_logger = logging.getLogger("pypdf")
    loggers = [parser_logger, *(
        logger for name, logger in logging.Logger.manager.loggerDict.items()
        if name.startswith("pypdf.") and isinstance(logger, logging.Logger)
    )]
    for logger in loggers:
        logger.propagate = False
        # An existing dependency handler must not bypass the privacy boundary.
        if len(logger.handlers) != 1 or not isinstance(logger.handlers[0], logging.NullHandler):
            logger.handlers[:] = [logging.NullHandler()]
