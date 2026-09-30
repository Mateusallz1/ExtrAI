import logging
from io import StringIO

import pytest

from doc_extractor_pydantic.privacy_logging import configure_sensitive_dependency_logging


@pytest.mark.parametrize("logger_name", ["pypdf", "pypdf._reader"])
def test_existing_dependency_handler_cannot_write_private_values(
    monkeypatch, caplog, logger_name
) -> None:
    output = StringIO()
    handler = logging.StreamHandler(output)
    logger = logging.getLogger(logger_name)
    monkeypatch.setattr(logger, "handlers", [handler])
    monkeypatch.setattr(logger, "propagate", True)
    configure_sensitive_dependency_logging()
    configure_sensitive_dependency_logging()
    logger.warning("SYNTHETIC_PRIVATE_VALUE")
    assert output.getvalue() == ""
    assert "SYNTHETIC_PRIVATE_VALUE" not in caplog.text
    assert len(logger.handlers) == 1
