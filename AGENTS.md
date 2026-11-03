# AGENTS.md – Instruções para trabalhar neste repositório

**Autor:** George Pagliuso · Projeto: Dashboard de Estoque e Reposição da Garden Shop (Lista 02)

Este arquivo orienta qualquer agente de IA (ou pessoa) que altere o projeto. Leia as seções 1 a 3 antes de mexer em código.

---

## 1. O que é o projeto

Painel em Streamlit que mostra quais produtos ativos precisam de reposição, em que ordem, de qual fornecedor e com que custo mínimo, além do valor do estoque a custo. Usa só vendas efetivas (pedidos `cancelled` não contam) e nunca recomenda reposição de produto descontinuado.

## 2. Documentos a consultar (nesta ordem)

| Ordem | Arquivo | Quando consultar |
|---|---|---|
| 1 | `PRD.md` | Para saber **o quê** e **por quê**: requisitos (RF), regras de negócio (RN) e critérios de aceitação (CA). |
| 2 | `SPEC.md` | Para saber **como** calcular: tabelas, campos, fórmulas, filtros, tratamento de erros, exemplos com resultado esperado. É a referência viva. |
| 3 | `AGENTS.md` (este) | Para preparar o ambiente, rodar, testar e revisar. |
| 4 | `docs/print_dashboard.png` | Para ver o painel em execução com os dados originais. |

Regra: se o código e a `SPEC.md` divergirem, **pare e decida qual está certo**. Corrija o outro na mesma alteração. Não deixe a divergência para depois.

## 3. Preparar o ambiente

Requisito: Python 3.13 (versão em que tudo foi testado).

```bash
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
pip install -r requirements.txt
```

Dependências: `pandas`, `streamlit`, `plotly`, `pytest` (versões mínimas em `requirements.txt`).

## 4. Comandos

| Objetivo | Comando |
|---|---|
| Rodar todos os testes | `python -m pytest -q` |
| Rodar só os testes de regras de cálculo | `python -m pytest -q tests/test_metrics.py` |
| Rodar só o carregador | `python -m pytest -q tests/test_loader.py` |
| Rodar só o app (Streamlit `AppTest`) | `python -m pytest -q tests/test_app.py` |
| Executar o painel | `streamlit run app.py` (abre em `http://localhost:8501`) |
| Executar o painel sem abrir navegador, em outra porta | `python -m streamlit run app.py --server.headless true --server.port 8765` |
| Usar outra pasta de CSVs | `GARDEN_SHOP_DATA_DIR=/caminho/para/csvs streamlit run app.py` |
| Conferir que os dados originais não mudaram | `git status --short data/raw` (deve ficar vazio) |

### Comandos verificados e não verificados

| Comando ou situação | Estado |
|---|---|
| `pip install -r requirements.txt` em ambiente virtual novo (Python 3.13) | **Verificado** (instalou pandas 3.1.0, streamlit 1.66.1, plotly 7.1.0, pytest 9.2.0) |
| `python -m pytest -q` | **Verificado**: 68 testes passando com pandas 3.0.5 e 3.1.0, e com pandas 2.2.3 (streamlit 1.66.1 nos três casos) |
| `python -m streamlit run app.py --server.headless true --server.port 8765` e abrir a página | **Verificado** em navegador automatizado (Chromium): indicadores, filtro de categoria e gráficos funcionaram |
| `streamlit run app.py` (porta padrão 8501, abertura automática do navegador) | **Não verificado** (usei porta 8765 e modo sem navegador) |
| Ativar o ambiente no Windows (`.venv\Scripts\activate`) | **Não verificado** |
| Python diferente de 3.13 | **Não verificado** |
| `GARDEN_SHOP_DATA_DIR` apontando para uma pasta fora do repositório no app em execução | **Não verificado** no navegador (verificado nos testes automáticos, que usam essa variável) |
| Hospedagem do painel na internet | **Fora do escopo** (PRD, seção 4) |

Ao verificar um comando novo, atualize esta tabela.

## 5. Organização do código

```
app.py                  Tela (Streamlit): filtros, indicadores, gráficos, tabelas. Sem regra de cálculo.
garden_shop/loader.py   Lê, valida e limpa os CSVs. Devolve Tables + avisos. Levanta DataError.
garden_shop/metrics.py  Regras de cálculo (funções puras sobre DataFrames).
tests/                  Testes. tests/fixtures/ é o recorte pequeno dos CSVs (linhas originais).
data/raw/               CSVs originais. SOMENTE LEITURA.
docs/print_dashboard.png  Print do painel em execução.
.streamlit/config.toml  Tema do painel (verde; sem vermelho).
```

Onde colocar cada mudança:

- Mudou uma **fórmula, faixa ou filtro** → `metrics.py` (e `SPEC.md` seções 3, 5 e 6).
- Mudou **leitura, validação ou aviso de dados** → `loader.py` (e `SPEC.md` seção 8).
- Mudou **aparência ou texto da tela** → `app.py` (e `PRD.md` se mudar um requisito).

## 6. Cuidados com os dados

1. **Nunca altere nem grave nada em `data/raw/`.** Os testes copiam o recorte para uma pasta temporária antes de editar. Faça o mesmo.
2. Use só as tabelas e os campos listados na `SPEC.md`, seção 2. `customers`, `price`, `unit_price` e `coupon_code` ficam de fora de propósito.
3. **`cancelled` nunca é venda.** A tela não oferece esse status no filtro e `metrics.py` levanta `ValueError` se ele for passado.
4. **Descontinuado nunca é recomendado** para reposição (`needs_reorder = False`), mesmo com estoque zerado.
5. **Período filtra só vendas.** `quantity_on_hand` é a posição atual e não depende do período.
6. **Não ligue `order_items` diretamente a `products` antes de agregar.** Some as vendas por `product_id` primeiro (SPEC, seção 7). Ligar antes repete o estoque de cada produto uma vez por item de pedido.
7. Dicionário diz datas em `DD/MM/AAAA`, os CSVs usam `AAAA-MM-DD`. O carregador aceita os dois. Não troque o formato dos arquivos.
8. **Não use a cor vermelha** na tela, em gráficos nem em documentos: ela é reservada às correções do professor. O tema do Streamlit já foi trocado por verde. Erros de dados usam `st.warning`.

## 7. Como trabalhar (fluxo)

1. **Entenda o problema** e leia `PRD.md` e `SPEC.md`.
2. **Uma mudança pequena por branch** (ex.: `feat/...`, `fix/...`, `docs/...`) e **um PR por branch**, com descrição curta do que mudou e por quê.
3. **Escreva o resultado esperado e o teste antes do código.** Confirme que o teste falha pelo motivo certo e só então implemente. Os testes atuais seguem esse caminho: veja o histórico (`git log --oneline`), em que cada commit `test:` vem antes do commit `feat:`.
4. **Rode `python -m pytest -q` e abra o painel** antes de integrar. Testes passando não garantem que a tela está legível (um indicador cortado só apareceu ao abrir o painel).
5. **Atualize `PRD.md` e `SPEC.md` na mesma alteração** quando uma descoberta mudar o comportamento esperado, e registre na tabela "Decisões e descobertas" da `SPEC.md` (seção 12).
6. Mensagens de commit curtas, em português, com prefixo `feat:`, `fix:`, `test:` ou `docs:`.

## 7.1 Revisão das alterações feitas por IA

Antes de aceitar uma alteração proposta por um agente, confira:

- [ ] O diff cabe no que foi pedido? Não há arquivos ou regras novas fora do escopo do PRD?
- [ ] Há teste novo ou ajustado para cada regra alterada, com resultado esperado calculado à mão?
- [ ] O teste falharia se a regra estivesse errada? (Teste de verdade: quebre a regra de propósito e veja o teste falhar.)
- [ ] `python -m pytest -q` passa por inteiro e `git status --short data/raw` está vazio?
- [ ] Os números do painel batem com os da `SPEC.md` (seção 10) e do `PRD.md` (seção 7)?
- [ ] `SPEC.md`, `PRD.md` e este arquivo continuam corretos? Algum comando novo entrou na tabela de verificados?
- [ ] Nada em vermelho na tela ou nos documentos?
- [ ] Um agente que "corrige" um teste para ele passar deve ser questionado: o teste ou o código estava errado? Explique antes de aceitar.

## 8. Resultados de referência (para conferir rapidamente)

Com os CSVs originais e filtros padrão: **23** produtos no escopo, **5** a repor (Hanging Basket, Tomato Seeds 'Roma', Hand Cultivator, Orchid Food, Pothos 'Golden'), **1** zerado, estoque a custo **US$ 4.731,00**, custo para repor **US$ 152,00**, **86** unidades vendidas. Tabela completa de exemplos em `SPEC.md`, seção 10.
