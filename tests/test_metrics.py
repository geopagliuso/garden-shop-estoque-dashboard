"""Testes das regras de cálculo (SPEC seções 3 a 7 e 10). Escritos antes de garden_shop/metrics.py."""
import dataclasses

import pandas as pd
import pytest

from garden_shop.loader import DataError, load_tables
from garden_shop.metrics import (
    EFFECTIVE_STATUSES,
    apply_filters,
    build_product_view,
    classify_status,
    compute_kpis,
    counts_by,
    effective_sales,
    ratio_chart_data,
    replenishment_list,
    sales_period,
)


@pytest.fixture
def small(fixtures_dir):
    return load_tables(fixtures_dir)


@pytest.fixture
def original(raw_dir):
    return load_tables(raw_dir)


def _units(view):
    return dict(zip(view.product_id, view.units_sold))


# ---------- vendas efetivas (RN-02) ----------

def test_effective_sales_excludes_cancelled(small):
    assert small.order_items.quantity.sum() == 16          # com o cancelado seriam 16
    sales = effective_sales(small)
    assert sales.units_sold.sum() == 15                    # o pedido 17 (1 un.) fica de fora
    assert dict(zip(sales.product_id, sales.units_sold))[9] == 1


def test_status_filter_rejects_cancelled(small):
    with pytest.raises(ValueError, match="cancelled"):
        effective_sales(small, statuses=("shipped", "cancelled"))
    with pytest.raises(ValueError, match="cancelled"):
        build_product_view(small, statuses=("cancelled",))


def test_pending_and_processing_count_as_sales(small):
    assert EFFECTIVE_STATUSES == ("shipped", "processing", "pending")
    units = _units(build_product_view(small))
    assert units[9] == 1      # pedido 7 está pending
    assert units[4] == 5      # pedido 19 (2 un.) está processing
    only_shipped = build_product_view(small, statuses=("shipped",))
    assert only_shipped.units_sold.sum() == 12            # 5 + 3 + 4 + 0 + 0


# ---------- período x estoque (RN-01) ----------

def test_period_filter_only_changes_sales(small):
    full = build_product_view(small)
    june = build_product_view(small, start=pd.Timestamp("2024-06-01"), end=pd.Timestamp("2024-06-30"))
    assert june.units_sold.sum() == 4                      # pedido 18 (2) + pedido 19 (2)
    for col in ["quantity_on_hand", "stock_value", "needs_reorder", "status", "reorder_cost"]:
        pd.testing.assert_series_equal(full[col], june[col])


def test_period_endpoints_are_inclusive(small):
    day = pd.Timestamp("2024-06-05")
    v = build_product_view(small, start=day, end=day)
    assert _units(v)[1] == 2


def test_period_without_sales_is_valid(small):
    v = build_product_view(small, start=pd.Timestamp("2025-01-01"), end=pd.Timestamp("2025-01-31"))
    assert v.units_sold.sum() == 0
    assert v.coverage.isna().all()
    assert compute_kpis(apply_filters(v))["stock_value"] == pytest.approx(494.5)


def test_sales_period_helper(small, original):
    assert sales_period(original) == (pd.Timestamp("2024-01-15"), pd.Timestamp("2024-06-14"))
    empty = dataclasses.replace(small, orders=small.orders.iloc[0:0], order_items=small.order_items.iloc[0:0])
    assert sales_period(empty) == (None, None)


# ---------- sem duplicação (RN-07) ----------

def test_product_view_one_row_per_product_no_duplication(small):
    v = build_product_view(small)
    assert len(v) == len(small.products) == 6
    assert v.product_id.is_unique
    fig = v.loc[v.product_id == 1].iloc[0]
    assert (small.order_items.product_id == 1).sum() == 4   # 4 itens de pedido para o produto 1
    assert fig.stock_value == pytest.approx(14 * 18)        # 252, e não 4 x 252
    assert v.stock_value.sum() == pytest.approx(526.5)


def test_duplicated_dimension_key_is_rejected(small):
    dup = pd.concat([small.categories, small.categories.iloc[[0]]], ignore_index=True)
    with pytest.raises(DataError, match="duplic"):
        build_product_view(dataclasses.replace(small, categories=dup))


# ---------- indicadores no recorte pequeno, conferidos à mão (CA-01) ----------

def test_stock_value_fixture_hand_calculated(small):
    scoped = apply_filters(build_product_view(small))
    expected = 14 * 18.00 + 8 * 5.00 + 5 * 0.90 + 18 * 11.00 + 0 * 6.00     # = 494,50
    assert compute_kpis(scoped)["stock_value"] == pytest.approx(expected)
    assert expected == pytest.approx(494.5)


def test_units_sold_fixture_hand_calculated(small):
    scoped = apply_filters(build_product_view(small))
    expected = (1 + 1 + 2 + 1) + (3 + 2) + 4 + 1 + 0                          # = 15
    assert compute_kpis(scoped)["units_sold"] == expected == 15


def test_kpis_fixture_default(small):
    k = compute_kpis(apply_filters(build_product_view(small)))
    assert k["n_products"] == 5
    assert k["n_to_reorder"] == 3
    assert k["n_zero"] == 1
    assert k["reorder_cost"] == pytest.approx((12 - 8) * 5 + (40 - 5) * 0.9 + (10 - 0) * 6)   # 111,50


def test_include_discontinued_changes_scope_value_and_sales_only(small):
    k = compute_kpis(apply_filters(build_product_view(small), include_discontinued=True))
    assert k["n_products"] == 6
    assert k["stock_value"] == pytest.approx(526.5)
    assert k["units_sold"] == 15
    assert k["n_to_reorder"] == 3 and k["n_zero"] == 1
    assert k["reorder_cost"] == pytest.approx(111.5)


# ---------- descontinuados (RN-03) ----------

def test_discontinued_never_recommended(small):
    v = build_product_view(small)
    bird = v.loc[v.product_id == 24].iloc[0]
    assert bird.status == "Descontinuado" and not bird.needs_reorder and bird.units_to_reorder == 0
    for include in (False, True):
        names = replenishment_list(apply_filters(v, include_discontinued=include)).product_name.tolist()
        assert "Bird Feeder" not in names


def test_discontinued_with_zero_stock_is_not_counted_as_zero(small):
    products = small.products.copy()
    products.loc[products.product_id == 24, "quantity_on_hand"] = 0
    v = build_product_view(dataclasses.replace(small, products=products))
    k = compute_kpis(apply_filters(v, include_discontinued=True))
    assert k["n_zero"] == 1 and k["n_to_reorder"] == 3


# ---------- situação (RN-04) ----------

@pytest.mark.parametrize("stock,point,disc,expected", [
    (0, 10, False, "Zerado"),
    (4, 10, False, "Crítico"),
    (5, 10, False, "Abaixo do ponto"),    # exatamente 50% não é crítico
    (9, 10, False, "Abaixo do ponto"),
    (10, 10, False, "Adequado"),          # igual ao ponto não precisa repor
    (4, 6, True, "Descontinuado"),
    (3, 0, False, "Adequado"),
    (0, 0, False, "Zerado"),
])
def test_situation_thresholds(stock, point, disc, expected):
    assert classify_status(stock, point, disc) == expected


def test_situation_in_view(small):
    v = build_product_view(small)
    assert dict(zip(v.product_id, v.status)) == {
        1: "Adequado", 4: "Abaixo do ponto", 7: "Crítico", 9: "Adequado", 14: "Zerado", 24: "Descontinuado",
    }


def test_zero_stock_with_zero_point_is_zero_but_not_reorder(small):
    products = small.products.copy()
    products.loc[products.product_id == 1, ["quantity_on_hand", "reorder_level"]] = 0
    v = build_product_view(dataclasses.replace(small, products=products))
    row = v.loc[v.product_id == 1].iloc[0]
    assert row.status == "Zerado" and not row.needs_reorder and pd.isna(row.ratio)


# ---------- reposição, prioridade, cobertura (RN-05, RN-08, RN-09) ----------

def test_replenishment_quantities_and_cost(small):
    lst = replenishment_list(apply_filters(build_product_view(small))).set_index("product_name")
    assert lst.loc["Pothos 'Golden'", "units_to_reorder"] == 4
    assert lst.loc["Tomato Seeds 'Roma'", "units_to_reorder"] == 35
    assert lst.loc["Hanging Basket", "reorder_cost"] == pytest.approx(60)


def test_priority_order(small):
    lst = replenishment_list(apply_filters(build_product_view(small)))
    assert lst.product_name.tolist() == ["Hanging Basket", "Tomato Seeds 'Roma'", "Pothos 'Golden'"]


def test_priority_tie_breaks_by_sales_then_name(small):
    products = small.products.iloc[:3].copy()
    products["product_id"] = [1, 2, 3]
    products["product_name"] = ["Zeta", "Beta", "Alfa"]
    products["quantity_on_hand"] = 2
    products["reorder_level"] = 10
    products["discontinued"] = False
    items = pd.DataFrame({"order_id": [10, 10, 18, 18, 24], "product_id": [1, 2, 3, 3, 1], "quantity": [1, 3, 2, 1, 0]})
    items = items[items.quantity > 0]            # Zeta 1, Beta 3, Alfa 3
    t = dataclasses.replace(small, products=products, order_items=items)
    lst = replenishment_list(apply_filters(build_product_view(t)))
    assert lst.product_name.tolist() == ["Alfa", "Beta", "Zeta"]


def test_product_without_sales_has_empty_coverage(small):
    v = build_product_view(small).set_index("product_id")
    assert v.loc[14, "units_sold"] == 0 and pd.isna(v.loc[14, "coverage"])
    assert v.loc[7, "coverage"] == pytest.approx(5 / 4)
    assert "Hanging Basket" in replenishment_list(apply_filters(build_product_view(small))).product_name.tolist()


# ---------- filtros (RF-03, RF-08) ----------

def test_filters_without_results_do_not_fail(small):
    v = build_product_view(small)
    scoped = apply_filters(v, categories=["Tools"], suppliers=["Terra Pots Co"])
    assert scoped.empty
    k = compute_kpis(scoped)
    assert all(k[key] == 0 for key in ["n_products", "n_to_reorder", "n_zero", "stock_value", "reorder_cost", "units_sold"])
    assert replenishment_list(scoped).empty
    assert ratio_chart_data(scoped).empty
    assert counts_by(scoped, "category_name").empty


def test_empty_filter_lists_mean_all_and_filters_combine_with_and(small):
    v = build_product_view(small)
    assert len(apply_filters(v, categories=[], suppliers=None, situations=[])) == 5
    assert apply_filters(v, categories=["Houseplants"]).product_id.tolist() == [1, 4]
    assert apply_filters(v, categories=["Houseplants"], suppliers=["SunGrow Nurseries"]).product_id.tolist() == [4]
    assert apply_filters(v, situations=["Zerado"]).product_name.tolist() == ["Hanging Basket"]


def test_missing_category_and_supplier_get_labels(small):
    products = small.products.copy()
    products.loc[products.product_id == 9, "category_id"] = 99
    products.loc[products.product_id == 1, "supplier_id"] = 99
    v = build_product_view(dataclasses.replace(small, products=products)).set_index("product_id")
    assert v.loc[9, "category_name"] == "Sem categoria"
    assert v.loc[1, "supplier_name"] == "Sem fornecedor"
    assert len(v) == 6


# ---------- gráficos ----------

def test_counts_by_category_and_supplier(small):
    scoped = apply_filters(build_product_view(small))
    cat = counts_by(scoped, "category_name")
    assert dict(zip(cat.category_name, cat["count"])) == {"Houseplants": 1, "Seeds & Bulbs": 1, "Pots & Planters": 1}
    sup = counts_by(scoped, "supplier_name")
    assert dict(zip(sup.supplier_name, sup["count"])) == {"SunGrow Nurseries": 1, "Bloomfield Seeds": 1, "Terra Pots Co": 1}


def test_ratio_chart_data_orders_active_products_by_ratio(small):
    data = ratio_chart_data(apply_filters(build_product_view(small), include_discontinued=True), n=3)
    assert data.product_name.tolist() == ["Hanging Basket", "Tomato Seeds 'Roma'", "Pothos 'Golden'"]
    assert "Bird Feeder" not in ratio_chart_data(apply_filters(build_product_view(small), include_discontinued=True)).product_name.tolist()


# ---------- dados originais (CA-01 a CA-07, CA-10, CA-11) ----------

def test_original_data_golden_values(original):
    view = build_product_view(original)
    k = compute_kpis(apply_filters(view))
    assert (k["n_products"], k["n_to_reorder"], k["n_zero"]) == (23, 5, 1)
    assert k["stock_value"] == pytest.approx(4731.0)
    assert k["reorder_cost"] == pytest.approx(152.0)
    assert k["units_sold"] == 86
    assert replenishment_list(apply_filters(view)).product_name.tolist() == [
        "Hanging Basket", "Tomato Seeds 'Roma'", "Hand Cultivator", "Orchid Food", "Pothos 'Golden'",
    ]
    with_disc = compute_kpis(apply_filters(view, include_discontinued=True))
    assert with_disc["n_products"] == 24 and with_disc["stock_value"] == pytest.approx(4763.0)
    assert with_disc["n_to_reorder"] == 5 and with_disc["reorder_cost"] == pytest.approx(152.0)
    assert _units(view)[9] == 1                                    # Pruning Shears: o pedido cancelado não conta
    assert view.loc[view.product_id == 1, "stock_value"].item() == pytest.approx(252.0)
    hanging = view.loc[view.product_name == "Hanging Basket"].iloc[0]
    assert hanging.units_sold == 0 and pd.isna(hanging.coverage)


def test_original_data_period_status_and_filters(original):
    june = build_product_view(original, start=pd.Timestamp("2024-06-01"), end=pd.Timestamp("2024-06-30"))
    k = compute_kpis(apply_filters(june))
    assert k["units_sold"] == 14 and k["stock_value"] == pytest.approx(4731.0) and k["n_to_reorder"] == 5
    shipped = compute_kpis(apply_filters(build_product_view(original, statuses=("shipped",))))
    assert shipped["units_sold"] == 65
    view = build_product_view(original)
    fert = compute_kpis(apply_filters(view, categories=["Fertilizer"]))
    assert fert["n_products"] == 2 and fert["n_to_reorder"] == 1
    assert apply_filters(view, categories=["Tools"], suppliers=["Terra Pots Co"]).empty
    jan = build_product_view(original, start=pd.Timestamp("2025-01-01"), end=pd.Timestamp("2025-01-31"))
    assert compute_kpis(apply_filters(jan))["units_sold"] == 0
