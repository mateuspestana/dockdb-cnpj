# Contribuindo com o DockDB-CNPJ

Obrigado pelo interesse em contribuir. Este documento descreve o fluxo esperado para issues e pull requests.

**Autor:** Matheus C. Pestana \<matheus.pestana@fgv.br\>

## Código de conduta

Ao participar, você concorda em seguir o [Código de Conduta](CODE_OF_CONDUCT.md).

## Como contribuir

1. Abra uma [issue](https://github.com/mateuspestana/dockdb-cnpj/issues) descrevendo o problema ou a ideia **antes** de um PR grande.
2. Faça um fork e crie um branch a partir de `main` (`fix/…`, `feat/…`, `docs/…`).
3. Implemente a mudança com escopo focado; evite misturar refactors não relacionados.
4. Teste localmente o que fizer sentido (CLI, carga, consultas, API).
5. Abra um pull request usando o template e referencie a issue (`Closes #N` quando aplicável).

## Ambiente de desenvolvimento

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Variáveis: veja [.env.example](.env.example). A base `data/cnpj.duckdb` é gerada localmente e não entra no Git.

Comandos úteis:

```bash
python scripts/download_cnpj.py -y
python scripts/load_duckdb.py
python cli/consulta.py info
```

## Escopo das contribuições

Bem-vindas, entre outras:

- Correções de bugs na carga, encoding, sync ou consultas
- Melhorias de documentação e exemplos SQL
- Interfaces (CLI, Streamlit, API) sem quebrar o fluxo existente
- Testes e hardening de segurança da API (ver [TODO.md](TODO.md))

Evite:

- Commits com dados brutos, ZIPs, CSVs ou o arquivo DuckDB
- Secrets (`.env`, tokens, credenciais)
- Mudanças de versão/release sem alinhamento com o mantenedor

## Estilo

- Preferir português na documentação voltada a usuários brasileiros
- Mensagens de commit curtas e no imperativo (“corrige…”, “adiciona…”)
- Seguir o padrão já usado no repositório; não reformate arquivos inteiros sem necessidade

## Relatando bugs

Inclua:

- Versão / commit (`git rev-parse --short HEAD`)
- SO e versão do Python
- Passos para reproduzir
- Trecho de log ou erro (sem dados sensíveis)

Use o template de issue de bug.

## Dúvidas

Abra uma issue ou escreva para [matheus.pestana@fgv.br](mailto:matheus.pestana@fgv.br).
