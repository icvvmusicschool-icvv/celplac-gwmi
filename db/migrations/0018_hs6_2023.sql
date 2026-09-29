-- 0018 — SH6 que apareceram na carga de EXP_2023 (serrados de folhosas temperadas).
INSERT INTO dw.map_hs6_product (hs6, product_code, description_pt) VALUES
('440791', 'SAWN_OTHER', 'Madeira serrada de carvalho (Quercus spp.), espessura > 6 mm'),
('440794', 'SAWN_OTHER', 'Madeira serrada de cerejeira (Prunus spp.), espessura > 6 mm')
ON CONFLICT (hs6) DO NOTHING;
