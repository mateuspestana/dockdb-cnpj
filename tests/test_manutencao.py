"""
Testes v0.8: cache/rate limit, compactação e retenção.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dockdb_cnpj.cache import RateLimiter, TTLCache
from dockdb_cnpj.db import connect
from dockdb_cnpj.load import load_duckdb
from dockdb_cnpj.manutencao import (
    compactar,
    limpar_backups,
    limpar_exports,
    listar_backups,
)
from dockdb_cnpj.queries import buscar_empresas

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


class Relogio:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_ttl_cache_expira_e_lru() -> None:
    rel = Relogio()
    c = TTLCache(ttl=10, max_items=2, clock=rel)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1  # "a" vira o mais recente
    c.set("c", 3)  # expulsa "b"
    assert c.get("b") is None
    assert c.get("c") == 3
    rel.t += 11
    assert c.get("a") is None
    s = c.stats()
    assert s["hits"] == 2 and s["misses"] == 2 and s["itens"] == 1


def test_rate_limiter_janela() -> None:
    rel = Relogio()
    rl = RateLimiter(2, janela=60, clock=rel)
    assert rl.permitir("ip")[0]
    assert rl.permitir("ip")[0]
    ok, espera = rl.permitir("ip")
    assert not ok and 0 < espera <= 61
    assert rl.permitir("outro_ip")[0]
    rel.t += 60
    assert rl.permitir("ip")[0]


def _carregar(db: Path, **kw) -> None:
    load_duckdb(zip_dir=FIXTURE, csv_dir=FIXTURE, db_path=db, extract=False, **kw)


def test_compactar_preserva_dados_e_fts(tmp_path: Path) -> None:
    db = tmp_path / "c.duckdb"
    _carregar(db, build_fts=True)
    con = connect(db, read_only=True)
    idx_antes = {r[0] for r in con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()}
    con.close()

    r = compactar(db, manter_backup=True, memoria="1GB")
    assert r["tabelas"] > 20
    assert r["backup"] and Path(r["backup"]).exists()
    assert not db.with_name(db.name + ".compact.tmp").exists()
    assert not db.with_name(db.name + ".compact.spill").exists()

    con = connect(db, read_only=True)
    assert con.execute("SELECT count(*) FROM estabelecimento").fetchone()[0] == 5
    assert con.execute("SELECT count(*) FROM municipio_ibge").fetchone()[0] > 5000
    assert buscar_empresas(con, q="ALFA", limit=5)[0]["cnpj"] == "12ABC34501DE35"  # FTS
    idx = {r[0] for r in con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()}
    assert "idx_estab_cnpj" in idx and idx == idx_antes
    con.close()


def test_compactar_libera_espaco(tmp_path: Path) -> None:
    import duckdb

    db = tmp_path / "e.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE fica AS SELECT range AS x FROM range(1000)")
    con.execute("CREATE TABLE lixo AS SELECT md5(range::VARCHAR) AS m FROM range(500000)")
    con.execute("CHECKPOINT")
    con.execute("CREATE TABLE depois AS SELECT range AS y FROM range(1000)")
    con.execute("CHECKPOINT")
    con.execute("DROP TABLE lixo")
    con.execute("CHECKPOINT")
    con.close()
    r = compactar(db)
    assert r["depois_bytes"] < r["antes_bytes"] / 2
    assert r["backup"] is None
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT count(*) FROM fica").fetchone()[0] == 1000
    assert con.execute("SELECT count(*) FROM depois").fetchone()[0] == 1000
    con.close()


def test_backup_rotativo_na_recarga(tmp_path: Path) -> None:
    db = tmp_path / "b.duckdb"
    _carregar(db, build_fts=False)
    assert listar_backups(db) == []
    _carregar(db, build_fts=False, manter_backups=1)
    bks = listar_backups(db)
    assert [p.name for p in bks] == ["b.duckdb.bak-202609"]
    time.sleep(0.01)
    _carregar(db, build_fts=False, manter_backups=1)
    bks = listar_backups(db)
    assert len(bks) == 1 and bks[0].name.startswith("b.duckdb.bak-202609-")
    assert db.exists()
    assert limpar_backups(db, manter=0, dry_run=True) == bks
    assert listar_backups(db) == bks
    limpar_backups(db, manter=0)
    assert listar_backups(db) == []


def test_limpar_exports(tmp_path: Path) -> None:
    velho = tmp_path / "velho.csv"
    novo = tmp_path / "novo.csv"
    velho.write_text("x")
    novo.write_text("y")
    antigo = time.time() - 48 * 3600
    os.utime(velho, (antigo, antigo))
    assert limpar_exports(tmp_path, max_idade_h=24) == [velho]
    assert not velho.exists() and novo.exists()
    assert limpar_exports(tmp_path, max_idade_h=0) == []
