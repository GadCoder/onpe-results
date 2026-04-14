# ONPE CLI Reference for LLM Agents

This document is designed for autonomous agents that need to operate the CLI reliably.

## Execution model

- Binary entrypoint: `python main.py`
- If no subcommand is provided, CLI defaults to `scrape`.
- Two top-level subcommands:
  - `scrape`
  - `insights`
- Exit code:
  - `0` success
  - `1` failure (`stderr` contains `command_failed error=...`)

## Route keys

Use only these values for `--route` or `--routes`:

- `presidenciales`
- `senadores_distrito_nacional_unico`
- `senadores_distrito_electoral_multiple`
- `diputados`
- `parlamento_andino`

## Command grammar

### Scrape

```bash
python main.py scrape --db <sqlite_path> [--sleep <seconds>] [--routes <route_key> ...]
```

Backward-compatible shorthand:

```bash
python main.py --db <sqlite_path> [--sleep <seconds>] [--routes <route_key> ...]
```

Output (single line):

- `run_id=<int> routes=<int> responses=<int> candidate_results=<int> db=<path>`

### Insights

Base grammar:

```bash
python main.py insights <insight_command> [flags]
```

All insight commands accept:

- `--db <sqlite_path>` (default `data/onpe_results.db`)
- `--limit <int>`
- `--format <table|json>` (default `table`)

Supported `insight_command` values:

- `latest-results`
- `historical-differences`
- `top-regions-by-candidate`
- `top-candidates-general`
- `least-vote-regions`
- `leaderboard-snapshots`
- `volatility-hotspots`
- `concentration-index`
- `momentum-by-region`

Output contract:

- `--format table`: fixed-width table (`|` separators)
- `--format json`: JSON array of objects where keys are column names
- Every insights command includes ONPE API timestamp fields:
  - Single-run commands: `api_timestamp_ms`
  - Two-run comparison commands: `current_api_timestamp_ms`, `previous_api_timestamp_ms`

## Intent to command mapping

- Latest results by candidate: `latest-results`
- Compare latest run vs previous run: `historical-differences`
- Top N regions for one candidate: `top-regions-by-candidate`
- Top N general candidates + actas metrics: `top-candidates-general`
- Regions with least votes: `least-vote-regions`
- Leader and runner-up per region: `leaderboard-snapshots`
- Regions with strongest vote-share change: `volatility-hotspots`
- Market concentration by region: `concentration-index`
- Biggest gainer/loser per region: `momentum-by-region`

## Per-command flags and output schema

### `latest-results`

Flags:

- `--route <route_key>` optional
- `--region <region_name>` optional
- `--kind <candidate|party_list|blank_vote|null_vote|all>` default `candidate`
- `--candidate-document <doc_id>` optional
- `--candidate-name <LIKE_pattern>` optional
- `--limit <int>` default `25`

Columns:

- `run_id`
- `route_key`
- `region_name`
- `result_kind`
- `group_name`
- `candidate_name`
- `candidate_document`
- `total_votes_validos`
- `pct_votes_validos`
- `pct_votes_emitidos`

### `historical-differences`

Flags:

- `--route <route_key>` optional
- `--region <region_name>` optional
- `--kind <candidate|party_list|blank_vote|null_vote|all>` default `candidate`
- `--candidate-document <doc_id>` optional
- `--candidate-name <LIKE_pattern>` optional
- `--limit <int>` default `30`

Columns:

- `route_key`
- `region_name`
- `result_kind`
- `group_name`
- `candidate_name`
- `candidate_document`
- `votes_current`
- `votes_previous`
- `delta_votes`
- `pct_current`
- `pct_previous`
- `delta_pct`
- `current_run`
- `previous_run`

Requires at least 2 successful runs (globally or per `--route` when provided).

### `top-regions-by-candidate`

Flags:

- `--route <route_key>` required
- `--candidate-document <doc_id>` optional
- `--candidate-name <LIKE_pattern>` optional
- `--limit <int>` default `5`

Constraint:

- At least one of `--candidate-document` or `--candidate-name` is required.

Columns:

- `run_id`
- `route_key`
- `region_name`
- `group_name`
- `candidate_name`
- `candidate_document`
- `total_votes_validos`
- `pct_votes_validos`
- `pct_votes_emitidos`

### `top-candidates-general`

Flags:

- `--route <route_key>` required
- `--limit <int>` default `5`

Columns:

- `run_id`
- `route_key`
- `group_name`
- `candidate_name`
- `candidate_document`
- `votes_total`
- `pct_votes_validos_total`
- `actas_contabilizadas_num`
- `total_actas`
- `actas_contabilizadas_pct`

Notes:

- Candidate totals are aggregated from all regions in the selected route.
- Actas metrics are taken from aggregated `regional_summary_totales` rows for the same run/route.

### `least-vote-regions`

Flags:

- `--route <route_key>` optional
- `--limit <int>` default `10`

Columns:

- `run_id`
- `route_key`
- `region_name`
- `total_votos_emitidos`
- `total_votos_validos`
- `participacion_ciudadana`
- `actas_contabilizadas`

### `leaderboard-snapshots`

Flags:

- `--route <route_key>` optional
- `--limit <int>` default `25`

Columns:

- `run_id`
- `route_key`
- `region_name`
- `leader_group`
- `leader_candidate`
- `leader_document`
- `leader_votes`
- `leader_pct`
- `runner_up_group`
- `runner_up_candidate`
- `runner_up_document`
- `runner_up_votes`
- `runner_up_pct`
- `margin_votes`
- `margin_pct`

### `volatility-hotspots`

Flags:

- `--route <route_key>` optional
- `--limit <int>` default `25`

Columns:

- `route_key`
- `region_name`
- `swing_index_pct`
- `swing_votes`
- `max_candidate_shift_pct`
- `max_shift_candidate`
- `max_shift_group`
- `max_shift_delta_pct`
- `current_run`
- `previous_run`

Requires at least 2 successful runs (globally or per `--route` when provided).

### `concentration-index`

Flags:

- `--route <route_key>` optional
- `--limit <int>` default `25`

Columns:

- `run_id`
- `route_key`
- `region_name`
- `candidate_count`
- `leader_candidate`
- `leader_group`
- `top1_pct`
- `top2_pct`
- `top2_share_pct`
- `hhi_index`
- `effective_candidate_count`

### `momentum-by-region`

Flags:

- `--route <route_key>` optional
- `--limit <int>` default `25`

Columns:

- `route_key`
- `region_name`
- `top_gainer_candidate`
- `top_gainer_group`
- `top_gainer_delta_votes`
- `top_gainer_delta_pct`
- `top_loser_candidate`
- `top_loser_group`
- `top_loser_delta_votes`
- `top_loser_delta_pct`
- `current_run`
- `previous_run`

Requires at least 2 successful runs (globally or per `--route` when provided).

## Reliable usage patterns for agents

- First ensure data exists:

```bash
python main.py scrape --db data/onpe_results.db
```

- For two-run metrics, run scrape at least twice before querying:

```bash
python main.py scrape --db data/onpe_results.db --routes presidenciales
```

- Use `--format json` for deterministic machine parsing.
- Use `--format table` for human-readable terminal review.

## Minimal examples

```bash
python main.py insights latest-results --db data/onpe_results.db --route presidenciales --limit 20 --format json
python main.py insights historical-differences --db data/onpe_results.db --route presidenciales --limit 20 --format json
python main.py insights top-candidates-general --db data/onpe_results.db --route presidenciales --limit 5 --format json
python main.py insights leaderboard-snapshots --db data/onpe_results.db --route presidenciales --limit 20 --format json
python main.py insights volatility-hotspots --db data/onpe_results.db --route presidenciales --limit 20 --format json
python main.py insights concentration-index --db data/onpe_results.db --route presidenciales --limit 20 --format json
python main.py insights momentum-by-region --db data/onpe_results.db --route presidenciales --limit 20 --format json
```
