-- 0013 — IBGE SIDRA: tabelas e categorias confirmadas no serviço de metadados (servicodados.ibge.gov.br/api/v3/agregados).
-- PEVS  tabela 291, variável 142 (quantidade produzida, m³), classificação 194 "Tipo de produto da silvicultura".
--       Detalhe por espécie existe de 2013 em diante:
--       33253 tora de eucalipto p/ papel e celulose · 33256 tora de eucalipto p/ outras finalidades
--       33254 tora de pinus p/ papel e celulose     · 33257 tora de pinus p/ outras finalidades
-- PIM-PF tabela 8888, variável 12607 (número-índice 2022=100 com ajuste sazonal),
--       classificação 544 categoria 129323 "3.16 Fabricação de produtos de madeira".
UPDATE dw.dim_indicator SET source_ref = '291/v142/c194:33254+33257',
       formula = 'soma das categorias oficiais 1.3.1.5 + 1.3.2.5 (tora de pinus: celulose + outras finalidades)',
       description = 'PEVS/IBGE tabela 291 — detalhe por espécie desde 2013'
 WHERE indicator_code = 'BR_SILV_PINUS_M3';
UPDATE dw.dim_indicator SET source_ref = '291/v142/c194:33253+33256',
       formula = 'soma das categorias oficiais 1.3.1.3 + 1.3.2.3 (tora de eucalipto: celulose + outras finalidades)',
       description = 'PEVS/IBGE tabela 291 — detalhe por espécie desde 2013'
 WHERE indicator_code = 'BR_SILV_EUCA_M3';
UPDATE dw.dim_indicator SET source_ref = '8888/v12607/c544:129323', unit = 'índice (2022=100, dessaz.)',
       description = 'PIM-PF/IBGE tabela 8888 — CNAE 16 Fabricação de produtos de madeira, com ajuste sazonal'
 WHERE indicator_code = 'BR_IP_WOOD';

INSERT INTO dw.dim_indicator (indicator_code, name_pt, unit, frequency, kind, polarity, category, source_id, source_ref, formula, pulse_key, description) VALUES
('BR_SILV_PINUS_OTHER_M3', 'BR — tora de pinus para outras finalidades (serraria, laminação)', 'm³', 'A', 'data', 1, 'production', 'ibge_sidra',
 '291/v142/c194:33257', NULL, NULL, 'PEVS/IBGE categoria 1.3.2.5 — matéria-prima de serrados, lâminas e compensados'),
('BR_SILV_EUCA_OTHER_M3', 'BR — tora de eucalipto para outras finalidades', 'm³', 'A', 'data', 1, 'production', 'ibge_sidra',
 '291/v142/c194:33256', NULL, NULL, 'PEVS/IBGE categoria 1.3.2.3')
ON CONFLICT (indicator_code) DO NOTHING;
