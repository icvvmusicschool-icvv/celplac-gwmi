-- 0019 — Fontes abertas para as lacunas dos sinais (frete, custos, macro) e regras v2.
-- Princípio: proxy nunca se passa pelo indicador original. Cada proxy é um indicador próprio,
-- com nome que diz o que é, e as regras que o usam ganham nova versão (a v1 fica no histórico).

INSERT INTO meta.source (source_id, name, url, source_type, periodicity, coverage, methodology, license_note, expected_lag_days, reliability) VALUES
('indec', 'INDEC — Argentina (via API de Series de Tiempo, datos.gob.ar)', 'https://apis.datos.gob.ar/series/api', 'oficial', 'mensal',
 'IPI manufacturero, ISAC (construção)', 'Índices oficiais; variação a/a calculada pela API (percent_change_a_year_ago)', 'Dados abertos', 45, 'ALTA')
ON CONFLICT (source_id) DO NOTHING;

INSERT INTO dw.dim_indicator (indicator_code, name_pt, unit, frequency, kind, polarity, category, source_id, source_ref, formula, pulse_key, description) VALUES
('FREIGHT_PPI_DEEPSEA_US', 'Frete marítimo de longo curso — PPI EUA (proxy de frete)', 'índice (dez/1988=100)', 'M', 'data', -1, 'freight', 'fred',
 'PCU483111483111', NULL, NULL, 'BLS via FRED. Preço ao produtor do transporte marítimo de longo curso nos EUA. PROXY: não é o índice de frete de contêiner (Drewry/FBX, licenciados).'),
('RESIN_PPI_THERMOSET_US', 'Resinas termofixas — PPI EUA (proxy de resina fenólica)', 'índice', 'M', 'data', -1, 'price', 'fred',
 'PCU3252113252114', NULL, NULL, 'BLS via FRED. Resinas termofixas incluem as fenólicas usadas em compensado. PROXY: não é a cotação da CELPLAC (Fase 5).'),
('US_PPI_SOFTWOOD_PLYWOOD', 'EUA — preço ao produtor: lâminas e compensado de coníferas', 'índice (1982=100)', 'M', 'data', 1, 'price', 'fred',
 'WPU083103', NULL, NULL, 'BLS via FRED. Referência de preço do produto concorrente no maior mercado do compensado BR.'),
('BR_IPP_WOOD', 'BR — preço ao produtor: produtos de madeira (IPP CNAE 16)', 'índice (dez/2018=100)', 'M', 'data', 1, 'price', 'ibge_sidra',
 '6903/v10008/c842:46625', NULL, NULL, 'IBGE IPP tabela 6903. Preço de saída da indústria de madeira (não é custo de tora).'),
('BR_LOG_PINUS_PRICE_IMPL', 'BR — preço implícito da tora de pinus p/ outras finalidades', 'R$/m³', 'A', 'indicator', -1, 'price', 'gwmi_calc',
 '291/v143÷v142/c194:33257', 'valor da produção (mil R$ × 1000) ÷ quantidade (m³), PEVS tabela 291, categoria 1.3.2.5', NULL,
 'Anual. Referência estrutural de custo de tora; não substitui cotação mensal (Ibá/CEPEA, licenciadas).')
ON CONFLICT (indicator_code) DO NOTHING;
UPDATE dw.dim_indicator SET expected_lag_days = 640 WHERE indicator_code = 'BR_LOG_PINUS_PRICE_IMPL';

UPDATE dw.dim_indicator SET source_ref = 'DCOILBRENTEU', description = 'EIA, via FRED (DCOILBRENTEU), US$/barril, diário'
 WHERE indicator_code = 'BRENT';
UPDATE dw.dim_indicator SET kind = 'indicator',
       formula = 'variação % sobre o mesmo mês do ano anterior do índice oficial de produção industrial do país',
       description = 'EUA: FRED INDPRO (a/a calculada) · UE: Eurostat sts_inpr_m B-D PCH_SM · China: NBS A020101 (via DBnomics) · Argentina: INDEC IPI manufacturero. México e Arábia Saudita: DADO INDISPONÍVEL (INEGI exige token; GASTAT sem API aberta).'
 WHERE indicator_code = 'MACRO_IP_YOY';
UPDATE dw.dim_indicator SET kind = 'indicator',
       formula = 'variação % sobre o mesmo mês do ano anterior do indicador oficial de construção do país',
       description = 'EUA: FRED TTLCONS, gasto nominal (a/a calculada) · UE: Eurostat sts_copr_m F PCH_SM · Argentina: INDEC ISAC. China, México e Arábia Saudita: DADO INDISPONÍVEL.'
 WHERE indicator_code = 'MACRO_CONSTRUCTION_YOY';

-- Regras v2: frete e resina passam a usar os proxies declarados; o resto é igual à v1.
INSERT INTO intel.signal_rule (rule_id, version, name, tone, conditions, markets, min_met_for_indication, is_active)
SELECT r.rule_id, 2, r.name, r.tone,
       (SELECT jsonb_agg(CASE
            WHEN c->>'indicator' = 'FREIGHT_CONTAINER_INDEX'
              THEN c || jsonb_build_object('indicator', 'FREIGHT_PPI_DEEPSEA_US', 'geo', 'USA',
                                           'label', (c->>'label') || ' (proxy: PPI frete marítimo EUA)')
            WHEN c->>'indicator' = 'PRICE_RESIN_PHENOLIC'
              THEN c || jsonb_build_object('indicator', 'RESIN_PPI_THERMOSET_US', 'geo', 'USA',
                                           'label', (c->>'label') || ' (proxy: PPI resinas termofixas EUA)')
            ELSE c END ORDER BY ord)
        FROM jsonb_array_elements(r.conditions) WITH ORDINALITY AS e(c, ord)),
       r.markets, r.min_met_for_indication, true
FROM intel.signal_rule r
WHERE r.version = 1 AND r.rule_id IN ('cost_pressure', 'demand_expansion', 'market_pressure')
ON CONFLICT DO NOTHING;
UPDATE intel.signal_rule SET is_active = false
 WHERE version = 1 AND rule_id IN ('cost_pressure', 'demand_expansion', 'market_pressure');
