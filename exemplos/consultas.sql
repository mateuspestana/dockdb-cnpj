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

-- Estabelecimentos ativos (situação 02) por CNAE
SELECT est.cnpj, e.razao_social, est.uf, c.descricao AS cnae
FROM estabelecimento est
JOIN empresas e ON e.cnpj_basico = est.cnpj_basico
LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
WHERE est.situacao_cadastral = '02'
  AND est.cnae_fiscal = '6201501'
LIMIT 50;

-- Referência da base
SELECT * FROM _referencia;
