"""Результаты операций с MAX и общее исключение."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PreparationResult:
    status: str
    page_url: str
    client_name: str
    verified_text: str


class MaxBrowserError(RuntimeError):
    pass


@dataclass
class RenameResult:
    status: str
    page_url: str
    client_name: str
    first_name: str
