---
name: dockdb-cnpj
description: >-
  Use when the user asks to look up a Brazilian company (CNPJ) — razão
  social, situação cadastral, sócios (QSA), CNAE, porte, capital social,
  endereço/coordenadas — to list ALL companies/establishments of a CNAE
  (principal or secundário, or a whole CNAE seção/divisão), or wants
  aggregates, cohorts, list enrichment, or free-form SQL over the full
  Receita Federal CNPJ dump. This is the DockDB-CNPJ project itself: a local
  DuckDB database with a rich CLI (`cli/consulta.py` / `dockdb-cnpj` if
  installed), a FastAPI service, and a Streamlit app. Runs directly against
  `data/cnpj.duckdb` on this machine — no SSH, no HTTP round-trip needed
  when already on this host.
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

## Todas as empresas de um CNAE (extração completa)

`buscar` já resolve CNAE principal + secundário, hierarquia e município IBGE:

- `--cnae 6201501` — casa CNAE principal **ou secundário** (padrão, via ponte `estabelecimento_cnae`); `--somente-principal` restringe ao `cnae_fiscal`.
- `--cnae-secao J` / `--cnae-divisao 62` — ramo inteiro, **só CNAE principal**.
- Combina com `--uf`, `--municipio-ibge`, `--situacao 02`, `--matriz-filial 1`, `--mei`, `--simples`, `--porte`, `--data-inicio-de/--data-inicio-ate`.

**Teto de linhas**: `buscar` e `sql` são limitados por `CNPJ_MAX_QUERY_LIMIT`
(default **10.000**) — **mesmo com `--export`**, e sem aviso de truncamento.
CNAEs comuns passam de 100 mil estabelecimentos. Para extração completa:

```bash
# 1) contar antes
python cli/consulta.py sql "SELECT tipo, count(*) n FROM estabelecimento_cnae WHERE cnae = '6201501' GROUP BY tipo"

# 2) subir o teto só nesta chamada e exportar
CNPJ_MAX_QUERY_LIMIT=500000 python cli/consulta.py buscar \
  --cnae 6201501 --somente-principal --situacao 02 \
  --limit 500000 --export data/exports/cnae_6201501.parquet --formato parquet
```

`data/exports/` (`CNPJ_EXPORTS_DIR`) está no `.gitignore`, mas o `GET /export`
da API e o comando `retencao` apagam lá arquivos com mais de
`CNPJ_EXPORTS_MAX_AGE_H` (24h) — copie para fora se precisar guardar.

O export sai com `cnpj, razao_social, nome_fantasia, uf, municipio(_nome/_ibge),
cep, cnae_secao, cnae_divisao, cnae_fiscal, cnae_descricao, cnae_origem,
latitude, longitude, geo_precisao, situacao_cadastral, matriz_filial,
porte_empresa, capital_social, data_inicio_atividades, ...`
(ex.: 68.270 linhas em ~3s). `exportar_busca` materializa o resultado em
memória Python antes de gravar — para extrações de milhões de linhas, prefira
`COPY` direto no DuckDB:

```bash
.venv/bin/python -c "import duckdb; duckdb.connect('data/cnpj.duckdb', read_only=True).execute(\"COPY (SELECT ...) TO 'data/exports/saida.parquet' (FORMAT parquet)\")"
```

**Empresa ≠ estabelecimento**: `buscar` devolve estabelecimentos (matriz +
filiais, cada um com seu CNAE). Para *empresas*, use `--matriz-filial 1` ou
`count(DISTINCT cnpj_basico)` — lembrando que uma filial pode ter um CNAE que
a matriz não tem.

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

Como só passa SELECT/WITH, `DESCRIBE`/`SHOW TABLES` não funcionam aqui —
use `information_schema`:

```bash
python cli/consulta.py sql "SELECT table_name FROM information_schema.tables ORDER BY 1"
python cli/consulta.py sql "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'estabelecimento' ORDER BY ordinal_position"
```

## Schema (resumo)

Colunas são `VARCHAR` com zero à esquerda (compare `'02'`, não `2`), salvo indicação.

- **`empresas`** (1 por `cnpj_basico`): `razao_social`, `natureza_juridica`, `qualificacao_responsavel`, `porte_empresa` (`00`/`01` micro/`03` EPP/`05` demais), `capital_social` (DOUBLE), `capital_social_str`, `ente_federativo_responsavel`.
- **`estabelecimento`** (singular; 1 por CNPJ completo): `cnpj`, `cnpj_basico`, `cnpj_ordem`, `cnpj_dv`, `matriz_filial` (`1`/`2`), `nome_fantasia`, `situacao_cadastral` (`01` nula, `02` ativa, `03` suspensa, `04` inapta, `08` baixada), `data_situacao_cadastral`, `motivo_situacao_cadastral`, `data_inicio_atividades` (`YYYYMMDD`), `cnae_fiscal`, `cnae_fiscal_secundaria` (lista com vírgula), endereço (`tipo_logradouro`, `logradouro`, `numero`, `complemento`, `bairro`, `cep`, `uf`, `municipio`), contato (`ddd1`, `telefone1`, `ddd2`, `telefone2`, `ddd_fax`, `fax`, `correio_eletronico`), `pais`, `nome_cidade_exterior`, `situacao_especial`, `data_situacao_especial`.
- **`socios`**: `cnpj`, `cnpj_basico`, `identificador_de_socio`, `nome_socio`, `cnpj_cpf_socio`, `qualificacao_socio`, `data_entrada_sociedade`, `pais`, `representante_legal`, `nome_representante`, `qualificacao_representante_legal`, `faixa_etaria`.
- **`simples`**: `cnpj_basico`, `opcao_simples`, `data_opcao_simples`, `data_exclusao_simples`, `opcao_mei`, `data_opcao_mei`, `data_exclusao_mei`.
- **CNAE**: `estabelecimento_cnae` (ponte `cnpj`, `cnae`, `tipo` = `principal`/`secundario`; indexada por `cnae` — use-a em vez de `LIKE` em `cnae_fiscal_secundaria`), `cnae` (`codigo`, `descricao`), `cnae_hierarquia` (`cnae` → `classe` → `grupo` → `divisao` → `secao`, cada um com `_desc`).
- **Views**: `mv_estabelecimento_ativo` (`situacao_cadastral='02'`), `mv_matriz` (`matriz_filial='1'`), `mv_mei` (join com `simples.opcao_mei='S'`) — views, não cópias físicas.
- **Referência**: `municipio` (código RF/TOM), `municipio_ibge` (`codigo_rf` → `codigo_ibge`, `nome`, `uf`, `regiao`, `capital`, `latitude`, `longitude`), `natureza_juridica`, `qualificacao_socio`, `motivo`, `pais` (`codigo`, `descricao`), `cnpj_base2matriz`, `cep_geo` (cache do `geocodificar`).
- **Metadados**: `_referencia` (data do dump, `cnpj_qtde`, ...), `_validacao` (saída do `validar`). `dict`/`docs`/`terms`/`fields`/`stats`/`stopwords` são internos do FTS.

## Workflow

1. CNPJ conhecido → `cnpj`. Nome de empresa/sócio → `buscar`/`socio`.
2. Filtro amplo (setor, região, porte) → `buscar` com os flags certos antes de recorrer a `sql`.
3. "Todas as empresas de X" → contar primeiro; se passar de 10.000, subir `CNPJ_MAX_QUERY_LIMIT` e usar `--export` (ver seção acima).
4. Lista de CNPJs (CSV/planilha) → `enriquecer`, não um loop de `cnpj` um por um.
5. Precisa de algo fora do que os comandos cobrem → `sql`, sabendo que só SELECT/WITH passa.
6. CPF de sócio é PII — mascarar em qualquer texto para o usuário, mesmo vindo de dado já público (QSA).

## Gotchas

- CNPJ alfanumérico (IN RFB 2.229/2024): 12 primeiras posições podem ter letras; todos os comandos aceitam com/sem pontuação e minúsculas.
- `estabelecimento.municipio` é o código **TOM/SIAFI** da Receita (4 dígitos), não o IBGE (7 dígitos) — use `municipio_ibge`/`--municipio-ibge` para cruzar com outras bases (TSE, Censo, RAIS...).
- `buscar`/`sql`/`--export` truncam silenciosamente em `CNPJ_MAX_QUERY_LIMIT` (10.000) — sempre comparar com um `count(*)` em extrações "completas".
- `--cnae-secao`/`--cnae-divisao` filtram só o CNAE principal; para secundários de um ramo inteiro, use `sql` com `estabelecimento_cnae` + `cnae_hierarquia`.
- Coordenadas default são o **centroide do município** (`geo_precisao=municipio`); rodar `geocodificar` para precisão de CEP (exige lock de escrita, usa BrasilAPI só para CEPs novos).
- `compactar`/`geocodificar`/`upgrade`/recarga exigem lock exclusivo — não rodar em paralelo com outra escrita na base.
- API **não tem autenticação** hoje (`TODO.md`) — só usar em rede confiável (bind já é só `127.0.0.1`).
- Sócio pode vir com `cnpj_cpf_socio` só o radical (8 díg.) quando o sócio é PJ pré-ago/2026 — a carga já resolve isso na maioria dos casos, mas cheque `qualificacao_socio` para não confundir CPF mascarado (pessoa física) com radical de CNPJ.
- Base é o **dump mais recente** — não acumula histórico; ex-sócios não aparecem mais em `socios`.
