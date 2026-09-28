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
from dockdb_cnpj.analytics import agregados_municipio, coortes  # noqa: E402
from dockdb_cnpj.config import DB_PATH, DEFAULT_QUERY_LIMIT  # noqa: E402
from dockdb_cnpj.db import connect  # noqa: E402
from dockdb_cnpj.enriquecimento import enriquecer, ler_lista  # noqa: E402
from dockdb_cnpj.queries import (  # noqa: E402
    agregados_cnae,
    agregados_situacao,
    agregados_uf,
    buscar_empresas,
    buscar_socios,
    consulta_cnpj,
    get_referencia,
    run_sql,
)
from dockdb_cnpj.sql_guard import UnsafeSQLError  # noqa: E402

__author__ = "Matheus Cavalcanti Pestana"

st.set_page_config(page_title="DockDB-CNPJ", page_icon="🦆", layout="wide")

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
    st.info(" · ".join(f"**{r['referencia']}:** {r['valor']}" for r in ref[:5]))

tab_cnpj, tab_buscar, tab_lista, tab_socio, tab_agg, tab_sql = st.tabs(
    ["CNPJ", "Buscar", "Lista", "Sócio", "Analytics", "SQL"]
)


def mapa(df: pd.DataFrame, size: str | None = None) -> None:
    if df.empty or "latitude" not in df:
        return
    pts = df.dropna(subset=["latitude", "longitude"])
    if pts.empty:
        return
    if size:
        st.map(pts, latitude="latitude", longitude="longitude", size=size)
    else:
        st.map(pts, latitude="latitude", longitude="longitude")

with tab_cnpj:
    cnpj = st.text_input(
        "CNPJ (8 ou 14 posições — aceita alfanumérico)", placeholder="12.ABC.345/01DE-35"
    )
    if st.button("Consultar CNPJ", type="primary") and cnpj:
        try:
            data = consulta_cnpj(con, cnpj)
            st.markdown(f"**{data['cnpj_formatado']}**")
            if data.get("dv_valido") is False:
                st.warning(
                    f"Dígito verificador inválido (esperado: {data.get('dv_esperado')})."
                )
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
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        uf = st.text_input("UF", placeholder="SP")
        cnae = st.text_input("CNAE")
        cnae_secao = st.text_input("Seção CNAE", placeholder="J")
        cnae_divisao = st.text_input("Divisão CNAE", placeholder="62")
        porte = st.text_input("Porte", placeholder="01")
    with c2:
        municipio = st.text_input("Município (código RF ou nome)")
        municipio_ibge = st.text_input("Município (código IBGE)", placeholder="3304557")
        situacao = st.text_input("Situação", placeholder="02")
        matriz_filial = st.selectbox("Matriz/Filial", ["", "1", "2"], format_func=lambda x: {"": "(qualquer)", "1": "Matriz", "2": "Filial"}[x])
    with c3:
        q = st.text_input("Razão social / fantasia")
        capital_min = st.number_input("Capital mín.", value=0.0, min_value=0.0)
        capital_max = st.number_input("Capital máx.", value=0.0, min_value=0.0)
    with c4:
        limit = st.number_input("Limite", 1, 10000, DEFAULT_QUERY_LIMIT)
        mei_opt = st.selectbox("MEI", ["(qualquer)", "sim", "não"])
        simples_opt = st.selectbox("Simples", ["(qualquer)", "sim", "não"])
    incluir_secundario = st.checkbox("Incluir CNAE secundário", value=True)
    fuzzy = st.checkbox("Busca fuzzy (Jaro-Winkler)", value=False)
    if st.button("Buscar", type="primary"):
        mei = None if mei_opt.startswith("(") else mei_opt == "sim"
        simples = None if simples_opt.startswith("(") else simples_opt == "sim"
        try:
            rows = buscar_empresas(
                con,
                uf=uf or None,
                cnae=cnae or None,
                incluir_cnae_secundario=incluir_secundario,
                municipio=municipio or None,
                municipio_ibge=municipio_ibge or None,
                cnae_secao=cnae_secao or None,
                cnae_divisao=cnae_divisao or None,
                q=q or None,
                fuzzy=fuzzy,
                situacao=situacao or None,
                porte=porte or None,
                matriz_filial=matriz_filial or None,
                mei=mei,
                simples=simples,
                capital_min=capital_min or None,
                capital_max=capital_max or None,
                limit=int(limit),
            )
        except ValueError as e:
            st.error(str(e))
            st.stop()
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
        if not df.empty:
            st.download_button(
                "Baixar CSV",
                df.to_csv(index=False).encode("utf-8"),
                file_name="dockdb_cnpj_busca.csv",
                mime="text/csv",
            )
            st.caption(
                "Mapa: centroide do município, ou ponto do CEP quando geocodificado "
                "(`geocodificar` na CLI)."
            )
            mapa(df)

with tab_lista:
    st.markdown(
        "Envie um **.csv / .txt / .parquet** com CNPJs (8 ou 14 posições). "
        "A coluna com “cnpj” no nome é detectada; zeros à esquerda perdidos são recuperados."
    )
    arq = st.file_uploader("Lista de CNPJs", type=["csv", "txt", "parquet"])
    col_lista = st.text_input("Coluna (opcional)")
    if arq is not None and st.button("Enriquecer", type="primary"):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=Path(arq.name).suffix, delete=False) as tmp:
            tmp.write(arq.getvalue())
        try:
            lista = ler_lista(tmp.name, coluna=col_lista or None)
            df_l = pd.DataFrame(enriquecer(con, lista))
        except ValueError as e:
            st.error(str(e))
            st.stop()
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        if not df_l.empty:
            st.caption(f"{int(df_l['encontrado'].sum())}/{len(df_l)} encontrados")
        st.dataframe(df_l, use_container_width=True)
        if not df_l.empty:
            st.download_button(
                "Baixar CSV",
                df_l.to_csv(index=False).encode("utf-8"),
                file_name="dockdb_cnpj_lista.csv",
                mime="text/csv",
            )

with tab_socio:
    snome = st.text_input("Nome do sócio")
    sdoc = st.text_input("CPF/CNPJ do sócio")
    slimit = st.number_input("Limite sócios", 1, 10000, 100, key="sl")
    if st.button("Buscar sócio", type="primary"):
        try:
            rows = buscar_socios(
                con, nome=snome or None, documento=sdoc or None, limit=int(slimit)
            )
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        except ValueError as e:
            st.error(str(e))

with tab_agg:
    st.subheader("Estabelecimentos por UF")
    df_uf = pd.DataFrame(agregados_uf(con, limit=30))
    if not df_uf.empty:
        st.bar_chart(df_uf.set_index("uf")["estabelecimentos"])
        st.dataframe(df_uf, use_container_width=True)
    st.subheader("Situação cadastral")
    df_sit = pd.DataFrame(agregados_situacao(con))
    if not df_sit.empty:
        st.bar_chart(df_sit.set_index("situacao_desc")["n"])
        st.dataframe(df_sit, use_container_width=True)
    uf_cnae = st.text_input("UF para top CNAE", placeholder="SP", key="ufc")
    nivel = st.selectbox(
        "Nível CNAE", ["subclasse", "classe", "grupo", "divisao", "secao"], key="nivel"
    )
    st.subheader("Top CNAE (ativos)")
    try:
        df_c = pd.DataFrame(agregados_cnae(con, uf=uf_cnae or None, nivel=nivel, limit=20))
        if not df_c.empty:
            st.dataframe(df_c, use_container_width=True)
    except ValueError as e:
        st.warning(str(e))

    st.subheader("Coortes: aberturas, baixas e sobrevivência")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        c_freq = st.selectbox("Frequência", ["ano", "mes"], key="cfreq")
    with k2:
        c_uf = st.text_input("UF", key="cuf")
    with k3:
        c_secao = st.text_input("Seção CNAE", key="csec")
    with k4:
        c_desde = st.text_input("Desde (AAAA/AAAAMM)", value="2000", key="cdesde")
    if st.button("Calcular coortes"):
        try:
            df_co = pd.DataFrame(
                coortes(
                    con,
                    freq=c_freq,  # type: ignore[arg-type]
                    uf=c_uf or None,
                    cnae_secao=c_secao or None,
                    desde=c_desde or None,
                )
            )
        except ValueError as e:
            st.error(str(e))
            st.stop()
        if not df_co.empty:
            st.line_chart(df_co.set_index("periodo")[["aberturas", "baixas"]])
            st.line_chart(df_co.set_index("periodo")["taxa_sobrevivencia"])
            st.dataframe(df_co, use_container_width=True)
        st.caption(
            "Retrato do dump atual: baixas = estabelecimentos hoje baixados, pela data da "
            "situação; sobrevivência = fração das aberturas do período ainda ativa hoje."
        )

    st.subheader("Mapa: ativos por município")
    m_uf = st.text_input("UF (vazio = Brasil)", key="muf")
    if st.button("Gerar mapa"):
        try:
            df_m = pd.DataFrame(agregados_municipio(con, uf=m_uf or None))
        except ValueError as e:
            st.error(str(e))
            st.stop()
        if not df_m.empty:
            df_m["raio"] = (df_m["n"] ** 0.5) * 40
            mapa(df_m, size="raio")
            st.dataframe(df_m, use_container_width=True)

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
        except UnsafeSQLError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Erro: {e}")

st.divider()
st.caption(
    "DockDB-CNPJ · Matheus Cavalcanti Pestana "
    f"<{__email__}> · dados públicos da Receita Federal"
)
