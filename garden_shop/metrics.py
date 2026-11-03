"""Regras de cálculo do painel (SPEC seções 3 a 7). Funções puras sobre DataFrames.

Não lê arquivos e não usa Streamlit. A garantia de "uma linha por produto"
vem de agregar as vendas por produto antes de ligá-las a ``products``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from garden_shop.loader import DataError, Tables

EFFECTIVE_STATUSES = ("shipped", "processing", "pending")
STATUS_ORDER = ["Zerado", "Crítico", "Abaixo do ponto", "Adequado", "Descontinuado"]
VIEW_COLUMNS = [
    "product_id", "product_name", "category_name", "supplier_name", "cost",
    "quantity_on_hand", "reorder_level", "discontinued", "units_sold", "stock_value",
    "ratio", "status", "needs_reorder", "units_to_reorder", "reorder_cost", "coverage",
]
LIST_COLUMNS = [
    "product_id", "product_name", "category_name", "supplier_name", "quantity_on_hand",
    "reorder_level", "units_sold", "coverage", "units_to_reorder", "reorder_cost", "status",
]


def classify_status(quantity_on_hand: int, reorder_level: int, discontinued: bool) -> str:
    """Situação do estoque (SPEC 5.1)."""
    if discontinued:
        return "Descontinuado"
    if quantity_on_hand == 0:
        return "Zerado"
    if reorder_level > 0 and quantity_on_hand < 0.5 * reorder_level:
        return "Crítico"
    if quantity_on_hand < reorder_level:
        return "Abaixo do ponto"
    return "Adequado"


def _check_statuses(statuses) -> tuple[str, ...]:
    statuses = tuple(statuses)
    if "cancelled" in statuses:
        raise ValueError("Pedidos 'cancelled' não são vendas efetivas e não podem ser selecionados.")
    unknown = set(statuses) - set(EFFECTIVE_STATUSES)
    if unknown:
        raise ValueError(f"Status de pedido não permitido para vendas: {sorted(unknown)}")
    return statuses


def sales_period(tables: Tables) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Menor e maior ``order_date`` da base (padrão do filtro de período)."""
    dates = tables.orders["order_date"]
    if dates.empty:
        return None, None
    return dates.min(), dates.max()


def effective_sales(tables: Tables, statuses=EFFECTIVE_STATUSES, start=None, end=None) -> pd.DataFrame:
    """Unidades vendidas por produto (SPEC 4, passo 2): uma linha por ``product_id``."""
    statuses = _check_statuses(statuses)
    orders = tables.orders[tables.orders["status"].isin(statuses)]
    if orders["order_id"].duplicated().any():
        raise DataError("orders: order_id duplicado; a junção com order_items duplicaria vendas")
    if start is not None:
        orders = orders[orders["order_date"] >= pd.Timestamp(start)]
    if end is not None:
        orders = orders[orders["order_date"] <= pd.Timestamp(end)]
    merged = tables.order_items.merge(orders[["order_id"]], on="order_id", how="inner")
    sales = merged.groupby("product_id", as_index=False)["quantity"].sum()
    sales = sales.rename(columns={"quantity": "units_sold"})
    return sales.astype({"product_id": "int64", "units_sold": "int64"})


def _attach_label(base: pd.DataFrame, dim: pd.DataFrame, key: str, label: str, missing: str, table: str) -> pd.DataFrame:
    if dim[key].duplicated().any():
        raise DataError(f"chave duplicada em {table}: {key}")
    out = base.merge(dim[[key, label]], on=key, how="left")
    out[label] = out[label].fillna(missing)
    return out


def build_product_view(tables: Tables, statuses=EFFECTIVE_STATUSES, start=None, end=None) -> pd.DataFrame:
    """Uma linha por produto com vendas do período e indicadores de estoque (SPEC 3.2)."""
    sales = effective_sales(tables, statuses, start, end)
    view = tables.products.copy()
    view = _attach_label(view, tables.categories, "category_id", "category_name", "Sem categoria", "categories")
    view = _attach_label(view, tables.suppliers, "supplier_id", "supplier_name", "Sem fornecedor", "suppliers")
    view = view.merge(sales, on="product_id", how="left")
    if len(view) != len(tables.products):
        raise DataError("A junção alterou o número de produtos (possível duplicação de estoque)")
    view["units_sold"] = view["units_sold"].fillna(0).astype("int64")

    qty, point = view["quantity_on_hand"], view["reorder_level"]
    view["stock_value"] = qty * view["cost"]
    view["ratio"] = np.where(point > 0, qty / point.where(point > 0, 1), np.nan)
    view["status"] = [classify_status(q, p, d) for q, p, d in zip(qty, point, view["discontinued"])]
    view["needs_reorder"] = (~view["discontinued"]) & (qty < point)
    view["units_to_reorder"] = np.where(view["needs_reorder"], point - qty, 0).astype("int64")
    view["reorder_cost"] = view["units_to_reorder"] * view["cost"]
    view["coverage"] = np.where(view["units_sold"] > 0, qty / view["units_sold"].where(view["units_sold"] > 0, 1), np.nan)
    return view[VIEW_COLUMNS].reset_index(drop=True)


def apply_filters(view: pd.DataFrame, categories=None, suppliers=None, situations=None,
                  include_discontinued: bool = False) -> pd.DataFrame:
    """Filtros combinados com E; lista vazia ou ``None`` significa "todos" (SPEC 6)."""
    out = view
    if not include_discontinued:
        out = out[~out["discontinued"]]
    if categories:
        out = out[out["category_name"].isin(categories)]
    if suppliers:
        out = out[out["supplier_name"].isin(suppliers)]
    if situations:
        out = out[out["status"].isin(situations)]
    return out.reset_index(drop=True)


def compute_kpis(view: pd.DataFrame) -> dict:
    """Seis indicadores do painel (SPEC 3.1). Escopo vazio resulta em zeros."""
    active = view[~view["discontinued"]]
    return {
        "n_products": int(len(view)),
        "n_to_reorder": int(view["needs_reorder"].sum()),
        "n_zero": int((active["status"] == "Zerado").sum()),
        "stock_value": float(view["stock_value"].sum()),
        "reorder_cost": float(view["reorder_cost"].sum()),
        "units_sold": int(view["units_sold"].sum()),
    }


def replenishment_list(view: pd.DataFrame) -> pd.DataFrame:
    """Lista de reposição prioritária (SPEC 5.2)."""
    rows = view[view["needs_reorder"]].copy()
    rows["_rank"] = rows["status"].map({s: i for i, s in enumerate(STATUS_ORDER)})
    rows = rows.sort_values(["_rank", "ratio", "units_sold", "product_name"],
                            ascending=[True, True, False, True], na_position="last")
    return rows[LIST_COLUMNS].reset_index(drop=True)


def ratio_chart_data(view: pd.DataFrame, n: int = 12) -> pd.DataFrame:
    """Produtos ativos com menor razão estoque ÷ ponto (SPEC 3.3)."""
    rows = view[(~view["discontinued"]) & view["ratio"].notna()]
    rows = rows.sort_values(["ratio", "product_name"])
    return rows[["product_name", "quantity_on_hand", "reorder_level", "ratio", "status"]].head(n).reset_index(drop=True)


def counts_by(view: pd.DataFrame, column: str) -> pd.DataFrame:
    """Quantidade de produtos a repor por categoria ou fornecedor."""
    rows = view[view["needs_reorder"]]
    if rows.empty:
        return pd.DataFrame({column: pd.Series(dtype="object"), "count": pd.Series(dtype="int64")})
    out = rows.groupby(column).size().rename("count").reset_index()
    return out.sort_values(["count", column], ascending=[False, True]).reset_index(drop=True)
