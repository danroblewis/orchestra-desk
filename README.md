# orchestra-desk

The Desk for [Orchestra](../orchestra_2): one person's view over the system.

- **The board** (`/desk`): your standing conditions, the statements about the system that should
  hold ("no pull request waits more than a day for review", "no secret expires within 30 days"),
  each checked against Orchestra's metrics. False ones first, the most severe and the longest
  false on top, each with its evidence and a link to where to act.
- **The ledger** (`/ledger`): what happened (tickets landed, PRs merged, reviews given, drafts
  sent, conditions that changed), read from the bus, by day or week, filtered by kind or to your
  own acts, each entry linked to where it happened.

The Desk is no machine: it never publishes an event and never writes a metric. The conditions'
state is a measurement, printed by the instrument `desk.conditions` and stored by `orchestra run`
as `desk_condition_holds{condition}`. It is the base for the morning brief, the status page and
the follow-up pacer, which are not built yet (SPEC §9).

- Design: [SPEC.md](SPEC.md). The condition language is SPEC §3, the configuration contract SPEC §4.
- How it works inside: [ARCHITECTURE.md](ARCHITECTURE.md).
- Rules for changing it: [AGENTS.md](AGENTS.md).

## Install

```bash
cd ~/orchestra-desk
uv sync --extra dev                # Orchestra comes from GitHub, at the commit uv.lock pins
set -o pipefail; uv run python -m pytest -q
uv run ruff check
```

To use it with a project, run `orchestra run` and `orchestra web` from this environment, or install
Orchestra with it as a tool, from GitHub with no clone:

```bash
uv tool install 'orchestra[sd] @ git+https://github.com/danroblewis/orchestra@main' --with 'orchestra-desk @ git+https://github.com/danroblewis/orchestra-desk'
```

Its command line comes with it as `orchestra desk` (`orchestra desk --help`); there is no
executable of its own.
The Desk and Ledger pages are behind Orchestra's login, like every page of `orchestra web`: open
the link it prints, or paste `orchestra web token` into its login page. A program reading
`/api/plugins/desk/*` sends `Authorization: Bearer <that token>`.

## Developing against a local Orchestra

`pyproject.toml` takes Orchestra from GitHub (`orchestra @ git+https://github.com/danroblewis/orchestra@main`),
and `uv.lock` pins the commit it resolved to, so nothing needs cloning beside this repository.
`uv lock --upgrade-package orchestra` moves the pin to the newest `main` (then `uv sync --extra dev`).

To run against an Orchestra checkout instead, with its uncommitted changes, lay it over this
environment for one command:

```bash
uv run --with-editable ~/orchestra_2 python -m pytest -q      # the path to your Orchestra checkout
uv run --with-editable ~/orchestra_2 orchestra web
```

Nothing is written: `.venv`, `pyproject.toml` and `uv.lock` keep GitHub's Orchestra, and a plain
`uv run` uses it again. Inside the command, `sys.executable` and the `orchestra` beside it import
the checkout, so the processes the tests and the host start do too.

For something that runs `.venv/bin/orchestra` directly, install the checkout into `.venv` and keep
uv from syncing it away:

```bash
uv pip install -e ~/orchestra_2
uv run --no-sync python -m pytest -q          # or export UV_NO_SYNC=1
uv sync --extra dev                            # back to the locked Orchestra from GitHub
```

A plain `uv run` or `uv sync` also puts the locked Orchestra back.

## Configure

In the project's configuration (`orchestra.toml`, or the owner's overlay for personal conditions):

```toml
[desk]
owner = ["person.danroblewis"]       # who you are on the bus: the ledger's "mine"

[desk.conditions."reviews-wait"]
statement = "No pull request waits more than a day for a review asked of someone"
severity = "high"
link = "https://github.com/acme/service/pulls"
series = "github_prs_review_request_oldest_seconds"
holds = "<= 86400"
```

A condition is one of three checks:

| Check | Keys | Holds when |
|---|---|---|
| one series | `series`, `labels`, `reduce`, `holds` | the latest fresh value (several series reduced by `max`, `min`, `sum`, `avg` or `count`) satisfies `holds`, e.g. `"<= 86400"` |
| an expression | `expr`, `vars`, `holds` | `expr` (numbers, the names in `vars`, `+ - * / %`, `min`, `max`, `abs`) satisfies `holds` |
| a script | `command`, `timeout` | its first line is `1`; the rest of its output is the reason shown on the board |

A reading older than `max_age` (15 minutes) is missing, and the condition is then `unknown`
unless `when_missing` says otherwise. SPEC §3 has every rule, and §4.4 an example of each.

The ledger has built-in rules for the task system's landings, the GitHub bridge's pull requests
and reviews, and the Outbox's sends (SPEC §5.2). Add or replace one per event type:

```toml
[desk.ledger.types."jira.issue.transitioned"]
kind = "jira"
link = "https://jira.example.com/browse/{subject}"
```

Check a configuration before committing it (the Supervisor's tools call the same):

```bash
uv run orchestra desk check --repo ~/work            # exit 1 and the reasons when it is wrong
uv run orchestra desk check --file proposed.toml --json
```

## What runs

With `[desk]` in the configuration, `orchestra run`:

- keeps `desk.reader` running: it follows the bus and keeps the ledger (`~/.orchestrator/<key>/desk/ledger.db`);
- runs the instrument `desk.conditions` every `[desk] every` (60 s): it checks every condition,
  records the outcomes (`.../desk/conditions.json`) and prints `desk_condition_holds`,
  `desk_condition_false_seconds` and `desk_conditions{state}`, which Orchestra stores.

The board shows the last check. With `orchestra web` alone, the ledger is still read on each
visit, but conditions are not checked.

## Limits

- No brief, nudges, status page or weekly draft yet (SPEC §9); they need a clock (the task
  system's recurring tickets, D7) and the Outbox.
- A condition turning false is not an event, so nothing can wake on it yet (SPEC §10, decision 3).
- "Mine" is by the event's source: a PR merged by someone else is not yours, even if you wrote it.
