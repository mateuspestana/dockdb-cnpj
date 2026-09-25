# DockDB-CNPJ

[![DOI](https://zenodo.org/badge/1382603178.svg)](https://doi.org/10.5281/zenodo.22940888)
[![versão](https://img.shields.io/github/v/release/mateuspestana/dockdb-cnpj?label=versão)](https://github.com/mateuspestana/dockdb-cnpj/releases)
[![licença](https://img.shields.io/github/license/mateuspestana/dockdb-cnpj?label=licença)](LICENSE)
[![atualizado](https://img.shields.io/github/last-commit/mateuspestana/dockdb-cnpj?label=atualizado)](https://github.com/mateuspestana/dockdb-cnpj/commits/main)

Base pública de CNPJ da Receita Federal em **[DuckDB](https://duckdb.org/)**, com download, carga, sync, CLI, Streamlit e API em Docker.

**Autor:** [Matheus Cavalcanti Pestana](mailto:matheus.pestana@fgv.br) · `matheus.pestana@fgv.br`  
**Licença:** [MIT](LICENSE) · **Versão:** ver [CHANGELOG.md](CHANGELOG.md)

## Referência

Este projeto segue a linha do **[cnpj-sqlite](https://github.com/rictom/cnpj-sqlite)** (Ricardo Tomasi / rictom): baixar os dados abertos de CNPJ e disponibilizá-los localmente para consulta. Aqui o destino é DuckDB em vez de SQLite, com interfaces de consulta embutidas (CLI, Streamlit e API).

## Por que DuckDB?

Para o uso típico desta base — filtros em dezenas de milhões de linhas, joins e agregações (UF, CNAE, etc.) — o DuckDB costuma ser **mais rápido**: armazenamento colunar e execução vetorizada (o “SQLite da analytics”).

Em lookups pontuais muito bem indexados (um CNPJ exato), o SQLite pode empatar ou ganhar. Para exploração analítica e consultas amplas, o DuckDB tende a se sair melhor.

## Ferramentas

| Peça | Comando |
|------|---------|
| Download | `python scripts/download_cnpj.py -y` |
| Carga | `python scripts/load_duckdb.py` |
| Sync | `python scripts/sync_cnpj.py -y` |
| Limpar brutos | `python scripts/cleanup_raw.py -y` |
| CLI | `python cli/consulta.py …` |
| Streamlit | `streamlit run streamlit_app/app.py` |
| API (Docker) | `docker compose up --build` → http://127.0.0.1:8000/docs |

## Pré-requisitos

- Python 3.10+
- Disco: ~25 GB para ZIPs/CSVs + dezenas de GB para `data/cnpj.duckdb` (na prática ~60–70 GB no pico; depois dá para limpar os brutos)
- Docker (opcional; só para a API)

```bash
git clone https://github.com/mateuspestana/dockdb-cnpj.git
cd dockdb-cnpj
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Fluxo

```bash
# 1) Baixar ZIPs do mês mais recente (Receita Federal)
python scripts/download_cnpj.py -y

# 2) Extrair e carregar em data/cnpj.duckdb
python scripts/load_duckdb.py
# retomar carga interrompida:
# python scripts/load_duckdb.py --no-extract --resume
# opcional: python scripts/load_duckdb.py --cleanup-raw

# 3) Consultar
python cli/consulta.py info
python cli/consulta.py cnpj 00000000000191
python cli/consulta.py buscar --uf SP --cnae 6201501 --situacao 02 --mei --limit 20
python cli/consulta.py buscar --uf SP --cnae 6201501 --export out.csv
python cli/consulta.py socio --nome "SILVA" --limit 20
python cli/consulta.py agregados uf
python cli/consulta.py validar
python cli/consulta.py sql "SELECT uf, count(*) n FROM estabelecimento GROUP BY 1 ORDER BY 2 DESC"

streamlit run streamlit_app/app.py
# testes: pytest
```

> **v0.5:** após atualizar o código, **recarregue** a base (`load_duckdb.py`) para gerar `estabelecimento_cnae`, views materializadas e FTS.

### Sync

A Receita publica um dump mensal completo. O sync baixa só o que mudou (tamanho/arquivo) e recarrega a base:

```bash
python scripts/sync_cnpj.py -y
```

Sem cron embutido — você escolhe quando rodar. Ver [TODO.md](TODO.md).

### Liberar disco

Com a base pronta, apague ZIPs e CSVs e mantenha só o DuckDB:

```bash
python scripts/cleanup_raw.py -y
python scripts/cleanup_raw.py --dry-run
```

> **Aviso (ago/2026):** em sócios, `cnpj_cpf_socio` pode trazer só o radical (8 dígitos) quando o sócio é empresa. A carga resolve para o CNPJ completo da matriz (mesma correção do cnpj-sqlite).

## API (Docker)

A imagem **não** inclui a base. Gere `data/cnpj.duckdb` no host e monte o volume:

```bash
docker compose up --build
```

| Método | Rota |
|--------|------|
| GET | `/health`, `/referencia`, `/cnpj/{cnpj}` |
| GET | `/empresas?uf=&cnae=&mei=&simples=&porte=&municipio_nome=&q=&fuzzy=&limit=` |
| GET | `/socios?nome=&documento=&limit=` |
| GET | `/agregados/{uf\|cnae\|situacao}` |
| GET | `/export?formato=csv\|parquet&…` (mesmos filtros de `/empresas`) |
| POST | `/query` — `{"sql":"SELECT …","limit":1000}` (somente SELECT/WITH) |
| Docs | http://127.0.0.1:8000/docs |

**Segurança:** sem autenticação. O compose publica só em `127.0.0.1:8000` (rede confiável). Não use `0.0.0.0` sem auth — ver [TODO.md](TODO.md).

Sem Docker:

```bash
export PYTHONPATH=src CNPJ_DB_PATH=data/cnpj.duckdb
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

## Estrutura

```
dockdb-cnpj/
  src/dockdb_cnpj/     # núcleo
  scripts/             # download, load, sync, cleanup_raw
  cli/                 # CLI
  streamlit_app/       # UI (+ Analytics)
  api/                 # FastAPI
  tests/               # integração (fixture mini)
  exemplos/            # SQL + notebook
  data/cnpj.duckdb     # gerado localmente (não versionado)
```

Variáveis: [.env.example](.env.example). Se o WebDAV da Receita mudar o token, ajuste `CNPJ_SHARE_TOKEN`.

## Exemplos SQL

[exemplos/consultas.sql](exemplos/consultas.sql)

## Créditos

- Dados: [CNPJ — Dados Abertos](https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj) (Receita Federal)
- Referência de fluxo e layout: [cnpj-sqlite](https://github.com/rictom/cnpj-sqlite)
- Listagem WebDAV: [cnpj-data-pipeline](https://github.com/caiopizzol/cnpj-data-pipeline)

## Autor

**Matheus Cavalcanti Pestana**  
[matheus.pestana@fgv.br](mailto:matheus.pestana@fgv.br)
