"""Leitura, validação e limpeza dos CSVs (SPEC seções 2 e 8).

Lê só os campos necessários, nunca altera os arquivos e devolve avisos sobre
linhas descartadas. Dados inválidos de ``products`` interrompem a carga.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

NEEDED_COLUMNS = {
    "products": ["product_id", "product_name", "category_id", "supplier_id",
                 "cost", "quantity_on_hand", "reorder_level", "discontinued"],
    "categories": ["category_id", "category_name"],
    "suppliers": ["supplier_id", "supplier_name"],
    "orders": ["order_id", "order_date", "status"],
    "order_items": ["order_id", "product_id", "quantity"],
}
KNOWN_STATUSES = {"shipped", "processing", "pending", "cancelled"}


class DataError(Exception):
    """Dado de entrada que impede o cálculo (arquivo, coluna ou valor inválido)."""


@dataclass
class Tables:
    products: pd.DataFrame
    categories: pd.DataFrame
    suppliers: pd.DataFrame
    orders: pd.DataFrame
    order_items: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def _read(data_dir: Path, name: str) -> pd.DataFrame:
    path = Path(data_dir) / f"{name}.csv"
    if not path.is_file():
        raise DataError(f"Arquivo {name}.csv não encontrado em {data_dir}")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in NEEDED_COLUMNS[name] if c not in df.columns]
    if missing:
        raise DataError(f"{name}.csv: coluna(s) obrigatória(s) ausente(s): {', '.join(missing)}")
    return df[NEEDED_COLUMNS[name]].copy()


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.str.strip(), errors="coerce")


def _unique_int_key(df: pd.DataFrame, name: str, key: str) -> pd.DataFrame:
    ids = _numeric(df[key])
    if ids.isna().any() or (ids % 1 != 0).any():
        raise DataError(f"{name}.csv: {key} inválido ou ausente")
    df = df.assign(**{key: ids.astype("int64")})
    if df[key].duplicated().any():
        dup = int(df.loc[df[key].duplicated(), key].iloc[0])
        raise DataError(f"{name}.csv: {key} repetido ({key}={dup})")
    return df


def _clean_products(df: pd.DataFrame) -> pd.DataFrame:
    df = _unique_int_key(df, "products", "product_id")
    for col, integer in [("quantity_on_hand", True), ("reorder_level", True), ("cost", False)]:
        num = _numeric(df[col])
        bad = num.isna() | (num < 0)
        if integer:
            bad = bad | (num % 1 != 0)
        if bad.any():
            pid = int(df.loc[bad, "product_id"].iloc[0])
            raise DataError(f"products.csv: {col} ausente, inválido ou negativo (product_id={pid})")
        df[col] = num.astype("int64") if integer else num.astype("float64")
    flags = df["discontinued"].str.strip().str.lower().map({"true": True, "false": False})
    if flags.isna().any():
        pid = int(df.loc[flags.isna(), "product_id"].iloc[0])
        raise DataError(f"products.csv: discontinued deve ser true ou false (product_id={pid})")
    df["discontinued"] = flags.astype(bool)
    for col in ("category_id", "supplier_id"):
        df[col] = _numeric(df[col]).astype("Int64")
    return df


def _clean_orders(df: pd.DataFrame, warnings: list[str]) -> tuple[pd.DataFrame, set[int]]:
    ids = _numeric(df["order_id"])
    if ids.isna().any() or (ids % 1 != 0).any():
        raise DataError("orders.csv: order_id inválido ou ausente")
    df = df.assign(order_id=ids.astype("int64"))
    if df["order_id"].duplicated().any():
        dup = int(df.loc[df["order_id"].duplicated(), "order_id"].iloc[0])
        raise DataError(f"orders.csv: order_id repetido (order_id={dup})")
    raw_ids = set(df["order_id"])

    df["status"] = df["status"].str.strip().str.lower()
    bad_status = ~df["status"].isin(KNOWN_STATUSES)
    if bad_status.any():
        warnings.append(f"{int(bad_status.sum())} pedido(s) excluído(s) das vendas: status desconhecido ou ausente.")
    df = df[~bad_status]

    raw_dates = df["order_date"].str.strip()
    dates = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="coerce")
    br = pd.to_datetime(raw_dates, format="%d/%m/%Y", errors="coerce")
    dates = dates.fillna(br)
    bad_date = dates.isna()
    if bad_date.any():
        warnings.append(f"{int(bad_date.sum())} pedido(s) excluído(s) das vendas: data ilegível.")
    df = df.assign(order_date=dates)[~bad_date]
    return df.reset_index(drop=True), raw_ids


def _clean_items(df: pd.DataFrame, orders: pd.DataFrame, raw_order_ids: set[int],
                 product_ids: set[int], warnings: list[str]) -> pd.DataFrame:
    df = df.assign(order_id=_numeric(df["order_id"]), product_id=_numeric(df["product_id"]),
                   quantity=_numeric(df["quantity"]))
    no_order = ~df["order_id"].isin(raw_order_ids)
    if no_order.any():
        warnings.append(f"{int(no_order.sum())} item(ns) de pedido excluído(s): sem pedido correspondente.")
    df = df[~no_order]
    no_product = ~df["product_id"].isin(product_ids)
    if no_product.any():
        warnings.append(f"{int(no_product.sum())} item(ns) de pedido excluído(s): sem produto correspondente.")
    df = df[~no_product]
    bad_qty = df["quantity"].isna() | (df["quantity"] <= 0) | (df["quantity"] % 1 != 0)
    if bad_qty.any():
        warnings.append(f"{int(bad_qty.sum())} item(ns) de pedido excluído(s): quantidade ausente, não numérica ou menor ou igual a zero.")
    df = df[~bad_qty]
    # Itens de pedidos já excluídos (status ou data inválidos) saem sem novo aviso.
    df = df[df["order_id"].isin(set(orders["order_id"]))]
    return df.astype({"order_id": "int64", "product_id": "int64", "quantity": "int64"}).reset_index(drop=True)


def load_tables(data_dir: str | Path) -> Tables:
    """Carrega e limpa os cinco CSVs usados pelo painel."""
    data_dir = Path(data_dir)
    warnings: list[str] = []
    products = _clean_products(_read(data_dir, "products"))
    categories = _unique_int_key(_read(data_dir, "categories"), "categories", "category_id")
    suppliers = _unique_int_key(_read(data_dir, "suppliers"), "suppliers", "supplier_id")
    orders, raw_order_ids = _clean_orders(_read(data_dir, "orders"), warnings)
    items = _clean_items(_read(data_dir, "order_items"), orders, raw_order_ids,
                         set(products["product_id"]), warnings)

    no_cat = ~products["category_id"].isin(set(categories["category_id"]))
    if no_cat.any():
        warnings.append(f"{int(no_cat.sum())} produto(s) sem categoria correspondente (rotulados 'Sem categoria').")
    no_sup = ~products["supplier_id"].isin(set(suppliers["supplier_id"]))
    if no_sup.any():
        warnings.append(f"{int(no_sup.sum())} produto(s) sem fornecedor correspondente (rotulados 'Sem fornecedor').")
    return Tables(products, categories, suppliers, orders, items, warnings)
