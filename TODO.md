# TODO — DockDB-CNPJ

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>

## Auth na API (prioritário → 1.0 / pré-exposição)

- [ ] Implementar autenticação na API FastAPI (ex.: API key via header `X-API-Key` ou Bearer token)
- [ ] Documentar como configurar a chave via variável de ambiente
- [ ] Só então considerar bind em `0.0.0.0` / exposição pública

**Estado atual:** a API **não tem autenticação**. O `docker-compose.yml` publica a porta apenas em `127.0.0.1:8000`. Use somente em **rede confiável** (localhost, VPN ou LAN privada).

## 1.0.0 — client Python

- [ ] Pacote instalável focado em API de consulta (`pip install dockdb-cnpj` como biblioteca cliente)

## Outros

- [ ] Serviço Streamlit no Docker Compose (opcional)
- [ ] Agendamento de sync (cron) — o script `sync_cnpj.py` já existe; falta só o agendamento do usuário
- [x] Testes de integração com amostra reduzida dos CSVs da RF (v0.4)
