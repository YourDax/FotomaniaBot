"""Unit tests for pure helpers in app.services."""

from app.models import Client
from app.services import (
    client_dict,
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
