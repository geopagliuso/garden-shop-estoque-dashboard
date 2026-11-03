"""Dashboard de estoque e reposição da Garden Shop (Streamlit).

Só monta a tela: as regras de cálculo ficam em ``garden_shop/metrics.py``
(SPEC seção 9). Para executar: ``streamlit run app.py``.
"""
import os
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from garden_shop.loader import DataError, load_tables
from garden_shop.metrics import (
    EFFECTIVE_STATUSES,
    STATUS_ORDER,
    apply_filters,
    build_product_view,
    compute_kpis,
    counts_by,
    ratio_chart_data,
    replenishment_list,
    sales_period,
)

DATA_DIR = os.environ.get("GARDEN_SHOP_DATA_DIR", str(Path(__file__).parent / "data" / "raw"))
# Paleta sem vermelho (a cor vermelha é reservada às correções do professor).
STATUS_COLORS = {"Zerado": "#4A2C7A", "Crítico": "#D9660B", "Abaixo do ponto": "#E9A900",
                 "Adequado": "#2E7D5B", "Descontinuado": "#8A949D"}
BLUE = "#3B6EA5"

st.set_page_config(page_title="Estoque e Reposição – Garden Shop", layout="wide")
st.markdown("<style>[data-testid='stMetricValue']{font-size:1.8rem}</style>", unsafe_allow_html=True)


def brl_number(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def usd(value: float) -> str:
    return f"US$ {brl_number(value)}"


@st.cache_data(show_spinner=False)
def get_tables(data_dir: str):
    return load_tables(data_dir)


def ratio_chart(data):
    shown = data.iloc[::-1]
    fig = go.Figure(go.Bar(
        x=shown["ratio"].clip(upper=4) * 100, y=shown["product_name"], orientation="h",
        marker_color=[STATUS_COLORS[s] for s in shown["status"]],
        text=[f"{q} / {p} un" for q, p in zip(shown["quantity_on_hand"], shown["reorder_level"])],
        textposition="outside", cliponaxis=False,
        customdata=shown[["status"]], hovertemplate="%{y}<br>%{x:.0f}% do ponto<br>%{customdata[0]}<extra></extra>",
    ))
    fig.add_vline(x=100, line_dash="dash", line_color="#1F2933", opacity=0.6,
                  annotation_text="ponto de reposição (100%)", annotation_position="top")
    fig.update_layout(height=max(260, 30 * len(shown) + 90), margin=dict(l=0, r=60, t=30, b=30),
                      xaxis=dict(title="% do ponto de reposição (eixo limitado a 400%)", range=[0, 470]),
                      yaxis=dict(title=None), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
    return fig


def count_chart(df, column):
    shown = df.iloc[::-1]
    fig = go.Figure(go.Bar(x=shown["count"], y=shown[column], orientation="h", marker_color=BLUE,
                           text=shown["count"], textposition="outside", cliponaxis=False))
    fig.update_layout(height=max(150, 32 * len(shown) + 60), margin=dict(l=0, r=30, t=10, b=30),
                      xaxis=dict(title="Produtos a repor", dtick=1, rangemode="tozero"),
                      yaxis=dict(title=None), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
    return fig


def style_status(df):
    def color(value):
        bg = STATUS_COLORS.get(value, "#FFFFFF")
        fg = "#1F2933" if value == "Abaixo do ponto" else "#FFFFFF"
        return f"background-color: {bg}; color: {fg}; font-weight: 600"
    styled = df.style.map(color, subset=["Situação"])
    return styled


PT_COLUMNS = {
    "product_name": "Produto", "category_name": "Categoria", "supplier_name": "Fornecedor",
    "quantity_on_hand": "Estoque", "reorder_level": "Ponto", "units_sold": "Vendas (un)",
    "coverage": "Cobertura", "units_to_reorder": "A repor",
    "reorder_cost": "Custo est. (US$)", "status": "Situação", "cost": "Custo unitário (US$)",
    "stock_value": "Valor em estoque (US$)",
}
COLUMN_CONFIG = {
    "Custo est. (US$)": st.column_config.NumberColumn(format="%.2f"),
    "Custo unitário (US$)": st.column_config.NumberColumn(format="%.2f"),
    "Valor em estoque (US$)": st.column_config.NumberColumn(format="%.2f"),
}


def show_table(df, columns):
    shown = df[columns].rename(columns=PT_COLUMNS)
    cov = PT_COLUMNS["coverage"]
    if cov in shown.columns:  # produto sem vendas: cobertura vazia ("—"), nunca 0
        shown[cov] = shown[cov].map(lambda v: "—" if v != v else f"{v:.2f}")
    st.dataframe(style_status(shown), hide_index=True, width="stretch", column_config=COLUMN_CONFIG)


# ------------------------------------------------------------------ dados
st.title("Painel de Estoque e Reposição – Garden Shop")
try:
    tables = get_tables(DATA_DIR)
except DataError as err:
    st.warning(f"Não foi possível carregar os dados: {err}")
    st.stop()

if tables.warnings:
    with st.expander(f"Avisos de qualidade dos dados ({len(tables.warnings)})"):
        st.info("\n".join(f"- {w}" for w in tables.warnings))

# ------------------------------------------------------------------ filtros
first_day, last_day = sales_period(tables)
st.sidebar.header("Filtros")
st.sidebar.caption("O período e o status filtram **somente as vendas**. O estoque é sempre a posição atual.")
start = end = None
if first_day is not None:
    start = st.sidebar.date_input("Vendas a partir de", value=first_day.date(), min_value=first_day.date(),
                                  max_value=last_day.date(), key="f_inicio", format="DD/MM/YYYY")
    end = st.sidebar.date_input("Vendas até", value=last_day.date(), min_value=first_day.date(),
                                max_value=last_day.date(), key="f_fim", format="DD/MM/YYYY")
    if start > end:
        st.warning("A data inicial das vendas é posterior à data final. Ajuste o período.")
        st.stop()
statuses = st.sidebar.multiselect("Status dos pedidos nas vendas", list(EFFECTIVE_STATUSES),
                                  default=list(EFFECTIVE_STATUSES), key="f_status",
                                  help="Pedidos cancelled nunca contam como venda.")
include_discontinued = st.sidebar.toggle("Incluir descontinuados", value=False, key="f_descontinuados",
                                         help="Descontinuados entram no escopo, no valor e nas vendas, mas nunca na reposição.")

full_view = build_product_view(tables, statuses=statuses, start=start, end=end)
situations_available = [s for s in STATUS_ORDER if include_discontinued or s != "Descontinuado"]
categories = st.sidebar.multiselect("Categoria", sorted(full_view["category_name"].unique()),
                                    placeholder="Todas", key="f_categorias")
suppliers = st.sidebar.multiselect("Fornecedor", sorted(full_view["supplier_name"].unique()),
                                   placeholder="Todos", key="f_fornecedores")
situations = st.sidebar.multiselect("Situação do estoque", situations_available,
                                    placeholder="Todas", key="f_situacoes")
if not statuses:
    st.sidebar.caption("Nenhum status selecionado: as vendas aparecem zeradas.")

view = apply_filters(full_view, categories=categories, suppliers=suppliers, situations=situations,
                     include_discontinued=include_discontinued)

# ------------------------------------------------------------------ indicadores
k = compute_kpis(view)
cols = st.columns(6)
cols[0].metric("Produtos no escopo", f"{k['n_products']}")
cols[1].metric("Produtos a repor", f"{k['n_to_reorder']}", help="Produtos ativos com estoque abaixo do ponto de reposição.")
cols[2].metric("Estoque zerado", f"{k['n_zero']}")
cols[3].metric("Valor do estoque (custo)", usd(k["stock_value"]), help="Estoque atual × custo unitário.")
cols[4].metric("Custo para repor", usd(k["reorder_cost"]), help="Custo mínimo para voltar ao ponto de reposição.")
cols[5].metric("Unidades vendidas", f"{k['units_sold']}", help="Vendas efetivas no período e status selecionados.")

if view.empty:
    st.info("Nenhum produto encontrado para os filtros selecionados. Ajuste ou limpe os filtros.")
    st.stop()

# ------------------------------------------------------------------ visualizações
st.subheader("Lista de reposição prioritária")
st.caption("Ordem: Zerado, Crítico (< 50% do ponto), Abaixo do ponto. \"A repor\" é o mínimo para voltar ao ponto. "
           "Cobertura = estoque ÷ unidades vendidas no período (— quando não houve vendas).")
to_reorder = replenishment_list(view)
if to_reorder.empty:
    st.info("Nenhum produto ativo abaixo do ponto de reposição neste recorte.")
else:
    show_table(to_reorder, ["product_name", "category_name", "supplier_name", "quantity_on_hand",
                            "reorder_level", "units_sold", "coverage", "units_to_reorder",
                            "reorder_cost", "status"])

left, right = st.columns([1.1, 1])
with left:
    st.subheader("Estoque atual ÷ ponto de reposição")
    st.caption("Os 12 produtos ativos mais próximos da ruptura. A linha tracejada marca 100% do ponto.")
    chart_data = ratio_chart_data(view)
    if chart_data.empty:
        st.info("Nenhum produto ativo com ponto de reposição definido neste recorte.")
    else:
        st.plotly_chart(ratio_chart(chart_data), width="stretch")
with right:
    for column, title in [("category_name", "Produtos a repor por categoria"),
                          ("supplier_name", "Produtos a repor por fornecedor")]:
        st.subheader(title)
        counts = counts_by(view, column)
        if counts.empty:
            st.info("Nenhum produto a repor neste recorte.")
        else:
            st.plotly_chart(count_chart(counts, column), width="stretch")

with st.expander("Detalhe de todos os produtos do escopo"):
    detail = view.assign(_rank=view["status"].map({s: i for i, s in enumerate(STATUS_ORDER)}))
    detail = detail.sort_values(["_rank", "product_name"])
    show_table(detail, ["product_name", "category_name", "supplier_name", "quantity_on_hand", "reorder_level",
                        "cost", "stock_value", "units_sold", "coverage", "status"])

st.caption("Vendas efetivas = pedidos shipped, processing e pending (cancelled nunca conta). "
           "Produtos descontinuados nunca recebem recomendação de reposição.")
