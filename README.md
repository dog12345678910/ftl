# Foot Locker Restock Monitor

A lightweight bot that polls Foot Locker product pages throughout the day and
alerts you the moment a watched sneaker — or a specific size — comes back in
stock. It only notifies on the **out-of-stock → in-stock transition**, so you
get one ping per restock instead of a stream of noise.

- 👟 Watch any number of products by URL or SKU
- 📏 Filter alerts down to the sizes you actually want
- 💸 Optional **price-drop alerts** (per-fall, or when a target price is hit)
- 🔔 Notify via console, desktop, Discord, Telegram, email, Slack, or a generic webhook (mix and match)
- 🕗 Optional active-hours window and randomized polling to look less bot-like
- 💾 Persistent state — survives restarts, alerts only on real changes
- ⏱️ Run continuously (`run_forever`) or once per invocation (great for cron)
- 🐳 Ship it with Docker, systemd, or a scheduled GitHub Action

> **Personal-use monitor.** This checks public product pages for your own
> restock notifications. It does **not** auto-checkout, bypass queues, or defeat
> bot protection. Foot Locker fronts its API with Akamai bot management, so
> heavy polling may get rate-limited (HTTP 403/429) — keep intervals sane and
> see [Getting blocked?](#getting-blocked) below.

## Install

```bash
pip install -r requirements.txt
# optional, for native desktop pop-ups:
pip install plyer
```

Python 3.10+.

## Configure

Copy the example and edit it:

```bash
cp config.example.json config.json
```

```jsonc
{
  "watch": [
    {
      "name": "Air Jordan 1 Retro High OG",
      "url": "https://www.footlocker.com/product/~/314206561604.html",
      "sizes": ["9", "9.5", "10"]   // empty [] = alert on ANY size
    },
    { "name": "Nike Dunk Low", "sku": "316153042104", "sizes": [] }
  ],
  "notifiers": [
    { "type": "console" },
    { "type": "desktop" }
  ],
  "interval_seconds": 90,     // base delay between sweeps
  "jitter_seconds": 30,       // + random 0..30s so it isn't clockwork
  "active_start_hour": 8,     // only monitor 08:00–23:00 (omit both for 24/7)
  "active_end_hour": 23,
  "state_file": "monitor_state.json"
}
```

The **SKU** is the number at the end of a Foot Locker product URL
(`.../314206561604.html`). You can provide either the full `url`, a bare
`sku`, or both.

### Notifiers

| Type       | Required options                     | Notes                                       |
|------------|--------------------------------------|---------------------------------------------|
| `console`  | –                                    | Prints to stdout. Always safe.              |
| `desktop`  | –                                    | Native pop-up via plyer / notify-send / osascript. |
| `discord`  | `webhook_url` (opt: `mention`)       | Server Settings → Integrations → Webhooks.  |
| `telegram` | `bot_token`, `chat_id`               | Create a bot with @BotFather.               |
| `email`    | `host`, `username`, `password`, `to` | SMTP; opt `port` (587), `from_addr`, `use_tls`. Gmail: use an app password. |
| `slack`    | `url`                                | Slack incoming webhook.                     |
| `webhook`  | `url` (opt: `headers`)               | Generic JSON POST — IFTTT, Zapier, n8n, Home Assistant, your own service. |

> `console` and `desktop` only reach you on the machine running the bot. For a
> server/Docker/CI deployment use `discord`, `telegram`, `email`, `slack`, or
> `webhook`.

```jsonc
"notifiers": [
  { "type": "discord", "webhook_url": "https://discord.com/api/webhooks/…", "mention": "@everyone" },
  { "type": "telegram", "bot_token": "123456:ABC-DEF…", "chat_id": "987654321" },
  { "type": "email", "host": "smtp.gmail.com", "username": "you@gmail.com", "password": "app-pw", "to": "you@gmail.com" },
  { "type": "slack", "url": "https://hooks.slack.com/services/…" },
  { "type": "webhook", "url": "https://example.com/hook", "headers": { "Authorization": "Bearer TOKEN" } }
]
```

### Price-drop alerts

Set `"track_price_drops": true` to also be notified when a watched product's
price falls. By default any decrease vs the last-seen price triggers an alert;
add a per-product `"target_price"` to only alert once the price reaches or
drops below your number:

```jsonc
{ "name": "Nike Dunk Low", "sku": "316153042104", "target_price": 90 }
```

## Run

```bash
# Continuous monitoring using config.json
python -m footlocker_monitor -c config.json

# One sweep and exit (pair with cron / Task Scheduler)
python -m footlocker_monitor -c config.json --once

# Quick ad-hoc watch, no config file needed
python -m footlocker_monitor --watch https://www.footlocker.com/product/~/314206561604.html
python -m footlocker_monitor --watch 316153042104 --interval 120
```

Run every 2 minutes via cron instead of a long-lived process:

```cron
*/2 8-23 * * * cd /path/to/ftl && python -m footlocker_monitor -c config.json --once >> monitor.log 2>&1
```

## Deploy it

Three ways to keep it running "throughout the day" without babysitting a
terminal:

**Docker** (long-running container, state in `./data`):

```bash
cp config.example.json config.json    # edit it; use a headless notifier
docker compose up -d
docker compose logs -f
```

**systemd** (Linux service): see [`deploy/footlocker-monitor.service`](deploy/footlocker-monitor.service)
for an install-and-enable recipe.

**GitHub Actions** (no server at all): the included
[`.github/workflows/monitor.yml`](.github/workflows/monitor.yml) runs a sweep
on a cron schedule. Add a repo secret `MONITOR_CONFIG` holding your
`config.json` (with a headless notifier), and state is cached between runs so
you only get alerted on real restocks.

## Getting blocked?

If you see `HTTP 403` / `HTTP 429` or "response was not JSON", Foot Locker is
serving a bot-challenge page. Options, in order of effort:

1. **Slow down** — raise `interval_seconds` and `per_product_delay`.
2. **Add browser cookies** — open footlocker.com in a browser, copy your
   cookies, and add a `"cookies": { ... }` object to the config.
3. **Use a proxy** — add `"proxies": { "https": "http://user:pass@host:port" }`.
   Residential proxies fare best against Akamai.

The JSON parser is intentionally forgiving of Foot Locker's occasional API
shape changes, but if the `pdp_template` endpoint itself moves you can override
it in the config.

## How it works

```
cli → config → Monitor.run_forever()
                 └─ every ~interval:
                     scraper.fetch(product)   # GET PDP JSON, parse sizes
                     state.evaluate(...)       # diff vs last-known stock
                     notifier.notify(event)    # only on OOS → in-stock
```

State lives in `state_file` as a small JSON map of `sku → {sizes, in_stock}`.
Because alerts fire on *transitions*, the first run just records the baseline
(set `"alert_on_first_seen": true` if you want it to ping for things already in
stock on startup).

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest          # 26 tests, no network required
```

Layout:

```
footlocker_monitor/
  cli.py         # argparse entrypoint
  config.py      # JSON config loading/validation
  monitor.py     # the polling loop
  scraper.py     # PDP fetch + defensive JSON parsing
  state.py       # persistence + restock/price-drop change-detection
  product.py     # data models, SKU extraction, size matching, price parsing
  notifiers/     # console / desktop / discord / telegram / email / slack / webhook
```
