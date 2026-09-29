---
name: dockdb-cnpj
description: >-
  Use when the user asks to look up a Brazilian company (CNPJ) — razão
  social, situação cadastral, sócios (QSA), CNAE, porte, capital social,
  endereço/coordenadas — or wants aggregates, cohorts, list enrichment, or
  free-form SQL over the full Receita Federal CNPJ dump. This is the
  DockDB-CNPJ project itself: a local DuckDB database with a rich CLI
  (`cli/consulta.py` / `dockdb-cnpj` if installed), a FastAPI service, and a
  Streamlit app. Runs directly against `data/cnpj.duckdb` on this machine —
  no SSH, no HTTP round-trip needed when already on this host.
---

# DockDB-CNPJ — consulta local ao CNPJ

## Goal

Given a CNPJ, a company name fragment, a sócio's name, or a set of filters
(UF, CNAE, porte, situação, município), return structured data from the
local Receita Federal CNPJ dump (`data/cnpj.duckdb`). Prefer the purpose-built
commands below over raw SQL — they already handle CNPJ alfanumérico
validation, município IBGE de-para, CNAE hierarchy, and geocoding. Fall back
to `sql` only for shapes the other commands don't cover.

This project **is** the primary/local data source — no SSH tunnel, no
remote round-trip. (A companion skill exists at
`~/.agents/skills/cnpj-dockdb` on other machines that reach this database
*over SSH* when they don't have it locally; that SSH path is a fallback for
machines without the dump, not how this repo itself should be used.)

## Setup

```bash
cd ~/Documents/DockDB-CNPJ
source .venv/bin/activate   # venv já existe neste servidor
# ou, se não instalado ainda: pip install -e .
```

Confirmar que a base existe: `ls -la data/cnpj.duckdb` (deve ter dezenas de GB).
Ver `_referencia` para a data do dump: `python cli/consulta.py sql "SELECT * FROM _referencia"`.

## CLI (via `python cli/consulta.py <comando>` ou `dockdb-cnpj <comando>` se instalado)

```bash
python cli/consulta.py info                                             # status da base
python cli/consulta.py cnpj 00000000000191                              # consulta por CNPJ (14 díg. ou alfanumérico)
python cli/consulta.py dv 12ABC34501DE                                  # calcula/valida dígito verificador (sem tocar a base)
python cli/consulta.py buscar --uf SP --cnae 6201501 --situacao 02 --limit 20
python cli/consulta.py buscar --municipio-ibge 3304557 --cnae-secao J --mei --limit 20
python cli/consulta.py socio --nome "SILVA" --limit 20                  # busca de sócio por nome
python cli/consulta.py enriquecer lista.csv --saida enriquecida.parquet # CNPJ em lote (CSV/TXT/Parquet)
python cli/consulta.py agregados cnae --nivel secao                     # ou: uf, municipio
python cli/consulta.py coortes --freq ano --uf SP --cnae-divisao 62 --desde 2015
python cli/consulta.py geocodificar --municipio-ibge 3304557 --limite 200  # CEP -> lat/lon (BrasilAPI, cacheado)
python cli/consulta.py sql "SELECT uf, count(*) n FROM estabelecimento GROUP BY 1 ORDER BY 2 DESC"
python cli/consulta.py validar                                          # checks de integridade/DV/cobertura IBGE
```

Todos os comandos de consulta aceitam `--export arquivo.csv|.parquet` (ou
`GET /export` na API) para gravar em vez de imprimir.

## API e Streamlit (opcional, mesma base)

```bash
docker compose up --build   # http://127.0.0.1:8000/docs — só bind local, sem auth (ver TODO.md)
streamlit run streamlit_app/app.py
```

## SQL livre — `sql` (fallback)

`sql` só aceita `SELECT`/`WITH` (bloqueado por `dockdb_cnpj.sql_guard`:
sem `INSERT/UPDATE/DELETE/DROP/ATTACH/COPY/PRAGMA/...`, uma única
instrução). Limite de linhas configurável (`--limit`, default
`CNPJ_QUERY_LIMIT=1000`, teto `CNPJ_MAX_QUERY_LIMIT=10000`). Use para
formas que os comandos de domínio não cobrem — a maioria dos casos já tem
comando próprio acima.

## Workflow

1. CNPJ conhecido → `cnpj`. Nome de empresa/sócio → `buscar`/`socio`.
2. Filtro amplo (setor, região, porte) → `buscar` com os flags certos antes de recorrer a `sql`.
3. Lista de CNPJs (CSV/planilha) → `enriquecer`, não um loop de `cnpj` um por um.
4. Precisa de algo fora do que os comandos cobrem → `sql`, sabendo que só SELECT/WITH passa.
5. CPF de sócio é PII — mascarar em qualquer texto para o usuário, mesmo vindo de dado já público (QSA).

## Gotchas

- CNPJ alfanumérico (IN RFB 2.229/2024): 12 primeiras posições podem ter letras; todos os comandos aceitam com/sem pontuação e minúsculas.
- `estabelecimento.municipio` é o código **TOM/SIAFI** da Receita (4 dígitos), não o IBGE (7 dígitos) — use `municipio_ibge`/`--municipio-ibge` para cruzar com outras bases (TSE, Censo, RAIS...).
- Coordenadas default são o **centroide do município** (`geo_precisao=municipio`); rodar `geocodificar` para precisão de CEP (exige lock de escrita, usa BrasilAPI só para CEPs novos).
- `compactar`/`geocodificar`/`upgrade`/recarga exigem lock exclusivo — não rodar em paralelo com outra escrita na base.
- API **não tem autenticação** hoje (`TODO.md`) — só usar em rede confiável (bind já é só `127.0.0.1`).
- Sócio pode vir com `cnpj_cpf_socio` só o radical (8 díg.) quando o sócio é PJ pré-ago/2026 — a carga já resolve isso na maioria dos casos, mas cheque `qualificacao_socio` para não confundir CPF mascarado (pessoa física) com radical de CNPJ.
