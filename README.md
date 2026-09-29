# DockDB-CNPJ

[![DOI](https://zenodo.org/badge/1382603178.svg)](https://doi.org/10.5281/zenodo.22940888)
[![versão](https://img.shields.io/github/v/release/mateuspestana/dockdb-cnpj?label=versão)](https://github.com/mateuspestana/dockdb-cnpj/releases)
[![licença](https://img.shields.io/github/license/mateuspestana/dockdb-cnpj?label=licença)](LICENSE)
[![atualizado](https://img.shields.io/github/last-commit/mateuspestana/dockdb-cnpj?label=atualizado)](https://github.com/mateuspestana/dockdb-cnpj/commits/main)
[![CI](https://github.com/mateuspestana/dockdb-cnpj/actions/workflows/ci.yml/badge.svg)](https://github.com/mateuspestana/dockdb-cnpj/actions/workflows/ci.yml)

Base pública de CNPJ da Receita Federal em **[DuckDB](https://duckdb.org/)**, com download, carga, sync, CLI, Streamlit e API em Docker.

**Autor:** [Matheus Cavalcanti Pestana](mailto:matheus.pestana@fgv.br) · `matheus.pestana@fgv.br`  
**Licença:** [MIT](LICENSE) · **Versão:** ver [CHANGELOG.md](CHANGELOG.md)  
**Para agentes de IA:** ver [SKILL.md](SKILL.md) — guia de uso da CLI por caso de uso, direto na base local.

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
python cli/consulta.py cnpj 12.ABC.345/01DE-35          # alfanumérico
python cli/consulta.py dv 12ABC34501DE                  # calcula/valida DV (sem base)
python cli/consulta.py buscar --uf SP --cnae 6201501 --situacao 02 --mei --limit 20
python cli/consulta.py buscar --municipio-ibge 3304557 --cnae 6201501 --limit 20
python cli/consulta.py buscar --uf RJ --cnae-secao J --situacao 02 --limit 20
python cli/consulta.py enriquecer minha_lista.csv --saida enriquecida.parquet
python cli/consulta.py coortes --freq ano --uf SP --cnae-divisao 62 --desde 2015
python cli/consulta.py agregados cnae --nivel secao
python cli/consulta.py geocodificar --municipio-ibge 3304557 --limite 200
python cli/consulta.py buscar --uf SP --cnae 6201501 --export out.csv
python cli/consulta.py socio --nome "SILVA" --limit 20
python cli/consulta.py agregados uf
python cli/consulta.py validar
python cli/consulta.py compactar                    # recupera espaço (lock exclusivo)
python cli/consulta.py retencao --manter-backups 1 --dry-run
python cli/consulta.py sql "SELECT uf, count(*) n FROM estabelecimento GROUP BY 1 ORDER BY 2 DESC"

streamlit run streamlit_app/app.py
```

> **Atualizando o código numa base já carregada:** rode `python cli/consulta.py upgrade` (exige lock exclusivo de escrita) em vez de recarregar tudo. Se a base já está na v0.5 ou depois, `upgrade --no-cnae-bridge --no-views --no-fts` basta para criar as tabelas auxiliares novas (leva segundos).

### CNPJ alfanumérico

Desde jul/2026 a Receita emite CNPJ com letras nas 12 primeiras posições (IN RFB nº 2.229/2024); os 2 dígitos verificadores continuam numéricos. Todas as consultas (CLI, API, Streamlit) aceitam os dois formatos, com ou sem pontuação e em minúsculas (`12.abc.345/01de-35` → `12ABC34501DE35`). A consulta informa `dv_valido` e, se errado, `dv_esperado`. O `validar` conta CNPJs com DV inválido e quantos são alfanuméricos.

### Código IBGE do município

O campo `estabelecimento.municipio` usa o código **TOM/SIAFI da Receita** (4 dígitos — Rio = `6001`), não o do IBGE (7 dígitos — Rio = `3304557`). A tabela `municipio_ibge` faz o de-para, com UF, região e centroide, e permite cruzar com Censo, RAIS, TSE, DATASUS etc.:

```sql
SELECT mi.codigo_ibge, mi.nome, count(*) AS ativas
FROM mv_estabelecimento_ativo e
JOIN municipio_ibge mi ON mi.codigo_rf = e.municipio
GROUP BY 1, 2 ORDER BY ativas DESC;
```

A busca e a consulta devolvem `municipio_ibge`, e `--municipio-ibge` / `?municipio_ibge=` filtra por ele. O CSV é versionado em `src/dockdb_cnpj/data/` (fonte: [kelvins/municipios-brasileiros](https://github.com/kelvins/municipios-brasileiros)); para regerar, `python scripts/build_reference_data.py`.

### Hierarquia CNAE

A tabela `cnae_hierarquia` liga cada subclasse à classe, ao grupo, à divisão e à seção da CNAE 2.3 (fonte: API de CNAE do IBGE). Com ela dá para filtrar por setor inteiro (`--cnae-secao C` = indústria de transformação; `--cnae-divisao 62` = TI) e agregar em qualquer nível (`agregados cnae --nivel secao`). Esses filtros olham o CNAE **principal**. Subclasses antigas que a Receita ainda usa são ligadas pelo prefixo da classe.

### Busca por lista

`enriquecer` recebe um `.csv`, `.txt` ou `.parquet` com CNPJs e devolve, na mesma ordem, os dados cadastrais de cada um (razão social, situação, CNAE e seção, porte, capital, endereço, município + IBGE, Simples/MEI), com `encontrado`, `dv_valido` e `erro`. CNPJ básico (8) devolve a matriz; zeros à esquerda perdidos no Excel são recuperados; a coluna com "cnpj" no nome é detectada (ou use `--coluna`). Na API: `POST /enriquecer {"cnpjs": [...]}`; no Streamlit: aba **Lista**. Uma lista de 20 mil CNPJs leva ~4 s na base completa.

### Coortes de abertura e baixa

`coortes` gera séries por ano ou mês com `aberturas`, `baixas`, `saldo`, `ativas_hoje` e `taxa_sobrevivencia`, filtráveis por UF, município, CNAE, seção e divisão. É um **retrato do dump atual**: baixas contam estabelecimentos hoje baixados pela data da situação cadastral, e a sobrevivência é a fração das aberturas do período que segue ativa na data de referência.

### Coordenadas e mapas

Busca, consulta e lista devolvem `latitude`, `longitude` e `geo_precisao`. Sem nada a fazer, o ponto é o **centroide do município** (`geo_precisao = municipio`). Para precisão de CEP, `geocodificar` consulta a [BrasilAPI](https://brasilapi.com.br/) só para CEPs ainda não vistos e guarda na tabela `cep_geo` (precisa de lock de escrita; use `--limite` e `--pausa` para não sobrecarregar o serviço). Esses CEPs passam a ter prioridade (`geo_precisao = cep`). O Streamlit mostra os resultados da busca num mapa e tem um mapa de ativos por município em **Analytics**.

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

### Compactação e retenção

O DuckDB não devolve ao disco o espaço de tabelas apagadas ou reescritas (ponte CNAE, `upgrade`, recarga de sócios). `compactar` copia a base para um arquivo novo, confere as contagens de todas as tabelas e só então troca (exige lock exclusivo e espaço livre do tamanho da base; ~26 min na base completa). O DuckDB usa no máximo metade da RAM (`--memoria 16GB` para mudar) e despeja o excedente em disco:

```bash
python cli/consulta.py compactar                 # --manter-backup guarda a original
```

Para não ficar sem base se a carga de um mês novo der problema, a recarga pode **guardar a base anterior** (`cnpj.duckdb.bak-AAAAMM`) e manter só as N mais recentes. Cada backup ocupa o tamanho da base (~50 GB):

```bash
python scripts/sync_cnpj.py -y --manter-backups 1     # ou CNPJ_KEEP_BACKUPS=1
python cli/consulta.py retencao --manter-backups 0 --dry-run
```

`retencao` também apaga exports velhos da API (`CNPJ_EXPORTS_MAX_AGE_H`, padrão 24 h). A própria API já apaga cada export logo depois de enviá-lo.

> **Aviso (ago/2026):** em sócios, `cnpj_cpf_socio` pode trazer só o radical (8 dígitos) quando o sócio é empresa. A carga resolve para o CNPJ completo da matriz (mesma correção do cnpj-sqlite).

## API (Docker)

A imagem **não** inclui a base. Gere `data/cnpj.duckdb` no host e monte o volume:

```bash
docker compose up --build
```

| Método | Rota |
|--------|------|
| GET | `/health`, `/referencia`, `/cnpj/{cnpj}` (aceita alfanumérico) |
| GET | `/dv/{cnpj}` — valida (14) ou calcula (12) o dígito verificador |
| GET | `/empresas?uf=&cnae=&cnae_secao=&cnae_divisao=&mei=&simples=&porte=&municipio_nome=&municipio_ibge=&q=&fuzzy=&limit=` |
| GET | `/socios?nome=&documento=&limit=` |
| GET | `/agregados/{uf\|cnae\|situacao\|municipio}` (`?nivel=secao` para CNAE) |
| GET | `/coortes?freq=ano\|mes&desde=&ate=&uf=&cnae_secao=&…` |
| POST | `/enriquecer` — `{"cnpjs": ["…", "…"]}` (até `CNPJ_MAX_QUERY_LIMIT`) |
| GET | `/export?formato=csv\|parquet&…` (mesmos filtros de `/empresas`) |
| POST | `/query` — `{"sql":"SELECT …","limit":1000}` (somente SELECT/WITH) |
| Docs | http://127.0.0.1:8000/docs |

**Segurança:** sem autenticação. O compose publica só em `127.0.0.1:8000` (rede confiável). Não use `0.0.0.0` sem auth — ver [TODO.md](TODO.md).

**Cache e rate limit.** Respostas `GET` em JSON ficam em cache na memória por `CNPJ_API_CACHE_TTL` segundos (padrão 300; `0` desliga), até `CNPJ_API_CACHE_MAX` itens (padrão 512), com o cabeçalho `X-Cache: HIT|MISS`. `/health`, `/export` e as rotas `POST` não são cacheadas. O rate limit vem **desligado**; `CNPJ_API_RATE_LIMIT=60` limita a 60 requisições/min por IP (responde `429` com `Retry-After`). Atrás de proxy reverso, `CNPJ_API_TRUST_PROXY=1` usa o `X-Forwarded-For`. Cache e limite são por processo: com vários workers do uvicorn, cada um tem os seus. O `/health` mostra a configuração e os acertos do cache.

Sem Docker:

```bash
export PYTHONPATH=src CNPJ_DB_PATH=data/cnpj.duckdb
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

## Estrutura

```
dockdb-cnpj/
  src/dockdb_cnpj/     # núcleo
  src/dockdb_cnpj/data # tabelas auxiliares versionadas (IBGE, CNAE)
  scripts/             # download, load, sync, cleanup_raw
  cli/                 # CLI
  streamlit_app/       # UI (+ Analytics)
  api/                 # FastAPI
  tests/               # integração (fixture mini)
  exemplos/            # SQL + notebook
  .github/workflows/   # CI (ruff, mypy, pytest)
  data/cnpj.duckdb     # gerado localmente (não versionado)
```

Variáveis: [.env.example](.env.example). Se o WebDAV da Receita mudar o token, ajuste `CNPJ_SHARE_TOKEN`.

## Desenvolvimento

```bash
pip install -e ".[dev]"
ruff check . && mypy && pytest
```

A CI roda os mesmos três passos em cada push e PR (Python 3.10, 3.12 e 3.13), usando a fixture mínima em `tests/fixtures/mini/` — não precisa da base real.

## Exemplos SQL

[exemplos/consultas.sql](exemplos/consultas.sql)

## Créditos

- Dados: [CNPJ — Dados Abertos](https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj) (Receita Federal)
- Referência de fluxo e layout: [cnpj-sqlite](https://github.com/rictom/cnpj-sqlite)
- Listagem WebDAV: [cnpj-data-pipeline](https://github.com/caiopizzol/cnpj-data-pipeline)
- Municípios (código SIAFI × IBGE e centroides): [kelvins/municipios-brasileiros](https://github.com/kelvins/municipios-brasileiros) (MIT)
- Hierarquia CNAE 2.3: [API de CNAE do IBGE](https://servicodados.ibge.gov.br/api/docs/cnae)
- Geocodificação de CEP (opcional): [BrasilAPI](https://brasilapi.com.br/)

## Autor

**Matheus Cavalcanti Pestana**  
[matheus.pestana@fgv.br](mailto:matheus.pestana@fgv.br)
