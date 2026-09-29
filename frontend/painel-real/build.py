"""Monta o painel.

  python build.py live
      → backend/app/static/painel.html, servido pela API em "/"; lê /v1/panel ao vivo (com chave).
  python build.py snapshot series.json meta.json trade.json [saida/]
      → celplac-painel.html + gwmi-data.js: retrato publicado sem API.
      Os três JSON são o resultado de SQL_SERIES, SQL_META e SQL_TRADE (backend/app/panel.py).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def page(data_tag: str) -> str:
    css = (HERE / "proto.css").read_text() + (HERE / "extra.css").read_text()
    js = (HERE / "app.js").read_text()
    return ('<title>Painel CELPLAC GWMI</title>\n'
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700'
            '&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">\n'
            '<style>' + css + '</style>\n'
            '<div class="app">\n<aside class="side" id="side"><div class="brand"><div class="co">CELPLAC</div>'
            '<div class="nm">Global Wood Market Intelligence</div><div class="sb">Compensados multilaminados · inteligência de mercado</div>'
            '</div><nav class="nav" id="nav" aria-label="Seções"></nav></aside>\n<div class="main">\n'
            '<div class="real-band"><b>DADOS REAIS</b><span id="bandt"></span></div>\n'
            '<div class="top"><button class="burger" id="burger" aria-label="Abrir menu">☰</button><span class="crumb" id="crumb"></span>'
            '<span class="sp"></span><span class="asof" id="asof"></span></div>\n'
            '<main class="content" id="view"></main>\n</div></div>\n'
            '<div class="scrim" id="scrim" hidden></div><aside class="drawer" id="drawer" hidden aria-label="Origem do número"></aside>'
            '<div id="tip" hidden></div>\n' + data_tag + '<script>' + js + '</script>\n')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "live"
    if mode == "live":
        out = ROOT / "backend" / "app" / "static" / "painel.html"
        out.parent.mkdir(exist_ok=True)
        head = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                '<meta name="robots" content="noindex"></head><body>')
        out.write_text(head + page("") + "</body></html>", encoding="utf-8")
        print("→", out)
    else:
        from app.panel import shape
        s, m, t = (json.loads(Path(p).read_text()) for p in sys.argv[2:5])
        asof, series = (s["asof"], s["series"]) if isinstance(s, dict) else (s[0]["asof"], json.loads(s[0]["series"]))
        meta = m if "indicators" in m else json.loads(m[0]["meta"])
        trade = t if "summary" in t else json.loads(t[0]["trade"])
        D = shape(asof, series if isinstance(series, list) else json.loads(series), meta, trade)
        dst = Path(sys.argv[5]) if len(sys.argv) > 5 else HERE / "dist"
        dst.mkdir(exist_ok=True)
        (dst / "gwmi-data.js").write_text("window.GWMI=" + json.dumps(D, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";")
        (dst / "celplac-painel.html").write_text(page('<script src="gwmi-data.js"></script>\n'))
        print("→", dst)


if __name__ == "__main__":
    main()
