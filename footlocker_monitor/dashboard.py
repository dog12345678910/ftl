"""Interactive web control panel for the restock monitor.

Serves a browser UI where you can add/remove watched products, trigger an
instant check, and see live stock — plus a JSON API. It can run the monitor
loop itself in a background thread, so one ``--dashboard`` process both watches
for restocks and lets you manage what's watched without editing config.json.

Built on the standard-library HTTP server — no extra dependencies.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from . import history
from .config import Config
from .product import WatchedProduct
from .retailers import get_retailer
from .state import StateStore

log = logging.getLogger(__name__)


# --- watch-list management (kept as plain functions so they're testable) ----

def add_watch(config: Config, spec) -> WatchedProduct:
    """Add (or replace, by SKU) a watched product from a dict or URL/SKU string."""
    if isinstance(spec, dict):
        raw = spec.get("input") or spec.get("url") or spec.get("sku")
        if spec.get("url") or spec.get("sku"):
            wp = WatchedProduct.from_config(spec)
        elif raw:
            wp = WatchedProduct.from_url_or_sku(str(raw))
            if spec.get("name"):
                wp.name = str(spec["name"]).strip()
            if spec.get("sizes"):
                wp.sizes = _clean_sizes(spec["sizes"])
        else:
            raise ValueError("provide a Foot Locker URL or SKU")
    else:
        wp = WatchedProduct.from_url_or_sku(str(spec))
    config.watch = [w for w in config.watch if w.sku != wp.sku] + [wp]
    return wp


def remove_watch(config: Config, sku: str) -> bool:
    before = len(config.watch)
    config.watch = [w for w in config.watch if w.sku != sku]
    return len(config.watch) < before


def _clean_sizes(sizes) -> list[str]:
    if isinstance(sizes, str):
        sizes = sizes.replace(",", " ").split()
    return [str(s).strip() for s in sizes if str(s).strip()]


def build_status(config: Config) -> dict:
    """Assemble the payload the dashboard renders. Watch list is the source of
    truth; live availability is merged in from the state file."""
    store = StateStore(config.state_file)
    state_by_sku = {row["sku"]: row for row in store.snapshot()}
    products = []
    for w in config.watch:
        row = state_by_sku.get(w.sku)
        if row:
            row = dict(row)
            row["pending"] = False
            if not row.get("name"):
                row["name"] = w.name or w.sku
            products.append(row)
        else:
            products.append({
                "sku": w.sku,
                "name": w.name or w.sku,
                "url": w.url or get_retailer(w.retailer).product_url(w.sku),
                "retailer": w.retailer,
                "in_stock": False,
                "available_sizes": [],
                "price": None,
                "checked_at": None,
                "error": None,
                "pending": True,
            })
    return {
        "products": products,
        "events": history.read_recent(config.history_file, limit=50),
        "in_stock_count": sum(1 for p in products if p.get("in_stock")),
        "watched_count": len(config.watch),
        "interval_seconds": config.interval_seconds,
    }


class _Context:
    """Shared server state: the config, where to persist it, and the monitor."""

    def __init__(self, config: Config, config_path: Optional[str], monitor) -> None:
        self.config = config
        self.config_path = config_path
        self.monitor = monitor
        self._lock = threading.Lock()

    def save(self) -> None:
        if self.config_path:
            with self._lock:
                self.config.save(self.config_path)

    def check_now(self) -> int:
        if not self.monitor:
            return 0
        return len(self.monitor.check_once())


class _Server(ThreadingHTTPServer):
    context: _Context


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence default request logging
        return

    @property
    def ctx(self) -> _Context:
        return self.server.context  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        if self.path.startswith("/api/status"):
            self._json(build_status(self.ctx.config))
        elif self.path in ("/", "/index.html"):
            self._html(_PAGE)
        else:
            self.send_error(404, "Not found")

    def do_POST(self) -> None:
        data = self._body()
        try:
            if self.path == "/api/watch":
                wp = add_watch(self.ctx.config, data)
                self.ctx.save()
                self._json({"ok": True, "sku": wp.sku, "name": wp.name, "retailer": wp.retailer})
            elif self.path == "/api/unwatch":
                ok = remove_watch(self.ctx.config, str(data.get("sku", "")))
                self.ctx.save()
                self._json({"ok": ok})
            elif self.path == "/api/check":
                alerts = self.ctx.check_now()
                self._json({"ok": True, "alerts": alerts})
            else:
                self.send_error(404, "Not found")
        except ValueError as exc:
            self._json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            log.exception("dashboard action failed")
            self._json({"ok": False, "error": str(exc)}, status=500)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}

    def _json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(
    config: Config,
    port: int = 8000,
    run_monitor: bool = True,
    host: str = "0.0.0.0",
    config_path: Optional[str] = None,
) -> None:
    """Start the control panel (and, by default, the monitor loop)."""
    from .monitor import Monitor

    monitor = Monitor(config)
    if run_monitor:
        threading.Thread(target=monitor.run_forever, daemon=True).start()
        log.info("Monitor loop running in the background.")

    server = _Server((host, port), _Handler)
    server.context = _Context(config, config_path, monitor)
    shown = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
    log.info("Dashboard: http://%s:%d  (Ctrl+C to stop)", shown, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        server.shutdown()


# --- the page (self-contained: inline CSS + JS) ----------------------------

_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Restock Monitor</title>
<style>
  :root {
    --bg:#f6f7f4; --panel:#fff; --panel2:#fbfbf9; --line:#e6e6df; --ink:#17181c;
    --muted:#6c6f78; --faint:#9a9da6; --accent:#3a53d0; --accent-soft:rgba(58,83,208,.10);
    --in:#128a4e; --in-soft:rgba(18,138,78,.12); --out:#6c7280; --out-soft:rgba(108,114,128,.12);
    --warn:#a9631a; --warn-soft:rgba(169,99,26,.13); --pending:#7a7f8a; --pending-soft:rgba(122,127,138,.12);
    --radius:14px; --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,"Roboto Mono",monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  @media (prefers-color-scheme: dark){ :root{
    --bg:#0d0f13; --panel:#14171d; --panel2:#171b22; --line:#262b34; --ink:#e9ecf2;
    --muted:#8b919e; --faint:#626775; --accent:#7d94ff; --accent-soft:rgba(125,148,255,.13);
    --in:#45d089; --in-soft:rgba(69,208,137,.13); --out:#8b919e; --out-soft:rgba(139,145,158,.13);
    --warn:#e0a558; --warn-soft:rgba(224,165,88,.14); --pending:#767c88; --pending-soft:rgba(118,124,136,.14);
  }}
  :root[data-theme="light"]{ --bg:#f6f7f4;--panel:#fff;--panel2:#fbfbf9;--line:#e6e6df;--ink:#17181c;--muted:#6c6f78;--faint:#9a9da6;--accent:#3a53d0;--accent-soft:rgba(58,83,208,.10);--in:#128a4e;--in-soft:rgba(18,138,78,.12);--out:#6c7280;--out-soft:rgba(108,114,128,.12);--warn:#a9631a;--warn-soft:rgba(169,99,26,.13);--pending:#7a7f8a;--pending-soft:rgba(122,127,138,.12); }
  :root[data-theme="dark"]{ --bg:#0d0f13;--panel:#14171d;--panel2:#171b22;--line:#262b34;--ink:#e9ecf2;--muted:#8b919e;--faint:#626775;--accent:#7d94ff;--accent-soft:rgba(125,148,255,.13);--in:#45d089;--in-soft:rgba(69,208,137,.13);--out:#8b919e;--out-soft:rgba(139,145,158,.13);--warn:#e0a558;--warn-soft:rgba(224,165,88,.14);--pending:#767c88;--pending-soft:rgba(118,124,136,.14); }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1080px;margin:0 auto;padding:26px 22px 60px}
  .top{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  .brand{display:flex;align-items:center;gap:11px}
  .glyph{width:34px;height:34px;border-radius:9px;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent);font-size:19px}
  .brand h1{margin:0;font-size:19px;font-weight:680;letter-spacing:-.01em}
  .brand .sub{margin:0;font-size:12.5px;color:var(--muted)}
  .live{margin-left:auto;display:inline-flex;align-items:center;gap:7px;font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums}
  .live .dot{width:8px;height:8px;border-radius:50%;background:var(--in);animation:pulse 2.4s infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 var(--in-soft)}70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
  @media (prefers-reduced-motion:reduce){.live .dot{animation:none}}
  button{font-family:inherit;cursor:pointer}
  .btn{background:var(--panel);border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:7px 12px;font-size:13px}
  .btn:hover{color:var(--ink)}
  .btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
  .btn.primary:hover{filter:brightness(1.06);color:#fff}

  .tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0 4px}
  @media (max-width:620px){.tiles{grid-template-columns:repeat(2,1fr)}}
  .tile{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:15px 16px}
  .tile .k{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);font-weight:600}
  .tile .v{margin-top:6px;font-size:27px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
  .tile .v.on{color:var(--in)}

  h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--faint);font-weight:680;margin:30px 0 12px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}

  .add{display:flex;gap:10px;flex-wrap:wrap;padding:16px}
  .add input{flex:1 1 260px;min-width:0;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:9px;padding:10px 12px;font-size:14px;font-family:inherit}
  .add input.small{flex:0 1 150px}
  .add input:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:transparent}
  .msg{padding:0 16px 14px;font-size:13px;color:var(--muted);min-height:0}
  .msg.err{color:var(--warn)}
  .msg.ok{color:var(--in)}

  .table-scroll{overflow-x:auto}
  table{width:100%;border-collapse:collapse;min-width:660px}
  thead th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint);font-weight:620;padding:12px 16px;border-bottom:1px solid var(--line)}
  tbody td{padding:12px 16px;border-bottom:1px solid var(--line);vertical-align:middle}
  tbody tr:last-child td{border-bottom:none}
  tbody tr:hover{background:var(--panel2)}
  .pname{font-weight:600;letter-spacing:-.005em}
  .pname a{color:inherit;text-decoration:none}
  .pname a:hover{color:var(--accent)}
  .sku{font-family:var(--mono);font-size:11.5px;color:var(--faint);margin-top:2px}
  .store{font-size:12.5px;color:var(--muted)}
  .sizes{font-family:var(--mono);font-size:13px;font-variant-numeric:tabular-nums}
  .price{font-variant-numeric:tabular-nums;font-weight:560}
  .when{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
  .pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px 3px 8px;border-radius:999px;font-size:12px;font-weight:620;white-space:nowrap}
  .pill .d{width:6px;height:6px;border-radius:50%;background:currentColor}
  .pill.in{background:var(--in-soft);color:var(--in)}
  .pill.out{background:var(--out-soft);color:var(--out)}
  .pill.err{background:var(--warn-soft);color:var(--warn)}
  .pill.pending{background:var(--pending-soft);color:var(--pending)}
  .x{background:none;border:1px solid var(--line);color:var(--faint);border-radius:7px;padding:4px 9px;font-size:12px}
  .x:hover{color:var(--warn);border-color:var(--warn)}

  .feed{list-style:none;margin:0;padding:4px 0}
  .feed li{display:flex;align-items:baseline;gap:10px;padding:11px 16px;border-bottom:1px solid var(--line)}
  .feed li:last-child{border-bottom:none}
  .tag{font-size:11px;font-weight:680;text-transform:uppercase;letter-spacing:.04em;padding:3px 8px;border-radius:6px;white-space:nowrap}
  .tag.restock{background:var(--in-soft);color:var(--in)}
  .tag.instock{background:var(--accent-soft);color:var(--accent)}
  .tag.price_drop{background:var(--warn-soft);color:var(--warn)}
  .ev-name{font-weight:570}
  .ev-meta{color:var(--muted);font-size:13px}
  .ev-when{margin-left:auto;color:var(--faint);font-size:12.5px;white-space:nowrap}
  .ev-open{color:var(--accent);text-decoration:none;font-size:12.5px}
  .empty{padding:22px 16px;color:var(--faint);text-align:center}
  footer{margin-top:24px;color:var(--faint);font-size:12px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand">
      <div class="glyph">👟</div>
      <div><h1>Restock Monitor</h1><p class="sub">Watching limited drops across the Foot Locker family</p></div>
    </div>
    <span class="live"><span class="dot"></span> <span id="clock">live</span></span>
    <button class="btn" id="check" type="button">Check now</button>
    <button class="btn" id="theme" type="button">Theme</button>
  </div>

  <div class="tiles">
    <div class="tile"><div class="k">In stock now</div><div class="v on" id="t-in">–</div></div>
    <div class="tile"><div class="k">Watching</div><div class="v" id="t-watch">–</div></div>
    <div class="tile"><div class="k">Stores</div><div class="v" id="t-stores">–</div></div>
    <div class="tile"><div class="k">Restocks logged</div><div class="v" id="t-events">–</div></div>
  </div>

  <h2>Add a shoe to watch</h2>
  <div class="card">
    <form class="add" id="addform">
      <input id="in-url" placeholder="Foot Locker URL or SKU (e.g. 314206561604)" autocomplete="off">
      <input id="in-sizes" class="small" placeholder="sizes (opt): 9, 10" autocomplete="off">
      <button class="btn primary" type="submit">Add</button>
    </form>
    <div class="msg" id="addmsg"></div>
  </div>

  <h2>Watched products</h2>
  <div class="card">
    <div class="table-scroll">
      <table>
        <thead><tr><th>Product</th><th>Store</th><th>Status</th><th>Sizes</th><th>Price</th><th>Checked</th><th></th></tr></thead>
        <tbody id="rows"><tr><td colspan="7" class="empty">Loading…</td></tr></tbody>
      </table>
    </div>
  </div>

  <h2>Recent restocks</h2>
  <div class="card"><ul class="feed" id="feed"><li class="empty">No events yet.</li></ul></div>

  <footer>Alerts are delivered by the notifiers in your config. This page manages what's watched.</footer>
</div>

<script>
const TAG={restock:"restock",in_stock:"in stock",price_drop:"price drop"};
const esc=s=>(s??"").toString().replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ago=ts=>{if(!ts)return"—";const s=Math.max(0,Math.floor(Date.now()/1000-ts));
  if(s<60)return s+"s ago";if(s<3600)return Math.floor(s/60)+"m ago";if(s<86400)return Math.floor(s/3600)+"h ago";return Math.floor(s/86400)+"d ago";};

function statusPill(p){
  if(p.pending)return `<span class="pill pending"><span class="d"></span>pending</span>`;
  if(p.error)return `<span class="pill err" title="${esc(p.error)}"><span class="d"></span>error</span>`;
  return p.in_stock?`<span class="pill in"><span class="d"></span>in stock</span>`:`<span class="pill out"><span class="d"></span>out</span>`;
}
async function refresh(){
  let d; try{ d=await (await fetch("/api/status",{cache:"no-store"})).json(); }catch(e){ return; }
  const stores=new Set(d.products.map(p=>p.retailer).filter(Boolean));
  t_in.textContent=d.in_stock_count; t_watch.textContent=d.watched_count;
  t_stores.textContent=stores.size; t_events.textContent=(d.events||[]).length;
  rows.innerHTML=d.products.map(p=>{
    const name=p.url?`<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.name)}</a>`:esc(p.name);
    const sizes=(p.available_sizes||[]).length?esc(p.available_sizes.join("  ")):"—";
    return `<tr><td><div class="pname">${name}</div><div class="sku">${esc(p.sku)}</div></td>
      <td class="store">${esc(p.retailer)}</td><td>${statusPill(p)}</td>
      <td class="sizes">${sizes}</td><td class="price">${esc(p.price)||"—"}</td>
      <td class="when">${ago(p.checked_at)}</td>
      <td><button class="x" data-sku="${esc(p.sku)}" title="Stop watching">Remove</button></td></tr>`;
  }).join("")||`<tr><td colspan="7" class="empty">Nothing watched yet — add a shoe above.</td></tr>`;
  feed.innerHTML=(d.events||[]).map(e=>{
    const sizes=(e.sizes||[]).length?` <span class="ev-meta">— sizes ${esc(e.sizes.join(", "))}</span>`:"";
    return `<li><span class="tag ${esc(e.kind)}">${TAG[e.kind]||esc(e.kind)}</span>
      <span class="ev-name">${esc(e.name)}</span>${sizes}
      <span class="ev-when">${ago(e.ts)}</span>
      ${e.url?`<a class="ev-open" href="${esc(e.url)}" target="_blank" rel="noopener">open ↗</a>`:""}</li>`;
  }).join("")||`<li class="empty">No restocks logged yet.</li>`;
}
function flash(el,text,cls){el.textContent=text;el.className="msg "+(cls||"");if(cls==="ok")setTimeout(()=>{if(el.textContent===text){el.textContent="";el.className="msg";}},4000);}

addform.addEventListener("submit",async ev=>{
  ev.preventDefault();
  const input=document.getElementById("in-url").value.trim();
  const sizes=document.getElementById("in-sizes").value.trim();
  if(!input){flash(addmsg,"Enter a Foot Locker URL or SKU.","err");return;}
  flash(addmsg,"Adding…");
  const r=await fetch("/api/watch",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({input,sizes})});
  const j=await r.json();
  if(j.ok){document.getElementById("in-url").value="";document.getElementById("in-sizes").value="";
    flash(addmsg,`Watching ${j.name||j.sku} (${j.retailer}).`,"ok");refresh();}
  else flash(addmsg,j.error||"Couldn't add that.","err");
});
rows.addEventListener("click",async ev=>{
  const b=ev.target.closest("button.x"); if(!b)return;
  b.disabled=true;
  await fetch("/api/unwatch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sku:b.dataset.sku})});
  refresh();
});
document.getElementById("check").addEventListener("click",async e=>{
  const btn=e.currentTarget; const t=btn.textContent; btn.textContent="Checking…"; btn.disabled=true;
  try{const j=await (await fetch("/api/check",{method:"POST"})).json();
    flash(addmsg,j.alerts?`Check done — ${j.alerts} restock alert(s)!`:"Check done — no changes.","ok");}
  finally{btn.textContent=t;btn.disabled=false;refresh();}
});
document.getElementById("theme").addEventListener("click",()=>{
  const root=document.documentElement, dark=matchMedia("(prefers-color-scheme: dark)").matches;
  const cur=root.getAttribute("data-theme")||(dark?"dark":"light");
  root.setAttribute("data-theme",cur==="dark"?"light":"dark");
});
const clock=()=>document.getElementById("clock").textContent="updated "+new Date().toLocaleTimeString();
clock(); setInterval(()=>{clock();refresh();},15000); refresh();
</script>
</body>
</html>
"""
