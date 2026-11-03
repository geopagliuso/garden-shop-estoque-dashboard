# SPEC – Dashboard de Estoque e Reposição (Garden Shop)

**Autor:** George Pagliuso · **Versão:** 1.0 · **Requisitos:** `PRD.md` (RF, RN, CA)
Esta especificação é a referência viva do projeto. Quando uma descoberta mudar o comportamento esperado, atualize este arquivo e o `PRD.md` na mesma alteração (ver `AGENTS.md`).

---

## 1. Visão geral

```
CSVs (data/raw) ──► loader.load_tables ──► Tables (limpas, só campos usados, avisos)
                                             │
filtros da tela ──► metrics.build_product_view (vendas por produto → 1 linha por produto)
                       │
                       ├─► metrics.apply_filters ──► metrics.compute_kpis ──► indicadores
                       ├─► metrics.replenishment_list ──► lista de reposição
                       └─► metrics.counts_by ──► gráficos por categoria/fornecedor
                                             app.py (Streamlit) só monta a tela
```

## 2. Entradas

Os CSVs ficam em `data/raw/` (ou no diretório indicado por `GARDEN_SHOP_DATA_DIR`). Só os campos abaixo são lidos. Os demais são ignorados e os arquivos nunca são alterados (RF-01, CA-14).

| Tabela | Chave | Campos usados | Uso |
|---|---|---|---|
| `products` | `product_id` | `product_name`, `category_id`, `supplier_id`, `cost`, `quantity_on_hand`, `reorder_level`, `discontinued` | Estoque, ponto de reposição, custo, descontinuado |
| `categories` | `category_id` | `category_name` | Rótulo e filtro |
| `suppliers` | `supplier_id` | `supplier_name` | Rótulo e filtro |
| `orders` | `order_id` | `order_date`, `status` | Período e status da venda |
| `order_items` | `order_item_id` | `order_id`, `product_id`, `quantity` | Unidades vendidas |

**Relacionamentos:** `products.category_id → categories.category_id`; `products.supplier_id → suppliers.supplier_id`; `order_items.order_id → orders.order_id`; `order_items.product_id → products.product_id`.

**Não usados:** `customers` (inteira), `products.price`, `order_items.unit_price` e `order_items.order_item_id` (exceto como chave), `orders.customer_id`, `shipped_date`, `coupon_code`, `suppliers.contact_email`, `suppliers.state`. São exclusões do PRD (seção 4).

**Tipos após a leitura:** `discontinued` vira booleano (`true`/`false` sem diferenciar maiúsculas); `quantity_on_hand`, `reorder_level` e `quantity` viram inteiros; `cost` vira decimal; `order_date` vira data; `status` vira texto minúsculo sem espaços nas pontas.

## 3. Saídas

### 3.1 Indicadores (RF-02)

| Rótulo | Chave em `compute_kpis` | Fórmula | Considera descontinuados (chave ligada)? |
|---|---|---|---|
| Produtos no escopo | `n_products` | número de linhas do `view` filtrado | Sim |
| Produtos a repor | `n_to_reorder` | linhas com `needs_reorder = True` | Não (RN-03) |
| Estoque zerado | `n_zero` | linhas ativas com `status = "Zerado"` | Não |
| Valor do estoque a custo | `stock_value` | Σ `quantity_on_hand × cost` | Sim |
| Custo para repor | `reorder_cost` | Σ `reorder_cost` das linhas com `needs_reorder` | Não |
| Unidades vendidas (efetivas) | `units_sold` | Σ `units_sold` | Sim |

Em escopo vazio, todos os indicadores valem 0.

### 3.2 Colunas do `view` (uma linha por produto)

`product_id`, `product_name`, `category_name`, `supplier_name`, `cost`, `quantity_on_hand`, `reorder_level`, `discontinued`, `units_sold`, `stock_value`, `ratio`, `status`, `needs_reorder`, `units_to_reorder`, `reorder_cost`, `coverage`.

| Coluna | Fórmula |
|---|---|
| `units_sold` | Σ `quantity` dos itens de vendas efetivas do produto no período; 0 se não houver |
| `stock_value` | `quantity_on_hand × cost` |
| `ratio` | `quantity_on_hand ÷ reorder_level` se `reorder_level > 0`; vazio caso contrário |
| `status` | ver 5.1 |
| `needs_reorder` | `not discontinued` **e** `quantity_on_hand < reorder_level` |
| `units_to_reorder` | `reorder_level − quantity_on_hand` se `needs_reorder`; 0 caso contrário |
| `reorder_cost` | `units_to_reorder × cost` |
| `coverage` | `quantity_on_hand ÷ units_sold` se `units_sold > 0`; vazio caso contrário (RN-09) |

### 3.3 Visualizações (RF-04 a RF-07)

| Componente | Função | Dados |
|---|---|---|
| Lista de reposição prioritária | `replenishment_list(view)` | Linhas com `needs_reorder`, ordenadas por 5.2. Colunas: produto, categoria, fornecedor, estoque, ponto, unidades vendidas, cobertura, a repor, custo estimado, situação. |
| Gráfico estoque ÷ ponto | `ratio_chart_data(view, n=12)` | Produtos **ativos** com `ratio` definido, os 12 de menor `ratio`. Linha de referência em 100%. |
| Gráficos por categoria e por fornecedor | `counts_by(view, "category_name")` / `("supplier_name")` | Contagem de linhas com `needs_reorder`, por rótulo, em ordem decrescente. |
| Detalhe de produtos | `view` filtrado | Todas as linhas do escopo, ordenadas por situação e nome. |

## 4. Pipeline de cálculo

1. **Carregar** (`load_tables`): lê, valida e limpa os cinco CSVs. Descarta linhas inválidas de pedidos com aviso (seção 8).
2. **Vendas efetivas** (`effective_sales`): une `order_items` a `orders` por `order_id`; mantém `status` em `{shipped, processing, pending}` escolhidos na tela e `order_date` dentro do período (inclusive nas duas pontas); **agrupa por `product_id`** somando `quantity`.
3. **Visão de produtos** (`build_product_view`): parte de `products` (uma linha por produto), junta `categories` e `suppliers` por chave única, junta as vendas **já agregadas** (`left join`, ausentes viram 0) e calcula as colunas de 3.2.
4. **Filtros** (`apply_filters`): reduz o `view` por categoria, fornecedor, situação e chave de descontinuados (seção 6).
5. **Saídas**: `compute_kpis`, `replenishment_list`, `ratio_chart_data`, `counts_by`.

## 5. Regras

### 5.1 Situação do estoque (RN-03, RN-04)

Avaliada nesta ordem, na primeira condição verdadeira:

| # | Condição | `status` |
|---|---|---|
| 1 | `discontinued` | **Descontinuado** |
| 2 | `quantity_on_hand = 0` | **Zerado** |
| 3 | `reorder_level > 0` e `quantity_on_hand < 0,5 × reorder_level` | **Crítico** |
| 4 | `quantity_on_hand < reorder_level` | **Abaixo do ponto** |
| 5 | caso contrário | **Adequado** |

Casos de borda: estoque exatamente igual ao ponto → Adequado; estoque exatamente igual a 50% do ponto → Abaixo do ponto; `reorder_level = 0` e estoque > 0 → Adequado; `reorder_level = 0` e estoque 0 → Zerado, mas `needs_reorder = False` (0 < 0 é falso).

### 5.2 Regra de reposição e prioridade (RN-05, RN-08)

- Recomenda-se reposição quando `needs_reorder = True`. Produto descontinuado **nunca** é recomendado, qualquer que seja o estoque.
- Quantidade a repor = `reorder_level − quantity_on_hand` (mínimo para voltar ao ponto; não é lote de compra).
- Ordem da lista: `status` (Zerado, Crítico, Abaixo do ponto) → `ratio` crescente → `units_sold` decrescente → `product_name` crescente.

### 5.3 Vendas efetivas (RN-01, RN-02)

- `EFFECTIVE_STATUSES = ("shipped", "processing", "pending")`. `cancelled` nunca entra. Se `build_product_view` receber `cancelled` em `statuses`, levanta `ValueError`.
- O período filtra **só** `orders.order_date`. Nunca altera `quantity_on_hand`, `stock_value` nem `needs_reorder`.
- Sem filtro de período, usa todas as datas (menor a maior `order_date`).

## 6. Filtros e exclusões

| Filtro (tela) | Parâmetro | Padrão | Efeito |
|---|---|---|---|
| Período das vendas | `start`, `end` em `build_product_view` | menor e maior `order_date` | Só `units_sold` e `coverage` |
| Status dos pedidos | `statuses` em `build_product_view` | os três | Só `units_sold` e `coverage` |
| Categoria | `categories` em `apply_filters` | todas | Mantém só as categorias escolhidas |
| Fornecedor | `suppliers` em `apply_filters` | todos | Mantém só os fornecedores escolhidos |
| Situação do estoque | `situations` em `apply_filters` | todas | Mantém só as situações escolhidas |
| Incluir descontinuados | `include_discontinued` em `apply_filters` | `False` | Se falso, remove linhas com `discontinued = True` |

Lista vazia ou `None` em categoria, fornecedor ou situação significa "todos". Filtros combinam com **E**. Resultado vazio é válido e não gera erro (RF-08).

## 7. Prevenção de duplicações (RN-07)

- O `view` tem **exatamente uma linha por `product_id`** (verificado por teste). A junção com `categories` e `suppliers` é por chave única (`category_id`, `supplier_id`).
- `order_items` **nunca** é ligada diretamente a `products` antes de agregar. O passo 2 reduz `order_items` a uma linha por produto, e só então ocorre o `left join`.
- Se uma junção aumentar o número de linhas do `view` em relação a `products`, `build_product_view` levanta `DataError`.
- Efeito de errar: um produto com 3 itens de pedido (Fiddle-Leaf Fig) teria o estoque contado 3 vezes (US$ 756 em vez de US$ 252).

## 8. Erros e valores ausentes

| Situação | Comportamento |
|---|---|
| Arquivo CSV não encontrado | `DataError` com o nome do arquivo e o diretório procurado. |
| Coluna obrigatória ausente | `DataError` com o arquivo e a coluna. |
| `products`: `quantity_on_hand`, `reorder_level` ou `cost` ausente, não numérico ou negativo | `DataError` com arquivo, campo e `product_id`. |
| `products`: `product_id` repetido | `DataError`. |
| `products`: `category_id` ou `supplier_id` sem correspondência | Mantém o produto; rótulo "Sem categoria" ou "Sem fornecedor"; aviso. |
| `order_items`: `order_id` sem pedido | Linha excluída das vendas; aviso com a contagem. |
| `order_items`: `product_id` sem produto | Linha excluída; aviso. |
| `order_items`: `quantity` ausente, não numérica ou ≤ 0 | Linha excluída; aviso. |
| `orders`: `status` fora de {shipped, processing, pending, cancelled} (inclui vazio) | Pedido excluído das vendas; aviso. |
| `orders`: `order_date` ilegível | Pedido excluído das vendas; aviso. |
| `orders`: data em `DD/MM/AAAA` | Aceita. A leitura tenta `AAAA-MM-DD` e, nas linhas que falharem, `DD/MM/AAAA`. |
| `discontinued` fora de true/false | `DataError`. |
| Escopo vazio, período sem vendas, produto sem vendas | Resultado válido: zeros e cobertura vazia, sem exceção. |

Os avisos são uma lista de textos em `Tables.warnings` e aparecem no painel, em uma área informativa (RF-01, RF-08).

## 9. Módulos e responsabilidades

| Arquivo | Responsabilidade | Não deve |
|---|---|---|
| `garden_shop/loader.py` | Ler, validar e limpar CSVs; produzir `Tables` e avisos; `DataError`. | Calcular indicadores. |
| `garden_shop/metrics.py` | Vendas efetivas, `view`, situação, filtros, KPIs, listas e dados de gráficos. Funções puras sobre DataFrames. | Ler arquivos ou usar Streamlit. |
| `app.py` | Montar filtros, indicadores, gráficos e tabelas; mensagens de estado vazio; avisos. | Conter regra de cálculo. |
| `tests/` | Testes das regras e do app; `tests/fixtures/` é o recorte pequeno dos CSVs. | Alterar `data/raw/`. |

## 10. Exemplos com resultado esperado

### 10.1 Recorte pequeno dos CSVs (`tests/fixtures/`), conferido à mão

O recorte contém 6 produtos e os pedidos ligados a eles, tirados das linhas originais.

| product_id | Produto | Estoque | Ponto | Custo | Descontinuado |
|---|---|---|---|---|---|
| 1 | Fiddle-Leaf Fig | 14 | 10 | 18,00 | não |
| 4 | Pothos 'Golden' | 8 | 12 | 5,00 | não |
| 7 | Tomato Seeds 'Roma' | 5 | 40 | 0,90 | não |
| 9 | Pruning Shears | 18 | 8 | 11,00 | não |
| 14 | Hanging Basket | 0 | 10 | 6,00 | não |
| 24 | Bird Feeder | 4 | 6 | 8,00 | **sim** |

| Pedido | Status | Data | Item (produto × qtd) |
|---|---|---|---|
| 10 | shipped | 28/02/2024 | 1 × 1 |
| 18 | shipped | 05/06/2024 | 1 × 2 |
| 24 | shipped | 30/01/2024 | 1 × 1 |
| 5 | shipped | 25/01/2024 | 4 × 3 |
| 19 | processing | 14/06/2024 | 4 × 2 |
| 12 | shipped | 15/01/2024 | 7 × 4 |
| 7 | pending | 01/05/2024 | 9 × 1 |
| 17 | **cancelled** | 03/04/2024 | 9 × 1 |

**Cálculo à mão, filtros padrão (descontinuados desligados):**

| Indicador | Conta | Esperado |
|---|---|---|
| Produtos no escopo | 1, 4, 7, 9, 14 | **5** |
| Unidades vendidas | 1: 1+2+1 = 4; 4: 3+2 = 5; 7: 4; 9: 1 (o cancelado não conta); 14: 0 → 4+5+4+1+0 | **14** |
| Valor do estoque a custo | 14×18 + 8×5 + 5×0,9 + 18×11 + 0×6 = 252 + 40 + 4,5 + 198 + 0 | **494,50** |
| Produtos a repor | 4 (8<12), 7 (5<40), 14 (0<10); 1 e 9 estão acima do ponto | **3** |
| Estoque zerado | produto 14 | **1** |
| Custo para repor | 4: (12−8)×5 = 20; 7: (40−5)×0,9 = 31,5; 14: (10−0)×6 = 60 | **111,50** |

**Lista de reposição esperada:** 1º Hanging Basket (Zerado), 2º Tomato Seeds 'Roma' (Crítico, 5/40 = 12,5%), 3º Pothos 'Golden' (Abaixo do ponto, 8/12 = 66,7%). O Bird Feeder (4 < 6) **não** aparece por ser descontinuado.

**Variações:**

| Cenário | Esperado |
|---|---|
| Incluir descontinuados | Produtos no escopo **6**; valor do estoque **526,50** (494,50 + 4×8); a repor **3**; custo para repor **111,50**; unidades **14**. |
| Período 01/06/2024 a 30/06/2024 | Unidades **4** (pedido 18: 2 do produto 1; pedido 19: 2 do produto 4). Valor do estoque **494,50**; a repor **3**. |
| Só status `shipped` | Unidades **11** (4 + 3 + 4 + 0). |
| Contando o cancelado por engano | Unidades seriam 15. O teste garante 14. |
| Fornecedor "Terra Pots Co" e categoria "Tools" | Escopo vazio: todos os indicadores 0 e lista vazia. |
| Período 01/01/2025 a 31/01/2025 | Unidades **0**, cobertura vazia em todas as linhas; valor do estoque **494,50**. |
| Junção errada (itens × produtos) | O produto 1 teria estoque contado 3 vezes (756 em vez de 252). O teste garante 252. |

### 10.2 Dados originais (`data/raw/`), filtros padrão

| Indicador | Esperado |
|---|---|
| Produtos no escopo | 23 |
| Produtos a repor | 5 (Hanging Basket, Tomato Seeds 'Roma', Hand Cultivator, Orchid Food, Pothos 'Golden') |
| Estoque zerado | 1 |
| Valor do estoque a custo | 4.731,00 (4.763,00 com descontinuados) |
| Custo para repor | 152,00 |
| Unidades vendidas | 86 (87 se o cancelado fosse contado); só `shipped`: 65; junho/2024: 14 |

### 10.3 Situação por faixa (exemplos de `status`)

| Estoque | Ponto | Descontinuado | Status |
|---|---|---|---|
| 0 | 10 | não | Zerado |
| 4 | 10 | não | Crítico |
| 5 | 10 | não | Abaixo do ponto (5 = 50%, não é crítico) |
| 10 | 10 | não | Adequado |
| 4 | 6 | sim | Descontinuado |
| 3 | 0 | não | Adequado |
| 0 | 0 | não | Zerado (`needs_reorder = False`) |

## 11. Verificações (testes)

Cada regra tem pelo menos um teste automatizado, escrito **antes** da implementação. Rodar: `python -m pytest -q`.

| Verificação | Requisitos | Arquivo de teste |
|---|---|---|
| Leitura dos CSVs, tipos e campos usados | RF-01 | `tests/test_loader.py` |
| Arquivos de `data/raw/` não são alterados | CA-14 | `tests/test_loader.py` |
| Erros de carga em `products` e arquivo/coluna ausente | RN-10, CA-13 | `tests/test_loader.py` |
| Linhas inválidas de pedidos são excluídas com aviso | RN-10, CA-12 | `tests/test_loader.py` |
| Cancelado fora das vendas; pending e processing contam | RN-02, CA-04, CA-06 | `tests/test_metrics.py` |
| Período só altera vendas | RN-01, CA-05, CA-09 | `tests/test_metrics.py` |
| Uma linha por produto, sem duplicar estoque | RN-07, CA-11 | `tests/test_metrics.py` |
| Indicadores no recorte pequeno (valor do estoque, unidades, a repor) | RN-05, RN-06, CA-01 | `tests/test_metrics.py` |
| Descontinuados nunca são recomendados | RN-03, CA-02, CA-03 | `tests/test_metrics.py` |
| Faixas de situação e casos de borda | RN-04 | `tests/test_metrics.py` |
| Prioridade da lista | RN-08, CA-02 | `tests/test_metrics.py` |
| Produto sem vendas; filtros sem resultado | RN-09, CA-08, CA-10, RF-08 | `tests/test_metrics.py` |
| Valores esperados com os CSVs originais | CA-01 a CA-07 | `tests/test_metrics.py` |
| O app abre e mostra o estado vazio | RF-02, RF-08 | `tests/test_app.py` |

## 12. Decisões e descobertas

| Data | Decisão ou descoberta | Efeito |
|---|---|---|
| 02/11/2026 | `pending` e `processing` contam como venda efetiva; só `cancelled` sai. | RN-02. O filtro de status permite ver só `shipped`. |
| 02/11/2026 | Descontinuados entram em escopo, valor e vendas quando a chave está ligada, mas nunca na reposição. | RN-03. |
| 02/11/2026 | O dicionário diz `DD/MM/AAAA`, mas os CSVs usam `AAAA-MM-DD`. | A leitura aceita os dois (seção 8). |
