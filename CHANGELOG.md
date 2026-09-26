# Changelog

Todas as mudanças notáveis deste projeto são documentadas aqui.

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
Autor: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>

## [0.5.2] — 2026-09-26

### Fixed

- Resume do pós-processamento quando `socios_original` já foi dropado (não quebra mais o `--resume`)
- Busca FTS ordena por BM25 (`ORDER BY _fts_score DESC`) — evita resultados irrelevantes no `LIMIT`

### Added

- Teste de integração cobrindo resume após sócios processados

## [0.5.1] — 2026-09-25

### Fixed

- `validar` faz fallback para somente leitura quando a base está com lock de escrita
- `mv_*` passam a ser **views** (não tabelas) — evita duplicar dezenas de GB em disco
- Mensagem clara no `upgrade` quando há conflito de lock

### Added

- CLI `upgrade` — aplica ponte CNAE / views / FTS / validação em base já carregada

## [0.5.0] — 2026-09-25

### Added

- Tabela ponte `estabelecimento_cnae` (principal + secundários) usada na busca
- Views materializadas: `mv_estabelecimento_ativo`, `mv_matriz`, `mv_mei`
- Carga resumível (`--resume` + checkpoint `{db}.load_checkpoint.json`)
- Validação pós-carga (`validar_base`, CLI `validar`, tabela `_validacao`)
- Full-text (FTS) em razão social + busca fuzzy (Jaro-Winkler) com `--fuzzy`
- Painel **Analytics** no Streamlit (UF, situação, top CNAE)

### Changed

- Pós-processamento da carga passa a gerar ponte CNAE, MVs, FTS e validação
- **Requer recarga** da base (`load_duckdb.py`) para ativar ponte/MVs/FTS

## [0.4.0] — 2026-09-25

### Added

- Filtros ricos na busca: porte, MEI, Simples, matriz/filial, município por nome, capital, data de abertura
- Export CSV/Parquet (`--export` na CLI, `GET /export` na API)
- Lookup de sócio (CLI `socio`, `GET /socios`)
- Decode ampliado na consulta CNPJ (porte, situação, país, qualificações, etc.)
- Testes de integração com fixture mínima (`tests/`)
- Notebook de exemplos (`exemplos/dockdb_cnpj_exemplos.ipynb`)
- Agregados (`agregados` CLI / `GET /agregados/{tipo}`)

## [0.3.0] — 2026-09-25

### Added

- Busca por CNAE também em `cnae_fiscal_secundaria` (lista CSV da Receita)
- Flag `--incluir-secundario/--somente-principal` na CLI; parâmetro `incluir_cnae_secundario` na API e checkbox no Streamlit
- Campo `cnae_origem` (`principal` / `secundario`) e `cnae_fiscal_secundaria` no resultado da busca

## [0.2.0] — 2026-09-22

### Added

- Script `scripts/cleanup_raw.py` para apagar ZIPs e CSVs brutos e manter só o DuckDB
- Flag `--cleanup-raw` em `scripts/load_duckdb.py` (limpa ZIP+CSV ao terminar a carga)
- Módulo `dockdb_cnpj.cleanup`

### Fixed

- Leitura CSV: `parallel=false` + `null_padding` (newlines entre aspas nos CSVs da RF)
- Encoding: `cp1252` via extensão `encodings` do DuckDB (evita erro “File is not latin-1 encoded”)

## [0.1.0] — 2026-09-22

### Added

- Download dos ZIPs públicos de CNPJ (WebDAV Receita Federal)
- Carga para DuckDB (`empresas`, `estabelecimento`, `socios`, `simples`, tabelas de código)
- Sync incremental (`scripts/sync_cnpj.py`)
- CLI de consulta, Streamlit e API FastAPI (Docker com volume + bind em localhost)
- Correção de sócios pós-ago/2026 (radical → CNPJ matriz)
- README com crédito ao [cnpj-sqlite](https://github.com/rictom/cnpj-sqlite)
- `TODO.md` com autenticação da API pendente

[0.5.2]: https://github.com/mateuspestana/DockDB-CNPJ/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/mateuspestana/DockDB-CNPJ/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/mateuspestana/DockDB-CNPJ/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/mateuspestana/DockDB-CNPJ/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/mateuspestana/DockDB-CNPJ/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mateuspestana/DockDB-CNPJ/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mateuspestana/DockDB-CNPJ/releases/tag/v0.1.0
