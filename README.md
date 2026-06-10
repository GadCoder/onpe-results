# onpe-results

Scraper for **ONPE**'s live presidential-results site
(`resultadosegundavuelta.onpe.gob.pe`, Peru 2026 second round).

The site is an Angular single-page app backed by a JSON API. This project does
**not** scrape rendered HTML — it replicates the API the SPA itself calls. It
ships two things:

1. **A discovery tool** (`discover`) that drives the real site in a browser
   (Playwright) and records every API request the app makes, so the contract can
   be re-verified whenever the site changes.
2. **A pure-HTTP scraper** (`scrape`) that replays those requests without a
   browser and crawls the full public dataset to JSON + CSV.

## Why a browser *and* an HTTP client?

The edge (CloudFront + WAF) **fingerprints TLS**. A plain `requests`/`curl`
client gets the Angular shell (`text/html`) instead of JSON, and any unknown
route falls through to `index.html` with a misleading `200`. Two consequences:

- The HTTP client uses **`curl_cffi` impersonating Chrome** (`chrome124`) so its
  TLS handshake matches a real browser. This is mandatory, not cosmetic.
- Discovery must run in a **real, non-headless Chrome**. Playwright's *bundled*
  Chromium is also rejected by the WAF (its `main.js` returns the SPA shell, so
  Angular never boots and fires zero XHR). The recorder therefore launches the
  system Chrome channel by default.

The HTTP client surfaces the "shell instead of JSON" case as an explicit
`BlockedError` so you never silently scrape an empty page.

## Install

```bash
uv sync
uv run playwright install chrome   # only needed for `discover`
```

## Usage

```bash
# Crawl everything: national + Peru/abroad + every department/province/district.
uv run onpe-scraper scrape --geo-level district --output data

# Faster, coarser runs:
uv run onpe-scraper scrape --geo-level department
uv run onpe-scraper scrape --geo-level national

# Re-record the API contract from the live site (opens a real Chrome window):
uv run onpe-scraper discover --manifest data/manifest.json

# Look up one polling-station tally sheet (acta) by its 6-digit code:
uv run onpe-scraper mesa 000001

# Build a notification snapshot of the national race + delta vs the previous run:
uv run onpe-scraper report
```

### `report` — notification snapshots with history

Captures the national totals + candidate results **and** the actas-processed
count per department, province and foreign country (via a province-level sweep),
appends them to a JSONL history file, and writes a `report.json` with everything
needed to send an update message — plus a ready-to-send `mensaje` string. Each
run compares against the most recent *earlier* snapshot to produce deltas:

- national: vote deltas, percentage-point deltas, and lead change;
- geographic: change in actas processed per **department / province / country**,
  listing **only units that changed**, each group ordered by the size of the
  variation. (The `EXTRANJERO` aggregate and per-country detail are included;
  abroad *continents* are not.)

Run it on a schedule; the comparison fills in once there are ≥2 distinct
snapshots. Flags: `--no-geo` (national race only, one request, fast),
`--top-geo N` (rows per geo group shown in the message; JSON keeps all).

**Outputs** (in the `report.json` directory): the structured `report.json`
(includes `mensaje`, the combined message, and `mensajes`, the split ones) plus
three standalone, ready-to-send message files:

| File | Contents |
|------|----------|
| `mensaje_general.txt` | National race: turnout, candidates, leader, and the national comparison. |
| `mensaje_departamentos.txt` | Actas processed per **department + province** that changed, ordered by variation. |
| `mensaje_paises.txt` | Actas processed per **foreign country** that changed, ordered by variation. |

Each geo line shows the current **% processed**, the count, and the change:
`• LORETO: 94.401% procesado (2.546/2.697) · +30 actas, +1.112 pp`.

```
$ uv run onpe-scraper report --output data/report.json --history data/history.jsonl
📬 Nuevos resultados ONPE
🕒 Actualización: 19:22:00 09/06/2026
📊 Actas contabilizadas: 96.412%
🟥 Keiko Fujimori — 8.908.141 (49.884%)
🟦 Roberto Sánchez — 8.949.555 (50.116%)
🏆 Va ganando: Roberto Sánchez · 📈 41.414 votos (0.232 pp)
🔁 vs anterior: Actas +0.020 pp · Keiko +737 / +0.001 pp · Roberto +384 / -0.001 pp · Ventaja -353 (-0.002 pp)
```

Candidate short names + colour emojis are configured in `config.CANDIDATE_DISPLAY`
(keyed by `codigoAgrupacionPolitica`); unknown codes fall back to a title-cased
name. Timestamps are rendered in `America/Lima`.

Useful flags: `--rps` (request rate, default 6/s), `--no-abroad`,
`--id-eleccion` (override the auto-detected election), `-v` (debug logging).

### Running behind a proxy (`--proxy`)

The edge filters datacenter IPs, so from a VPS the direct request returns the
SPA shell (`BlockedError`). Route through a residential SOCKS exit (e.g. a
Tailscale + phone proxy). Every command accepts `--proxy`:

```bash
uv run onpe-scraper report --proxy                       # bare → hardcoded default
uv run onpe-scraper report --proxy socks5h://host:1080   # explicit override
```

Bare `--proxy` uses the hardcoded default in `config.DEFAULT_PROXY`
(`socks5h://100.66.12.22:1080`). `socks5h` resolves DNS through the proxy too
(matches `curl --socks5-hostname`); `curl_cffi`/libcurl speaks SOCKS natively,
so no extra dependency. The proxy goes through the phone, so expect higher
latency — consider a gentler `--rps` for the geo sweep.

## Output

Written under `--output` (default `data/`):

| File | Contents |
|------|----------|
| `totales.csv` | One row per geographic scope: actas processed, turnout, vote totals. |
| `participantes.csv` | One row per candidate per scope (national + Peru/abroad). |
| `scopes.json` | Full structured results (totals + participants per scope). |
| `raw/process.json`, `raw/elecciones.json`, `raw/ubigeos.json` | The process, election tree, and full UBIGEO list. |

## Reverse-engineered API

Base: `https://resultadosegundavuelta.onpe.gob.pe/presentacion-backend`

| Method | Path | Params | Returns |
|--------|------|--------|---------|
| GET | `proceso/proceso-electoral-activo` | — | active process (`id`, `idEleccionPrincipal`) |
| GET | `proceso/{idProceso}/elecciones` | — | election / menu tree |
| GET | `ubigeos/dep-prov-distritos` | `idEleccion` | flat list of all district UBIGEOs + `DEP \ PROV \ DIST` paths |
| GET | `ubigeos/departamentos` | `idEleccion`, `idAmbitoGeografico` | departments |
| GET | `ubigeos/provincias` | `idEleccion`, `idAmbitoGeografico`, `idUbigeoDepartamento` | provinces |
| GET | `ubigeos/distritos` | `idEleccion`, `idAmbitoGeografico`, `idUbigeoProvincia` | districts |
| GET | `resumen-general/totales` | `idEleccion`, `tipoFiltro`, `idAmbitoGeografico`, `idUbigeoDepartamento/Provincia/Distrito` | processing/turnout/vote totals for a scope |
| GET | `resumen-general/participantes` | `idEleccion`, `tipoFiltro` (`eleccion` \| `ambito_geografico`), `idAmbitoGeografico` | candidate results |
| POST | `actas/buscar/mesa` | body `{codigoMesa}` | one polling-station acta |
| POST | `actas/locales` | body `{idEleccion, idUbigeo}` | voting venues within a UBIGEO |

Key constants (from the SPA): `idAmbitoGeografico` 1 = Peru, 2 = abroad;
`tipoFiltro` ∈ `eleccion`, `ambito_geografico`, `ubigeo_nivel_01/02/03`.

**Gotchas discovered while reversing the contract:**

- Geographic filtering on `totales` uses **numeric** `idUbigeoDepartamento` /
  `idUbigeoProvincia` / `idUbigeoDistrito` (the 6-digit UBIGEO read as an int,
  e.g. `010200` → `10200`). The `ubigeoNivelN` *string* params that appear in
  the bundle are silently ignored — pass them and every province returns the
  first one's data.
- `dep-prov-distritos` returns **only district leaves**; departments and
  provinces are reconstructed from the codes + path segments (see
  `scraper._expand_levels`).
- **Abroad** geography uses the same 6-digit scheme — continent (`910000`–
  `950000`) / country (`..00`) / city — but must be queried under
  `idAmbitoGeografico=2`; querying an abroad UBIGEO under the Peru ambito returns
  204. The sweep picks the ambito per unit, so a `province` crawl covers Peru
  departments + provinces **and** abroad continents + countries in one pass.
- `resumen-general/participantes` serves only the national and ambito scopes for
  this process; geographic levels return HTTP 500 upstream.

## Architecture

```
src/onpe_scraper/
  config.py     Settings: base URL, impersonation profile, rate limit, retries
  http.py       OnpeClient — curl_cffi Chrome-impersonated session,
                rate limiter, retry/backoff, envelope unwrap, BlockedError
  models.py     Typed dataclasses (Proceso, Eleccion, Ubigeo, Totales, ...)
  api.py        OnpeApi — one typed method per endpoint
  scraper.py    OnpeScraper — full crawl, per-scope error isolation, geo sweep
  storage.py    JSON + CSV writers
  discovery.py  DiscoveryRecorder — Playwright network recorder -> manifest
  report.py     Snapshot/History — national snapshots, deltas, message rendering
  cli.py        scrape / discover / mesa / report commands
```

Design notes:

- **One source of truth for the contract.** Every field-name quirk lives in
  `models.from_api` / `api.py`; the rest of the code speaks typed objects.
- **Resilient by scope.** A failed request for one district is logged into
  `ScrapeResult.errors` and skipped — election-night flakiness never discards
  work already collected.
- **Polite.** A client-side token bucket caps request rate; default 6 req/s.

> Scrapes a public, official results site for analysis. Respect the rate limit
> and ONPE's terms of use.
