"""Fail-closed Gunicorn configuration for the public synthetic demo."""

import os

from app.web.deployment import WebDeploymentSettings


def _positive_int(name: str, default: int, *, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if not 1 <= value <= maximum:
        raise RuntimeError(f"{name} must be between 1 and {maximum}")
    return value


deployment = WebDeploymentSettings.from_environment()
if not deployment.public_demo:
    raise RuntimeError("Gunicorn production mode requires RIDE_WEB_MODE=public_demo")

bind = f"{deployment.host}:{deployment.port}"
workers = _positive_int("WEB_CONCURRENCY", 2, maximum=2)
threads = _positive_int("WEB_THREADS", 2, maximum=2)
worker_class = "gthread"
timeout = 30
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
capture_output = False
# The runtime image is intentionally read-only for the non-root application
# user. The optional Gunicorn control socket is not needed by this service and
# would otherwise try to create /app/.gunicorn/gunicorn.ctl.
control_socket_disable = True
limit_request_line = 4_094
limit_request_fields = 50
limit_request_field_size = 8_190
