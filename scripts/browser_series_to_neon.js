// Carga de SÉRIES (PTAX, SIDRA, FRED…) → Neon executada no navegador, via API HTTP SQL do Neon.
// Mesmo contrato do pipeline Python: meta.etl_run → raw.ingestion (SHA-256 do payload original)
// → stg.series → dw.merge_series (versionado) → dq.run_checks('series').
// Uso: window.GWMI_NEON = 'postgresql://…'; await gwmiSeries.ptax(['USD','EUR','GBP'], '2021-01-01').
(() => {
  function endpoint(cs) { const host = new URL(cs.replace(/^postgres(ql)?:/, 'https:')).hostname; return 'https://' + host.replace(/^[^.]+\./, 'api.') + '/sql'; }
  async function q(query, params = []) {
    const cs = window.GWMI_NEON;
    const r = await fetch(endpoint(cs), { method: 'POST', headers: { 'Neon-Connection-String': cs }, body: JSON.stringify({ query, params }) });
    const t = await r.text();
    if (!r.ok) throw new Error(`Neon ${r.status}: ${t.slice(0, 400)}`);
    return JSON.parse(t).rows;
  }
  async function sha256(b) { const h = await crypto.subtle.digest('SHA-256', b); return [...new Uint8Array(h)].map(x => x.toString(16).padStart(2, '0')).join(''); }

  // Executa um job de série completo. fetchFn() → [{uri, bytes(Uint8Array), meta}], parseFn(payloads) → linhas stg.series.
  async function runSeriesJob(source, job, params, fetchFn, parseFn) {
    const run = (await q(`INSERT INTO meta.etl_run (source_id, job, params, is_simulated) VALUES ($1, $2, $3::jsonb, false) RETURNING run_id`,
      [source, job, JSON.stringify({ ...params, mode: 'browser_pane' })]))[0].run_id;
    try {
      const files = await fetchFn();
      for (const f of files)
        await q(`INSERT INTO raw.ingestion (run_id, source_id, uri, storage_path, content_sha256, bytes, http_status, meta)
                 VALUES ($1, $2, $3, $4, $5, $6, 200, $7::jsonb)`,
          [run, source, f.uri, f.uri + ' (payload original na fonte; não armazenado em raw store — carga via navegador)',
           await sha256(f.bytes), f.bytes.length, JSON.stringify(f.meta || {})]);
      const all = parseFn(files.map(f => new TextDecoder('utf-8').decode(f.bytes)));
      const ok = all.filter(r => r.value === null || Number.isFinite(r.value));
      const bad = all.filter(r => !(r.value === null || Number.isFinite(r.value)));
      if (bad.length) await q(`INSERT INTO dq.rejected_row (run_id, dataset, reason, row_data)
          SELECT $1, 'series', 'valor não numérico', x FROM json_array_elements($2::json) x`, [run, JSON.stringify(bad)]);
      for (let i = 0; i < ok.length; i += 3000)
        await q(`INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value, obs_status)
                 SELECT $1, x.indicator_code, x.geo_iso3, x.period, x.value, x.obs_status
                 FROM json_to_recordset($2::json) AS x(indicator_code text, geo_iso3 char(3), period date, value numeric, obs_status text)`,
          [run, JSON.stringify(ok.slice(i, i + 3000))]);
      const m = (await q(`SELECT * FROM dw.merge_series($1)`, [run]))[0];
      const dq = await q(`SELECT * FROM dq.run_checks($1, 'series')`, [run]);
      const errs = dq.filter(d => !d.passed && d.severity === 'error');
      await q(`UPDATE meta.etl_run SET status = $2, finished_at = now(), rows_staged = $3, rows_rejected = $4 WHERE run_id = $1`,
        [run, bad.length || errs.length ? 'partial' : 'success', ok.length, bad.length]);
      return { run, job, staged: ok.length, rejected: bad.length, merge: m, dq_fail: dq.filter(d => !d.passed).map(d => d.rule_id) };
    } catch (e) {
      await q(`DELETE FROM stg.series WHERE run_id = $1`, [run]);
      await q(`UPDATE meta.etl_run SET status = 'failed', finished_at = now(), error = $2 WHERE run_id = $1`, [run, String(e)]);
      throw e;
    }
  }
  async function get(url) { const r = await fetch(url); if (!r.ok) throw new Error(url + ' → HTTP ' + r.status); return new Uint8Array(await r.arrayBuffer()); }

  // ---------------- BCB PTAX: boletim de fechamento (venda); sem fechamento no dia → último intermediário, obs_status 'P'
  const PTAX = 'https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/';
  const mdY = iso => { const [y, m, d] = iso.split('-'); return `${m}-${d}-${y}`; };
  function parsePtax(text, cur) {
    const byDay = {};
    for (const v of JSON.parse(text).value) {
      const day = String(v.dataHoraCotacao).slice(0, 10), fech = String(v.tipoBoletim || '').includes('Fechamento');
      if (fech || !byDay[day] || !byDay[day].fech) byDay[day] = { v, fech };
    }
    return Object.keys(byDay).sort().map(day => ({ indicator_code: `FX_${cur}_BRL`, geo_iso3: 'BRA', period: day,
      value: Number(byDay[day].v.cotacaoVenda), obs_status: byDay[day].fech ? 'A' : 'P' }));
  }
  async function ptax(currencies = ['USD', 'EUR', 'GBP'], start = '2021-01-01', end = new Date().toISOString().slice(0, 10)) {
    const out = [];
    for (const cur of currencies) {
      const url = PTAX + `CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)` +
        `?@moeda='${cur}'&@dataInicial='${mdY(start)}'&@dataFinalCotacao='${mdY(end)}'&$format=json&$top=100000` +
        `&$select=cotacaoVenda,dataHoraCotacao,tipoBoletim`;
      out.push(await runSeriesJob('bcb_ptax', `bcb.ptax.${cur.toLowerCase()}`, { currency: cur, start, end },
        async () => [{ uri: url, bytes: await get(url), meta: { currency: cur } }], ([t]) => parsePtax(t, cur)));
    }
    return out;
  }

  // ---------------- IBGE SIDRA (/values): seleção por rótulos de dimensão, igual ao parse_sidra do Python
  function parseSidra(text, indicator, match, geo = 'BRA', scale = 1) {
    const [header, ...rows] = JSON.parse(text);
    const dims = {}; for (const k in header) if (/^D\dN$/.test(k)) dims[k.slice(0, 2)] = header[k];
    const pk = Object.keys(dims).find(k => ['Ano', 'Mês', 'Trimestre'].includes(dims[k]));
    const l2k = Object.fromEntries(Object.entries(dims).map(([k, l]) => [l, k]));
    for (const l in match) if (!l2k[l]) throw new Error(`dimensão '${l}' não existe: ${Object.values(dims)}`);
    const per = c => dims[pk] === 'Mês' ? `${c.slice(0, 4)}-${c.slice(4, 6)}-01` : `${c.slice(0, 4)}-01-01`;
    return rows.filter(r => Object.entries(match).every(([l, v]) => String(r[l2k[l] + 'N']).trim().toLowerCase() === v.toLowerCase()))
      .map(r => { const n = /^-?\d+(\.\d+)?$/.test(String(r.V).trim()) ? Number(r.V) * scale : null;
        return { indicator_code: indicator, geo_iso3: geo, period: per(String(r[pk + 'C'])), value: n, obs_status: n === null ? 'M' : 'A' }; });
  }
  async function sidra(path, indicator, match, scale = 1) {
    const url = 'https://apisidra.ibge.gov.br/values' + path;
    return runSeriesJob('ibge_sidra', `ibge.sidra.${indicator.toLowerCase()}`, { path, indicator, match, scale },
      async () => [{ uri: url, bytes: await get(url), meta: {} }], ([t]) => parseSidra(t, indicator, match, 'BRA', scale));
  }

  // ---------------- FRED (a chave nunca é gravada: a URI registrada omite api_key)
  async function fred(seriesId, indicator, apiKey, geo = 'USA', start = '2000-01-01') {
    const base = 'https://api.stlouisfed.org/fred/series/observations';
    const url = `${base}?series_id=${seriesId}&file_type=json&observation_start=${start}`;
    return runSeriesJob('fred', `fred.${seriesId.toLowerCase()}`, { series_id: seriesId, indicator, geo },
      async () => [{ uri: url, bytes: await get(url + `&api_key=${apiKey}`), meta: {} }],
      ([t]) => JSON.parse(t).observations.map(o => { const n = o.value === '.' ? null : Number(o.value);
        return { indicator_code: indicator, geo_iso3: geo, period: o.date, value: n, obs_status: n === null ? 'M' : 'A' }; }));
  }

  window.gwmiSeries = { q, runSeriesJob, ptax, parsePtax, sidra, parseSidra, fred };
})();
