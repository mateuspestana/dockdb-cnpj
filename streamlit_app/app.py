"""
Interface Streamlit para consulta CNPJ (DuckDB).

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj import __email__, __version__  # noqa: E402
from dockdb_cnpj.config import DB_PATH, DEFAULT_QUERY_LIMIT  # noqa: E402
from dockdb_cnpj.db import connect  # noqa: E402
from dockdb_cnpj.queries import (  # noqa: E402
    buscar_empresas,
    consulta_cnpj,
    get_referencia,
    run_sql,
)
from dockdb_cnpj.sql_guard import UnsafeSQLError  # noqa: E402

__author__ = "Matheus Cavalcanti Pestana"

st.set_page_config(
    page_title="DockDB-CNPJ",
    page_icon="🦆",
    layout="wide",
)

st.title("DockDB-CNPJ")
st.caption(
    f"Consulta à base pública de CNPJ em DuckDB · v{__version__} · "
    f"Matheus Cavalcanti Pestana <{__email__}>"
)

with st.sidebar:
    st.header("Sobre")
    st.markdown(
        f"""
**Autor:** Matheus Cavalcanti Pestana  
**E-mail:** [{__email__}](mailto:{__email__})  

Inspirado no projeto
[cnpj-sqlite](https://github.com/rictom/cnpj-sqlite).

Base: `{DB_PATH}`
"""
    )
    if st.button("Recarregar conexão"):
        st.cache_resource.clear()


@st.cache_resource
def get_con():
    return connect(DB_PATH, read_only=True)


try:
    con = get_con()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

ref = get_referencia(con)
if ref:
    st.info(" · ".join(f"**{r['referencia']}:** {r['valor']}" for r in ref[:4]))

tab_cnpj, tab_buscar, tab_sql = st.tabs(["CNPJ", "Buscar", "SQL"])

with tab_cnpj:
    cnpj = st.text_input("CNPJ (8 ou 14 dígitos)", placeholder="00000000000191")
    if st.button("Consultar CNPJ", type="primary") and cnpj:
        try:
            data = consulta_cnpj(con, cnpj)
            st.subheader("Empresa(s)")
            st.dataframe(pd.DataFrame(data["empresas"]), use_container_width=True)
            st.subheader("Estabelecimento(s)")
            st.dataframe(
                pd.DataFrame(data["estabelecimentos"]), use_container_width=True
            )
            st.subheader("Sócios")
            st.dataframe(pd.DataFrame(data["socios"]), use_container_width=True)
            st.subheader("Simples / MEI")
            st.dataframe(pd.DataFrame(data["simples"]), use_container_width=True)
        except ValueError as e:
            st.error(str(e))

with tab_buscar:
    col1, col2, col3 = st.columns(3)
    with col1:
        uf = st.text_input("UF", placeholder="SP")
        cnae = st.text_input("CNAE fiscal")
    with col2:
        municipio = st.text_input("Código município")
        situacao = st.text_input("Situação cadastral", placeholder="02")
    with col3:
        q = st.text_input("Razão social / fantasia")
        limit = st.number_input("Limite", 1, 10000, DEFAULT_QUERY_LIMIT)
    if st.button("Buscar", type="primary"):
        rows = buscar_empresas(
            con,
            uf=uf or None,
            cnae=cnae or None,
            municipio=municipio or None,
            q=q or None,
            situacao=situacao or None,
            limit=int(limit),
        )
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
        if not df.empty:
            st.download_button(
                "Baixar CSV",
                df.to_csv(index=False).encode("utf-8"),
                file_name="dockdb_cnpj_busca.csv",
                mime="text/csv",
            )

with tab_sql:
    st.markdown("Apenas `SELECT` / `WITH`. DDL/DML são bloqueados.")
    sql = st.text_area(
        "SQL",
        height=160,
        value="SELECT uf, count(*) AS n FROM estabelecimento GROUP BY 1 ORDER BY 2 DESC LIMIT 30",
    )
    limit_sql = st.number_input("Limite SQL", 1, 10000, DEFAULT_QUERY_LIMIT, key="lim_sql")
    if st.button("Executar SQL", type="primary"):
        try:
            result = run_sql(con, sql, limit=int(limit_sql))
            df = pd.DataFrame(result["rows"])
            st.dataframe(df, use_container_width=True)
            st.caption(f"{result['count']} linha(s)")
            if not df.empty:
                st.download_button(
                    "Baixar CSV",
                    df.to_csv(index=False).encode("utf-8"),
                    file_name="dockdb_cnpj_sql.csv",
                    mime="text/csv",
                )
        except UnsafeSQLError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Erro: {e}")

st.divider()
st.caption(
    "DockDB-CNPJ · Matheus Cavalcanti Pestana "
    f"<{__email__}> · dados públicos da Receita Federal"
)
