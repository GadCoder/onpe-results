# ONPE Regional Scraper

Scrapes regional-level data from these ONPE routes and stores everything in SQLite:

- `https://resultadoelectoral.onpe.gob.pe/main/presidenciales`
- `https://resultadoelectoral.onpe.gob.pe/main/senadores-distrito-nacional-unico`
- `https://resultadoelectoral.onpe.gob.pe/main/senadores-distrito-electoral-multiple`
- `https://resultadoelectoral.onpe.gob.pe/main/diputados`
- `https://resultadoelectoral.onpe.gob.pe/main/parlamento-andino`

## What is scraped

Per run, the scraper stores:

- Process metadata endpoints (`proceso-electoral-activo`, `proceso/2/elecciones`)
- Regional catalog per route:
  - `ubigeos/departamentos` for `presidenciales`, `senadores_distrito_nacional_unico`, `parlamento_andino`
  - `distrito-electoral/distritos` for `senadores_distrito_electoral_multiple`, `diputados`
- Regional-level endpoint payloads per region:
  - Participants endpoint
  - Summary totals endpoint
  - Mesa totals endpoint
  - Mapa calor endpoint (for `ambito_geografico` routes)

## Run

```bash
uv run python main.py --db data/onpe_results.db
```

Optional:

```bash
uv run python main.py --routes presidenciales diputados --sleep 0.05
```

The previous syntax still works because the CLI defaults to `scrape`.

Equivalent explicit command:

```bash
uv run python main.py scrape --db data/onpe_results.db
```

## Insights CLI

Latest results:

```bash
uv run python main.py insights latest-results --db data/onpe_results.db --route presidenciales --limit 20
```

Historical differences (latest run vs previous run):

```bash
uv run python main.py insights historical-differences --db data/onpe_results.db --route presidenciales --limit 30
```

Top 5 regions by candidate:

```bash
uv run python main.py insights top-regions-by-candidate \
  --db data/onpe_results.db \
  --route presidenciales \
  --candidate-document 17903382 \
  --limit 5
```

Top 5 general candidates with actas number and percentage:

```bash
uv run python main.py insights top-candidates-general \
  --db data/onpe_results.db \
  --route presidenciales \
  --limit 5
```

Regions with least vote count:

```bash
uv run python main.py insights least-vote-regions --db data/onpe_results.db --limit 10
```

Leaderboard snapshots (leader vs runner-up by region):

```bash
uv run python main.py insights leaderboard-snapshots --db data/onpe_results.db --route presidenciales --limit 25
```

Volatility hotspots (largest two-run swing by region):

```bash
uv run python main.py insights volatility-hotspots --db data/onpe_results.db --route presidenciales --limit 25
```

Concentration index (top2 share, HHI, effective candidate count):

```bash
uv run python main.py insights concentration-index --db data/onpe_results.db --route presidenciales --limit 25
```

Momentum by region (top gainer and loser between latest 2 runs):

```bash
uv run python main.py insights momentum-by-region --db data/onpe_results.db --route presidenciales --limit 25
```

Machine-readable JSON output (any insights command):

```bash
uv run python main.py insights latest-results \
  --db data/onpe_results.db \
  --route presidenciales \
  --limit 20 \
  --format json
```

All insights outputs now include ONPE timestamp metadata:
- `api_timestamp_ms` for single-run commands
- `current_api_timestamp_ms` and `previous_api_timestamp_ms` for two-run diff commands

## LLM-focused CLI docs

For autonomous/agentic usage, use this reference:

- `docs/CLI_FOR_LLM.md`

It includes:

- Strict command grammar
- Full flag catalog per command
- Output column schema per insight
- Error/constraint notes (for example, commands that require at least 2 runs)
- Intent-to-command mapping

## Project structure

- `onpe_results/cli.py`: CLI parsing and orchestration entrypoint
- `onpe_results/scraper.py`: route/regional scraping workflow
- `onpe_results/client.py`: HTTP client with browser-like headers
- `onpe_results/database.py`: SQLite schema and persistence
- `onpe_results/normalizer.py`: normalized table population logic
- `onpe_results/insights.py`: query service and table output for insights CLI
- `onpe_results/routes.py`: route catalog and constants
- `onpe_results/models.py`: dataclasses and API result model
- `onpe_results/utils.py`: conversion/time/json helpers
- `onpe_scraper.py`: backward-compatible wrapper

## Route keys

- `presidenciales`
- `senadores_distrito_nacional_unico`
- `senadores_distrito_electoral_multiple`
- `diputados`
- `parlamento_andino`

## Database tables

Raw ingestion:
- `scrape_runs`
- `routes`
- `regions`
- `endpoint_responses`

Normalized (LLM/query-friendly):
- `political_groups`
- `candidates`
- `candidate_results`
- `regional_summaries`
- `mesa_status`
- `v_candidate_results_llm` (view with joined candidate/group labels)

`endpoint_responses.response_json` still stores full raw JSON payloads for traceability.

## Query examples

Top candidates/party options by route and region:

```sql
SELECT
  route_key,
  region_name,
  group_name,
  candidate_name,
  total_votes_validos,
  pct_votes_validos
FROM v_candidate_results_llm
WHERE run_id = (SELECT MAX(id) FROM scrape_runs WHERE status = 'success')
  AND result_kind IN ('candidate', 'party_list')
ORDER BY route_key, region_name, total_votes_validos DESC;
```

Regional summary progress (actas/participación):

```sql
SELECT
  route_key,
  region_name,
  actas_contabilizadas,
  participacion_ciudadana,
  total_votos_emitidos
FROM regional_summaries
WHERE run_id = (SELECT MAX(id) FROM scrape_runs WHERE status = 'success')
  AND endpoint_key = 'regional_summary_totales'
ORDER BY route_key, region_name;
```
