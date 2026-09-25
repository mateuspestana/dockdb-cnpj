# Changelog

Todas as mudanças notáveis deste projeto são documentadas aqui.

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
Autor: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>

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

[0.3.0]: https://github.com/mateuspestana/DockDB-CNPJ/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mateuspestana/DockDB-CNPJ/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mateuspestana/DockDB-CNPJ/releases/tag/v0.1.0
