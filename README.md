# CELPLAC Global Wood Market Intelligence — Fases 2 e 3

Banco de dados, ETL, histórico, qualidade de dados e API da plataforma.
A Fase 1 (protótipo navegável com dados DEMO) está em `frontend/prototype/index.html`.

```
FONTES ─► INGESTÃO ─► RAW ─► STAGING ─► VALIDAÇÃO ─► DW (versionado) ─► INDICADORES ─► ANALYTICS ─► API ─► DASHBOARD
Comex     gwmi-etl    arquivo   stg.*      linha:      dw.fact_trade     mart.*          sinais,        FastAPI  React
BCB       (Python)    + SHA256             Python      dw.fact_series    (SQL)           ciclo,         /v1/*
IBGE…                 raw.ingestion        conjunto:   dim_*                             índice
                                           dq.rule (SQL)                                 (gwmi_core)
```

## O que tem aqui

| Pasta | Conteúdo |
|---|---|
| `db/migrations/` | 22 migrações SQL (0009–0022 vieram das cargas reais). `db/migrate.sh` aplica com controle de checksum |
| `etl/` | Pacote `gwmi-etl`: conectores, pipeline, validação, gerador DEMO, CLI |
| `core/` | Pacote `gwmi-core`: funções analíticas puras (sinais, ciclo, índice, correlação) usadas pelo ETL e pela API |
| `backend/` | API FastAPI, 27 endpoints em `/v1` + `/health`, consultas em `app/sql/queries.sql` |
| `frontend/src/api/` | Contratos TypeScript e cliente para o React da Fase 3 |
| `tests/` | 46 testes; fixtures no formato das fontes reais |
| `infra/` | Agenda sugerida para o ETL (crontab) |
| `scripts/` | `load_comex_local.py` (CSVs baixados), `browser_comex_to_neon.js` e `browser_series_to_neon.js` (carga via navegador → API HTTP do Neon), `browser_comtrade_collect.js` (Comtrade sem chave), `fred_csv_to_sql.py`, `signals_offline.py`, `browser_macro_collect.js` |

## Início rápido (Docker)

```bash
cp .env.example .env                  # troque a senha
docker compose up -d db
docker compose run --rm etl migrate   # cria o modelo de dados
docker compose run --rm etl seed-demo # carrega o conjunto DEMO (is_simulated = true)
docker compose up -d api              # http://localhost:8000/docs
```

## Carregar dados reais (Fase 3 começa aqui)

```bash
docker compose run --rm etl comex-reference              # países, NCM cap. 44, unidades, URF (tabelas oficiais)
docker compose run --rm etl comex-trade --flow X --year 2025
docker compose run --rm etl comex-trade --flow X --year 2026
docker compose run --rm etl ptax -c USD -c EUR -c GBP --start 2021-01-01    # PTAX não publica CNY/MXN
docker compose run --rm etl fred                        # HOUST, HOUST1F, PERMIT, DEXMXUS, DEXCHUS (+ câmbio cruzado)
                                                        # sem FRED_API_KEY usa o fredgraph.csv público
docker compose run --rm etl pevs                        # IBGE PEVS 291: tora de pinus/eucalipto
docker compose run --rm etl pim-wood                    # IBGE PIM-PF 8888: produção de produtos de madeira
docker compose run --rm etl comtrade-preview -p 2024 -p 2025                       # concorrentes (SH 4412/4408/4407)
docker compose run --rm etl comtrade-preview -c 4412 --flow M --partner 0,76 -p 202501 -p 202502   # importações dos mercados
docker compose run --rm etl manual --file /data/inbox/frete.csv --source drewry  # fontes licenciadas
docker compose run --rm etl derive && docker compose run --rm etl signals && docker compose run --rm etl dq
docker compose run --rm etl status   # INTEGRADO / SIMULADO / SEM DADOS por fonte
```

Todo conector aceita `--file` para processar um arquivo já baixado (útil quando o portal está fora do ar ou atrás de proxy).

## Princípios implementados no banco, não só na interface

**Nunca apresentar dado simulado como real.** Cada linha de fato tem `is_simulated`. As views `mart.v_trade_effective` e `mart.v_series_effective` escolhem, por recorte, o dado real quando ele existe e ignoram o DEMO daquele recorte. A API calcula `meta.is_simulated` a partir das linhas retornadas. Com `meta.setting api.allow_simulated = false`, a API passa a responder `DADO INDISPONÍVEL` em vez de servir dados simulados.

**Histórico e revisões.** O Comex Stat e a Comtrade revisam números. O merge nunca sobrescreve: a versão anterior fica `is_current = false` e a nova entra com `version + 1`, apontando para o run que a trouxe. `dw.trade_as_of(timestamp)` responde "qual era este número naquela data?".

**"De onde veio este número?"** Fato → `run_id` → `meta.etl_run` (job, parâmetros, horário) → `raw.ingestion` (URL, SHA-256, arquivo guardado) → `meta.source` (metodologia, periodicidade, licença). O caminho está exposto em `/v1/trace/trade/{id}` e `/v1/trace/series/{indicador}`.

**Dado ausente não vira zero.** O parser marca valores faltantes (`..`, `...`, `X`, `.`) como `obs_status = 'M'`. A condição de sinal sem série fica "sem dado". Resposta vazia = `DADO INDISPONÍVEL`.

**Separação epistêmica.** `dim_indicator.kind` distingue dado de indicador, e o indicador leva a fórmula registrada. `intel.analysis_note.kind` distingue análise, hipótese e tendência. Um evento geopolítico exige evidência para ser registrado. Sinais só podem resultar em `SINAL`, `INDICAÇÃO`, `SEM SINAL` ou `EVIDÊNCIA INSUFICIENTE`, nunca em previsão. Correlação sempre sai com a nota "correlação ≠ causalidade".

**Pesos do índice não definitivos.** A configuração padrão usa pesos iguais. Cada nova configuração é registrada em `intel.index_config`, e o resultado lista os componentes usados e os excluídos (com o motivo).

## Qualidade de dados

- **Por linha (antes do staging):** as linhas rejeitadas vão para `dq.rejected_row` com o conteúdo original e o motivo.
- **Por conjunto (`dq.rule`, SQL declarativo, historizado em `dq.result`):** valores negativos, país não mapeado, volume em m³ indisponível, SH6 sem produto, preço fora de ±3σ, meses ausentes, divergência >15% entre a exportação BR e o espelho Comtrade, série desatualizada, salto >5σ e evento sem evidência.
- **`dq.v_source_quality`:** cobertura, último período, último run e situação de cada fonte (INTEGRADO / SIMULADO / SEM DADOS).

## Endpoints (`/docs` traz o OpenAPI completo)

`/pulse` · `/indicators` · `/series/{code}` · `/latest` · `/fx` · `/correlation` · `/macro` ·
`/trade/exports/summary` · `/trade/exports/destinations` · `/trade/exports/shift` · `/trade/exports/by-hs6` ·
`/trade/flows` · `/trade/monthly` · `/trade/ncm` · `/trade/ncm/search` · `/trade/competitors` ·
`/events` · `/news` · `/alerts` · `/signals` · `/cycle` · `POST /index` ·
`/sources` · `/quality` · `/runs` · `/trace/trade/{id}` · `/trace/series/{code}`

Toda resposta segue o formato `{status, data, meta:{is_simulated, kind, sources[], period, notes[], generated_at}}`.

## Testes

```bash
export GWMI_TEST_ADMIN_DSN="postgresql://gwmi:gwmi@localhost:5432/postgres"
pip install -e core -e etl -r backend/requirements.txt pytest
pytest tests/            # ou: python tests/run_all.py
```

Os testes rodam de ponta a ponta contra um PostgreSQL real e cobrem:
- carga das tabelas oficiais;
- rejeição de linha inválida;
- idempotência da recarga;
- revisão com nova versão e consulta "as of";
- rastreio até o arquivo original (SHA-256);
- conectores PTAX, FRED, SIDRA, Comtrade e CSV manual;
- derivados, regras de qualidade, sinais e ciclo;
- dado real substituindo o DEMO automaticamente;
- o interruptor `allow_simulated`;
- todas as consultas da API e a lógica de cada grupo de endpoints.

## O que foi verificado nesta entrega e o que ainda falta confirmar

**Verificado:**
- As 22 migrações foram aplicadas em PostgreSQL 16 local e os 46 testes passaram.
- No Neon, as mesmas migrações estão aplicadas e os dados reais foram conferidos:
  - totais do Comex contra uma carga local independente;
  - SHA-256 dos arquivos FRED e Comtrade contra os calculados na coleta;
  - PEVS 2024: pinus = 16.276.790 + 31.318.750 m³, conforme a tabela 291.

**Ainda não exercitado:**
- **Camada HTTP:** o servidor FastAPI não foi exercitado por HTTP. O primeiro `docker compose up api` + `/docs` fecha essa verificação.
- **Conectores Python ao vivo:** `fred`, `pevs`, `pim-wood` e `comtrade-preview` foram testados com fixtures no formato real. As cargas reais foram feitas pelo navegador com a mesma lógica.

**Confirmar:**
- **Densidades kg→m³:** usadas só quando a unidade estatística não é m³. Validar com a engenharia da CELPLAC.
- **SH6 do capítulo 44:** conferir contra a NCM vigente. Hoje estão com `is_verified = false`.
- **Frete (Drewry/FBX) e ITTO:** licença de uso. Por isso entram via CSV manual.
- **Comtrade com chave:** a API paga ou gratuita com chave dá SH6 e acesso sem o limite de 500 linhas. A pré-visualização basta para os totais SH4.

## API no ar (Render + Neon)

A API FastAPI serve também o painel: `https://<serviço>.onrender.com/` abre o painel, que lê `/v1/panel` ao vivo.

- **Chave de acesso:** toda rota `/v1/*` exige `X-API-Key` (ou `Authorization: Bearer`). As chaves ficam em `GWMI_API_KEYS` (vírgula separa várias; mínimo 32 caracteres). Sem chave configurada a API recusa tudo. `/health` e `/docs` não exigem chave e não expõem dados. `GWMI_OPEN_READ=1` libera só leitura — use apenas localmente.
- **Papel de banco próprio (migração 0022):** a API conecta como `gwmi_api`, que lê todos os esquemas e só grava em `intel.index_config`. Crie o papel no Console do Neon (Roles → New role) e rode `SELECT meta.grant_api_role();`. Nunca use a string do `gwmi_owner` no servidor.
- **Render:** `render.yaml` é um Blueprint (Docker, região Virginia, health check em `/health`). `DATABASE_URL` é pedida na criação e não fica no repositório; `GWMI_API_KEYS` é gerada pelo Render.
- **Painel:** `frontend/painel-real/build.py live` gera `backend/app/static/painel.html` (sem dados embutidos). `build.py snapshot …` gera o retrato publicado sem API.
- **Neon Functions** não está disponível na região São Paulo; por isso o servidor é externo.

## Banco em produção — Neon

- **Onde:** projeto `celplac-gwmi` (id `royal-breeze-27060137`), região AWS São Paulo, PostgreSQL 16, banco `gwmi`. As 22 migrações estão aplicadas (tabela `meta.schema_migrations`, com checksum).
- **Conectar a API:** `DATABASE_URL` é a connection string do console do Neon. Use o host *pooler* e `sslmode=require`, e **não versione a senha**.
- **Credencial:** a senha usada nas cargas pelo navegador precisa ser trocada (Console → Branches → main → Roles → `gwmi_owner` → Reset password). A nova senha deve ir só para o `.env`/cofre do servidor da API, nunca para código ou conversa.
- **Nenhum dado DEMO no Neon:** todas as linhas têm `is_simulated = false`.

### O que está carregado (25/09/2026)

| Fonte | Conteúdo | Linhas | Até |
|---|---|---|---|
| Comex Stat | Tabelas oficiais + exportações cap. 44 (SH4 4403, 4407, 4408, 4410, 4411, 4412), 2023–2026 | 39.114 | ago/2026 |
| BCB PTAX | USD, EUR, GBP — boletim de fechamento, desde 2021 | 4.314 | 23/09/2026 |
| FRED | Housing starts (total e unifamiliar), licenças de construção, MXN/US$ e CNY/US$ (Fed H.10) | 3.940 | ago–set/2026 |
| Câmbio cruzado (indicador) | MXN/BRL e CNY/BRL = PTAX ÷ H.10 no mesmo dia útil | 2.770 | set/2026 |
| IBGE PEVS 291 | Tora de pinus e eucalipto (total e "outras finalidades"), 2013–2025. A PEVS 2025 saiu e o IBGE revisou 2024: a revisão virou nova versão, a anterior segue consultável | 52 (+4 versões) | 2025 |
| IBGE PIM-PF 8888 | Produção física de produtos de madeira (CNAE 16), dessazonalizada, 2002– | 295 | jul/2026 |
| UN Comtrade | Exportadores mundiais (SH 4412, 4408, 4407), anual 2023–2025 | 972 | 2025 (parcial) |
| UN Comtrade | Importações de SH 4412 de 31 mercados, do mundo e do Brasil, mensal | 2.219 | jul/2026 (parcial) |
| FRED (custos, frete, macro EUA) | Brent diário; PPI EUA de frete marítimo, resinas termofixas e compensado de coníferas; produção industrial e gasto em construção dos EUA (variação a/a) | 1.965 | set/2026 |
| Eurostat | UE-27: produção industrial (B–D) e produção da construção (F), a/a, ajustadas | 134 | jul/2026 |
| NBS China (via DBnomics) | Produção industrial, a/a | 13 (valores até dez/2025) | dez/2025 (**parada**: jan–fev/2026 vêm sem valor e o espelho DBnomics não traz meses posteriores) |
| INDEC (datos.gob.ar) | Argentina: IPI manufatureiro e ISAC (construção), a/a | 110 | jul/2026 |
| IBGE IPP 6903 | Preço ao produtor de produtos de madeira (CNAE 16) | 200 | jul/2026 |
| Indicador calculado | Preço implícito da tora de pinus p/ outras finalidades (PEVS: valor ÷ quantidade), 2013–2025 | 13 | 2025 (R$ 164,77/m³) |

Cada carga tem `meta.etl_run` e `raw.ingestion` com o SHA-256 do arquivo original.

### Decisões tomadas com os dados reais

- **CNY e MXN:** o serviço PTAX só publica AUD, CAD, CHF, DKK, EUR, GBP, JPY, NOK, SEK e USD. Por isso `FX_MXN_BRL` e `FX_CNY_BRL` viraram **indicadores calculados** (`kind = indicator`, fórmula registrada): PTAX ÷ taxa H.10 do Fed. Os horários de referência diferem (BCB ~13h × Fed meio-dia NY).
- **IBGE:** as tabelas e categorias foram confirmadas no serviço de metadados:
  - PEVS 291, variável 142, classificação 194 (detalhe por espécie só existe a partir de 2013);
  - PIM-PF 8888, variável 12607, categoria 129323.
  - Quando uma das parcelas de uma soma falta, o total fica **ausente**, nunca parcial.
- **Comtrade sem chave:** a API pública de pré-visualização serve os totais por SH4.
  - Os valores entram como pseudo-SH6 (`441200`, `440800`, `440700` → produtos "agregado SH4").
  - O volume em m³ fica **indisponível** de propósito: sem unidade m³ declarada, não há estimativa por densidade.
  - Importações usam o valor do importador, que é CIF na maioria dos países.
  - O Brasil como exportador vem do Comex Stat, nunca da Comtrade.
- **Concorrentes:** o ano padrão passou a ser o último ano fechado com cobertura de reportantes ≥ 90% da do ano anterior. Hoje é **2024**, porque 2025 tem só 91 dos 122 reportantes. Com o EXP_2023 carregado, a variação do Brasil também sai (+20,4% em compensado).
- **Qualidade de dados:**
  - séries derivadas por país não acusam "mês ausente": mês sem embarque não é lacuna;
  - a defasagem esperada pode ser definida por indicador (a PEVS publica ~9 meses após o fim do ano);
  - o espelho BR × Comtrade compara o mesmo SH4, só em anos com os 12 meses carregados;
  - o teste de salto (>5σ) vale só para séries de nível estritamente positivas; séries a/a cruzam o zero e a razão explodia sem erro (migração 0021);
  - macro a/a tem defasagem esperada de 75 dias (a construção dos EUA sai ~60 dias após o mês).
  - Após a 0021 restam 32 saltos, todos reais: exportações BR a destinos pequenos (um embarque num mês, quase nada no anterior) e a PIM-PF de jun/2018 (retomada após a greve dos caminhoneiros). Série parada: só a China.

### Fontes abertas para as lacunas (migração 0019)

Proxy nunca se passa pelo indicador original: cada proxy é um indicador próprio, com o nome dizendo o que é.

| Lacuna | O que entrou | Situação |
|---|---|---|
| Frete de contêiner (Drewry/FBX, licenciados) | `FREIGHT_PPI_DEEPSEA_US`: PPI EUA de frete marítimo de longo curso (**proxy**) | carregado |
| Resina fenólica (cotação CELPLAC, Fase 5) | `RESIN_PPI_THERMOSET_US`: PPI EUA de resinas termofixas (**proxy**) | carregado |
| Petróleo | `BRENT` (EIA via FRED), diário | carregado |
| Preço do concorrente nos EUA | `US_PPI_SOFTWOOD_PLYWOOD` | carregado |
| Macro EUA | `MACRO_IP_YOY`, `MACRO_CONSTRUCTION_YOY` (INDPRO, TTLCONS nominal) | carregado |
| Macro UE / China / Argentina | Eurostat, NBS (via DBnomics), INDEC (datos.gob.ar) | carregado (China: só produção industrial, parada em dez/2025) |
| Preço de saída da madeira BR | `BR_IPP_WOOD` (IBGE IPP 6903, CNAE 16) | carregado |
| Tora de pinus | `BR_LOG_PINUS_PRICE_IMPL`: preço implícito anual da PEVS | carregado |
| Tora de pinus mensal | `PRICE_LOG_PINUS` (Ibá/CEPEA) | **licenciada**: CSV manual |
| México e Arábia Saudita (macro) | — | **DADO INDISPONÍVEL**: INEGI exige token gratuito; GASTAT sem API aberta |
| Construção na China | — | **DADO INDISPONÍVEL**: sem série mensal aberta |

As regras de sinal ganharam a **versão 2**: frete e resina usam os proxies declarados (o rótulo diz "proxy"). A v1 continua no histórico.

`stg.load_series_compact` (migração 0020) grava uma série inteira num comando: run, raw com SHA-256, staging e merge versionado.

### Sinais e ciclo (early warning)

- **Ciclo** (`mart.market_cycle`, SQL): roda direto no Neon. Hoje com 2 indicadores reais:
  - preço FOB do compensado BR: RECUPERAÇÃO;
  - housing starts EUA: CONTRAÇÃO.
- **Sinais** (`intel.signal_state`, as_of 2026-09-01): calculados com a mesma função Python do ETL. O extrato das séries sai do Neon e `scripts/signals_offline.py` gera o SQL.
  - Versão 2 (com proxies), recalculada em 25/09 com a macro de UE, China e Argentina: nenhum sinal disparou. 9 SEM SINAL e 4 EVIDÊNCIA INSUFICIENTE:
    - expansão de demanda no México (sem macro) e na China (produção industrial parada em dez/2025);
    - pressão de mercado na UE e na Arábia Saudita (séries de comércio defasadas).
  - A UE passou de EVIDÊNCIA INSUFICIENTE para SEM SINAL (1 de 4 condições: produção industrial +0,3% a/a; construção −1,8%). Argentina: SEM SINAL (0 de 4; indústria −4,9%, construção −4,5%).
  - Condições atendidas hoje: resina termofixa +8,3% (3m), frete marítimo +11,2% (3m), importações de compensado dos EUA +30% e do México +11% (3m), produção industrial EUA +1,4% a/a; exportações BR para a UE −29% (3m).
- **Série defasada não conta como evidência:** último dado com mais de 6 meses → a condição fica "sem dado" (`stale = true` no detalhe). Exemplos: as importações mensais da China param em dez/2024, e a Arábia Saudita não compra compensado BR desde mar/2025.

### Painel com dados reais (`frontend/painel-real/`)

Enquanto a API não está no ar, o painel é publicado como página com um **retrato** do banco: as consultas `mart.*` rodam no Neon, o resultado vira `gwmi-data.js` e `build.py` monta a página (mesmo visual do protótipo da Fase 1). Cada número tem o botão **fonte**, que mostra indicador, fórmula, fonte, run e arquivos de origem com SHA-256. Proxies e indicadores calculados têm selo próprio; o que falta aparece como DADO INDISPONÍVEL, com o motivo. Próximo passo: com a API no ar, trocar o retrato pela leitura de `/v1/*`.

### Carga sem o ETL rodando (navegador → Neon)

Enquanto o ETL não roda num servidor, as cargas foram feitas pelo navegador:

- **Fontes com CORS liberado** (PTAX, SIDRA): os scripts `browser_*.js` fazem a coleta e a gravação na API HTTP do Neon, a partir de uma página já aberta. A connection string fica só na memória da página.
- **Fontes sem CORS** (FRED, Comtrade): a coleta roda numa aba da própria fonte. O CSV/JSON original vai para o banco por SQL, onde o SHA-256 é recalculado (FRED) ou registrado (Comtrade).
  - Os hashes foram conferidos contra os calculados no navegador.
  - O mesmo SQL é gerado por `scripts/fred_csv_to_sql.py`.
- **Assim que o ETL rodar em um servidor:** `gwmi-etl fred`, `pevs`, `pim-wood`, `comtrade-preview`, `ptax` e `comex-trade` fazem o mesmo, com raw store em disco.
