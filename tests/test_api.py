"""
Testes da API FastAPI sobre a fixture mínima.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dockdb_cnpj.load import load_duckdb

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "mini"


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> Iterator[TestClient]:
    db = tmp_path_factory.mktemp("apidb") / "api.duckdb"
    load_duckdb(zip_dir=FIXTURE, csv_dir=FIXTURE, db_path=db, extract=False, build_fts=False)
    sys.path.insert(0, str(ROOT))
    api_main = importlib.import_module("api.main")
    api_main.DB_PATH = db
    with TestClient(api_main.app) as c:
        yield c


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_cnpj_alfanumerico(client: TestClient) -> None:
    r = client.get("/cnpj/12ABC34501DE35")
    assert r.status_code == 200
    body = r.json()
    assert body["dv_valido"] is True
    assert body["estabelecimentos"][0]["municipio_ibge"] == "3304557"


def test_cnpj_invalido(client: TestClient) -> None:
    assert client.get("/cnpj/123").status_code == 400


def test_dv(client: TestClient) -> None:
    assert client.get("/dv/12ABC34501DE").json()["dv"] == "35"
    body = client.get("/dv/12ABC34501DE36").json()
    assert body["dv_valido"] is False
    assert body["dv_esperado"] == "35"


def test_empresas_ibge(client: TestClient) -> None:
    r = client.get("/empresas", params={"municipio_ibge": "3550308"})
    assert r.status_code == 200
    assert {x["cnpj"] for x in r.json()} == {"12345678000195", "87654321000198"}


def test_coortes_api(client: TestClient) -> None:
    r = client.get("/coortes", params={"freq": "ano", "uf": "SP"})
    assert r.status_code == 200
    assert {x["periodo"] for x in r.json()} == {"2019", "2020", "2021"}
    assert client.get("/coortes", params={"freq": "semana"}).status_code == 422


def test_enriquecer_api(client: TestClient) -> None:
    r = client.post("/enriquecer", json={"cnpjs": ["12ABC345", "00000000000000"]})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["cnpj"] == "12ABC34501DE35"
    assert body[1]["encontrado"] is False
    assert client.post("/enriquecer", json={"cnpjs": []}).status_code == 422


def test_agregados_api(client: TestClient) -> None:
    secoes = client.get("/agregados/cnae", params={"nivel": "secao"}).json()
    assert {x["secao"] for x in secoes} == {"J", "G"}
    mun = client.get("/agregados/municipio").json()
    assert mun and "latitude" in mun[0]
    assert client.get("/agregados/cnae", params={"nivel": "x"}).status_code == 400
