-- Exemplos de consulta — DockDB-CNPJ (DuckDB)
-- Autor: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
-- Inspirado nos exemplos do projeto cnpj-sqlite (https://github.com/rictom/cnpj-sqlite)

-- Contagem por UF
SELECT uf, count(*) AS estabelecimentos
FROM estabelecimento
GROUP BY uf
ORDER BY estabelecimentos DESC;

-- Empresa + matriz por CNPJ básico
SELECT e.cnpj_basico, e.razao_social, e.capital_social, est.cnpj, est.uf, est.nome_fantasia
FROM empresas e
JOIN estabelecimento est ON est.cnpj_basico = e.cnpj_basico AND est.matriz_filial = '1'
WHERE e.razao_social ILIKE '%PETROBRAS%'
LIMIT 20;

-- Sócios de um CNPJ (14 dígitos)
SELECT s.*
FROM socios s
WHERE s.cnpj = '00000000000191';

-- Estabelecimentos ativos (situação 02) por CNAE principal
SELECT est.cnpj, e.razao_social, est.uf, c.descricao AS cnae
FROM estabelecimento est
JOIN empresas e ON e.cnpj_basico = est.cnpj_basico
LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
WHERE est.situacao_cadastral = '02'
  AND est.cnae_fiscal = '6201501'
LIMIT 50;

-- Mesmo CNAE no principal OU na lista de secundários (campo CSV da RF)
SELECT est.cnpj, e.razao_social, est.uf,
       est.cnae_fiscal,
       est.cnae_fiscal_secundaria,
       CASE
         WHEN est.cnae_fiscal = '6201501' THEN 'principal'
         ELSE 'secundario'
       END AS cnae_origem
FROM estabelecimento est
JOIN empresas e ON e.cnpj_basico = est.cnpj_basico
WHERE est.cnae_fiscal = '6201501'
   OR list_contains(
        string_split(COALESCE(est.cnae_fiscal_secundaria, ''), ','),
        '6201501'
      )
LIMIT 50;

-- Referência da base
SELECT * FROM _referencia;

-- Validação pós-carga (v0.5)
SELECT * FROM _validacao;

-- Views materializadas (v0.5)
SELECT count(*) FROM mv_estabelecimento_ativo;
SELECT count(*) FROM mv_mei;
SELECT count(*) FROM mv_matriz;

-- Ponte CNAE (v0.5)
SELECT tipo, count(*) FROM estabelecimento_cnae GROUP BY 1;
