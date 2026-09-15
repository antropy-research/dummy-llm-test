# dummy-llm-test

[中文](README.md) · English

Run reproducible community LLM checks through OpenAI-compatible APIs, Codex CLI,
or Claude Code. Preserve every attempt, review open-ended answers yourself, and
compare compatible runs. There is no model judge or single “IQ score.”

Quick checks are an anomaly screen, not proof of reduced capability. ModelTrace
reports matches within its candidate bank, not authenticated model identities.

## Start here

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/),
and macOS or Linux. Native Windows process handling is not supported.

```bash
git clone https://github.com/antropy-research/dummy-llm-test.git
cd dummy-llm-test
uv sync --frozen
uv run dummy-llm-test list --level quick
uv run dummy-llm-test run --level full --dry-run
```

These commands do not call models. To preview the report without credentials,
open [the synthetic share demo](examples/shared-report/index.html) locally after cloning.
GitHub displays its source; download the folder to view the HTML.

For a real evaluation, install and sign in to Codex CLI, then run:

```bash
uv run dummy-llm-test doctor --target codex
uv run dummy-llm-test run --level quick --target codex --concurrency 2
```

`run` consumes your configured provider or CLI quota. `doctor` only performs local
and configuration checks; it does not prove that a model request will succeed.
Reports and original evidence are stored under `runs/`, excluded from Git.

| Level | Calls per target by default | Content |
|---|---:|---|
| `quick` | 5 | Candy, pelican SVG, self-reported cutoff, decimal comparison, character count |
| `full` | 189 | All enabled cases, including three ModelTrace challenges |
| `fingerprint` | 3 | One ModelTrace challenge group |

Full includes 131 open-ended questions requiring human review. Completing requests
does not complete their evaluation. Original community prompts and local variants
remain distinct; Candy's ambiguous original compatibility result is separate from
strict final-answer scoring. See [methods](docs/methodology.md) and [research](docs/research.md).

## Configure your target

Copy `config.yaml` to ignored `config.local.yaml`, or use the explicit
[API](examples/config-api.yaml) / [CLI](examples/config-cli.yaml) examples. Set your
API key in the environment named by `api_key_env`; never place it in YAML.
Choose `chat_completions` or `responses` explicitly. Models, protocols, reasoning
parameters, and streaming are never silently substituted.

```bash
uv run dummy-llm-test --config config.local.yaml run --level quick --target api
uv run dummy-llm-test run --level full --target codex --mode native
uv run dummy-llm-test run --resume runs/YOUR_RUN --concurrency 4
uv run dummy-llm-test compare --baseline runs/OLD --current runs/NEW
uv run dummy-llm-test share export runs/YOUR_RUN --output shared-report
```

Controlled CLI runs use new sessions and isolated directories. Native mode retains
local tools and configuration and is compared separately. Tool-generated integers
cannot provide valid ModelTrace attribution in either mode.

Concurrency is a global cap, optionally constrained per target. Each completed
sample is saved before refilling its slot. Ctrl+C stops dispatch and retries, then
waits for in-flight calls to finish or time out; it cannot cancel provider billing.
Resume fills missing samples, never reruns incorrect answers to pick a better one.

Since 0.4, presentation changes do not invalidate new experiment signatures.
Changing concurrency is allowed on resume, with conditions retained per sample
and launch. Performance comparisons flag changed concurrency, retry policy,
timeout, streaming, and output limits. Legacy runs retain conservative checks.
See [compatibility rules](docs/compatibility.md).

Reports separate objective scores, manual reviews, self-reported cutoff, candidate
matches, and execution failures. Performance includes attempt/sample durations,
TPS, P5/P50/P95, coverage, retries, plots, and observed aggregate throughput.
Missing measurements stay missing. API streaming observes visible text arrival,
not pure token-generation speed; CLI incremental timing is currently unsupported.
See [performance](docs/performance.md) and [tested transports](docs/compatibility-matrix.md).

The share command exports anonymous, allowlisted numeric statistics. It excludes
prompts, answers, SVG, model identities, addresses, local paths, raw events, and
reviewer details. Inspect it before sharing: scores, output lengths, and performance
remain public. The export is not resumable or regradable raw evidence.

## Development and distribution

```bash
uv sync --frozen
uv run python scripts/check_repo.py
uv build
uv run python scripts/check_dist.py --dist dist --version 0.4.0
```

Tests use local fixtures and do not need API keys. Start with
[CONTRIBUTING](CONTRIBUTING.md), [AGENTS.md](AGENTS.md), and the
[agent development guide](docs/agent-development.md). Changes are recorded in
[CHANGELOG](CHANGELOG.md); security reporting is in [SECURITY](SECURITY.md).
[Release preparation](docs/releasing.md) builds and checks artifacts without
automatically publishing to PyPI or creating a GitHub Release.

Harness source is MIT licensed. Third-party content retains its own terms, including
BSD-3-Clause data and source-attributed short prompts without an upstream license
declaration. See [third-party notices](THIRD_PARTY_NOTICES.md); this is not a claim
that all bundled material is covered by MIT or cleared for every redistribution.
