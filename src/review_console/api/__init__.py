"""Driving (inbound) HTTP adapter: the FastAPI app. Thin, translating requests into domain calls."""

from __future__ import annotations

from .app import app

__all__ = ["app"]
