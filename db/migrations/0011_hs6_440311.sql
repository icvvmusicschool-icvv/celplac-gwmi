-- CELPLAC GWMI · 0011 · SH6 encontrado na carga de 2024 sem produto associado
INSERT INTO dw.map_hs6_product (hs6, product_code, description_pt)
VALUES ('440311','ROUNDWOOD_CONIFER_OTHER','Madeira em bruto tratada com agentes de conservação — coníferas')
ON CONFLICT (hs6) DO NOTHING;
