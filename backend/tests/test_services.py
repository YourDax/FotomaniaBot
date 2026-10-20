"""Unit tests for pure helpers in app.services."""

import pytest

from app.models import Client
from app.services import (
    client_dict,
    contact_first_name,
    csv_safe,
    detect_header_row,
    normalized_header,
    render_message,
)


def _client(**overrides: object) -> Client:
    data = {"name": "Иван", "custom_fields": "{}"}
    data.update(overrides)
    return Client(**data)


def test_csv_safe_prefixes_spreadsheet_formulas():
    assert csv_safe("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert csv_safe("+7 999") == "'+7 999"
    assert csv_safe("-5") == "'-5"
    assert csv_safe("@user") == "'@user"


def test_csv_safe_keeps_ordinary_values_and_none():
    assert csv_safe("Иван") == "Иван"
    assert csv_safe(None) == ""
    assert csv_safe(0) == "0"


def test_render_message_substitutes_name_and_custom_fields():
    client = _client(custom_fields='{"school": "Школа 5"}')
    assert render_message("Здравствуйте, {name}! {school}", client) == "Здравствуйте, Иван! Школа 5"


def test_render_message_tolerates_broken_custom_fields_json():
    client = _client(custom_fields="{not json")
    assert render_message("Привет, {name}", client) == "Привет, Иван"


def test_render_message_keeps_unknown_placeholders():
    assert render_message("Привет, {unknown}", _client()) == "Привет, {unknown}"


def test_normalized_header_lowercases_and_drops_spaces():
    assert normalized_header("ФИО КР") == "фиокр"
    assert normalized_header("Телёфон") == "телефон"


def test_detect_header_row_finds_header_below_preamble():
    rows = [["", ""], ["Список класса"], ["Класс", "ФИО КР", "Телефон КР"]]
    assert detect_header_row(rows) == 2


def test_detect_header_row_defaults_to_first_row_without_keywords():
    assert detect_header_row([["Имя", "Заметка"], ["Иван", "нет"]]) == 0


def test_client_dict_parses_custom_fields_json():
    data = client_dict(_client(id=3, custom_fields='{"a": 1}', role="RK"))
    assert data["id"] == 3
    assert data["role"] == "RK"
    assert data["custom_fields"] == {"a": 1}


def test_client_dict_survives_invalid_custom_fields():
    assert client_dict(_client(custom_fields="oops"))["custom_fields"] == {}


def test_contact_first_name_drops_surname_and_adds_school_class_year():
    name = contact_first_name("KR", "Школа 5", "5А", "Иванов Иван Иванович", 2026)
    assert name == "КР Школа 5 5А - 2026 Иван Иванович"


def test_contact_first_name_keeps_name_and_patronymic_without_surname():
    name = contact_first_name("KR", "Школа 5", "5А", "Ольга Юрьевна", 2026)
    assert name == "КР Школа 5 5А - 2026 Ольга Юрьевна"


def test_contact_first_name_matches_approved_example():
    name = contact_first_name("RK", "М_36", "7Д", "Петрова Екатерина Ивановна", 2026)
    assert name == "РК М_36 7Д - 2026 Екатерина Ивановна"


def test_contact_first_name_uses_rk_prefix_for_parents():
    name = contact_first_name("RK", "Лицей 1", "1Б", "Петрова Анна", 2026)
    assert name == "РК Лицей 1 1Б - 2026 Анна"


def test_contact_first_name_requires_school_and_class():
    with pytest.raises(ValueError):
        contact_first_name("KR", "", "5А", "Иванов Иван", 2026)
    with pytest.raises(ValueError):
        contact_first_name("KR", "Школа 5", "  ", "Иванов Иван", 2026)


def test_contact_first_name_rejects_names_over_max_length():
    with pytest.raises(ValueError):
        contact_first_name("KR", "Ш" * 60, "5А", "Иванов Иван", 2026)


def test_contact_first_name_rejects_unknown_role():
    with pytest.raises(ValueError):
        contact_first_name("XX", "Школа 5", "5А", "Иванов Иван", 2026)
