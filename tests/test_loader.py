"""Testes do carregador (RF-01, RN-10, CA-12, CA-13, CA-14). Escritos antes de garden_shop/loader.py."""
import hashlib

import pandas as pd
import pytest

from garden_shop.loader import DataError, load_tables


def _rewrite(path, fn):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    fn(df).to_csv(path, index=False)


def _append(path, rows):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    pd.concat([df, pd.DataFrame(rows, columns=df.columns)]).to_csv(path, index=False)


def test_load_original_csvs_columns_and_types(raw_dir):
    t = load_tables(raw_dir)
    assert list(t.products.columns) == [
        "product_id", "product_name", "category_id", "supplier_id",
        "cost", "quantity_on_hand", "reorder_level", "discontinued",
    ]
    assert list(t.categories.columns) == ["category_id", "category_name"]
    assert list(t.suppliers.columns) == ["supplier_id", "supplier_name"]
    assert list(t.orders.columns) == ["order_id", "order_date", "status"]
    assert list(t.order_items.columns) == ["order_id", "product_id", "quantity"]
    assert len(t.products) == 24 and len(t.orders) == 24 and len(t.order_items) == 48
    assert t.products["discontinued"].dtype == bool
    assert t.products.loc[t.products.product_id == 24, "discontinued"].item() is True
    assert pd.api.types.is_integer_dtype(t.products["quantity_on_hand"])
    assert pd.api.types.is_float_dtype(t.products["cost"])
    assert pd.api.types.is_datetime64_any_dtype(t.orders["order_date"])
    assert t.warnings == []


def test_loader_does_not_modify_raw_files(raw_dir):
    def digest():
        return {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in raw_dir.glob("*.csv")}

    before = digest()
    load_tables(raw_dir)
    assert digest() == before


def test_fixtures_are_a_slice_of_the_original_rows(raw_dir, fixtures_dir):
    """O recorte pequeno usado nos testes é feito de linhas originais, sem edição."""
    for name, key in [("products", "product_id"), ("orders", "order_id"), ("order_items", "order_item_id")]:
        raw = pd.read_csv(raw_dir / f"{name}.csv", dtype=str, keep_default_na=False).set_index(key)
        fix = pd.read_csv(fixtures_dir / f"{name}.csv", dtype=str, keep_default_na=False).set_index(key)
        assert fix.index.isin(raw.index).all()
        pd.testing.assert_frame_equal(fix, raw.loc[fix.index])


def test_missing_file_raises_data_error(tmp_data):
    (tmp_data / "orders.csv").unlink()
    with pytest.raises(DataError, match="orders.csv"):
        load_tables(tmp_data)


def test_missing_column_raises_data_error(tmp_data):
    _rewrite(tmp_data / "products.csv", lambda d: d.drop(columns=["quantity_on_hand"]))
    with pytest.raises(DataError, match="quantity_on_hand"):
        load_tables(tmp_data)


@pytest.mark.parametrize("field", ["quantity_on_hand", "reorder_level", "cost"])
@pytest.mark.parametrize("bad", ["", "-3", "abc"])
def test_invalid_product_numbers_raise_with_product_id(tmp_data, field, bad):
    def edit(d):
        d.loc[d.product_id == "7", field] = bad
        return d

    _rewrite(tmp_data / "products.csv", edit)
    with pytest.raises(DataError) as exc:
        load_tables(tmp_data)
    msg = str(exc.value)
    assert "products.csv" in msg and field in msg and "7" in msg


def test_duplicate_product_id_raises(tmp_data):
    _append(tmp_data / "products.csv", [["1", "Repetido", "1", "1", "1.00", "1.00", "1", "1", "false"]])
    with pytest.raises(DataError, match="product_id"):
        load_tables(tmp_data)


def test_invalid_discontinued_raises(tmp_data):
    def edit(d):
        d.loc[d.product_id == "9", "discontinued"] = "talvez"
        return d

    _rewrite(tmp_data / "products.csv", edit)
    with pytest.raises(DataError, match="discontinued"):
        load_tables(tmp_data)


def test_discontinued_accepts_any_case(tmp_data):
    def edit(d):
        d.loc[d.product_id == "24", "discontinued"] = "TRUE"
        d.loc[d.product_id == "1", "discontinued"] = "False"
        return d

    _rewrite(tmp_data / "products.csv", edit)
    t = load_tables(tmp_data)
    flags = dict(zip(t.products.product_id, t.products.discontinued))
    assert flags[24] is True and flags[1] is False


def test_orphan_and_invalid_items_are_dropped_with_warning(tmp_data):
    valid = len(pd.read_csv(tmp_data / "order_items.csv"))
    _append(tmp_data / "order_items.csv", [
        ["901", "999", "1", "1", "1.00"],   # pedido inexistente
        ["902", "5", "999", "1", "1.00"],   # produto inexistente
        ["903", "5", "4", "0", "1.00"],     # quantidade zero
        ["904", "5", "4", "", "1.00"],      # quantidade ausente
    ])
    t = load_tables(tmp_data)
    assert len(t.order_items) == valid
    text = " | ".join(t.warnings)
    assert "sem pedido" in text and "sem produto" in text and "quantidade" in text


def test_unknown_status_drops_order_and_its_items_with_one_warning(tmp_data):
    def edit(d):
        d.loc[d.order_id == "5", "status"] = "foo"
        d.loc[d.order_id == "7", "status"] = ""
        return d

    _rewrite(tmp_data / "orders.csv", edit)
    t = load_tables(tmp_data)
    assert 5 not in set(t.orders.order_id) and 7 not in set(t.orders.order_id)
    assert not t.order_items.order_id.isin([5, 7]).any()
    text = " | ".join(t.warnings)
    assert "status" in text and "sem pedido" not in text


def test_status_is_normalized(tmp_data):
    def edit(d):
        d.loc[d.order_id == "5", "status"] = "  Shipped "
        return d

    _rewrite(tmp_data / "orders.csv", edit)
    t = load_tables(tmp_data)
    assert t.orders.loc[t.orders.order_id == 5, "status"].item() == "shipped"


def test_dates_accept_iso_and_br_format_and_drop_unreadable(tmp_data):
    def edit(d):
        d.loc[d.order_id == "5", "order_date"] = "25/01/2024"
        d.loc[d.order_id == "7", "order_date"] = "xx"
        return d

    _rewrite(tmp_data / "orders.csv", edit)
    t = load_tables(tmp_data)
    assert t.orders.loc[t.orders.order_id == 5, "order_date"].item() == pd.Timestamp("2024-01-25")
    assert 7 not in set(t.orders.order_id)
    assert any("data" in w for w in t.warnings)


def test_unmatched_category_and_supplier_warn_but_keep_product(tmp_data):
    def edit(d):
        d.loc[d.product_id == "9", "category_id"] = "99"
        d.loc[d.product_id == "1", "supplier_id"] = "99"
        return d

    _rewrite(tmp_data / "products.csv", edit)
    t = load_tables(tmp_data)
    assert 9 in set(t.products.product_id) and 1 in set(t.products.product_id)
    text = " | ".join(t.warnings)
    assert "categoria" in text and "fornecedor" in text
