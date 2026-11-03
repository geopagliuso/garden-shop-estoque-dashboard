"""Testes do app Streamlit (RF-02, RF-03, RF-08, CA-08, CA-12, CA-13). Escritos antes de app.py."""
from datetime import date

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import ROOT

APP = str(ROOT / "app.py")


def run_app(monkeypatch, data_dir):
    monkeypatch.setenv("GARDEN_SHOP_DATA_DIR", str(data_dir))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def kpis(at):
    return {m.label: m.value for m in at.metric}


def text_of(elements):
    return " ".join(e.value for e in elements)


def test_app_runs_with_default_filters_on_original_data(monkeypatch, raw_dir):
    at = run_app(monkeypatch, raw_dir)
    assert not at.exception
    assert kpis(at) == {
        "Produtos no escopo": "23",
        "Produtos a repor": "5",
        "Estoque zerado": "1",
        "Valor do estoque (custo)": "US$ 4.731,00",
        "Custo para repor": "US$ 152,00",
        "Unidades vendidas": "86",
    }


def test_app_values_on_small_fixture(monkeypatch, fixtures_dir):
    at = run_app(monkeypatch, fixtures_dir)
    assert not at.exception
    assert kpis(at) == {
        "Produtos no escopo": "5",
        "Produtos a repor": "3",
        "Estoque zerado": "1",
        "Valor do estoque (custo)": "US$ 494,50",
        "Custo para repor": "US$ 111,50",
        "Unidades vendidas": "15",
    }


def test_app_shows_empty_state_for_filters_without_results(monkeypatch, fixtures_dir):
    at = run_app(monkeypatch, fixtures_dir)
    at.sidebar.multiselect(key="f_categorias").select("Tools")
    at.sidebar.multiselect(key="f_fornecedores").select("Terra Pots Co")
    at.run()
    assert not at.exception
    assert "Nenhum produto encontrado para os filtros selecionados" in text_of(at.info)
    values = kpis(at)
    assert values["Produtos no escopo"] == "0" and values["Valor do estoque (custo)"] == "US$ 0,00"


def test_app_include_discontinued_changes_scope_and_value_only(monkeypatch, fixtures_dir):
    at = run_app(monkeypatch, fixtures_dir)
    at.sidebar.toggle(key="f_descontinuados").set_value(True).run()
    assert not at.exception
    values = kpis(at)
    assert values["Produtos no escopo"] == "6"
    assert values["Valor do estoque (custo)"] == "US$ 526,50"
    assert values["Produtos a repor"] == "3" and values["Custo para repor"] == "US$ 111,50"


def test_app_period_changes_only_sales(monkeypatch, fixtures_dir):
    at = run_app(monkeypatch, fixtures_dir)
    at.sidebar.date_input(key="f_inicio").set_value(date(2024, 6, 1)).run()
    assert not at.exception
    values = kpis(at)
    assert values["Unidades vendidas"] == "4"
    assert values["Valor do estoque (custo)"] == "US$ 494,50" and values["Produtos a repor"] == "3"


def test_app_status_filter_never_offers_cancelled(monkeypatch, fixtures_dir):
    at = run_app(monkeypatch, fixtures_dir)
    options = at.sidebar.multiselect(key="f_status").options
    assert "cancelled" not in options and set(options) == {"shipped", "processing", "pending"}
    at.sidebar.multiselect(key="f_status").unselect("processing").unselect("pending").run()
    assert kpis(at)["Unidades vendidas"] == "12"


def test_app_shows_data_quality_warnings(monkeypatch, tmp_data):
    items = pd.read_csv(tmp_data / "order_items.csv", dtype=str, keep_default_na=False)
    bad = pd.DataFrame([["901", "999", "1", "1", "1.00"]], columns=items.columns)
    pd.concat([items, bad]).to_csv(tmp_data / "order_items.csv", index=False)
    at = run_app(monkeypatch, tmp_data)
    assert not at.exception
    assert "sem pedido correspondente" in text_of(at.info)
    assert kpis(at)["Unidades vendidas"] == "15"


def test_app_shows_message_instead_of_crashing_on_invalid_products(monkeypatch, tmp_data):
    products = pd.read_csv(tmp_data / "products.csv", dtype=str, keep_default_na=False)
    products.loc[products.product_id == "7", "quantity_on_hand"] = "-3"
    products.to_csv(tmp_data / "products.csv", index=False)
    at = run_app(monkeypatch, tmp_data)
    assert not at.exception
    assert "products.csv" in text_of(at.warning) and "product_id=7" in text_of(at.warning)


def test_app_period_without_orders_shows_zero_sales_and_keeps_stock(monkeypatch, raw_dir):
    """CA-09: entre 03/02/2024 e 10/02/2024 não há pedidos na base original."""
    at = run_app(monkeypatch, raw_dir)
    at.sidebar.date_input(key="f_inicio").set_value(date(2024, 2, 3))
    at.sidebar.date_input(key="f_fim").set_value(date(2024, 2, 10)).run()
    assert not at.exception
    values = kpis(at)
    assert values["Unidades vendidas"] == "0"
    assert values["Valor do estoque (custo)"] == "US$ 4.731,00" and values["Produtos a repor"] == "5"


def test_app_warns_when_start_is_after_end(monkeypatch, fixtures_dir):
    at = run_app(monkeypatch, fixtures_dir)
    at.sidebar.date_input(key="f_inicio").set_value(date(2024, 6, 1))
    at.sidebar.date_input(key="f_fim").set_value(date(2024, 5, 1)).run()
    assert not at.exception
    assert "posterior" in text_of(at.warning)
