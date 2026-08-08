import logging
import sys
from pythonjsonlogger import jsonlogger
from asgi_correlation_id import correlation_id


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)

        # Inject the Correlation ID into every single log line!
        req_id = correlation_id.get()
        if req_id:
            log_record["request_id"] = req_id

        log_record["level"] = record.levelname
        log_record["logger"] = record.name


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Clear any existing handlers (like Uvicorn's default text logger)
    logger.handlers = []

    handler = logging.StreamHandler(sys.stdout)

    # Format logs as JSON with timestamp
    formatter = CustomJsonFormatter(
        "%(timestamp)s %(level)s %(name)s %(message)s", timestamp=True
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    # Override Uvicorn's default loggers to use our JSON format
    logging.getLogger("uvicorn.access").handlers = [handler]
    logging.getLogger("uvicorn.error").handlers = [handler]
