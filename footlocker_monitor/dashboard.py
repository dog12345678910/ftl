"""A tiny live web dashboard for the restock monitor.

Serves a self-contained status page plus a JSON API at ``/api/status``, reading
the monitor's state and history files. It can also run the monitor loop itself
in a background thread, so a single ``--dashboard`` process both watches for
restocks and shows you what's happening.

Built on the standard-library HTTP server — no extra dependencies.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import history
from .config import Config
from .state import StateStore

log = logging.getLogger(__name__)


def build_status(config: Config) -> dict:
    """Assemble the payload the dashboard renders."""
    store = StateStore(config.state_file)
    products = store.snapshot()
    events = history.read_recent(config.history_file, limit=50)
    return {
        "products": products,
        "events": events,
        "in_stock_count": sum(1 for p in products if p.get("in_stock")),
        "watched_count": len(config.watch),
        "interval_seconds": config.interval_seconds,
    }


class _Handler(BaseHTTPRequestHandler):
    config: Config  # set on the server subclass

    def log_message(self, *args) -> None:  # silence default request logging
        return

    def do_GET(self) -> None:
        if self.path.startswith("/api/status"):
            self._send_json(build_status(self.config))
        elif self.path in ("/", "/index.html"):
            self._send_html(_PAGE)
        else:
            self.send_error(404, "Not found")

    def _send_json(self, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(config: Config, port: int = 8000, run_monitor: bool = True) -> None:
    """Start the dashboard (and, by default, the monitor loop)."""
    if run_monitor:
        # Imported here to avoid a circular import at module load.
        from .monitor import Monitor

        monitor = Monitor(config)
        thread = threading.Thread(target=monitor.run_forever, daemon=True)
        thread.start()
        log.info("Monitor loop running in the background.")

    handler = type("BoundHandler", (_Handler,), {"config": config})
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    log.info("Dashboard: http://localhost:%d  (Ctrl+C to stop)", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        server.shutdown()


# --- the page (self-contained: inline CSS + JS, polls /api/status) ---------

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Foot Locker Restock Monitor</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0f1115; color: #e7e9ee; }
  @media (prefers-color-scheme: light) { body { background: #f6f7f9; color: #1b1d22; } }
  header { padding: 20px 24px; border-bottom: 1px solid #2a2e37; display: flex;
           align-items: center; gap: 16px; flex-wrap: wrap; }
  @media (prefers-color-scheme: light) { header { border-color: #e2e4e9; } }
  h1 { font-size: 18px; margin: 0; font-weight: 650; }
  .stats { display: flex; gap: 20px; margin-left: auto; font-size: 13px; opacity: .85; }
  .stats b { font-size: 16px; }
  main { padding: 20px 24px; max-width: 1100px; margin: 0 auto; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; opacity: .6; margin: 28px 0 10px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #23262e; vertical-align: top; }
  @media (prefers-color-scheme: light) { th, td { border-color: #e6e8ec; } }
  th { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; opacity: .55; }
  a { color: #6ea8fe; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .pill { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .in { background: rgba(46,204,113,.18); color: #48d18a; }
  .out { background: rgba(120,130,145,.18); color: #9aa4b2; }
  .err { background: rgba(231,76,60,.18); color: #f0776a; }
  .sizes { font-variant-numeric: tabular-nums; }
  .muted { opacity: .55; }
  .feed li { list-style: none; padding: 8px 0; border-bottom: 1px solid #23262e; }
  @media (prefers-color-scheme: light) { .feed li { border-color: #e6e8ec; } }
  .feed ul { padding: 0; margin: 0; }
  .kind { font-weight: 650; margin-right: 6px; }
  .empty { opacity: .5; padding: 16px 0; }
  footer { padding: 16px 24px; opacity: .4; font-size: 12px; }
</style>
</head>
<body>
<header>
  <h1>👟 Restock Monitor</h1>
  <div class="stats">
    <span><b id="s-instock">–</b> in stock</span>
    <span><b id="s-watched">–</b> watched</span>
    <span class="muted" id="s-updated">updating…</span>
  </div>
</header>
<main>
  <h2>Products</h2>
  <table>
    <thead><tr><th>Product</th><th>Store</th><th>Status</th><th>Sizes</th><th>Price</th><th>Checked</th></tr></thead>
    <tbody id="products"><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
  </table>

  <h2>Recent restocks</h2>
  <div class="feed"><ul id="feed"><li class="empty">No events yet.</li></ul></div>
</main>
<footer>Auto-refreshes every 15s.</footer>

<script>
const KIND_LABEL = { restock: "🔔 Restock", in_stock: "👟 In stock", price_drop: "💸 Price drop" };
function ago(ts) {
  if (!ts) return "—";
  const s = Math.max(0, Math.floor(Date.now()/1000 - ts));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s/60) + "m ago";
  if (s < 86400) return Math.floor(s/3600) + "h ago";
  return Math.floor(s/86400) + "d ago";
}
function esc(s){ return (s??"").toString().replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
async function refresh() {
  try {
    const r = await fetch("/api/status"); const d = await r.json();
    document.getElementById("s-instock").textContent = d.in_stock_count;
    document.getElementById("s-watched").textContent = d.watched_count;
    document.getElementById("s-updated").textContent = "updated " + new Date().toLocaleTimeString();

    const rows = d.products.map(p => {
      let status = p.error
        ? `<span class="pill err" title="${esc(p.error)}">error</span>`
        : p.in_stock ? `<span class="pill in">in stock</span>` : `<span class="pill out">out</span>`;
      const name = p.url ? `<a href="${esc(p.url)}" target="_blank">${esc(p.name)}</a>` : esc(p.name);
      const sizes = (p.available_sizes||[]).length ? esc(p.available_sizes.join(", ")) : "—";
      return `<tr><td>${name}</td><td class="muted">${esc(p.retailer)}</td><td>${status}</td>
        <td class="sizes">${sizes}</td><td>${esc(p.price)||"—"}</td><td class="muted">${ago(p.checked_at)}</td></tr>`;
    });
    document.getElementById("products").innerHTML = rows.join("") ||
      `<tr><td colspan="6" class="empty">No checks recorded yet.</td></tr>`;

    const feed = d.events.map(e => {
      const label = KIND_LABEL[e.kind] || e.kind;
      const sizes = (e.sizes||[]).length ? " — sizes " + esc(e.sizes.join(", ")) : "";
      const link = e.url ? ` <a href="${esc(e.url)}" target="_blank">open</a>` : "";
      return `<li><span class="kind">${label}</span>${esc(e.name)}${sizes}
        <span class="muted">· ${ago(e.ts)}</span>${link}</li>`;
    });
    document.getElementById("feed").innerHTML = feed.join("") ||
      `<li class="empty">No events yet.</li>`;
  } catch (e) {
    document.getElementById("s-updated").textContent = "connection lost";
  }
}
refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>
"""
