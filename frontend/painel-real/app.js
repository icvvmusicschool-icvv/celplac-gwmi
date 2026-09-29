function gwmiApp(){
'use strict';
var D=window.GWMI;

/* ---------- séries ---------- */
var S={};
D.S.forEach(function(s){var p=[],v=[];s.v.split(';').forEach(function(kv){var k=kv.indexOf('=');p.push(kv.slice(0,k));v.push(+kv.slice(k+1))});if((D.I[s.i]||{}).f==='A')p=p.map(function(x){return x.slice(0,4)});S[s.i+'|'+s.g]={i:s.i,g:s.g,src:s.src,run:s.run,at:s.at,p:p,v:v}});
function ser(i,g){return S[i+'|'+g]||null}
var LAT={};D.LATEST.forEach(function(l){LAT[l.indicator_code+'|'+l.geo_iso3]=l});
var ASOF=D.ASOF.slice(0,10), CURM=ASOF.slice(0,7);

/* ---------- formatação ---------- */
var NFc={};function nf(d){return NFc[d]||(NFc[d]=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d}))}
function fmt(v,d){if(v==null||isNaN(v))return '—';return nf(d==null?2:d).format(v)}
function sgn(v){return v>0?'+':v<0?'−':''}
function big(v,unit,pre){if(v==null||isNaN(v))return '—';var a=Math.abs(v),s;if(a>=1e9)s=fmt(v/1e9,2)+' bi';else if(a>=1e6)s=fmt(v/1e6,1)+' mi';else if(a>=1e4)s=fmt(v/1e3,0)+' mil';else s=fmt(v,0);return (pre||'')+s+(unit||'')}
function usd(v){return big(v,'','US$ ')}
function m3(v){return big(v,' m³')}
function pct(v,d){if(v==null||isNaN(v))return '—';return sgn(v)+fmt(Math.abs(v)*100,d==null?1:d)+'%'}
function ppt(v){if(v==null||isNaN(v))return '—';return sgn(v)+fmt(Math.abs(v)*100,1)+' p.p.'}
function yoyp(v){if(v==null||isNaN(v))return '—';return sgn(v)+fmt(Math.abs(v),1)+'%'}
function cls(v,pol){if(v==null||isNaN(v))return 'fl';var x=v*(pol==null?1:pol);return x>0.0005?'up':x<-0.0005?'dn':'fl'}
function arr(v){return v==null?'':v>0.005?'↑':v<-0.005?'↓':'→'}
var MN=['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
function mon(p){if(!p)return '—';var y=p.slice(0,4),m=+p.slice(5,7);if(!m)return y;return MN[m-1]+'/'+y.slice(2)}
function monL(p){if(!p)return '—';var y=p.slice(0,4),m=+p.slice(5,7);if(!m)return y;return MN[m-1]+'/'+y}
function dt(s){if(!s)return '—';var d=new Date(s);return d.toLocaleDateString('pt-BR')+' '+d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function cn(iso){if(iso==='WLD')return 'Mundo';if(iso==='EUU')return 'União Europeia';var c=D.C[iso];return c?c[0]:iso}
function fmtVal(code,v){var I=D.I[code]||{};var u=I.u||'';
  if(/^US\$$/.test(u))return usd(v);if(u==='m³')return m3(v);if(u==='% a/a')return yoyp(v);
  if(/US\$\/m³/.test(u))return 'US$ '+fmt(v,0)+'/m³';if(/R\$\/m³/.test(u))return 'R$ '+fmt(v,2)+'/m³';
  if(u==='R$')return 'R$ '+fmt(v,4);if(/bbl/.test(u))return 'US$ '+fmt(v,2);if(/SAAR/.test(u))return fmt(v,0)+' mil/ano';
  if(/\/US\$/.test(u))return fmt(v,4);return fmt(v,1)}

/* ---------- natureza do número ---------- */
function isProxy(c){var I=D.I[c];return !!(I&&/PROXY/.test(I.d||''))}
function kindChip(c){var I=D.I[c];if(!I)return '';if(isProxy(c))return '<span class="chip proxy" title="Indicador substituto: aproxima o dado original, que é licenciado ou indisponível">PROXY</span>';
  return I.k==='indicator'?'<span class="chip ind" title="Calculado pela plataforma a partir de dados oficiais; fórmula registrada">INDICADOR</span>':'<span class="chip real" title="Publicado pela fonte oficial, sem transformação além da média mensal">DADO</span>'}
var NA='<span class="chip na">DADO INDISPONÍVEL</span>';

/* ---------- rastreio ---------- */
var TR=[];
function tr(o){TR.push(o);return TR.length-1}
function srcS(i,g,p,lbl){return '<button class="src" data-tr="'+tr({t:'s',i:i,g:g,p:p})+'" title="De onde veio este número?">'+(lbl||'fonte')+'</button>'}
function srcT(o,lbl){o.t='t';return '<button class="src" data-tr="'+tr(o)+'" title="De onde veio este número?">'+(lbl||'fonte')+'</button>'}
var BASE={EXP_BR_VALUE:['comexstat'],EXP_BR_M3:['comexstat'],PLYWOOD_FOB_BR:['comexstat'],IMP_TOTAL_WOOD:['comtrade'],FX_MXN_BRL:['bcb_ptax','fred'],FX_CNY_BRL:['bcb_ptax','fred'],BR_LOG_PINUS_PRICE_IMPL:['ibge_sidra']};
function runsOf(src,n){var r=[];for(var k in D.RUNS){if(D.RUNS[k].s===src)r.push(+k)}r.sort(function(a,b){return b-a});return r.slice(0,n||4)}
function rawOf(run){return D.RAW.filter(function(x){return x.run===run})}
function srcBlock(id){var s=D.SRC[id];if(!s)return '<dd>'+esc(id)+'</dd>';return '<dd><b>'+esc(s.name)+'</b>'+(s.url?'<br><a href="'+esc(s.url)+'" target="_blank" rel="noopener">'+esc(s.url)+'</a>':'')+(s.m?'<br><span class="muted small">'+esc(s.m)+'</span>':'')+(s.lic?'<br><span class="muted small">Licença: '+esc(s.lic)+'</span>':'')+'</dd>'}
function runBlock(run){var R=D.RUNS[run];if(!R)return '';var f=rawOf(run);
  return '<div class="file"><div><b class="mono">run #'+run+'</b> · '+esc(R.j)+' · '+esc(R.st)+' · '+dt(R.f)+(R.n!=null?' · '+fmt(R.n,0)+' linhas':'')+'</div>'+
  f.slice(0,4).map(function(x){return '<a href="'+esc(x.uri)+'" target="_blank" rel="noopener">'+esc(x.uri)+'</a><span class="sha">SHA-256 '+esc(x.sha)+' · '+fmt(x.bytes,0)+' bytes</span>'}).join('')+
  (f.length>4?'<span class="muted">+ '+(f.length-4)+' arquivos neste run</span>':'')+(f.length?'':'<span class="muted">Sem arquivo bruto: run de cálculo (derivado de dados já carregados).</span>')+'</div>'}
function openTrace(o){var h='';
  if(o.t==='s'){var I=D.I[o.i]||{},s=ser(o.i,o.g),k=s?s.p.indexOf(o.p):-1,v=k>=0?s.v[k]:null;
    h+='<div class="q">De onde veio este número?</div><h3>'+esc(I.n||o.i)+'</h3><div class="srow">'+kindChip(o.i)+'<span class="chip">'+esc(cn(o.g))+'</span></div>';
    if(v!=null)h+='<div><div class="val">'+esc(fmtVal(o.i,v))+'</div><div class="muted small">'+(I.f==='A'?'ano '+o.p.slice(0,4):monL(o.p)+(I.f==='D'?' · média dos dias úteis do mês':''))+(o.p===CURM?' · mês em andamento':'')+'</div></div>';
    h+='<dl class="kv"><dt>Código</dt><dd class="mono">'+esc(o.i)+' · '+esc(o.g)+'</dd><dt>Unidade</dt><dd>'+esc(I.u)+'</dd>';
    if(I.fo)h+='<dt>Fórmula</dt><dd>'+esc(I.fo)+'</dd>';if(I.d)h+='<dt>Descrição</dt><dd>'+esc(I.d)+'</dd>';if(I.r)h+='<dt>Ref. na fonte</dt><dd class="mono">'+esc(I.r)+'</dd>';
    var bs=BASE[o.i]||(s?s.src.split(','):[I.s]);bs.forEach(function(b){h+='<dt>Fonte</dt>'+srcBlock(b)});
    if(s)h+='<dt>Coletado em</dt><dd>'+esc(s.at)+'</dd>';h+='</dl>';
    h+='<div class="lbl">Execução que gravou a série</div><div class="files">'+(s?runBlock(s.run):'')+'</div>';
    if(BASE[o.i]){h+='<div class="lbl">Cargas de origem</div><div class="files">'+BASE[o.i].map(function(b){return runsOf(b,2).map(runBlock).join('')}).join('')+'</div>'}
  }else{
    h+='<div class="q">De onde veio este número?</div><h3>'+esc(o.title)+'</h3>';if(o.value)h+='<div class="val">'+esc(o.value)+'</div>';
    h+='<dl class="kv"><dt>Consulta</dt><dd class="mono">'+esc(o.fn)+'</dd>';if(o.calc)h+='<dt>Cálculo</dt><dd>'+esc(o.calc)+'</dd>';if(o.note)h+='<dt>Observação</dt><dd>'+esc(o.note)+'</dd>';
    (o.src||[]).forEach(function(b){h+='<dt>Fonte</dt>'+srcBlock(b)});h+='</dl><div class="lbl">Cargas mais recentes da fonte</div><div class="files">'+(o.src||[]).map(function(b){return runsOf(b,3).map(runBlock).join('')}).join('')+'</div>';
  }
  h+='<p class="note">Cada carga guarda o arquivo de origem (URI) e o SHA-256 calculado na coleta. Revisões da fonte viram nova versão; a anterior continua consultável.</p>';
  var dr=document.getElementById('drawer');dr.innerHTML='<button class="x" id="dx">Fechar</button>'+h;dr.hidden=false;document.getElementById('scrim').hidden=false;document.getElementById('dx').focus()}
function closeTrace(){document.getElementById('drawer').hidden=true;document.getElementById('scrim').hidden=true}

/* ---------- gráficos ---------- */
var CH=[];
function chart(sp){CH.push(sp);return '<div class="chart" data-ch="'+(CH.length-1)+'" style="min-height:'+(sp.h||210)+'px"></div>'}
function nice(lo,hi,n){if(lo===hi){lo-=1;hi+=1}var r=hi-lo,st=Math.pow(10,Math.floor(Math.log10(r/n))),e=r/n/st;st*=e>=5?10:e>=2?5:e>=1?2:1;var a=Math.floor(lo/st)*st,b=Math.ceil(hi/st)*st,t=[];for(var x=a;x<=b+st/2;x+=st)t.push(+x.toFixed(10));return t}
function axisFmt(v,sp){if(sp.pctAxis)return fmt(v*100,0)+'%';var a=Math.abs(v);if(a>=1e9)return fmt(v/1e9,1)+' bi';if(a>=1e6)return fmt(v/1e6,0)+' mi';if(a>=1e4)return fmt(v/1e3,0)+' mil';return fmt(v,a<10&&a!==0?(a<1?2:1):0)}
function prep(sp){var set={};sp.series.forEach(function(s){s.p.forEach(function(p){set[p]=1})});var P=Object.keys(set).sort();
  if(sp.from)P=P.filter(function(p){return p>=sp.from});var idx={};P.forEach(function(p,i){idx[p]=i});
  var vals=[];sp.series.forEach(function(s){s.m={};s.p.forEach(function(p,i){if(idx[p]!=null&&s.v[i]!=null&&!isNaN(s.v[i])){s.m[p]=s.v[i];vals.push(s.v[i])}})});
  var lo=Math.min.apply(null,vals),hi=Math.max.apply(null,vals);if(sp.zero||sp.type==='bar'){lo=Math.min(lo,0);hi=Math.max(hi,0)}if(sp.ref!=null){lo=Math.min(lo,sp.ref);hi=Math.max(hi,sp.ref)}
  return {P:P,T:nice(lo,hi,4)}}
function svgChart(sp,W){var H=sp.h||210,L=52,R=14,T=10,B=24,pr=prep(sp),P=pr.P,Tk=pr.T;if(!P.length)return '<div class="unavail">SEM PONTOS NO PERÍODO</div>';
  var y0=Tk[0],y1=Tk[Tk.length-1],iw=W-L-R,ih=H-T-B,n=P.length,bw=sp.type==='bar'?iw/n:0;
  function X(i){return sp.type==='bar'?L+bw*(i+.5):L+(n===1?iw/2:iw*i/(n-1))}function Y(v){return T+ih*(1-(v-y0)/(y1-y0))}
  var g='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+esc(sp.label||'gráfico')+'">';
  Tk.forEach(function(t){g+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Y(t)+'" y2="'+Y(t)+'" style="stroke:var(--line2)" stroke-width="1"/><text x="'+(L-6)+'" y="'+(Y(t)+3.5)+'" text-anchor="end">'+axisFmt(t,sp)+'</text>'});
  if(sp.ref!=null)g+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Y(sp.ref)+'" y2="'+Y(sp.ref)+'" style="stroke:var(--muted)" stroke-dasharray="3 3"/>';
  var step=Math.max(1,Math.ceil(n/Math.max(2,Math.floor(iw/64))));for(var i=0;i<n;i+=step){g+='<text x="'+X(i)+'" y="'+(H-6)+'" text-anchor="middle">'+(P[i].length===4?P[i]:mon(P[i]))+'</text>'}
  sp.series.forEach(function(s,si){var col='var('+(s.c||['--copper','--slate','--forest','--wood','--info','--warn'][si%6])+')';
    if(sp.type==='bar'){P.forEach(function(p,i){var v=s.m[p];if(v==null)return;var y=Y(Math.max(v,0)),h=Math.abs(Y(v)-Y(0));g+='<rect x="'+(X(i)-bw*.36)+'" y="'+y+'" width="'+(bw*.72)+'" height="'+Math.max(h,.5)+'" style="fill:'+col+'" opacity="'+(p===CURM?.45:.9)+'"/>'});return}
    var d='',pen=false,last=null;P.forEach(function(p,i){var v=s.m[p];if(v==null){pen=false;return}d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1);pen=true;last=[X(i),Y(v)]});
    if(sp.series.length===1&&d){var a=d.replace(/^M/,'M');var fx=P.map(function(p,i){return s.m[p]!=null?i:-1}).filter(function(i){return i>=0});g+='<path d="'+a+'L'+X(fx[fx.length-1])+' '+Y(Math.max(y0,Math.min(0,y1)))+'L'+X(fx[0])+' '+Y(Math.max(y0,Math.min(0,y1)))+'Z" style="fill:'+col+'" opacity=".08"/>'}
    g+='<path d="'+d+'" fill="none" style="stroke:'+col+'" stroke-width="'+(s.w||1.8)+'" stroke-linejoin="round"'+(s.dash?' stroke-dasharray="4 3"':'')+'/>';if(last)g+='<circle cx="'+last[0]+'" cy="'+last[1]+'" r="3" style="fill:'+col+'"/>'});
  g+='<line class="gd" x1="0" x2="0" y1="'+T+'" y2="'+(T+ih)+'" style="stroke:var(--muted)" stroke-width="1" visibility="hidden"/><rect class="ov" x="'+L+'" y="'+T+'" width="'+iw+'" height="'+ih+'" fill="transparent"/></svg>';
  sp._g={L:L,iw:iw,n:n,P:P,X:X};return g}
var TIP;
function bindTip(el,sp){var svg=el.querySelector('svg');if(!svg||!sp._g)return;var ov=svg.querySelector('.ov'),gd=svg.querySelector('.gd'),G=sp._g;
  function mv(e){var r=svg.getBoundingClientRect(),x=(e.touches?e.touches[0].clientX:e.clientX)-r.left,i=sp.type==='bar'?Math.floor((x-G.L)/(G.iw/G.n)):Math.round((x-G.L)/(G.iw/Math.max(1,G.n-1)));i=Math.max(0,Math.min(G.n-1,i));var p=G.P[i];
    gd.setAttribute('x1',G.X(i));gd.setAttribute('x2',G.X(i));gd.setAttribute('visibility','visible');
    var h='<b>'+(p.length===4?p:monL(p))+(p===CURM?' (parcial)':'')+'</b>';sp.series.forEach(function(s){var v=s.m[p];h+='<br>'+(sp.series.length>1?esc(s.name)+': ':'')+(v==null?'—':(sp.fmt?sp.fmt(v):fmt(v,2)))});
    TIP.innerHTML=h;TIP.hidden=false;var tx=(e.touches?e.touches[0].clientX:e.clientX)+14,ty=(e.touches?e.touches[0].clientY:e.clientY)+14;if(tx+240>innerWidth)tx-=260;TIP.style.left=tx+'px';TIP.style.top=ty+'px'}
  function lv(){gd.setAttribute('visibility','hidden');TIP.hidden=true}
  ov.addEventListener('mousemove',mv);ov.addEventListener('mouseleave',lv);ov.addEventListener('touchstart',mv,{passive:true});ov.addEventListener('touchend',lv)}
function drawAll(){document.querySelectorAll('[data-ch]').forEach(function(el){var sp=CH[+el.getAttribute('data-ch')];if(!sp)return;el.innerHTML=svgChart(sp,Math.max(260,el.clientWidth));bindTip(el,sp)});}
function legend(items){return '<div class="legend">'+items.map(function(it,i){return '<span><i style="background:var('+(it.c||['--copper','--slate','--forest','--wood','--info','--warn'][i%6])+')"></i>'+esc(it.name)+'</span>'}).join('')+'</div>'}

/* ---------- blocos ---------- */
function panel(title,sub,right,body,flush){return '<section class="panel"><div class="hd"><h2>'+title+'</h2>'+(sub?'<span class="sub">'+sub+'</span>':'')+(right?'<div class="r">'+right+'</div>':'')+'</div><div class="bd'+(flush?' flush':'')+'">'+body+'</div></section>'}
function ph(kick,title,p,tools){return '<header class="ph"><div><div class="kick">'+kick+'</div><h1>'+title+'</h1>'+(p?'<p>'+p+'</p>':'')+'</div>'+(tools?'<div class="tools">'+tools+'</div>':'')+'</header>'}
function lastIdx(s){for(var i=s.v.length-1;i>=0;i--)if(s.v[i]!=null&&!isNaN(s.v[i]))return i;return -1}
function chgN(s,n){var i=lastIdx(s);if(i<n)return null;var a=s.v[i],b=s.v[i-n];return b?a/b-1:null}
function win3(s){var a=[];for(var i=0;i<s.v.length;i++)if(s.v[i]!=null&&!isNaN(s.v[i]))a.push(s.v[i]);if(a.length<6)return null;var c=(a[a.length-1]+a[a.length-2]+a[a.length-3])/3,p=(a[a.length-4]+a[a.length-5]+a[a.length-6])/3;return p?c/p-1:null}
function tile(o){return '<div class="st"><div class="t"><span class="lbl">'+o.label+'</span>'+(o.chip||'')+'</div>'+
  (o.na?'<div class="v na">'+o.na+'</div>':'<div class="v">'+o.value+'</div>')+'<div class="d">'+(o.d||'')+'</div><div class="foot"><span class="kpi-hint">'+(o.when||'')+'</span>'+(o.src||'')+'</div></div>'}
function tileS(code,geo,label,mode,pol){var s=ser(code,geo);if(!s)return tile({label:label,na:'DADO INDISPONÍVEL',chip:NA});var i=lastIdx(s),p=s.p[i],v=s.v[i],I=D.I[code]||{},d='';
  var l=LAT[code+'|'+geo];pol=pol==null?(I.pol||1):pol;
  if(mode==='3m'){var c=win3(s);d='<span class="'+cls(c,pol)+'">'+arr(c)+' '+pct(c)+'</span> média 3m vs 3m anteriores'}
  else if(mode==='yoyval'){var pv=s.v[i-1];d='mês anterior: '+yoyp(pv)}
  else if(mode==='ann'){var c2=chgN(s,1);d='<span class="'+cls(c2,pol)+'">'+pct(c2)+'</span> sobre o ano anterior'}
  else{var y=l?l.chg_yoy:null,m=l?l.chg_mom:null;d='<span class="'+cls(m,pol)+'">'+pct(m)+'</span> no mês · <span class="'+cls(y,pol)+'">'+pct(y)+'</span> em 12 meses'}
  return tile({label:label,chip:kindChip(code),value:fmtVal(code,v),d:d,when:(I.f==='A'?'ano '+p.slice(0,4):monL(p)+(p===CURM?' · parcial':'')),src:srcS(code,geo,p)})}
function seriesPanel(code,geo,o){o=o||{};var s=ser(code,geo),I=D.I[code]||{};var name=o.title||I.n||code;
  if(!s)return panel(esc(name),'',NA,'<div class="unavail">DADO INDISPONÍVEL'+(o.why?' — '+esc(o.why):'')+'</div>');
  var i=lastIdx(s),p=s.p[i],l=LAT[code+'|'+geo],pol=I.pol||1;
  var st='<div class="srow" style="margin-bottom:8px"><span class="num" style="font-size:18px">'+esc(fmtVal(code,s.v[i]))+'</span><span class="muted small">'+(I.f==='A'?p.slice(0,4):monL(p))+(p===CURM?' (mês parcial)':'')+'</span>';
  if(l&&I.f!=='A'&&!/% a\/a/.test(I.u||''))st+='<span class="small '+cls(l.chg_mom,pol)+'">'+pct(l.chg_mom)+' no mês</span><span class="small '+cls(l.chg_yoy,pol)+'">'+pct(l.chg_yoy)+' em 12m</span>'+(l.vs_avg60!=null?'<span class="small muted">'+pct(l.vs_avg60)+' vs média 60m</span>':'');
  st+='</div>';
  var sp={series:[{name:name,p:s.p,v:s.v}],from:o.from||'2019-01',h:o.h||200,fmt:function(v){return fmtVal(code,v)},zero:o.zero,ref:o.ref,type:o.type,label:name};
  return panel(esc(name),esc(o.sub||I.u||''),kindChip(code)+srcS(code,geo,p),st+chart(sp)+(o.note?'<p class="note">'+o.note+'</p>':''))}
function multiPanel(title,sub,items,o){o=o||{};var ser2=[],chips='',miss=[];items.forEach(function(it){var s=ser(it.i,it.g);if(!s){miss.push(it.name);return}ser2.push({name:it.name,p:s.p,v:s.v,c:it.c,dash:it.dash});chips+=srcS(it.i,it.g,s.p[lastIdx(s)],it.g)});
  var sp={series:ser2,from:o.from||'2019-01',h:o.h||220,fmt:o.fmt,ref:o.ref,zero:o.zero,label:title};
  return panel(title,sub,chips,(ser2.length?chart(sp)+legend(ser2):'<div class="unavail">DADO INDISPONÍVEL</div>')+(miss.length?'<p class="note"><b>DADO INDISPONÍVEL:</b> '+miss.map(esc).join(', ')+(o.why?' — '+o.why:'')+'</p>':'')+(o.note?'<p class="note">'+o.note+'</p>':''))}

/* ---------- comércio ---------- */
var T=D.T,LP=T.last_period.slice(0,7);
var WIN='set/'+(+LP.slice(2,4)-1)+' a '+mon(LP);
var FAM=[['all','Todo o cap. 44'],['plywood','Compensado'],['veneer','Lâminas'],['sawnwood','Serrada'],['panels','Painéis'],['lvl','LVL']];
var FAMN={};FAM.forEach(function(f){FAMN[f[0]]=f[1]});
function famTrace(f,label,val){return srcT({title:label,value:val,src:['comexstat'],fn:'mart.exports_summary(fim '+mon(LP)+', 12 meses'+(f==='all'?'':', família '+f)+')',calc:'Soma do valor FOB (US$) e do volume das exportações brasileiras nos 12 meses até '+monL(LP)+', comparada com os 12 meses anteriores.',note:'Volume em m³: unidade estatística quando é m³; senão, peso líquido ÷ densidade cadastrada do produto (a validar com a engenharia CELPLAC).'})}

/* ---------- páginas ---------- */
var PAGES={},STATE={fam:'all',dfam:'all',comp:'4412',mkt:'USA',nq:''};

PAGES.visao=function(){
  var a=T.summary.all,pw=T.summary.plywood;var h=ph('Visão geral','Mercado de madeira em '+ASOF.split('-').reverse().join('/'),'Tudo nesta tela vem do banco de produção. Onde a fonte não tem o dado, a tela diz DADO INDISPONÍVEL. Clique em <span class="src" style="cursor:default">fonte</span> para ver de onde veio cada número.');
  h+='<div class="status">'+
    tile({label:'Exportações BR · cap. 44',chip:'<span class="chip real">DADO</span>',value:usd(a.value_usd),d:'<span class="'+cls(a.value_var)+'">'+arr(a.value_var)+' '+pct(a.value_var)+'</span> vs 12 meses anteriores · '+m3(a.qty_m3),when:WIN,src:famTrace('all','Exportações BR, cap. 44 (12 meses)',usd(a.value_usd))})+
    tile({label:'Compensado exportado',chip:'<span class="chip real">DADO</span>',value:usd(pw.value_usd),d:'<span class="'+cls(pw.value_var)+'">'+arr(pw.value_var)+' '+pct(pw.value_var)+'</span> · '+m3(pw.qty_m3)+' · US$ '+fmt(pw.price_usd_m3,0)+'/m³',when:WIN,src:famTrace('plywood','Compensado exportado (12 meses)',usd(pw.value_usd))})+
    tileS('PLYWOOD_FOB_BR','BRA','Preço FOB compensado BR')+
    tileS('FX_USD_BRL','BRA','Dólar (PTAX)','',1)+
    tileS('US_HOUSING_STARTS','USA','Casas iniciadas EUA')+
    tileS('RESIN_PPI_THERMOSET_US','USA','Resina termofixa EUA','3m',-1)+
    tileS('FREIGHT_PPI_DEEPSEA_US','USA','Frete marítimo EUA','3m',-1)+
    tileS('BRENT','WLD','Petróleo Brent','',-1)+
    tileS('BR_IP_WOOD','BRA','Produção de madeira BR')+
    tileS('BR_LOG_PINUS_PRICE_IMPL','BRA','Tora de pinus (preço implícito)','ann',-1)+
  '</div>';
  // sinais compactos
  var rows=D.SIG.map(function(s){return '<tr class="click" data-go="sinais"><td>'+esc(ruleName(s.rule_id))+'</td><td>'+esc(cn(s.market_iso3))+'</td><td>'+dots(s)+'</td><td>'+resChip(s.result)+'</td></tr>'}).join('');
  var sig=panel('Sinais de alerta','regras v2 · referência '+mon(D.SIG[0].as_of.slice(0,7)),'<a href="#sinais" class="small">detalhes</a>','<div class="tw"><table class="t"><thead><tr><th>Regra</th><th>Mercado</th><th>Condições</th><th>Resultado</th></tr></thead><tbody>'+rows+'</tbody></table></div><p class="note" style="padding:0 14px 12px">Nenhum sinal disparou. Um sinal exige todas as condições atendidas; uma indicação, a maioria. Condição sem dado atual não conta como evidência.</p>',true);
  var cyc=panel('Ciclo de mercado','posição por nível e momento','',cycleBlock());
  var dq=D.DQ.filter(function(r){return r.passed===false}).map(function(r){return '<div class="li"><span class="sev" style="background:var('+(r.sev==='error'?'--neg':'--warn')+')"></span><div><div class="ti">'+esc(r.desc)+'</div><div class="mt"><span class="chip">'+esc(r.id)+'</span><span class="chip warn">'+fmt(r.fail,0)+' ocorrências</span></div></div></div>'}).join('');
  var dqp=panel('Qualidade de dados','regras que acusaram algo','<a href="#fontes" class="small">todas</a>','<div class="gap-list">'+(dq||'<div class="empty">Todas as regras passaram.</div>')+'</div>',true);
  var ms=T.monthly,mp=T.monthly_plywood;
  var ex=panel('Exportações brasileiras por mês','valor FOB, US$','',chart({series:[{name:'Cap. 44',p:ms.map(function(r){return r.period.slice(0,7)}),v:ms.map(function(r){return r.value_usd})},{name:'Compensado',p:mp.map(function(r){return r.period.slice(0,7)}),v:mp.map(function(r){return r.value_usd}),c:'--forest'}],h:230,fmt:usd,zero:true,label:'Exportações mensais'})+legend([{name:'Todo o cap. 44'},{name:'Compensado',c:'--forest'}])+'<p class="note">Fonte: Comex Stat (MDIC/SECEX). '+srcT({title:'Exportações mensais',src:['comexstat'],fn:'mart.exports_monthly(família, parceiro, fluxo X)',calc:'Soma do FOB por mês'})+'</p>');
  h+='<div class="g g-7-5">'+sig+'<div class="g">'+cyc+dqp+'</div></div>'+ex+gapsPanel();
  return h};

function ruleName(id){var r=D.SIGR.filter(function(x){return x.rule_id===id})[0];return r?r.name.replace(/^SINAL DE /,'').toLowerCase().replace(/^./,function(c){return c.toUpperCase()}):id}
function dots(s){return '<span class="dots" title="'+s.conditions_met+' de '+s.conditions_total+' atendidas">'+s.detail.map(function(d){return '<i class="'+(d.met===true?'y':d.met===false?'n':'u')+'"></i>'}).join('')+'</span>'}
function resChip(r){var c=r==='SINAL'?'SINAL':r==='INDICAÇÃO'?'INDICACAO':r==='SEM SINAL'?'SEM':'EVID';return '<span class="res '+c+'">'+esc(r)+'</span>'}
var PH=['EXPANSÃO','PICO','DESACELERAÇÃO','CONTRAÇÃO','RECUPERAÇÃO'];
function cycleBlock(){return '<div class="cyc">'+D.CYC.map(function(c){var k=PH.indexOf(c.phase),g='<svg width="64" height="64" viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="24" fill="none" style="stroke:var(--line)" stroke-width="6"/>';
  if(k>=0){var a0=(k/5)*2*Math.PI-Math.PI/2,a1=((k+1)/5)*2*Math.PI-Math.PI/2;g+='<path d="M'+(32+24*Math.cos(a0))+' '+(32+24*Math.sin(a0))+' A24 24 0 0 1 '+(32+24*Math.cos(a1))+' '+(32+24*Math.sin(a1))+'" fill="none" style="stroke:var(--copper)" stroke-width="6"/>'}g+='</svg>';
  var lbl=c.indicator_code==='PLYWOOD_FOB_BR'?'Preço FOB do compensado BR':c.indicator_code==='US_HOUSING_STARTS'?'Casas iniciadas EUA':(D.I[c.indicator_code]||{}).n;
  return '<div class="cy">'+g+'<div><div class="ph2">'+esc(c.phase)+'</div><div class="small">'+esc(lbl)+'</div><div class="mini">nível '+pct(c.level_vs_avg)+' vs média · momento 6m '+pct(c.momentum_6m)+' · '+mon(c.period.slice(0,7))+'</div><div style="margin-top:4px">'+kindChip(c.indicator_code)+' '+srcS(c.indicator_code,c.geo_iso3,c.period.slice(0,7))+'</div></div></div>'}).join('')+'</div><p class="note">Só entram indicadores com histórico real suficiente. Os demais componentes do ciclo previstos (lâminas, painéis, construção global) são DADO INDISPONÍVEL.</p>'}
function gapsPanel(){var G=[
  ['Preço mensal da tora de pinus','Ibá/CEPEA — licenciado. Entra por CSV manual quando houver licença.'],
  ['Frete de contêiner Brasil → EUA/Europa/Ásia','Drewry/FBX — licenciado. Hoje usamos o PPI de frete marítimo dos EUA como proxy declarado.'],
  ['Cotação de resina fenólica','Dado interno CELPLAC (Fase 5). Hoje usamos o PPI de resinas termofixas dos EUA como proxy declarado.'],
  ['Macro do México','INEGI exige token (gratuito). Sem ele, a expansão de demanda no México fica com evidência insuficiente.'],
  ['Macro da Arábia Saudita','GASTAT não tem API aberta.'],
  ['Construção na China','Sem série mensal aberta.'],
  ['Produção industrial da China depois de dez/2025','O espelho DBnomics da NBS não traz meses posteriores.'],
  ['Importações da China e da UE (total do bloco)','Comtrade mensal da China para em dez/2024; o total UE exige os 27 membros carregados.'],
  ['Índice CELPLAC de mercado','7 dos 10 componentes configurados não têm dado real. O índice não é calculado com 3 componentes.'],
  ['Notícias e eventos geopolíticos','Nenhum item real cadastrado ainda. A tela não mostra exemplos inventados.'],
  ['Dados internos CELPLAC (vendas, carteira, custos)','Fase 5.']];
  return panel('O que ainda não temos','DADO INDISPONÍVEL — com o motivo','','<div class="gap-list">'+G.map(function(g){return '<div class="li"><span class="sev" style="background:var(--line)"></span><div><div class="ti">'+esc(g[0])+'</div><div class="muted small">'+esc(g[1])+'</div></div></div>'}).join('')+'</div>',true)}

PAGES.exportacoes=function(){var f=STATE.fam,s=T.summary[f];
  var h=ph('Comex Stat · MDIC/SECEX','Exportações brasileiras','Madeira e derivados do capítulo 44 (SH 4403, 4407, 4408, 4410, 4411, 4412). Janela móvel de 12 meses: '+WIN+', contra os 12 meses anteriores.',seg('fam',FAM));
  if(!s)h+='<div class="unavail">SEM EXPORTAÇÕES NESTA FAMÍLIA NO PERÍODO</div>';else h+='<div class="status">'+
    tile({label:'Valor FOB (12m)',chip:'<span class="chip real">DADO</span>',value:usd(s.value_usd),d:'<span class="'+cls(s.value_var)+'">'+arr(s.value_var)+' '+pct(s.value_var)+'</span> vs '+usd(s.value_usd_prev),when:WIN,src:famTrace(f,'Valor FOB — '+FAMN[f],usd(s.value_usd))})+
    tile({label:'Volume (12m)',chip:'<span class="chip ind">INDICADOR</span>',value:m3(s.qty_m3),d:'<span class="'+cls(s.m3_var)+'">'+arr(s.m3_var)+' '+pct(s.m3_var)+'</span> vs '+m3(s.qty_m3_prev),when:'m³ declarados ou peso ÷ densidade',src:famTrace(f,'Volume — '+FAMN[f],m3(s.qty_m3))})+
    tile({label:'Preço médio',chip:'<span class="chip ind">INDICADOR</span>',value:'US$ '+fmt(s.price_usd_m3,0)+'/m³',d:'antes: US$ '+fmt(s.price_usd_m3_prev,0)+'/m³ ('+pct(s.price_usd_m3/s.price_usd_m3_prev-1)+')',when:'valor ÷ volume',src:famTrace(f,'Preço médio — '+FAMN[f],'US$ '+fmt(s.price_usd_m3,0)+'/m³')})+
    tile({label:'Destinos',chip:'<span class="chip real">DADO</span>',value:fmt(s.destinations,0),d:'países com embarque nos 12 meses',when:WIN,src:famTrace(f,'Destinos — '+FAMN[f],fmt(s.destinations,0))})+'</div>';
  var ms=f==='all'?T.monthly:f==='plywood'?T.monthly_plywood:null;
  if(ms)h+=panel('Por mês','valor FOB e volume','',chart({series:[{name:'Valor FOB',p:ms.map(function(r){return r.period.slice(0,7)}),v:ms.map(function(r){return r.value_usd})}],type:'bar',h:220,fmt:usd,label:'Exportações mensais'})+'<p class="note">'+FAMN[f]+'. Barras claras: mês ainda sem dado completo.</p>');
  var DS=STATE.dfam==='plywood'?T.destinations_plywood:T.destinations;
  var gain=DS.filter(function(d){return d.prev_window_complete&&d.share_delta!=null&&d.value_usd>5e6}).sort(function(a,b){return b.share_delta-a.share_delta});
  var dt2='<div class="tw"><table class="t"><thead><tr><th>#</th><th>Destino</th><th>Região</th><th class="n">FOB 12m</th><th class="n">Var.</th><th class="n">Participação</th><th class="n">Δ part.</th><th class="n">m³</th><th class="n">US$/m³</th></tr></thead><tbody>'+
    DS.slice(0,25).map(function(d){return '<tr><td class="n">'+d.rank+'</td><td>'+esc(d.name_pt)+(d.is_new?' <span class="chip info">NOVO</span>':'')+'</td><td class="small muted">'+esc(d.region||'')+'</td><td class="n">'+usd(d.value_usd)+'</td><td class="n '+cls(d.value_var)+'">'+pct(d.value_var)+'</td><td class="n">'+fmt(d.share*100,1)+'%</td><td class="n '+cls(d.share_delta)+'">'+ppt(d.share_delta)+'</td><td class="n">'+m3(d.qty_m3)+'</td><td class="n">'+(d.price_usd_m3?fmt(d.price_usd_m3,0):'—')+'</td></tr>'}).join('')+'</tbody></table></div>';
  h+='<div class="g g-8-4">'+panel('Destinos','top 25 · 12 meses',seg('dfam',[['all','Cap. 44'],['plywood','Compensado']])+srcT({title:'Destinos das exportações',src:['comexstat'],fn:'mart.export_destinations(fim '+mon(LP)+', 12 meses'+(STATE.dfam==='plywood'?', compensado':'')+')',calc:'FOB por país de destino; participação = FOB do país ÷ FOB total; Δ participação em pontos percentuais contra os 12 meses anteriores.'}),dt2,true)+
    '<div class="g">'+panel('Ganhando participação','destinos com mais de US$ 5 mi','',mover(gain.slice(0,6)),true)+panel('Perdendo participação','','',mover(gain.slice(-6).reverse()),true)+'</div></div>';
  var hs=T.by_hs6.slice().sort(function(a,b){return b.value_usd-a.value_usd});
  h+=panel('Por produto (SH6)','12 meses',srcT({title:'Exportações por SH6',src:['comexstat'],fn:'mart.exports_by_hs6(fim '+mon(LP)+', 12 meses)'}),'<div class="tw"><table class="t"><thead><tr><th>SH6</th><th>Produto</th><th class="n">FOB 12m</th><th class="n">Var.</th><th class="n">m³</th><th class="n">US$/m³</th></tr></thead><tbody>'+hs.filter(function(r){return r.value_usd>0}).map(function(r){return '<tr><td class="mono">'+esc(r.hs6)+'</td><td>'+esc(r.description_pt)+'</td><td class="n">'+usd(r.value_usd)+'</td><td class="n '+cls(r.value_var)+'">'+(r.prev_window_complete?pct(r.value_var):'—')+'</td><td class="n">'+m3(r.qty_m3)+'</td><td class="n">'+(r.qty_m3?fmt(r.value_usd/r.qty_m3,0):'—')+'</td></tr>'}).join('')+'</tbody></table></div>',true);
  var port={},uf={};T.flows.forEach(function(r){var k=r.port_name+' ('+r.uf+')';port[k]=(port[k]||0)+r.value_usd;uf[r.uf]=(uf[r.uf]||0)+r.value_usd});
  function barsOf(o,n){var a=Object.keys(o).map(function(k){return [k,o[k]]}).sort(function(x,y){return y[1]-x[1]}).slice(0,n),mx=a.length?a[0][1]:1,tot=0;for(var k in o)tot+=o[k];return '<div class="bars">'+a.map(function(x){return '<div class="bar"><span class="nm">'+esc(x[0])+'</span><span class="tr"><span class="fi" style="width:'+(x[1]/mx*100)+'%;display:block"></span></span><span class="v">'+usd(x[1])+'</span><span class="dd">'+fmt(x[1]/tot*100,1)+'%</span></div>'}).join('')+'</div>'}
  var ft=srcT({title:'Exportações por UF e porto',src:['comexstat'],fn:'mart.export_flows(fim '+mon(LP)+', 12 meses)',note:'UF = estado produtor declarado; porto = unidade de despacho (URF).'});
  h+='<div class="g g2">'+panel('Por estado de origem','12 meses',ft,barsOf(uf,10))+panel('Por porto de saída','12 meses',ft,barsOf(port,10))+'</div>';
  h+=ncmPanel();return h};
function mover(a){if(!a.length)return '<div class="empty">Sem destinos comparáveis.</div>';return '<table class="t"><tbody>'+a.map(function(d){return '<tr><td>'+esc(d.name_pt)+'</td><td class="n '+cls(d.share_delta)+'">'+ppt(d.share_delta)+'</td><td class="n muted">'+usd(d.value_usd)+'</td></tr>'}).join('')+'</tbody></table>'}
function ncmPanel(){var q=(STATE.nq||'').toLowerCase();var rows=T.ncm.filter(function(r){return !q||(r.ncm8+' '+r.description_pt+' '+(r.family||'')).toLowerCase().indexOf(q)>=0}).sort(function(a,b){return b.value_usd-a.value_usd});var tot=rows.length;if(!q)rows=rows.slice(0,15);
  return panel('Consulta por NCM','exportações acumuladas desde jan/2023','<input type="search" id="nq" placeholder="NCM ou descrição" value="'+esc(STATE.nq)+'" aria-label="Buscar NCM">'+srcT({title:'Consulta por NCM',src:['comexstat'],fn:'mart.ncm_search(fluxo X)',calc:'Soma de todos os meses carregados (jan/2023 a '+monL(LP)+').'}),
  '<div class="tw" id="ncmt"><table class="t"><thead><tr><th>NCM</th><th>Descrição</th><th>Família</th><th class="n">FOB</th><th class="n">m³</th><th class="n">US$/m³</th><th class="n">Meses</th></tr></thead><tbody>'+rows.map(function(r){return '<tr><td class="mono">'+esc(r.ncm8)+'</td><td class="small">'+esc(r.description_pt)+'</td><td class="small muted">'+esc(r.family||'—')+'</td><td class="n">'+usd(r.value_usd)+'</td><td class="n">'+m3(r.qty_m3)+'</td><td class="n">'+(r.price_usd_m3?fmt(r.price_usd_m3,0):'—')+'</td><td class="n">'+r.months+'</td></tr>'}).join('')+'</tbody></table>'+(!q&&tot>15?'<p class="note" style="padding:8px 14px">Mostrando os 15 maiores de '+tot+' NCMs. Digite na busca para ver os demais.</p>':'')+'</div>',true)}

/* mercados de destino */
var MK=(function(){var by={};T.imp_br_share.forEach(function(r){(by[r.iso3]=by[r.iso3]||[]).push(r)});var out=[];for(var k in by){var a=by[k].sort(function(x,y){return x.p<y.p?-1:1}),last=a[a.length-1].p;
  var ly=+last.slice(0,4),lm=+last.slice(5,7);function back(n){var y=ly,m=lm-n;while(m<=0){m+=12;y--}return y+'-'+(m<10?'0':'')+m}
  var c12=back(11),p12=back(23),s12=0,b12=0,n12=0,sp=0,np=0;a.forEach(function(r){if(r.p>=c12){n12++;s12+=r.w||0;b12+=r.b||0}else if(r.p>=p12){np++;sp+=r.w||0}});
  var s3=0,sp3=0,c3=back(2),pp3=back(5);a.forEach(function(r){if(r.p>=c3)s3+=r.w||0;else if(r.p>=pp3)sp3+=r.w||0});
  out.push({iso:k,rows:a,last:last,w12:n12===12?s12:null,var12:n12===12&&np===12&&sp?s12/sp-1:null,share:n12===12&&s12?b12/s12:null,var3:sp3?s3/sp3-1:null,stale:last<back2(CURM,6)})}
  return out.sort(function(x,y){return (y.w12||0)-(x.w12||0)})})();
function back2(p,n){var y=+p.slice(0,4),m=+p.slice(5,7)-n;while(m<=0){m+=12;y--}return y+'-'+(m<10?'0':'')+m}
PAGES.mercados=function(){var h=ph('UN Comtrade · SH 4412','Mercados de destino','Importações de compensado e painéis estratificados (SH 4412) de 31 mercados monitorados, de todas as origens e do Brasil. Valor declarado pelo importador (base CIF na maioria dos países).');
  var sel=MK.filter(function(m){return m.iso===STATE.mkt})[0]||MK[0];
  var rows=MK.map(function(m){return '<tr class="click'+(m.iso===sel.iso?' hl':'')+'" data-mkt="'+m.iso+'"><td>'+esc(cn(m.iso))+'</td><td class="n">'+(m.w12!=null?usd(m.w12):'<span class="muted">incompleto</span>')+'</td><td class="n '+cls(m.var12)+'">'+pct(m.var12)+'</td><td class="n '+cls(m.var3)+'">'+pct(m.var3)+'</td><td class="n">'+(m.share!=null?fmt(m.share*100,1)+'%':'—')+'</td><td class="n'+(m.stale?' stale':'')+'">'+mon(m.last)+(m.stale?' ⚠':'')+'</td></tr>'}).join('');
  var tb='<div class="tw"><table class="t"><thead><tr><th>Mercado</th><th class="n">Importação 12m</th><th class="n">Var. 12m</th><th class="n">Var. 3m</th><th class="n">Parte do Brasil</th><th class="n">Último mês</th></tr></thead><tbody>'+rows+'</tbody></table></div><p class="note" style="padding:0 14px 12px">12 meses = os 12 meses até o último mês reportado pelo país. Sem os 12 meses completos, o total não é mostrado. ⚠ = último dado com mais de 6 meses: não conta como evidência nos sinais.</p>';
  var p=sel.rows.map(function(r){return r.p});
  var ch=chart({series:[{name:'De todas as origens',p:p,v:sel.rows.map(function(r){return r.w})},{name:'Do Brasil',p:p,v:sel.rows.map(function(r){return r.b}),c:'--forest'}],h:240,fmt:usd,zero:true,label:'Importações de '+cn(sel.iso)});
  var tt=srcT({title:'Importações de '+cn(sel.iso)+' (SH 4412)',src:['comtrade'],fn:'dw.fact_trade · reporter '+sel.iso+' · fluxo M · SH 4412 · parceiros Mundo e Brasil',note:'API pública de pré-visualização da Comtrade (totais SH4, sem chave). Base CIF quando o país não reporta FOB; não é comparável 1:1 com o FOB do Comex Stat.'});
  h+='<div class="g g-7-5">'+panel('Mercados monitorados','clique para ver o mês a mês','',tb,true)+'<div class="g">'+panel(esc(cn(sel.iso)),'importações mensais, US$','<span class="chip real">DADO</span>'+tt,ch+legend([{name:'De todas as origens'},{name:'Do Brasil',c:'--forest'}]))+
  seriesPanel('EXP_BR_VALUE',sel.iso,{title:'Exportações BR para '+cn(sel.iso)+' (Comex Stat)',from:'2023-01',type:'bar',h:180,sub:'FOB, US$ · cap. 44'})+'</div></div>';
  return h};

/* concorrentes */
PAGES.concorrentes=function(){var hs=STATE.comp,rows=T['comp_'+hs]||[],Y=D.COMPY[hs]||{};
  var h=ph('UN Comtrade · anual','Concorrentes globais','Exportadores mundiais por SH4, ano fechado mais recente com cobertura de reportantes comparável à do ano anterior. O Brasil vem do Comex Stat.',seg('comp',[['4412','4412 Compensado'],['4408','4408 Lâminas'],['4407','4407 Serrada']]));
  var warn=Y.partial?'<p class="note" style="color:var(--warn)"><b>Cobertura parcial:</b> '+Y.yr+' tem '+Y.n+' reportantes, contra '+Y.np+' em '+(Y.yr-1)+'. Nenhum ano recente atinge 90% de cobertura; o ranking pode mudar quando mais países reportarem.</p>':'<p class="note">Ano '+Y.yr+': '+Y.n+' países reportaram ('+Y.np+' em '+(Y.yr-1)+').</p>';
  var mx=rows.length?rows[0].value_usd:1;
  var tb='<div class="tw"><table class="t"><thead><tr><th class="n">#</th><th>País</th><th class="n">Exportação '+Y.yr+'</th><th class="n">'+(Y.yr-1)+'</th><th class="n">Cresc.</th><th class="n">Participação</th><th style="width:28%"></th></tr></thead><tbody>'+
    rows.slice(0,30).map(function(r){return '<tr'+(r.iso3==='BRA'?' class="hl"':'')+'><td class="n">'+r.rank+'</td><td>'+esc(r.name_pt)+'</td><td class="n">'+usd(r.value_usd)+'</td><td class="n muted">'+usd(r.value_usd_prev)+'</td><td class="n '+cls(r.growth)+'">'+pct(r.growth)+'</td><td class="n">'+fmt(r.share*100,1)+'%</td><td><span class="tr" style="display:block;height:10px;background:var(--surface2)"><span style="display:block;height:100%;width:'+(r.value_usd/mx*100)+'%;background:var(--'+(r.iso3==='BRA'?'forest':'copper')+')"></span></span></td></tr>'}).join('')+'</tbody></table></div>';
  var br=rows.filter(function(r){return r.iso3==='BRA'})[0];
  h+='<div class="status">'+tile({label:'Posição do Brasil',chip:'<span class="chip real">DADO</span>',value:br?br.rank+'º':'—',d:br?fmt(br.share*100,1)+'% das exportações mundiais':'Brasil fora do ranking',when:'SH '+hs+' · '+Y.yr})+tile({label:'Exportação do Brasil',chip:'<span class="chip real">DADO</span>',value:br?usd(br.value_usd):'—',d:br?'<span class="'+cls(br.growth)+'">'+pct(br.growth)+'</span> sobre '+(Y.yr-1):'',when:'Comex Stat'})+tile({label:'Líder',chip:'<span class="chip real">DADO</span>',value:rows[0]?esc(rows[0].name_pt):'—',d:rows[0]?fmt(rows[0].share*100,1)+'% · '+usd(rows[0].value_usd):'',when:'Comtrade'})+tile({label:'Países no ranking',chip:'<span class="chip real">DADO</span>',value:fmt(rows.length,0),d:'com exportação positiva',when:'SH '+hs})+'</div>';
  h+=panel('Ranking de exportadores','SH '+hs+' · '+Y.yr,srcT({title:'Concorrentes SH '+hs,src:['comtrade','comexstat'],fn:"mart.competitors('"+hs+"')",calc:'Exportações de cada país para o mundo; participação sobre a soma dos reportantes. Crescimento contra o ano anterior.',note:'Volume em m³ indisponível no agregado SH4 da Comtrade (sem unidade m³ declarada).'}),warn+tb,false);
  return h};

PAGES.precos=function(){var h=ph('Preços e custos','Preços e custos','Preço do produto brasileiro, do concorrente americano e dos insumos. Proxies aparecem marcados como tal: aproximam um dado que é licenciado ou interno.');
  h+='<div class="g g2">'+seriesPanel('PLYWOOD_FOB_BR','BRA',{sub:'US$/m³ · valor ÷ volume exportado',from:'2023-01'})+seriesPanel('US_PPI_SOFTWOOD_PLYWOOD','USA',{sub:'índice 1982=100'})+
    seriesPanel('BR_IPP_WOOD','BRA',{sub:'índice dez/2018=100'})+seriesPanel('BR_LOG_PINUS_PRICE_IMPL','BRA',{type:'bar',from:'2013',sub:'R$/m³ · anual',note:'Valor da produção ÷ quantidade (PEVS/IBGE). Referência estrutural de custo; não substitui a cotação mensal.'})+
    seriesPanel('RESIN_PPI_THERMOSET_US','USA',{sub:'índice · proxy da resina fenólica'})+seriesPanel('FREIGHT_PPI_DEEPSEA_US','USA',{sub:'índice dez/1988=100 · proxy do frete de contêiner'})+
    seriesPanel('BRENT','WLD',{sub:'US$/barril · média mensal'})+panel('Tora de pinus — cotação mensal','R$/m³',NA,'<div class="unavail">DADO INDISPONÍVEL — Ibá/CEPEA são licenciados. Entra por CSV manual.</div><p class="note">A condição “Tora ↑” da regra de pressão de custo fica sem dado enquanto isso.</p>')+'</div>';
  return h};

PAGES.cambio=function(){var h=ph('BCB PTAX · Fed H.10','Câmbio','PTAX de fechamento do Banco Central. Peso mexicano e yuan não são publicados pela PTAX: saem do cruzamento PTAX ÷ taxa do Fed no mesmo dia útil (indicador calculado).');
  var rows=D.FX.map(function(f){return '<tr><td>'+esc(f.name_pt)+'</td><td>'+kindChip(f.indicator_code)+'</td><td class="n">'+fmt(f.value,4)+'</td><td class="n muted">'+mon(f.period.slice(0,7))+'</td><td class="n '+cls(f.chg_mom,1)+'">'+pct(f.chg_mom)+'</td><td class="n '+cls(f.chg_yoy,1)+'">'+pct(f.chg_yoy)+'</td><td class="n">'+(f.vol_12m!=null?fmt(f.vol_12m*100,1)+'%':'—')+'</td><td>'+srcS(f.indicator_code,f.geo_iso3,f.period.slice(0,7))+'</td></tr>'}).join('');
  h+=panel('Resumo','média mensal; setembro parcial','','<div class="tw"><table class="t"><thead><tr><th>Moeda</th><th></th><th class="n">R$</th><th class="n">Mês</th><th class="n">No mês</th><th class="n">12 meses</th><th class="n">Volatilidade 12m</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div>',true);
  h+='<div class="g g2">'+seriesPanel('FX_USD_BRL','BRA',{sub:'R$ por US$'})+seriesPanel('FX_EUR_BRL','BRA',{sub:'R$ por €'})+seriesPanel('FX_GBP_BRL','BRA',{sub:'R$ por £'})+seriesPanel('FX_MXN_BRL','BRA',{sub:'R$ por peso mexicano'})+seriesPanel('FX_CNY_BRL','BRA',{sub:'R$ por yuan'})+'</div>';
  return h};

PAGES.macro=function(){var h=ph('Demanda','Construção e macroeconomia','Demanda nos mercados de destino e oferta de madeira no Brasil. Variações anuais vêm do órgão oficial de cada país.');
  h+=multiPanel('Construção residencial nos EUA','mil unidades/ano, ajustado',[{i:'US_HOUSING_STARTS',g:'USA',name:'Casas iniciadas'},{i:'US_HOUSING_STARTS_1F',g:'USA',name:'Unifamiliares',c:'--forest'},{i:'US_BUILDING_PERMITS',g:'USA',name:'Licenças',c:'--slate',dash:1}],{fmt:function(v){return fmt(v,0)+' mil'},note:'Fonte: US Census via FRED. O mercado americano concentra '+fmt((T.destinations.filter(function(d){return d.iso3==='USA'})[0]||{share:0}).share*100,0)+'% das exportações brasileiras do cap. 44 nos últimos 12 meses.'});
  var geos=[{g:'USA',name:'EUA'},{g:'EUU',name:'União Europeia',c:'--slate'},{g:'ARG',name:'Argentina',c:'--forest'},{g:'CHN',name:'China',c:'--wood'},{g:'MEX',name:'México',c:'--info'},{g:'SAU',name:'Arábia Saudita',c:'--warn'}];
  h+='<div class="g g2">'+multiPanel('Produção industrial','% sobre o mesmo mês do ano anterior',geos.map(function(x){return {i:'MACRO_IP_YOY',g:x.g,name:x.name,c:x.c}}),{from:'2022-01',ref:0,fmt:yoyp,why:'INEGI exige token; GASTAT sem API aberta',note:'China: série parada em dez/2025.'})+
    multiPanel('Construção','% sobre o mesmo mês do ano anterior',geos.filter(function(x){return x.g!=='CHN'}).concat([{g:'CHN',name:'China'}]).map(function(x){return {i:'MACRO_CONSTRUCTION_YOY',g:x.g,name:x.name,c:x.c}}),{from:'2022-01',ref:0,fmt:yoyp,why:'sem série mensal aberta (China), INEGI exige token (México), GASTAT sem API (Arábia Saudita)',note:'EUA: gasto nominal em construção (TTLCONS). UE: produção da construção (Eurostat). Argentina: ISAC (INDEC).'})+'</div>';
  h+='<div class="g g2">'+seriesPanel('BR_IP_WOOD','BRA',{sub:'índice 2022=100, dessazonalizado · PIM-PF/IBGE',from:'2016-01'})+
    multiPanel('Silvicultura brasileira','m³ de tora por ano · PEVS/IBGE',[{i:'BR_SILV_PINUS_M3',g:'BRA',name:'Pinus — total'},{i:'BR_SILV_PINUS_OTHER_M3',g:'BRA',name:'Pinus — outras finalidades',c:'--copper',dash:1},{i:'BR_SILV_EUCA_M3',g:'BRA',name:'Eucalipto — total',c:'--slate'},{i:'BR_SILV_EUCA_OTHER_M3',g:'BRA',name:'Eucalipto — outras finalidades',c:'--slate',dash:1}],{from:'2013',fmt:m3,zero:true,note:'“Outras finalidades” exclui papel e celulose: é a tora que abastece serrarias e laminadoras. A PEVS 2025 saiu em setembro e revisou 2024.'})+'</div>';
  return h};

PAGES.sinais=function(){var h=ph('Early warning','Sinais e ciclo','Regras declaradas e versionadas. Cada condição compara a variação recente de um indicador (média dos 3 últimos meses contra os 3 anteriores, ou a variação anual) com um limiar. O resultado é SINAL (todas atendidas), INDICAÇÃO (maioria), SEM SINAL ou EVIDÊNCIA INSUFICIENTE (faltam dados para decidir).');
  D.SIGR.forEach(function(r){var st=D.SIG.filter(function(s){return s.rule_id===r.rule_id});
    var cards=st.map(function(s){return '<div class="sg"><div class="h"><span class="mk">'+esc(cn(s.market_iso3))+'</span>'+resChip(s.result)+'</div><div class="mini">'+s.conditions_met+' de '+s.conditions_total+' condições atendidas</div>'+s.detail.map(function(d){var obs=d.observed==null?'sem dado':(d.test==='positive'?yoyp(d.observed)+' a/a':pct(d.observed)+' (3m)');
      var thr=d.test==='up'?'> +'+fmt(d.threshold*100,0)+'%':d.test==='down'?'< −'+fmt(d.threshold*100,0)+'%':d.test==='stable'?'entre ±'+fmt(d.threshold*100,0)+'%':'> 0';
      return '<div class="cond"><span class="m '+(d.met===true?'up':'fl')+'">'+(d.met===true?'✓':d.met===false?'✗':'?')+'</span><span>'+esc(d.label)+(d.stale?' <span class="chip warn">defasado · '+mon((d.last_period||'').slice(0,7))+'</span>':'')+(d.met==null&&!d.stale?' <span class="chip na">sem dado</span>':'')+'<br><span class="mini">limiar '+thr+'</span></span><span class="o">'+obs+(d.observed!=null&&d.last_period?' '+srcS(d.indicator,d.geo,d.last_period.slice(0,7),mon(d.last_period.slice(0,7))):'')+'</span></div>'}).join('')+'</div>'}).join('');
    h+=panel(esc(r.name.replace(/^SINAL DE /,'')),'v'+r.version+' · referência '+mon(st[0]?st[0].as_of.slice(0,7):''),'<span class="chip">mín. '+r.min_met_for_indication+' p/ indicação</span>','<div class="sig">'+cards+'</div>',true)});
  h+='<p class="note">Correlação não é causalidade: um sinal diz que as condições da regra ocorreram juntas, não que uma causou a outra. Condição com último dado há mais de 6 meses é tratada como sem dado.</p>';
  var cfg=D.IDX[0]||{components:[]};var comp=cfg.components.map(function(c){var ok=!!ser(c.indicator,c.geo);return '<tr><td class="mono small">'+esc(c.indicator)+'</td><td>'+esc(cn(c.geo))+'</td><td class="n">'+c.weight+'</td><td>'+(c.invert?'invertido':'')+'</td><td>'+(ok?'<span class="chip real">com dado</span>':NA)+'</td></tr>'}).join('');
  var have=cfg.components.filter(function(c){return !!ser(c.indicator,c.geo)}).length;
  h+='<div class="g g2">'+panel('Ciclo de mercado','','',cycleBlock())+panel('Índice CELPLAC de mercado','configuração padrão','<span class="res EVID">EVIDÊNCIA INSUFICIENTE</span>','<p class="note" style="padding:12px 14px 0">'+have+' de '+cfg.components.length+' componentes têm dado real. O índice não é calculado com a maioria dos pesos sem dado; os pesos iguais também não são definitivos (estudo previsto na Fase 4).</p><div class="tw"><table class="t"><thead><tr><th>Componente</th><th>Geo</th><th class="n">Peso</th><th></th><th>Situação</th></tr></thead><tbody>'+comp+'</tbody></table></div>',true)+'</div>';
  return h};

PAGES.fontes=function(){var h=ph('Rastreabilidade','Fontes e qualidade','Situação de cada fonte, regras de qualidade de dados e as cargas feitas no banco, com o arquivo de origem e o SHA-256 de cada uma.');
  var stc={INTEGRADO:'pos','SEM DADOS':'','SIMULADO':'warn'};
  var sq=D.SQ.slice().sort(function(a,b){return (a.integration_status==='INTEGRADO'?0:1)-(b.integration_status==='INTEGRADO'?0:1)||a.name.localeCompare(b.name)});
  h+=panel('Fontes','',D.MIG+' migrações aplicadas','<div class="tw"><table class="t"><thead><tr><th>Fonte</th><th>Situação</th><th>Tipo</th><th>Confiab.</th><th class="n">Períodos</th><th class="n">De</th><th class="n">Até</th><th class="n">Última carga</th><th class="n">Linhas rejeitadas</th></tr></thead><tbody>'+
    sq.map(function(s){return '<tr><td>'+esc(s.name)+'</td><td><span class="chip '+(stc[s.integration_status]||'')+'">'+esc(s.integration_status)+'</span></td><td class="small muted">'+esc(s.source_type)+'</td><td class="small">'+esc(s.reliability||'')+'</td><td class="n">'+(s.periods||'—')+'</td><td class="n">'+(s.first_period?mon(s.first_period.slice(0,7)):'—')+'</td><td class="n">'+(s.last_period?mon(s.last_period.slice(0,7)):'—')+'</td><td class="n">'+(s.last_run_at?dt(s.last_run_at):'—')+'</td><td class="n">'+(s.rejected_rows||0)+'</td></tr>'}).join('')+'</tbody></table></div>',true);
  h+=panel('Regras de qualidade','última verificação','','<div class="tw"><table class="t"><thead><tr><th>Regra</th><th>O que verifica</th><th>Gravidade</th><th class="n">Ocorrências</th><th>Resultado</th></tr></thead><tbody>'+
    D.DQ.map(function(r){return '<tr><td class="mono small">'+esc(r.id)+'</td><td class="small">'+esc(r.desc)+'</td><td class="small">'+(r.sev==='error'?'erro':'aviso')+'</td><td class="n">'+fmt(r.fail,0)+'</td><td>'+(r.passed?'<span class="chip pos">OK</span>':'<span class="chip warn">ACUSOU</span>')+'</td></tr>'}).join('')+'</tbody></table></div><p class="note" style="padding:0 14px 12px"><b>Leitura:</b> os saltos restantes são reais (embarques pontuais para destinos pequenos e a retomada após a greve dos caminhoneiros em jun/2018). A divergência do espelho compara FOB brasileiro com CIF do importador: diferença esperada acima de 15% em parte dos países. Série parada: só a produção industrial da China.</p>',true);
  var runs=Object.keys(D.RUNS).map(Number).sort(function(a,b){return b-a});
  h+=panel('Cargas no banco','execuções reais, mais recentes primeiro','','<div class="tw"><table class="t"><thead><tr><th class="n">Run</th><th>Fonte</th><th>Tarefa</th><th>Situação</th><th class="n">Concluída</th><th class="n">Linhas</th><th>Arquivos de origem (SHA-256)</th></tr></thead><tbody>'+
    runs.map(function(k){var R=D.RUNS[k],f=rawOf(k);return '<tr><td class="n">'+k+'</td><td class="small">'+esc(R.s)+'</td><td class="mono small">'+esc(R.j)+'</td><td class="small">'+esc(R.st)+'</td><td class="n">'+dt(R.f)+'</td><td class="n">'+(R.n!=null?fmt(R.n,0):'—')+'</td><td class="mini">'+(f.length?f.slice(0,2).map(function(x){return '<span title="'+esc(x.uri)+'">'+esc(x.sha.slice(0,12))+'…</span>'}).join(' ')+(f.length>2?' +'+(f.length-2):''):'cálculo')+'</td></tr>'}).join('')+'</tbody></table></div>',true);
  h+=gapsPanel();return h};

function seg(key,opts){return '<div class="seg" role="group">'+opts.map(function(o){return '<button type="button" data-seg="'+key+'" data-v="'+o[0]+'" class="'+(STATE[key]===o[0]?'on':'')+'" aria-pressed="'+(STATE[key]===o[0])+'">'+esc(o[1])+'</button>'}).join('')+'</div>'}

/* ---------- navegação ---------- */
var NAV=[['Painel',[['visao','Visão geral']]],['Comércio',[['exportacoes','Exportações BR'],['mercados','Mercados de destino'],['concorrentes','Concorrentes']]],['Mercado',[['precos','Preços e custos'],['cambio','Câmbio'],['macro','Construção e macro']]],['Inteligência',[['sinais','Sinais e ciclo']]],['Base',[['fontes','Fontes e qualidade']]]];
var TITLES={};NAV.forEach(function(g){g[1].forEach(function(i){TITLES[i[0]]=g[0]+' / '+i[1]})});
var CUR=null;
function render(){var p=(location.hash||'#visao').slice(1);if(!PAGES[p])p='visao';if(p!==CUR)window.scrollTo(0,0);CUR=p;CH=[];TR=[];
  document.getElementById('view').innerHTML=PAGES[p]();document.getElementById('crumb').textContent='CELPLAC GWMI / '+TITLES[p].toUpperCase();
  document.querySelectorAll('.nav a').forEach(function(a){var on=a.getAttribute('data-p')===p;a.classList.toggle('on',on);if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
  document.getElementById('side').classList.remove('open');drawAll()}
function init(){TIP=document.getElementById('tip');
  document.getElementById('nav').innerHTML=NAV.map(function(g){return '<div class="grp">'+g[0]+'</div>'+g[1].map(function(i){return '<a href="#'+i[0]+'" data-p="'+i[0]+'">'+i[1]+'</a>'}).join('')}).join('');
    document.getElementById('bandt').textContent=D.LIVE?'Ao vivo: consultado no banco de produção em '+dt(D.ASOF)+'. Nenhum número simulado.':'Dados reais do banco de produção, extraídos em '+dt(D.ASOF)+'. Nenhum número simulado. Para atualizar, peça um novo retrato.';
  document.getElementById('asof').textContent=(D.LIVE?'ao vivo · ':'retrato do banco · ')+dt(D.ASOF);
  document.addEventListener('click',function(e){var b=e.target.closest('[data-tr]');if(b){e.preventDefault();openTrace(TR[+b.getAttribute('data-tr')]);return}
    var s=e.target.closest('[data-seg]');if(s){STATE[s.getAttribute('data-seg')]=s.getAttribute('data-v');render();return}
    var m=e.target.closest('[data-mkt]');if(m){STATE.mkt=m.getAttribute('data-mkt');var y=window.scrollY;render();window.scrollTo(0,y);return}
    var g=e.target.closest('[data-go]');if(g&&!e.target.closest('button,a')){location.hash=g.getAttribute('data-go');return}
    if(e.target.id==='scrim'||e.target.id==='dx')closeTrace();if(e.target.id==='burger')document.getElementById('side').classList.toggle('open')});
  document.addEventListener('keydown',function(e){if(e.key==='Escape')closeTrace()});
  document.addEventListener('input',function(e){if(e.target.id==='nq'){STATE.nq=e.target.value;var t=document.createElement('div');t.innerHTML=ncmPanel();document.getElementById('ncmt').innerHTML=t.querySelector('#ncmt').innerHTML}});
  window.addEventListener('hashchange',render);var rz;window.addEventListener('resize',function(){clearTimeout(rz);rz=setTimeout(drawAll,150)});render()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
}

/* ---------- carregamento: retrato embutido ou API ao vivo ---------- */
(function(){
  var KEY='gwmi-api-key';
  function getKey(){try{return localStorage.getItem(KEY)||''}catch(e){return ''}}
  function setKey(k){try{if(k)localStorage.setItem(KEY,k);else localStorage.removeItem(KEY)}catch(e){}}
  function view(){return document.getElementById('view')}
  function keyForm(msg){view().innerHTML='<header class="ph"><div><div class="kick">Acesso</div><h1>Chave de acesso</h1><p>Este painel lê o banco de produção da CELPLAC pela API. Informe a chave que você recebeu. Ela fica guardada só neste navegador.</p></div></header>'+
    (msg?'<p class="note" style="color:var(--neg)">'+msg+'</p>':'')+
    '<form id="kf" class="srow" autocomplete="off"><label for="kin" class="lbl">Chave</label><input id="kin" type="password" style="min-width:0;flex:1;max-width:420px" required><button type="submit" class="x" style="align-self:auto">Entrar</button></form>';
    document.getElementById('kf').addEventListener('submit',function(e){e.preventDefault();var k=document.getElementById('kin').value.trim();setKey(k);load()})}
  function load(){var k=getKey();if(!k){keyForm('');return}
    view().innerHTML='<div class="empty">Consultando o banco…</div>';
    fetch('v1/panel',{headers:{'X-API-Key':k}}).then(function(r){
      if(r.status===401){setKey('');keyForm('Chave recusada. Confira e tente de novo.');return null}
      if(!r.ok){view().innerHTML='<div class="unavail">A API respondeu '+r.status+'. Tente de novo em instantes.</div>';return null}
      return r.json()}).then(function(j){if(!j)return;window.GWMI=j.data;window.GWMI.LIVE=true;gwmiApp()})
    .catch(function(){view().innerHTML='<div class="unavail">Não foi possível falar com a API. Se ela estava parada, a primeira consulta pode levar até 1 minuto: recarregue a página.</div>'})}
  function go(){if(window.GWMI){gwmiApp()}else{document.getElementById('bandt').textContent='Dados reais, lidos ao vivo do banco de produção.';load()}}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go();
})();
