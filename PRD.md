# PRD – Dashboard de Estoque e Reposição (Garden Shop)

**Autor:** George Pagliuso · **Versão:** 1.0 · **Continua:** proposta de dashboard da Aula 1
**Documentos relacionados:** `SPEC.md` (como calcular) e `AGENTS.md` (como trabalhar no repositório).

Os requisitos têm identificadores (RF, RN, CA) para serem referenciados na `SPEC.md` e nos testes.

---

## 1. Problema

A Garden Shop vende produtos de jardinagem pela internet. A equipe de gestão não consegue ver rapidamente quais produtos precisam de atenção: quais estão abaixo do nível de reposição, zerados ou muito baixos, qual o capital parado em estoque, o que vende e de qual fornecedor vem cada item. Hoje essa informação está espalhada em seis tabelas.

## 2. Usuário

| Usuário | O que decide com o painel |
|---|---|
| Responsável por compras/operação (principal) | O que repor, de qual fornecedor e em que ordem. |
| Gestão | Se o estoque está saudável e quanto capital está imobilizado. |

## 3. Objetivos

1. Mostrar, em uma tela, quais produtos **ativos** precisam de reposição e em que ordem de prioridade.
2. Informar o **custo mínimo estimado** para voltar ao nível de reposição e o **valor do estoque a custo**.
3. Relacionar os itens a repor com **categoria e fornecedor**.
4. Usar apenas **vendas efetivas** (pedidos cancelados não contam) e nunca recomendar reposição de produto **descontinuado**.

**Revisão de escopo em relação à proposta da Aula 1.** A proposta tinha mais gráficos (curva ABC, margem, cobertura em dias). Para a versão implementada foram mantidos só os componentes que a base sustenta e que respondem às perguntas da gestão. Ficaram de fora margem (`price`), receita (`unit_price`) e cobertura em dias, por não haver histórico de movimentação nem prazo de entrega (ver seção 5).

## 4. Escopo

**Dentro do escopo**

- Leitura dos CSVs `products`, `categories`, `suppliers`, `orders` e `order_items`, usando só os campos necessários (lista na `SPEC.md`, seção 2).
- Indicadores, filtros, uma lista priorizada, gráficos e uma tabela de detalhe (seção 6).
- Execução local com Streamlit. Não é preciso hospedar na internet.

**Fora do escopo (exclusões)**

| Exclusão | Motivo |
|---|---|
| Previsão de demanda, data prevista de ruptura, ponto de pedido dinâmico | Não há histórico de movimentação de estoque nem prazo de entrega dos fornecedores. |
| Receita, margem, cupons, dados de clientes (`customers`) | Não ajudam a decidir reposição. |
| Alterar, gravar ou corrigir os CSVs | Os dados originais devem ser preservados. |
| Criar pedidos de compra ou enviar e-mails | O painel apoia a decisão, não executa a compra. |

## 5. Premissas e limitações da base

- `quantity_on_hand` é a **posição atual** do estoque. Não há histórico de movimentação.
- Não há prazo de entrega dos fornecedores. A quantidade a repor é um **mínimo** para atingir `reorder_level`, não um lote de compra.
- As vendas cobrem pouco tempo (15/01/2024 a 14/06/2024, 24 pedidos). Rankings têm muitos empates e não servem para previsão.
- O dicionário de dados informa datas em `DD/MM/AAAA`, mas os CSVs usam `AAAA-MM-DD`. A leitura aceita os dois formatos (ver `SPEC.md`, seção 8).
- Não se sabe se `quantity_on_hand` já desconta pedidos ainda não enviados (`pending`, `processing`).

## 6. Indicadores, filtros e visualizações

### 6.1 Requisitos funcionais

| ID | Requisito | Utilidade para o negócio |
|---|---|---|
| **RF-01** | Carregar os cinco CSVs de `data/raw/` sem alterá-los e mostrar avisos de qualidade quando linhas forem descartadas. | Garante dados originais preservados e transparência sobre exclusões. |
| **RF-02** | Mostrar seis indicadores: **Produtos no escopo**, **Produtos a repor**, **Estoque zerado**, **Valor do estoque a custo**, **Custo para repor**, **Unidades vendidas (efetivas)**. | Resposta em segundos às perguntas da gestão. |
| **RF-03** | Oferecer filtros: **período das vendas**, **categoria**, **fornecedor**, **situação do estoque**, **status dos pedidos considerados** (shipped, processing, pending) e a chave **incluir descontinuados** (padrão: desligada). | Permite ao comprador recortar por quem ele negocia e por tipo de produto. |
| **RF-04** | Mostrar a **lista de reposição prioritária**: produtos ativos abaixo do ponto, ordenados por gravidade, com fornecedor, estoque/ponto, vendas, quantidade a repor e custo estimado. | É o que a equipe usa para agir. |
| **RF-05** | Mostrar um gráfico de barras **estoque atual ÷ ponto de reposição** (os 12 produtos ativos com menor razão), com linha em 100%. | Compara produtos de escalas diferentes em uma régua comum. |
| **RF-06** | Mostrar dois gráficos de barras: **produtos a repor por categoria** e **por fornecedor**. | Responde quais categorias e fornecedores concentram a reposição. |
| **RF-07** | Mostrar uma tabela de **detalhe de todos os produtos** do escopo, com a situação de cada um. | Permite conferir qualquer número do painel. |
| **RF-08** | Mostrar mensagens claras quando não houver dados (filtros sem resultado, produto sem vendas, período sem vendas). | Evita telas quebradas ou números enganosos. |

### 6.2 Regras de negócio

| ID | Regra |
|---|---|
| **RN-01** | O estoque é a posição atual (`quantity_on_hand`). **O filtro de período muda só as vendas**, nunca o estoque. A tela deve dizer isso. |
| **RN-02** | **Vendas efetivas** são os itens de pedidos com status `shipped`, `processing` ou `pending`. Pedidos `cancelled` nunca contam, e o filtro de status não oferece essa opção. *Decisão:* `pending` e `processing` contam porque são demanda já assumida pelo cliente. |
| **RN-03** | Produtos **descontinuados** nunca recebem recomendação de reposição: não entram em "Produtos a repor", "Estoque zerado", "Custo para repor", na lista de reposição nem nos gráficos de reposição. Com a chave ligada, aparecem nos indicadores de escopo, de valor e de vendas e na tabela de detalhe com a situação "Descontinuado". |
| **RN-04** | Situação do estoque de produto ativo: **Zerado** (estoque = 0); **Crítico** (0 < estoque < 50% do ponto); **Abaixo do ponto** (50% ≤ estoque < 100% do ponto); **Adequado** (estoque ≥ ponto). |
| **RN-05** | Um produto ativo **precisa de reposição** se `quantity_on_hand < reorder_level`. A quantidade a repor é `reorder_level − quantity_on_hand` e o custo estimado é essa quantidade × `cost`. |
| **RN-06** | O **valor do estoque** é `quantity_on_hand × cost`, somado nos produtos do escopo. Não usa preço de venda. |
| **RN-07** | **Sem duplicação.** As vendas são somadas por produto antes de serem ligadas a `products`. O estoque de um produto nunca é contado mais de uma vez, não importa quantos itens de pedido ele tenha. |
| **RN-08** | **Prioridade.** Ordem da lista: situação (Zerado, Crítico, Abaixo do ponto), depois menor razão estoque ÷ ponto, depois maior volume vendido, depois nome. |
| **RN-09** | Produto **sem vendas** no período tem 0 unidades vendidas, continua elegível à reposição e tem cobertura vazia (não é 0 nem infinito). |
| **RN-10** | Linhas inválidas das tabelas de pedidos (item sem pedido, item sem produto, quantidade ≤ 0, status desconhecido, data ilegível) são **excluídas das vendas com um aviso**. Dados inválidos de `products` (estoque, ponto ou custo ausente ou negativo, `product_id` repetido) **interrompem a carga** com erro claro. |

## 7. Critérios de aceitação

Cada critério é observável na tela ou nos testes. Os valores usam os CSVs originais em `data/raw/`, com os filtros no padrão (todas as categorias, todos os fornecedores, período completo, três status, descontinuados desligados), salvo indicação.

| ID | Cenário | Resultado esperado | Refs |
|---|---|---|---|
| **CA-01** | Abrir o painel com os filtros padrão. | Produtos no escopo = **23**; Produtos a repor = **5**; Estoque zerado = **1**; Valor do estoque a custo = **US$ 4.731,00**; Custo para repor = **US$ 152,00**; Unidades vendidas = **86**. | RF-02, RN-02, RN-05, RN-06 |
| **CA-02** | A lista de reposição com filtros padrão. | Cinco linhas, nesta ordem: Hanging Basket, Tomato Seeds 'Roma', Hand Cultivator, Orchid Food, Pothos 'Golden'. O Bird Feeder (descontinuado, 4/6) **não** aparece. | RF-04, RN-03, RN-08 |
| **CA-03** | Ligar "Incluir descontinuados". | Produtos no escopo = **24**; Valor do estoque = **US$ 4.763,00**; Produtos a repor continua **5**; Custo para repor continua **US$ 152,00**. O Bird Feeder aparece na tabela de detalhe como "Descontinuado". | RF-03, RN-03 |
| **CA-04** | Pedido cancelado. | O pedido 17 (1 Pruning Shears) não conta: Unidades vendidas = **86** (seriam 87 com o cancelado) e Pruning Shears = **1** unidade. | RN-02 |
| **CA-05** | Filtrar o período de 01/06/2024 a 30/06/2024. | Unidades vendidas = **14**. Valor do estoque continua **US$ 4.731,00** e Produtos a repor continua **5**. | RN-01 |
| **CA-06** | Considerar só o status `shipped`. | Unidades vendidas = **65**. | RF-03, RN-02 |
| **CA-07** | Filtrar categoria Fertilizer. | Produtos no escopo = **2**; Produtos a repor = **1** (Orchid Food). | RF-03 |
| **CA-08** | Filtrar categoria Tools e fornecedor Terra Pots Co (combinação sem produtos). | Painel mostra "Nenhum produto encontrado para os filtros selecionados". Indicadores de contagem e valores em zero. Sem erro. | RF-08 |
| **CA-09** | Período sem pedidos (ex.: 01/01/2025 a 31/01/2025). | Unidades vendidas = **0**; cobertura vazia para todos; nenhum erro. O estoque e a reposição não mudam. | RN-01, RN-09 |
| **CA-10** | Produto sem vendas (Hanging Basket). | Aparece na lista de reposição com 0 unidades vendidas e cobertura vazia. | RN-09 |
| **CA-11** | Relacionar produtos e itens de pedido. | O valor do estoque de qualquer produto com vários itens de pedido (ex.: Fiddle-Leaf Fig, 4 itens) é contado uma vez: 14 × US$ 18 = **US$ 252,00**. | RN-07 |
| **CA-12** | CSV com linhas inválidas (item sem pedido, quantidade 0, status desconhecido). | As linhas são excluídas das vendas e o painel mostra um aviso com a contagem. | RF-01, RN-10 |
| **CA-13** | CSV com `quantity_on_hand` ausente ou negativo. | A carga é interrompida com mensagem que indica o arquivo, o campo e o `product_id`. | RN-10 |
| **CA-14** | Verificar os CSVs depois de usar o painel. | Os arquivos de `data/raw/` não mudaram. | RF-01 |

## 8. Pontos em aberto

- Confirmar com o negócio se `quantity_on_hand` já desconta pedidos `pending` e `processing`.
- Confirmar se `reorder_level` considera o prazo de entrega de cada fornecedor.
