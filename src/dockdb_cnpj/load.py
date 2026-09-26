"""
Carga dos CSVs públicos de CNPJ para DuckDB.

Layout alinhado ao projeto cnpj-sqlite (Receita Federal pós-2021),
incluindo correção de sócios a partir de ago/2026 (radical → CNPJ matriz).

v0.5: carga resumível, ponte estabelecimento_cnae, views materializadas, FTS.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import duckdb

from dockdb_cnpj.config import CSV_DIR, DATA_DIR, DB_PATH, ZIP_DIR, ensure_dirs
from dockdb_cnpj.db import connect
from dockdb_cnpj.validate import validar_base

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

CSV_ENCODING = "cp1252"

LOAD_STEPS = (
    "codigos",
    "empresas",
    "estabelecimento",
    "socios_original",
    "simples",
    "post_process",
)


def _ensure_encodings(con: duckdb.DuckDBPyConnection) -> None:
    try:
        con.execute("LOAD encodings")
    except duckdb.Error:
        con.execute("INSTALL encodings")
        con.execute("LOAD encodings")


def _sql_names(cols: list[str]) -> str:
    return ", ".join(cols)


def _read_csv_select(path: Path, cols: list[str]) -> str:
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


def _checkpoint_path(db_path: Path) -> Path:
    return Path(str(db_path) + ".load_checkpoint.json")


def _load_checkpoint(db_path: Path) -> dict:
    path = _checkpoint_path(db_path)
    if not path.exists():
        return {"completed": [], "files_done": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"completed": [], "files_done": {}}


def _save_checkpoint(db_path: Path, data: dict) -> None:
    path = _checkpoint_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_checkpoint(db_path: Path) -> None:
    path = _checkpoint_path(db_path)
    if path.exists():
        path.unlink()


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
    empre = list(csv_dir.glob("*.EMPRECSV"))
    if not empre:
        raise FileNotFoundError(f"Nenhum .EMPRECSV em {csv_dir}")
    parts = empre[0].name.split(".")
    aux = parts[2] if len(parts) >= 3 else ""
    if len(aux) == 6 and aux.startswith("D"):
        data_ref = f"{aux[4:6]}/{aux[2:4]}/202{aux[1]}"
        ano_mes = "202" + aux.removeprefix("D")[:3]
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
    *,
    files_done: set[str] | None = None,
    on_file_done=None,
) -> None:
    files = sorted(csv_dir.glob(pattern))
    if not files:
        files = sorted(p for p in csv_dir.iterdir() if p.name.endswith(pattern.lstrip("*")))
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo para {pattern} em {csv_dir}")

    done = files_done or set()
    pending = [p for p in files if p.name not in done]
    if not pending and done:
        print(f"  {table}: todos os arquivos já carregados (resume)")
        return

    table_exists = (
        con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1",
            [table],
        ).fetchone()
        is not None
    )

    first = not table_exists
    if first and not done:
        con.execute(f"DROP TABLE IF EXISTS {table}")

    for path in pending:
        print(f"  {table} ← {path.name}")
        src = _read_csv_select(path, cols)
        if first:
            con.execute(f"CREATE TABLE {table} AS {src}")
            first = False
        else:
            con.execute(f"INSERT INTO {table} {src}")
        if on_file_done:
            on_file_done(path.name)


def _build_estabelecimento_cnae(con: duckdb.DuckDBPyConnection) -> None:
    print("  ponte estabelecimento_cnae …")
    con.execute("DROP TABLE IF EXISTS estabelecimento_cnae")
    con.execute(
        """
        CREATE TABLE estabelecimento_cnae AS
        SELECT cnpj, cnae_fiscal AS cnae, 'principal' AS tipo
        FROM estabelecimento
        WHERE cnae_fiscal IS NOT NULL AND cnae_fiscal <> ''
        UNION ALL
        SELECT
            est.cnpj,
            trim(cnae_sec) AS cnae,
            'secundario' AS tipo
        FROM estabelecimento est,
             UNNEST(string_split(COALESCE(est.cnae_fiscal_secundaria, ''), ','))
                 AS t(cnae_sec)
        WHERE trim(cnae_sec) <> ''
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_estab_cnae_cnae ON estabelecimento_cnae(cnae)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_estab_cnae_cnpj ON estabelecimento_cnae(cnpj)"
    )


def _build_materialized_views(con: duckdb.DuckDBPyConnection) -> None:
    """Cria views (não cópias físicas) — evita duplicar dezenas de GB em disco."""
    print("  views (ativos / matriz / mei) …")
    con.execute("DROP VIEW IF EXISTS mv_estabelecimento_ativo")
    con.execute("DROP TABLE IF EXISTS mv_estabelecimento_ativo")
    con.execute(
        """
        CREATE VIEW mv_estabelecimento_ativo AS
        SELECT * FROM estabelecimento WHERE situacao_cadastral = '02'
        """
    )
    con.execute("DROP VIEW IF EXISTS mv_matriz")
    con.execute("DROP TABLE IF EXISTS mv_matriz")
    con.execute(
        """
        CREATE VIEW mv_matriz AS
        SELECT * FROM estabelecimento WHERE matriz_filial = '1'
        """
    )
    con.execute("DROP VIEW IF EXISTS mv_mei")
    con.execute("DROP TABLE IF EXISTS mv_mei")
    con.execute(
        """
        CREATE VIEW mv_mei AS
        SELECT est.*
        FROM estabelecimento est
        JOIN simples si ON si.cnpj_basico = est.cnpj_basico
        WHERE UPPER(COALESCE(si.opcao_mei, '')) = 'S'
        """
    )


def upgrade_base(
    con: duckdb.DuckDBPyConnection,
    *,
    build_cnae_bridge: bool = True,
    build_mvs: bool = True,
    build_fts: bool = True,
    run_validate: bool = True,
) -> dict:
    """Atualiza base já carregada com artefatos v0.5 (sem recarregar CSVs)."""
    out: dict = {}
    if build_cnae_bridge:
        _build_estabelecimento_cnae(con)
        out["estabelecimento_cnae"] = True
    if build_mvs:
        _build_materialized_views(con)
        out["views"] = True
    if build_fts:
        fts_ok = _build_fts(con)
        out["fts"] = fts_ok
        try:
            con.execute("DELETE FROM _referencia WHERE referencia = 'fts'")
            con.execute(
                "INSERT INTO _referencia VALUES ('fts', ?)",
                ["1" if fts_ok else "0"],
            )
        except duckdb.Error:
            pass
    if run_validate:
        out["validacao"] = validar_base(con, persist=True)
    return out


def _build_fts(con: duckdb.DuckDBPyConnection) -> bool:
    print("  índice FTS (razão social) …")
    try:
        try:
            con.execute("LOAD fts")
        except duckdb.Error:
            con.execute("INSTALL fts")
            con.execute("LOAD fts")
        con.execute("PRAGMA drop_fts_index('empresas')")
    except duckdb.Error:
        pass
    try:
        con.execute(
            "PRAGMA create_fts_index('empresas', 'cnpj_basico', 'razao_social', "
            "stemmer='none', stopwords='none')"
        )
        return True
    except duckdb.Error as e:
        print(f"  FTS (aviso): {e}")
        return False


def _post_process(
    con: duckdb.DuckDBPyConnection,
    ano_mes: str,
    data_ref: str,
    *,
    build_cnae_bridge: bool = True,
    build_mvs: bool = True,
    build_fts: bool = True,
    run_validate: bool = True,
) -> None:
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
    # Colunas explícitas (evita drift de schema com ts.*)
    socios_cols = """
        te.cnpj AS cnpj,
        ts.cnpj_basico,
        ts.identificador_de_socio,
        ts.nome_socio,
        ts.cnpj_cpf_socio,
        ts.qualificacao_socio,
        ts.data_entrada_sociedade,
        ts.pais,
        ts.representante_legal,
        ts.nome_representante,
        ts.qualificacao_representante_legal,
        ts.faixa_etaria
    """
    if ano_mes >= "202608":
        con.execute(
            f"""
            CREATE TABLE socios AS
            SELECT {socios_cols}
            FROM socios_original ts
            LEFT JOIN cnpj_base2matriz te ON te.cnpj_basico = ts.cnpj_basico
            WHERE ts.identificador_de_socio <> '1'
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
            WHERE ts.identificador_de_socio = '1'
            """
        )
    else:
        con.execute(
            f"""
            CREATE TABLE socios AS
            SELECT {socios_cols}
            FROM socios_original ts
            LEFT JOIN cnpj_base2matriz te ON te.cnpj_basico = ts.cnpj_basico
            """
        )

    con.execute("DROP TABLE IF EXISTS socios_original")

    if build_cnae_bridge:
        _build_estabelecimento_cnae(con)
    if build_mvs:
        _build_materialized_views(con)
    fts_ok = _build_fts(con) if build_fts else False

    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_empresas_cnpj_basico ON empresas(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS idx_empresas_razao_social ON empresas(razao_social)",
        "CREATE INDEX IF NOT EXISTS idx_estab_cnpj_basico ON estabelecimento(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS idx_estab_cnpj ON estabelecimento(cnpj)",
        "CREATE INDEX IF NOT EXISTS idx_estab_uf ON estabelecimento(uf)",
        "CREATE INDEX IF NOT EXISTS idx_estab_cnae ON estabelecimento(cnae_fiscal)",
        "CREATE INDEX IF NOT EXISTS idx_socios_cnpj ON socios(cnpj)",
        "CREATE INDEX IF NOT EXISTS idx_socios_cpf ON socios(cnpj_cpf_socio)",
        "CREATE INDEX IF NOT EXISTS idx_socios_nome ON socios(nome_socio)",
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
    con.execute(
        "INSERT INTO _referencia VALUES ('fts', ?)",
        ["1" if fts_ok else "0"],
    )

    if run_validate:
        print("  validação pós-carga …")
        result = validar_base(con, persist=True)
        print(f"  validação: {'OK' if result['ok'] else 'FALHAS'} ({len(result['checks'])} checks)")


def load_duckdb(
    *,
    zip_dir: Path = ZIP_DIR,
    csv_dir: Path = CSV_DIR,
    db_path: Path = DB_PATH,
    extract: bool = True,
    remove_csv_after: bool = False,
    resume: bool = False,
    build_cnae_bridge: bool = True,
    build_mvs: bool = True,
    build_fts: bool = True,
    run_validate: bool = True,
) -> Path:
    """Extrai ZIPs (opcional) e cria/substitui a base DuckDB.

    Com ``resume=True``, continua a partir do checkpoint
    (``{db}.load_checkpoint.json``) sem apagar a base.
    """
    ensure_dirs()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(time.asctime(), "Início da carga DuckDB")

    if extract:
        extract_zips(zip_dir, csv_dir)

    data_ref, ano_mes = _detect_referencia(csv_dir)
    print(f"Referência detectada: {data_ref} (ano_mes={ano_mes})")

    ckpt = _load_checkpoint(db_path) if resume else {"completed": [], "files_done": {}}
    completed = set(ckpt.get("completed") or [])
    files_done: dict[str, list[str]] = dict(ckpt.get("files_done") or {})

    if resume and db_path.exists():
        print(f"Resume ativo — steps feitos: {sorted(completed) or '(nenhum)'}")
    else:
        if db_path.exists():
            print(f"Removendo base existente {db_path}")
            db_path.unlink()
            wal = Path(str(db_path) + ".wal")
            if wal.exists():
                wal.unlink()
        _clear_checkpoint(db_path)
        completed = set()
        files_done = {}

    def mark_step(step: str) -> None:
        completed.add(step)
        _save_checkpoint(
            db_path,
            {"completed": sorted(completed), "files_done": files_done, "ano_mes": ano_mes},
        )

    def mark_file(step: str, name: str) -> None:
        files_done.setdefault(step, [])
        if name not in files_done[step]:
            files_done[step].append(name)
        _save_checkpoint(
            db_path,
            {"completed": sorted(completed), "files_done": files_done, "ano_mes": ano_mes},
        )

    con = connect(db_path, read_only=False)
    try:
        _ensure_encodings(con)

        if "codigos" not in completed:
            for ext, table in TABELAS_CODIGO:
                _load_codigo(con, csv_dir, ext, table)
            mark_step("codigos")
        else:
            print("  [skip] codigos")

        if "empresas" not in completed:
            _load_glob(
                con,
                csv_dir,
                "*.EMPRECSV",
                "empresas",
                COLUNAS_EMPRESAS,
                files_done=set(files_done.get("empresas") or []),
                on_file_done=lambda n: mark_file("empresas", n),
            )
            mark_step("empresas")
        else:
            print("  [skip] empresas")

        if "estabelecimento" not in completed:
            _load_glob(
                con,
                csv_dir,
                "*.ESTABELE",
                "estabelecimento",
                COLUNAS_ESTABELECIMENTO,
                files_done=set(files_done.get("estabelecimento") or []),
                on_file_done=lambda n: mark_file("estabelecimento", n),
            )
            mark_step("estabelecimento")
        else:
            print("  [skip] estabelecimento")

        if "socios_original" not in completed:
            _load_glob(
                con,
                csv_dir,
                "*.SOCIOCSV",
                "socios_original",
                COLUNAS_SOCIOS,
                files_done=set(files_done.get("socios_original") or []),
                on_file_done=lambda n: mark_file("socios_original", n),
            )
            mark_step("socios_original")
        else:
            print("  [skip] socios_original")

        if "simples" not in completed:
            simples_files = sorted(csv_dir.glob("*SIMPLES.CSV*"))
            if not simples_files:
                simples_files = sorted(csv_dir.glob("*.SIMPLES.CSV.*"))
            done_s = set(files_done.get("simples") or [])
            if simples_files:
                table_exists = (
                    con.execute(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name='simples' LIMIT 1"
                    ).fetchone()
                    is not None
                )
                first = not table_exists
                if first and not done_s:
                    con.execute("DROP TABLE IF EXISTS simples")
                for path in simples_files:
                    if path.name in done_s:
                        continue
                    print(f"  simples ← {path.name}")
                    src = _read_csv_select(path, COLUNAS_SIMPLES)
                    if first:
                        con.execute(f"CREATE TABLE simples AS {src}")
                        first = False
                    else:
                        con.execute(f"INSERT INTO simples {src}")
                    mark_file("simples", path.name)
            else:
                print("  aviso: arquivos SIMPLES não encontrados — tabela vazia")
                con.execute("DROP TABLE IF EXISTS simples")
                con.execute(
                    """
                    CREATE TABLE simples (
                        cnpj_basico VARCHAR,
                        opcao_simples VARCHAR,
                        data_opcao_simples VARCHAR,
                        data_exclusao_simples VARCHAR,
                        opcao_mei VARCHAR,
                        data_opcao_mei VARCHAR,
                        data_exclusao_mei VARCHAR
                    )
                    """
                )
            mark_step("simples")
        else:
            print("  [skip] simples")

        if "post_process" not in completed:
            try:
                con.execute("SELECT 1 FROM simples LIMIT 1")
            except duckdb.Error:
                con.execute(
                    """
                    CREATE TABLE simples (
                        cnpj_basico VARCHAR,
                        opcao_simples VARCHAR,
                        data_opcao_simples VARCHAR,
                        data_exclusao_simples VARCHAR,
                        opcao_mei VARCHAR,
                        data_opcao_mei VARCHAR,
                        data_exclusao_mei VARCHAR
                    )
                    """
                )
            _post_process(
                con,
                ano_mes,
                data_ref,
                build_cnae_bridge=build_cnae_bridge,
                build_mvs=build_mvs,
                build_fts=build_fts,
                run_validate=run_validate,
            )
            mark_step("post_process")
        else:
            print("  [skip] post_process")

        n_emp = con.execute("SELECT count(*) FROM empresas").fetchone()[0]
        n_est = con.execute("SELECT count(*) FROM estabelecimento").fetchone()[0]
        n_soc = con.execute("SELECT count(*) FROM socios").fetchone()[0]
        print(f"Empresas: {n_emp:,}")
        print(f"Estabelecimentos: {n_est:,}")
        print(f"Sócios: {n_soc:,}")
        print(f"Base criada: {db_path} ({db_path.stat().st_size / 1e9:.2f} GB)")
    finally:
        con.close()

    ckpt_final = _load_checkpoint(db_path)
    if "post_process" in set(ckpt_final.get("completed") or []):
        _clear_checkpoint(db_path)

    if remove_csv_after:
        for p in csv_dir.iterdir():
            if p.is_file() and not p.name.startswith("."):
                p.unlink()
        print("CSVs removidos após carga.")

    print(time.asctime(), f"Fim da carga ({time.time() - t0:.0f}s)")
    return db_path
