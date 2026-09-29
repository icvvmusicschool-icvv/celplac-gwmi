// Carga Comex Stat → Neon executada num navegador aberto em https://balanca.mdic.gov.br
// (mesma origem dos arquivos) usando a API HTTP SQL do Neon. Toda a lógica de
// merge/versionamento/DQ roda no banco (dw.merge_trade, dw.apply_comex_reference…);
// o navegador só lê os CSVs oficiais, filtra o cap. 44 e grava no staging.
// Uso: definir window.GWMI_NEON = 'postgresql://…' e chamar await gwmiLoad([2025, 2026]).
(() => {
  const HS4 = ['4403', '4407', '4408', '4410', '4411', '4412'];
  const BLOCOS = new Set(['África', 'América Central e Caribe', 'América do Norte', 'América do Sul',
    'Ásia (Exclusive Oriente Médio)', 'Europa', 'Oceania', 'Oriente Médio']);

  function endpoint(cs) { const host = new URL(cs.replace(/^postgres(ql)?:/, 'https:')).hostname; return 'https://' + host.replace(/^[^.]+\./, 'api.') + '/sql'; }
  async function q(query, params = []) {
    const cs = window.GWMI_NEON;
    const r = await fetch(endpoint(cs), { method: 'POST', headers: { 'Neon-Connection-String': cs }, body: JSON.stringify({ query, params }) });
    const t = await r.text();
    if (!r.ok) throw new Error(`Neon ${r.status}: ${t.slice(0, 400)}`);
    return JSON.parse(t).rows;
  }
  function parseLine(line) { // CSV ';' com aspas
    const out = []; let cur = '', inq = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (inq) { if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else inq = false; } else cur += c; }
      else if (c === '"') inq = true; else if (c === ';') { out.push(cur); cur = ''; } else cur += c;
    }
    out.push(cur); return out.map(s => s.trim());
  }
  async function getBytes(path) { const r = await fetch(path); if (!r.ok) throw new Error(path + ' ' + r.status); return new Uint8Array(await r.arrayBuffer()); }
  function decode(b) { try { return new TextDecoder('utf-8', { fatal: true }).decode(b); } catch { return new TextDecoder('latin1').decode(b); } }
  async function sha256(b) { const h = await crypto.subtle.digest('SHA-256', b); return [...new Uint8Array(h)].map(x => x.toString(16).padStart(2, '0')).join(''); }
  function rows(text) { const L = text.split(/\r?\n/).filter(Boolean); const H = parseLine(L[0]); return L.slice(1).map(l => { const v = parseLine(l); const o = {}; H.forEach((h, i) => o[h] = v[i]); return o; }); }

  async function startRun(source, job, params) {
    return (await q(`INSERT INTO meta.etl_run (source_id, job, params, is_simulated) VALUES ($1, $2, $3::jsonb, false) RETURNING run_id`,
      [source, job, JSON.stringify(params)]))[0].run_id;
  }
  async function finishRun(run, status, staged, error = null) {
    await q(`UPDATE meta.etl_run SET status = $2, finished_at = now(), rows_staged = $3, error = $4 WHERE run_id = $1`, [run, status, staged, error]);
  }
  async function registerRaw(run, url, bytes, meta) {
    await q(`INSERT INTO raw.ingestion (run_id, source_id, uri, storage_path, content_sha256, bytes, http_status, meta)
             VALUES ($1, 'comexstat', $2, $3, $4, $5, 200, $6::jsonb)`,
      [run, url, url + ' (arquivo original na fonte; não armazenado em raw store — carga via navegador)', await sha256(bytes), bytes.length, JSON.stringify(meta || {})]);
  }
  async function insertJson(sql, run, list, chunk = 2500) {
    for (let i = 0; i < list.length; i += chunk) await q(sql, [run, JSON.stringify(list.slice(i, i + chunk))]);
  }

  async function loadReference() {
    const base = '/balanca/bd/tabelas/';
    const run = await startRun('comexstat', 'comexstat.reference', { mode: 'browser_pane' });
    try {
      const ref = [];
      const spec = { PAIS_BLOCO: 'bloco', PAIS: 'pais', NCM_UNIDADE: 'unidade', NCM: 'ncm', URF: 'urf' };
      for (const t of Object.keys(spec)) {
        const url = base + t + '.csv', b = await getBytes(url);
        await registerRaw(run, location.origin + url, b, { table: t });
        for (const r of rows(decode(b))) {
          if (t === 'PAIS_BLOCO') { if (BLOCOS.has(r.NO_BLOCO)) ref.push({ kind: 'bloco', c1: r.CO_PAIS, c2: r.NO_BLOCO }); }
          else if (t === 'PAIS') ref.push({ kind: 'pais', c1: r.CO_PAIS, c2: r.CO_PAIS_ISOA3, c3: r.NO_PAIS });
          else if (t === 'NCM_UNIDADE') ref.push({ kind: 'unidade', c1: r.CO_UNID, c2: r.NO_UNID });
          else if (t === 'NCM') { if ((r.CO_NCM || '').padStart(8, '0').startsWith('44')) ref.push({ kind: 'ncm', c1: r.CO_NCM, c2: r.CO_UNID, c3: r.NO_NCM_POR }); }
          else if (t === 'URF') ref.push({ kind: 'urf', c1: r.CO_URF, c2: r.NO_URF });
        }
      }
      await insertJson(`INSERT INTO stg.ref (run_id, kind, c1, c2, c3) SELECT $1, x.kind, x.c1, x.c2, x.c3
                        FROM json_to_recordset($2::json) AS x(kind text, c1 text, c2 text, c3 text)`, run, ref);
      const res = await q(`SELECT * FROM dw.apply_comex_reference($1)`, [run]);
      await finishRun(run, 'success', ref.length);
      return { run, staged: ref.length, res };
    } catch (e) { await finishRun(run, 'failed', 0, String(e)); throw e; }
  }

  async function loadYear(year) {
    const url = `/balanca/bd/comexstat-bd/ncm/EXP_${year}.csv`;
    const run = await startRun('comexstat', 'comexstat.exp', { flow: 'X', year, mode: 'browser_pane' });
    try {
      const b = await getBytes(url);
      await registerRaw(run, location.origin + url, b, { flow: 'X', year });
      const text = new TextDecoder('latin1').decode(b);
      const L = text.split(/\r?\n/); const H = parseLine(L[0]); const ix = n => H.indexOf(n);
      const out = [], rejected = [];
      for (let i = 1; i < L.length; i++) {
        if (!L[i]) continue;
        const v = parseLine(L[i]); const ncm = (v[ix('CO_NCM')] || '').padStart(8, '0');
        if (!HS4.includes(ncm.slice(0, 4))) continue;
        const r = { flow: 'X', period: `${v[ix('CO_ANO')]}-${String(v[ix('CO_MES')]).padStart(2, '0')}-01`,
          reporter_code: 'BRA', partner_code: String(parseInt(v[ix('CO_PAIS')], 10)), code_scheme: 'comex', ncm8: ncm,
          uf: (v[ix('SG_UF_NCM')] || '--').slice(0, 2) || '--', urf_code: parseInt(v[ix('CO_URF')] || '0', 10),
          via_code: parseInt(v[ix('CO_VIA')] || '0', 10), value_usd_fob: Number(v[ix('VL_FOB')]),
          net_kg: Number(v[ix('KG_LIQUIDO')]), qty_stat: Number(v[ix('QT_ESTAT')]), stat_unit_code: parseInt(v[ix('CO_UNID')], 10) };
        if (!(r.value_usd_fob >= 0) || r.net_kg < 0 || r.qty_stat < 0) rejected.push(r); else out.push(r);
      }
      if (rejected.length) await insertJson(`INSERT INTO dq.rejected_row (run_id, dataset, reason, row_data)
          SELECT $1, 'trade', 'valor/quantidade inválido ou negativo', x FROM json_array_elements($2::json) x`, run, rejected);
      await insertJson(`INSERT INTO stg.trade (run_id, flow, period, reporter_code, partner_code, code_scheme, ncm8, uf, urf_code,
            via_code, value_usd_fob, net_kg, qty_stat, stat_unit_code)
          SELECT $1, x.flow, x.period, x.reporter_code, x.partner_code, x.code_scheme, x.ncm8, x.uf, x.urf_code, x.via_code,
                 x.value_usd_fob, x.net_kg, x.qty_stat, x.stat_unit_code
          FROM json_to_recordset($2::json) AS x(flow char(1), period date, reporter_code text, partner_code text, code_scheme text,
               ncm8 char(8), uf char(2), urf_code int, via_code int, value_usd_fob numeric, net_kg numeric, qty_stat numeric, stat_unit_code int)`,
        run, out);
      const m = (await q(`SELECT * FROM dw.merge_trade($1, $2::date, $3::date)`, [run, `${year}-01-01`, `${year}-12-01`]))[0];
      await q(`UPDATE meta.etl_run SET rows_rejected = $2 WHERE run_id = $1`, [run, rejected.length]);
      const dq = await q(`SELECT * FROM dq.run_checks($1, 'trade')`, [run]);
      const bad = dq.filter(d => !d.passed && d.severity === 'error');
      await finishRun(run, rejected.length || bad.length ? 'partial' : 'success', out.length);
      return { run, year, bytes: b.length, staged: out.length, rejected: rejected.length, merge: m, dq_fail: dq.filter(d => !d.passed).map(d => d.rule_id) };
    } catch (e) { await finishRun(run, 'failed', 0, String(e)); throw e; }
  }

  async function derive() {
    const sim = (await q(`SELECT mart.derive_group_is_simulated('br_exports') AS s`))[0].s;
    const run = (await q(`INSERT INTO meta.etl_run (source_id, job, params, is_simulated) VALUES ('gwmi_calc', 'derive.br_exports', '{"group":"br_exports"}', $1) RETURNING run_id`, [sim]))[0].run_id;
    const staged = (await q(`SELECT mart.derive_trade_series($1, 'br_exports') AS n`, [run]))[0].n;
    const m = (await q(`SELECT * FROM dw.merge_series($1)`, [run]))[0];
    await finishRun(run, 'success', staged);
    return { run, is_simulated: sim, staged, merge: m };
  }

  window.gwmiLoad = async (years = [2025, 2026]) => {
    const log = [];
    log.push(await loadReference());
    for (const y of years) log.push(await loadYear(y));
    log.push(await derive());
    return log;
  };
})();
