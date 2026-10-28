# Rules for working on the Desk

Read `SPEC.md` first. It is the design. This file is the short list of rules that must not be
broken without updating the spec and saying so in the commit. Orchestra's own rules
(`../orchestra_2/AGENTS.md`) bind this plugin too; rules 2, 3, 5, 7, 9 and 10 most of all.

## Invariants

1. **The Desk is no machine.** It never announces itself, never publishes an event (under its own
   name or another's), and never writes the metrics store. Its process (`desk.reader`) reads the
   bus; its instrument (`desk.conditions`) prints measurements that `orchestra run` stores. The test
   `tests/unit/test_not_a_machine.py` must stay green. If the Desk must one day publish, that is a
   change to this rule and to SPEC §10, decided by the owner.
2. **Conditions are measurements.** Their state reaches the store only as the instrument's output
   (`instrument.py`). A condition's statement, evidence and a script's reason are text: they stay
   in the Desk's state and on its pages, never in a metric label or value, never on the bus.
3. **Read only through Orchestra.** Series through `orchestra.metrics` (`series`, `latest`), never
   the store's files; events through `orchestra.events`; configuration through `project.config`,
   followed with `project.config_stamp()`, never by opening `orchestra.toml`. Every reading is
   limited to this project's series (`project` label).
4. **The envelope first.** Ledger rules read the envelope, and only the `data` keys a template
   names, and only for event types published as a protocol for listeners. An entry keeps the
   fields of SPEC §5.1 and nothing else of the event.
5. **The ledger never doubles.** An entry's id is its event's id. Any new way of reading the bus
   must keep that; a restart, a replay or two readers at once write each event once.
6. **Read only for humans.** The pages and the API change nothing (Orchestra's rule 9). A human
   path that acts (a nudge, a remedy) belongs to a machine and the Outbox, not here.
7. **The language stays small.** A comparison, an arithmetic expression over named readings, or a
   script. Never `eval`; a new function or operator comes with a test that it parses and one that
   what it does not allow is refused. Anything bigger is an instrument that serves a series.
8. **State lives in `~/.orchestrator/<key>/desk/`** (0700; the ledger 0600). Nothing here imports
   Orchestra's web app, host or model outside tests.

## Conventions

- Python 3.12+, `uv` for everything. `uv sync --extra dev`, then `set -o pipefail; uv run python
  -m pytest -q` and `uv run ruff check`.
- Orchestra comes from GitHub (`[tool.uv] override-dependencies`, `main`), at the
  commit `uv.lock` pins; README, "Developing against a local Orchestra". Test projects live in
  temporary plain directories with their own `ORCHESTRATOR_HOME`.
- The configuration contract (SPEC §4) is what the Supervisor's tools will edit: change it only
  deliberately, with `config.py`, `check.py`, their tests and the SPEC's example in the same commit.
- Keep modules small and single-purpose. If a file needs a section divider comment, split it.
