"""
Carga dos CSVs públicos de CNPJ para DuckDB.

Layout alinhado ao projeto cnpj-sqlite (Receita Federal pós-2021),
incluindo correção de sócios a partir de ago/2026 (radical → CNPJ matriz).

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

import duckdb

from dockdb_cnpj.config import CSV_DIR, DB_PATH, ZIP_DIR, ensure_dirs
from dockdb_cnpj.db import connect

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

# CSVs da RF costumam ser Windows-1252 (bytes 0x80–0x9F). O encoding nativo
# "latin-1" do DuckDB rejeita esses bytes ("File is not latin-1 encoded").
CSV_ENCODING = "cp1252"


def _ensure_encodings(con: duckdb.DuckDBPyConnection) -> None:
    """Carrega a extensão encodings (necessária para cp1252 / windows-1252)."""
    try:
        con.execute("LOAD encodings")
    except duckdb.Error:
        con.execute("INSTALL encodings")
        con.execute("LOAD encodings")


def _sql_names(cols: list[str]) -> str:
    return ", ".join(cols)


def _read_csv_select(path: Path, cols: list[str]) -> str:
    """Gera SELECT tipado a partir de read_csv do DuckDB.

    Os CSVs da Receita têm:
    - encoding Windows-1252 (não ISO-8859-1 puro);
    - campos com quebras de linha entre aspas e linhas irregulares
      → parallel=false + null_padding.
    """
    p = str(path).replace("'", "''")
    names = "[" + ", ".join(f"'{c}'" for c in cols) + "]"
    return (
        f"SELECT * FROM read_csv('{p}', "
        f"header=false, "
        f"delim=';', "
        f"quote='\"', "
        f"escape='\"', "
        f"encoding='{CSV_ENCODING}', "
        f"names={names}, "
        f"all_varchar=true, "
        f"parallel=false, "
        f"null_padding=true, "
        f"ignore_errors=true, "
        f"strict_mode=false)"
    )


COLUNAS_EMPRESAS = [
    "cnpj_basico",
    "razao_social",
    "natureza_juridica",
    "qualificacao_responsavel",
    "capital_social_str",
    "porte_empresa",
    "ente_federativo_responsavel",
]

COLUNAS_ESTABELECIMENTO = [
    "cnpj_basico",
    "cnpj_ordem",
    "cnpj_dv",
    "matriz_filial",
    "nome_fantasia",
    "situacao_cadastral",
    "data_situacao_cadastral",
    "motivo_situacao_cadastral",
    "nome_cidade_exterior",
    "pais",
    "data_inicio_atividades",
    "cnae_fiscal",
    "cnae_fiscal_secundaria",
    "tipo_logradouro",
    "logradouro",
    "numero",
    "complemento",
    "bairro",
    "cep",
    "uf",
    "municipio",
    "ddd1",
    "telefone1",
    "ddd2",
    "telefone2",
    "ddd_fax",
    "fax",
    "correio_eletronico",
    "situacao_especial",
    "data_situacao_especial",
]

COLUNAS_SOCIOS = [
    "cnpj_basico",
    "identificador_de_socio",
    "nome_socio",
    "cnpj_cpf_socio",
    "qualificacao_socio",
    "data_entrada_sociedade",
    "pais",
    "representante_legal",
    "nome_representante",
    "qualificacao_representante_legal",
    "faixa_etaria",
]

COLUNAS_SIMPLES = [
    "cnpj_basico",
    "opcao_simples",
    "data_opcao_simples",
    "data_exclusao_simples",
    "opcao_mei",
    "data_opcao_mei",
    "data_exclusao_mei",
]

TABELAS_CODIGO = [
    (".CNAECSV", "cnae"),
    (".MOTICSV", "motivo"),
    (".MUNICCSV", "municipio"),
    (".NATJUCSV", "natureza_juridica"),
    (".PAISCSV", "pais"),
    (".QUALSCSV", "qualificacao_socio"),
]


def extract_zips(zip_dir: Path = ZIP_DIR, csv_dir: Path = CSV_DIR) -> list[Path]:
    ensure_dirs()
    zips = sorted(zip_dir.glob("*.zip"))
    if not zips:
        raise FileNotFoundError(
            f"Nenhum .zip em {zip_dir}. Rode scripts/download_cnpj.py primeiro."
        )
    print(f"Descompactando {len(zips)} arquivos em {csv_dir} …")
    for zpath in zips:
        print(f"  extract {zpath.name}")
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(csv_dir)
    return zips


def _detect_referencia(csv_dir: Path) -> tuple[str, str]:
    """Retorna (data_referencia dd/mm/aaaa, anoMes YYYYMM)."""
    empre = list(csv_dir.glob("*.EMPRECSV"))
    if not empre:
        raise FileNotFoundError(f"Nenhum .EMPRECSV em {csv_dir}")
    # Nome típico: K3241.K03200Y0.D30610.EMPRECSV → D30610
    parts = empre[0].name.split(".")
    aux = parts[2] if len(parts) >= 3 else ""
    if len(aux) == 6 and aux.startswith("D"):
        # D30610 → 10/06/2023? Original: D + year digit + MMDD
        # rictom: dataReferenciaAux[4:6]/[2:4]/202[1]  → DD/MM/202Y
        data_ref = f"{aux[4:6]}/{aux[2:4]}/202{aux[1]}"
        ano_mes = "202" + aux.removeprefix("D")[:3]  # 202 + YMM
        return data_ref, ano_mes
    return "desconhecida", "000000"


def _load_codigo(con: duckdb.DuckDBPyConnection, csv_dir: Path, ext: str, table: str) -> None:
    files = list(csv_dir.glob(f"*{ext}"))
    if not files:
        print(f"  aviso: nenhum arquivo *{ext}")
        return
    path = files[0]
    print(f"  {table} ← {path.name}")
    con.execute(f"DROP TABLE IF EXISTS {table}")
    src = _read_csv_select(path, ["codigo", "descricao"])
    con.execute(f"CREATE TABLE {table} AS {src}")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_codigo ON {table}(codigo)")


def _load_glob(
    con: duckdb.DuckDBPyConnection,
    csv_dir: Path,
    pattern: str,
    table: str,
    cols: list[str],
) -> None:
    files = sorted(csv_dir.glob(pattern))
    if not files:
        # fallback: pattern as suffix match
        files = sorted(p for p in csv_dir.iterdir() if p.name.endswith(pattern.lstrip("*")))
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo para {pattern} em {csv_dir}")

    con.execute(f"DROP TABLE IF EXISTS {table}")
    first = True
    for path in files:
        print(f"  {table} ← {path.name}")
        src = _read_csv_select(path, cols)
        if first:
            con.execute(f"CREATE TABLE {table} AS {src}")
            first = False
        else:
            con.execute(f"INSERT INTO {table} {src}")


def _post_process(con: duckdb.DuckDBPyConnection, ano_mes: str, data_ref: str) -> None:
    print("Pós-processamento …")
    try:
        con.execute("ALTER TABLE empresas ADD COLUMN capital_social DOUBLE")
    except duckdb.Error:
        pass
    con.execute(
        """
        UPDATE empresas SET capital_social =
            TRY_CAST(replace(capital_social_str, ',', '.') AS DOUBLE)
        """
    )
    try:
        con.execute("ALTER TABLE estabelecimento ADD COLUMN cnpj VARCHAR")
    except duckdb.Error:
        pass

    con.execute(
        """
        UPDATE estabelecimento
        SET cnpj = cnpj_basico || cnpj_ordem || cnpj_dv
        """
    )

    con.execute("DROP TABLE IF EXISTS cnpj_base2matriz")
    con.execute(
        """
        CREATE TABLE cnpj_base2matriz AS
        SELECT DISTINCT t.cnpj_basico, te.cnpj AS cnpj
        FROM empresas t
        LEFT JOIN estabelecimento te ON te.cnpj_basico = t.cnpj_basico
        WHERE te.matriz_filial = '1';
        """
    )

    con.execute("DROP TABLE IF EXISTS socios")
    if ano_mes >= "202608":
        con.execute(
            """
            CREATE TABLE socios AS
            SELECT te.cnpj AS cnpj, ts.*
            FROM socios_original ts
            LEFT JOIN cnpj_base2matriz te ON te.cnpj_basico = ts.cnpj_basico
            WHERE ts.identificador_de_socio <> '1';
            """
        )
        con.execute(
            """
            INSERT INTO socios
            SELECT
                te.cnpj AS cnpj,
                ts.cnpj_basico,
                ts.identificador_de_socio,
                ts.nome_socio,
                tes.cnpj AS cnpj_cpf_socio,
                ts.qualificacao_socio,
                ts.data_entrada_sociedade,
                ts.pais,
                ts.representante_legal,
                ts.nome_representante,
                ts.qualificacao_representante_legal,
                ts.faixa_etaria
            FROM socios_original ts
            LEFT JOIN cnpj_base2matriz te ON te.cnpj_basico = ts.cnpj_basico
            LEFT JOIN cnpj_base2matriz tes ON tes.cnpj_basico = ts.cnpj_cpf_socio
            WHERE ts.identificador_de_socio = '1';
            """
        )
    else:
        con.execute(
            """
            CREATE TABLE socios AS
            SELECT te.cnpj AS cnpj, ts.*
            FROM socios_original ts
            LEFT JOIN cnpj_base2matriz te ON te.cnpj_basico = ts.cnpj_basico;
            """
        )

    con.execute("DROP TABLE IF EXISTS socios_original")

    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_empresas_cnpj_basico ON empresas(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS idx_empresas_razao_social ON empresas(razao_social)",
        "CREATE INDEX IF NOT EXISTS idx_estab_cnpj_basico ON estabelecimento(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS idx_estab_cnpj ON estabelecimento(cnpj)",
        "CREATE INDEX IF NOT EXISTS idx_estab_uf ON estabelecimento(uf)",
        "CREATE INDEX IF NOT EXISTS idx_estab_cnae ON estabelecimento(cnae_fiscal)",
        "CREATE INDEX IF NOT EXISTS idx_socios_cnpj ON socios(cnpj)",
        "CREATE INDEX IF NOT EXISTS idx_socios_cpf ON socios(cnpj_cpf_socio)",
        "CREATE INDEX IF NOT EXISTS idx_simples_basico ON simples(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS idx_cnpj_base2matriz ON cnpj_base2matriz(cnpj_basico)",
    ]:
        try:
            con.execute(sql)
        except duckdb.Error as e:
            print(f"  índice (aviso): {e}")

    qtde = con.execute("SELECT count(*) FROM estabelecimento").fetchone()[0]
    con.execute("DROP TABLE IF EXISTS _referencia")
    con.execute(
        """
        CREATE TABLE _referencia (
            referencia VARCHAR,
            valor VARCHAR
        )
        """
    )
    con.execute("INSERT INTO _referencia VALUES ('CNPJ', ?)", [data_ref])
    con.execute("INSERT INTO _referencia VALUES ('cnpj_qtde', ?)", [str(qtde)])
    con.execute("INSERT INTO _referencia VALUES ('ano_mes', ?)", [ano_mes])
    con.execute(
        "INSERT INTO _referencia VALUES ('projeto', ?)",
        ["DockDB-CNPJ — Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>"],
    )


def load_duckdb(
    *,
    zip_dir: Path = ZIP_DIR,
    csv_dir: Path = CSV_DIR,
    db_path: Path = DB_PATH,
    extract: bool = True,
    remove_csv_after: bool = False,
) -> Path:
    """Extrai ZIPs (opcional) e cria/substitui a base DuckDB."""
    ensure_dirs()
    t0 = time.time()
    print(time.asctime(), "Início da carga DuckDB")

    if extract:
        extract_zips(zip_dir, csv_dir)

    data_ref, ano_mes = _detect_referencia(csv_dir)
    print(f"Referência detectada: {data_ref} (ano_mes={ano_mes})")

    if db_path.exists():
        print(f"Removendo base existente {db_path}")
        db_path.unlink()
        wal = Path(str(db_path) + ".wal")
        if wal.exists():
            wal.unlink()

    con = connect(db_path, read_only=False)
    try:
        _ensure_encodings(con)
        for ext, table in TABELAS_CODIGO:
            _load_codigo(con, csv_dir, ext, table)

        _load_glob(con, csv_dir, "*.EMPRECSV", "empresas", COLUNAS_EMPRESAS)
        _load_glob(con, csv_dir, "*.ESTABELE", "estabelecimento", COLUNAS_ESTABELECIMENTO)
        _load_glob(con, csv_dir, "*.SOCIOCSV", "socios_original", COLUNAS_SOCIOS)

        # SIMPLES: arquivos *SIMPLES.CSV* ou padrão .SIMPLES.CSV.*
        simples_files = sorted(csv_dir.glob("*SIMPLES.CSV*"))
        if not simples_files:
            simples_files = sorted(csv_dir.glob("*.SIMPLES.CSV.*"))
        if simples_files:
            con.execute("DROP TABLE IF EXISTS simples")
            first = True
            for path in simples_files:
                print(f"  simples ← {path.name}")
                src = _read_csv_select(path, COLUNAS_SIMPLES)
                if first:
                    con.execute(f"CREATE TABLE simples AS {src}")
                    first = False
                else:
                    con.execute(f"INSERT INTO simples {src}")
        else:
            print("  aviso: arquivos SIMPLES não encontrados")

        _post_process(con, ano_mes, data_ref)

        n_emp = con.execute("SELECT count(*) FROM empresas").fetchone()[0]
        n_est = con.execute("SELECT count(*) FROM estabelecimento").fetchone()[0]
        n_soc = con.execute("SELECT count(*) FROM socios").fetchone()[0]
        print(f"Empresas: {n_emp:,}")
        print(f"Estabelecimentos: {n_est:,}")
        print(f"Sócios: {n_soc:,}")
        print(f"Base criada: {db_path} ({db_path.stat().st_size / 1e9:.2f} GB)")
    finally:
        con.close()

    if remove_csv_after:
        for p in csv_dir.iterdir():
            if p.is_file() and not p.name.startswith("."):
                p.unlink()
        print("CSVs removidos após carga.")

    print(time.asctime(), f"Fim da carga ({time.time() - t0:.0f}s)")
    return db_path
