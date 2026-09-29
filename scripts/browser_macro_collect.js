// Coleta das fontes macro e de custo que faltam (rodar no painel do navegador, qualquer origem:
// Eurostat, IBGE, datos.gob.ar e DBnomics liberam CORS). Gera, para cada série, o texto compacto
// 'AAAA-MM=valor;…' + SHA-256 do arquivo original, prontos para stg.load_series_compact (migração 0020).
//
//   MACRO_IP_YOY / MACRO_CONSTRUCTION_YOY · EUU  ← Eurostat sts_inpr_m (B-D) e sts_copr_m (F), EU27_2020, PCH_SM, CA
//   MACRO_IP_YOY · CHN                          ← NBS A020101 (valor adicionado industrial, a/a), espelho DBnomics
//   MACRO_IP_YOY / MACRO_CONSTRUCTION_YOY · ARG ← INDEC IPI manufacturero / ISAC, a/a calculada pela API
//   BR_IPP_WOOD · BRA                           ← IBGE IPP tabela 6903, CNAE 16, número-índice
//   BR_LOG_PINUS_PRICE_IMPL · BRA               ← IBGE PEVS 291: valor (mil R$) × 1000 ÷ quantidade (m³), cat. 33257
//
// Uso: await gwmiMacro.collect(); depois gwmiMacro.sql() devolve os SELECT stg.load_series_compact(...) prontos.
(() => {
  const sha = async t => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(t)))]
    .map(x => x.toString(16).padStart(2, '0')).join('');
  const get = async u => { const r = await fetch(u); const t = await r.text();
    if (!r.ok) throw new Error(u + ' → HTTP ' + r.status); return { u, t, sha: await sha(t), bytes: new TextEncoder().encode(t).length }; };
  const out = {};

  async function eurostat(ds, nace) {
    const g = await get(`https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/${ds}?geo=EU27_2020&unit=PCH_SM&s_adj=CA&nace_r2=${nace}&indic_bt=PRD&sinceTimePeriod=2021-01`);
    const j = JSON.parse(g.t), idx = j.dimension.time.category.index;
    return { ...g, s: Object.entries(idx).sort((a, b) => a[1] - b[1]).map(([p, i]) => p + '=' + (j.value[i] ?? '')).join(';') };
  }
  async function indec(id) {
    const g = await get(`https://apis.datos.gob.ar/series/api/series/?ids=${id}&representation_mode=percent_change_a_year_ago&start_date=2021-01-01&format=json&limit=1000`);
    return { ...g, s: JSON.parse(g.t).data.map(([p, v]) => p.slice(0, 7) + '=' + (v == null ? '' : +(v * 100).toFixed(4))).join(';') };
  }
  async function collect() {
    out.EU_IP = { src: 'eurostat', ind: 'MACRO_IP_YOY', geo: 'EUU', ...(await eurostat('sts_inpr_m', 'B-D')) };
    out.EU_CO = { src: 'eurostat', ind: 'MACRO_CONSTRUCTION_YOY', geo: 'EUU', ...(await eurostat('sts_copr_m', 'F')) };
    const nb = await get('https://api.db.nomics.world/v22/series/NBS/M_A0201/A020101?observations=1&format=json');
    const d = JSON.parse(nb.t).series.docs[0];
    out.CN_IP = { src: 'nbs', ind: 'MACRO_IP_YOY', geo: 'CHN', ...nb,
      s: d.period.map((p, i) => p >= '2021-01' ? p + '=' + (d.value[i] === 'NA' ? '' : d.value[i]) : null).filter(Boolean).join(';') };
    out.AR_IP = { src: 'indec', ind: 'MACRO_IP_YOY', geo: 'ARG', ...(await indec('453.1_SERIE_ORIGNAL_0_0_14_46')) };
    out.AR_CO = { src: 'indec', ind: 'MACRO_CONSTRUCTION_YOY', geo: 'ARG', ...(await indec('33.2_ISAC_NIVELRAL_0_M_18_63')) };
    const ipp = await get('https://apisidra.ibge.gov.br/values/t/6903/n1/all/v/10008/p/all/c842/46625');
    out.BR_IPP = { src: 'ibge_sidra', ind: 'BR_IPP_WOOD', geo: 'BRA', ...ipp,
      s: JSON.parse(ipp.t).slice(1).map(r => `${r.D3C.slice(0, 4)}-${r.D3C.slice(4, 6)}=${/^[\d.]+$/.test(r.V) ? r.V : ''}`).join(';') };
    const pv = await get('https://apisidra.ibge.gov.br/values/t/291/n1/all/v/142,143/p/all/c194/33257');
    const by = {}; for (const r of JSON.parse(pv.t).slice(1)) (by[r.D3C] ??= {})[r.D2C] = /^\d+$/.test(r.V) ? +r.V : null;
    out.PEVS_PRICE = { src: 'gwmi_calc', ind: 'BR_LOG_PINUS_PRICE_IMPL', geo: 'BRA', ...pv,
      s: Object.keys(by).sort().filter(y => +y >= 2013)
        .map(y => y + '=' + (by[y]['142'] && by[y]['143'] != null ? (by[y]['143'] * 1000 / by[y]['142']).toFixed(2) : '')).join(';') };
    return Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v.s.split(';').length + ' obs, último ' + v.s.slice(-24)]));
  }
  const q = s => "'" + String(s).replace(/'/g, "''") + "'";
  const sql = () => Object.entries(out).map(([k, v]) =>
    `SELECT * FROM stg.load_series_compact(${q(v.src)}, ${q('coleta.' + k.toLowerCase())}, '{}'::jsonb, ${q(v.u)}, ${q(v.sha)}, ${v.bytes}, ${q(v.ind)}, ${q(v.geo)}, ${q(v.s)})`);
  window.gwmiMacro = { collect, sql, out };
})();
