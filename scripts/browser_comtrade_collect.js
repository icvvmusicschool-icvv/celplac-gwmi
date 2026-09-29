// Coleta UN Comtrade pela API pública de pré-visualização (sem chave), executada num navegador
// aberto em https://comtradeapi.un.org (mesma origem → sem bloqueio de CORS).
// Limites da pré-visualização: 1 período por consulta, até 500 linhas, ~1 consulta/s.
// Para cada resposta guarda: período, URI, SHA-256 do JSON original e as linhas compactadas.
// A gravação no banco (stg.trade → dw.merge_trade) é feita depois, pelo SQL descrito no README
// (seção "Carga sem o ETL rodando"), ou direto pelo ETL Python (`gwmi-etl comtrade-preview`).
//
// Uso:
//   await gwmiComtrade.annual(['4412','4408','4407'], [2023, 2024, 2025])   // concorrentes (X → mundo)
//   await gwmiComtrade.monthlyImports('4412', '202301', '202608')            // importações dos mercados (M ← mundo e ← Brasil)
//   gwmiComtrade.batch('202301','202412')                                    // texto compacto para o SQL de carga
(() => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const sha = async t => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(t)))]
    .map(x => x.toString(16).padStart(2, '0')).join('');
  let ISO = null;
  async function iso() {
    if (!ISO) ISO = Object.fromEntries((await fetch('/files/v1/app/reference/Reporters.json').then(r => r.json()))
      .results.map(r => [r.reporterCode, r.reporterCodeIsoAlpha3]));
    return ISO;
  }
  async function get(path) {   // repete em 429 (limite de taxa)
    for (let a = 0; a < 6; a++) {
      await sleep(2200);
      const r = await fetch(path); const t = await r.text();
      if (r.status === 200) { try { const j = JSON.parse(t); if (j.data) return { t, j }; } catch { } }
    }
    throw new Error('Comtrade sem resposta válida: ' + path);
  }
  const TOTALS = '&customsCode=C00&motCode=0&partner2Code=0';
  // Mercados monitorados: destinos do compensado BR + grandes importadores
  const MARKETS = new Set(['USA', 'MEX', 'GBR', 'DEU', 'ITA', 'BEL', 'NLD', 'DOM', 'SWE', 'NZL', 'DNK', 'ESP', 'FRA', 'CAN', 'JPN',
    'KOR', 'AUS', 'POL', 'CHL', 'ARG', 'URY', 'PRY', 'PER', 'COL', 'IRL', 'PRT', 'CHN', 'IND', 'ZAF', 'SAU', 'TUR']);

  const store = { annual: [], monthly: [] };
  async function annual(cmds, years) {
    const m = await iso();
    for (const cmd of cmds) for (const y of years) {
      const path = `/public/v1/preview/C/A/HS?cmdCode=${cmd}&flowCode=X&partnerCode=0&period=${y}${TOTALS}`;
      const { t, j } = await get(path);
      store.annual.push({ cmd, y, uri: location.origin + path, sha: await sha(t), bytes: new TextEncoder().encode(t).length,
        rows: j.data.filter(d => d.reporterCode !== 76 && m[d.reporterCode])      // BRA vem do Comex Stat
          .map(d => [m[d.reporterCode], y, Math.round(d.fobvalue ?? d.primaryValue), d.netWgt || ''].join(',')) });
    }
    return store.annual.map(c => [c.cmd, c.y, c.rows.length]);
  }
  async function monthlyImports(cmd, from, to) {
    const m = await iso();
    const pers = []; for (let y = +from.slice(0, 4); y <= +to.slice(0, 4); y++) for (let k = 1; k <= 12; k++) {
      const p = `${y}${String(k).padStart(2, '0')}`; if (p >= from && p <= to) pers.push(p); }
    for (const p of pers) {
      const path = `/public/v1/preview/C/M/HS?cmdCode=${cmd}&flowCode=M&partnerCode=0,76&period=${p}${TOTALS}`;
      const { t, j } = await get(path);
      store.monthly.push({ p, uri: location.origin + path, sha: await sha(t), bytes: new TextEncoder().encode(t).length,
        rows: j.data.filter(d => MARKETS.has(m[d.reporterCode]))
          .map(d => [m[d.reporterCode], p, d.partnerCode === 0 ? 'W' : 'B', Math.round(d.primaryValue),
                     d.netWgt ? Math.round(d.netWgt) : ''].join(',')) });
    }
    return store.monthly.map(c => c.p + ':' + c.rows.length).join(' ');
  }
  function batch(from, to) {
    const cs = store.monthly.filter(c => c.p >= from && c.p <= to);
    return { raw: cs.map(c => `${c.p}|${c.sha}|${c.bytes}`).join(';'), rows: cs.flatMap(c => c.rows).join(';') };
  }
  window.gwmiComtrade = { annual, monthlyImports, batch, store };
})();
