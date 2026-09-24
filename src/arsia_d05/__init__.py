"""Role D L5 trend query."""

from .trend import (
    QUERY_VERSION,
    TrendRequest,
    install_sql,
    query_trend,
)

__all__ = ["QUERY_VERSION", "TrendRequest", "install_sql", "query_trend"]
