# The Desk: specification

Status: phase 1, 2026-10-27. Building block 3 of `../orchestra_2/docs/roadmap/story-placement.md`.

The Desk is one person's view over an Orchestra system. Phase 1 is its base:

- the **board**: standing conditions (statements about the system that should hold), each checked
  against the metrics store, ranked so that what is false and matters most is on top;
- the **ledger**: a record of what happened (tickets landed, PRs merged, reviews given, drafts
  sent, conditions that changed), read from the bus.

The morning brief, the status page, the follow-up pacer and the weekly update are built on these
two later (§9).

Contents: 1 Principles · 2 Conditions · 3 The condition language · 4 Configuration: the contract ·
5 The ledger · 6 Measurements · 7 Pages and API · 8 State · 9 What builds on this · 10 Not in
phase 1, and open questions.

## 1. Principles

1. **The Desk is no machine.** It never announces itself, never publishes an event (under its own
   name or any other) and never writes the metrics store. Its process, `desk.reader`, is a plugin's
   infrastructure: it reads the bus. Its instrument, `desk.conditions`, measures: it prints
   Prometheus text and `orchestra run` stores it (Orchestra's rules 2 and 7; PLUGINS.md §4.7, §6).
2. **Conditions are instruments** (story placement §2.4). A condition is a measurement, 0 or 1,
   so its state is served by an instrument the plugin declares (`Plugin.collectors`), and is a
   series like any other: discovery may read it as a flag.
3. **The Desk reads; it does not act.** No remedy, nudge or message is sent from here. Those are
   machines' acts, and anything said as the owner goes through the Outbox.
4. **Read only through Orchestra.** Series through `orchestra.metrics` (never the store's files),
   events through `orchestra.events`, configuration through `project.config` with
   `project.config_stamp()` (never `orchestra.toml`; Orchestra's rule 10).
5. **No text on the bus or in metrics.** Statements, evidence and a script's reason stay in the
   Desk's state and on its pages. A metric's only label is the condition's name.
6. **The envelope first.** The ledger's rules read an event's envelope; they read `data` keys only
   for the event types other packages publish as a protocol for listeners (PLUGINS.md §7), and
   only the keys a template names.

## 2. Conditions

A condition has a **name** (its id: `reviews-wait`), a **statement** (what should hold, in the
owner's words), a **severity** (`critical`, `high`, `medium`, `low`), a **link** (where to act on
it) and one **check**. Each round of the instrument (every `[desk] every`, default 60 s) checks
every condition and gets one of three outcomes:

| Outcome | Meaning |
|---|---|
| `holds` | the check passed |
| `false` | the check failed |
| `unknown` | the check could not be made: a reading missing or too old, a division by zero, a script that failed, timed out or answered nonsense. The evidence says which. |

The record keeps, per condition, the outcome, its **evidence** (what was read, as one line), a
script's **reason**, **since** when it has been in its state and **false since** when it has been
false. An unknown outcome does not reset "false since": an outage of the readings is not a
recovery. A condition that turns false, or holds again after being false, is a **change**, and is
written to the ledger (§5.5).

The **board** ranks: false first (most severe first; among equals, longest false first), then
unknown (most severe first: a check that cannot be made is something to fix), then those that
hold. A condition not checked yet is unknown, with that as its evidence.

## 3. The condition language

Three checks, one per condition. The language is deliberately small: a comparison, an arithmetic
expression, or a script. Anything more belongs in an instrument that serves a series.

### 3.1 One series against a bound

```toml
[desk.conditions."reviews-wait"]
statement = "No PR of mine waits more than a day for review"
series = "github_prs_awaiting_review_oldest_seconds"
labels = { author = "danroblewis" }   # optional: label = value, all must match
reduce = "max"                       # optional: how several matching series become one number
holds = "<= 86400"                   # an operator and a number
```

A **reading** is every series of this project (`project` = the project's key, always added) with
that name and those labels; the latest point of each; the points older than `max_age` (default
`[desk] max_age`, 15 minutes) left out; and what is left reduced by `reduce`:

| `reduce` | Value | With no fresh point |
|---|---|---|
| `max` (default) | the largest | missing |
| `min` | the smallest | missing |
| `sum` | the sum | missing |
| `avg` | the mean | missing |
| `count` | how many series have a fresh point | 0 (never missing) |

`holds` is one of `<`, `<=`, `>`, `>=`, `==`, `!=` and a number (`"< 0.2"`, `">= 1e3"`). The
condition holds when `value <op> number`.

A missing reading makes the condition `unknown`, unless `when_missing` says `"holds"` or
`"false"` (for a series an instrument writes only while something is wrong, for example).

### 3.2 An expression over several readings

```toml
[desk.conditions."few-stuck"]
statement = "Under a fifth of the tickets in progress are stuck"
expr = "stuck / max(working, 1)"
holds = "< 0.2"
vars = { stuck = "tasks_tickets_stuck", working = { series = "tasks_tickets", labels = { state = "working" } } }
```

`vars` names each reading: a series name, or a table with `series`, `labels`, `reduce`,
`max_age` (as in §3.1). `expr` is numbers, those names, `+ - * / %`, parentheses, unary minus, and
`min(...)`, `max(...)`, `abs(x)`. Nothing else parses: no attributes, indexing, other calls,
comparisons, booleans or strings. It is parsed once with Python's `ast` and evaluated by walking
the tree (`language.py`), never with `eval`. Every name in `expr` must be in `vars`, and every var
must be used. A division by zero, or a result that is not finite, makes the condition `unknown`.
`when_missing` applies when any reading is missing.

### 3.3 A script

```toml
[desk.conditions."secrets"]
statement = "No secret expires within 30 days"
command = ["scripts/desk/secrets.sh"]   # or a string, split like a shell would (not run by one)
timeout = "20s"                         # default 20 s, at most [desk] every minus 5 s
```

The instrument runs the command in the repository root (a first word with a `/` is relative to the
root; a bare name is found on `PATH`), with `ORCHESTRA_REPO` and `DESK_CONDITION` (the condition's
name) in its environment. Scripts run side by side. Its standard output:

```
0
the deploy key expires in 12 days
rotate it in Vault before Nov 8
```

- **First line**: `1` (holds) or `0` (false); `true`/`false` and `ok`/`fail` are read the same.
- **The rest**: the reason, up to 500 characters, shown on the board under the statement.
- **Exit 0** is required. Another exit status (the last line of its standard error is kept as the
  error), a timeout (the script's process group is killed), or a first line that is none of the
  above makes the condition `unknown`.

The reason is text: it stays in the Desk's record and on its board, never in a metric or on the
bus. A script may read Orchestra's store or bus as any program may. If a check is a measurement
that other things should see (the model, other machines), make it an instrument of its own
(`[[collect]]`) and point a series condition at it instead (§10, decision 2).

## 4. Configuration: the contract

The Desk reads `[desk]` from `project.config.raw` (the repository's `orchestra.toml` with the
owner's private overlay merged over it), and follows edits by `project.config_stamp()`. The
Supervisor changes it through `project.config_edit` (personal conditions and identities belong in
the overlay), after `orchestra desk check` accepts it. Every key is checked; an unknown key is
refused, so a typo is caught. Durations are `"60s"`, `"15m"`, `"2h"` (Orchestra's `parse_duration`: ms, s, m, h), or a number of seconds.

### 4.1 `[desk]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `owner` | source or list of sources | `[]` | who the owner is on the bus (`person.danroblewis`): the ledger's "mine" |
| `every` | duration, 10 s – 1 h | `60s` | how often the instrument `desk.conditions` checks every condition |
| `max_age` | duration, 1 s – 30 d | `15m` | a reading's points older than this are left out (each reading may override) |
| `conditions` | table | none | the conditions, `[desk.conditions."<name>"]` |
| `ledger` | table | built-in rules | the ledger's rules, `[desk.ledger]` |

The section's presence is what turns the Desk on in a project: with `[desk]`, `orchestra run`
keeps `desk.reader` running and runs `desk.conditions`. Without it, the pages say so.

### 4.2 `[desk.conditions."<name>"]`

The name is lowercase letters, digits, `.`, `_` and `-`, at most 64 characters.

| Key | For | Required | Meaning |
|---|---|---|---|
| `statement` | all | yes | what should hold, at most 200 characters |
| `severity` | all | no (`medium`) | `critical`, `high`, `medium`, `low` |
| `link` | all | no | where to act: `https://...`, `http://...`, or a path on this Orchestra (`/tickets`) |
| `series` | series | one of `series`, `expr`, `command` | the series' name |
| `labels` | series, each var | no | `{ name = "value", ... }`; `project` is refused (always this project) |
| `reduce` | series, each var | no (`max`) | `max`, `min`, `sum`, `avg`, `count` |
| `max_age` | series, each var | no (`[desk] max_age`) | points older than this are left out |
| `expr` | expr | | the expression (§3.2) |
| `vars` | expr | with `expr` | name → series name, or `{ series, labels, reduce, max_age }` |
| `holds` | series, expr | yes for these | an operator and a number |
| `when_missing` | series, expr | no (`unknown`) | `unknown`, `holds`, `false` |
| `command` | script | | a list of arguments, or a string split like a shell would |
| `timeout` | script | no (20 s) | 1 s to `every` − 5 s |

`labels`, `reduce` and `max_age` beside `expr` are refused (they belong in each var), as are
`holds`, `labels`, `reduce`, `max_age`, `when_missing` and `vars` on a script condition.

### 4.3 `[desk.ledger]`

| Key | Default | Meaning |
|---|---|---|
| `defaults` | `true` | use the built-in rules (§5.2); `false`: only the types below |
| `types."<event type>"` | | a rule: replaces the built-in rule for that type, or adds one |

A rule, `[desk.ledger.types."<event type>"]`:

| Key | Default | Meaning |
|---|---|---|
| `kind` | required | the entry's kind: a short lowercase word (`landed`, `merged`); `condition` is the Desk's own |
| `label` | `"{subject}"` | a template: what the entry says |
| `link` | none | a template that makes an http(s) URL or a path on this Orchestra |
| `sources` | `[]` (any) | only events from these sources (a machine, or one instance `worker/1`) |
| `ignore` | `false` | `true` (alone): drop the built-in rule for this type |

Templates take `{type}`, `{source}`, `{subject}`, `{id}`, `{repo}` and `{number}` (from a subject
shaped `owner/name#7`, as the GitHub bridge names an item), and `{data.<key>}` (a string or number
in the event's data). A template whose placeholder the event cannot fill renders to nothing: the
entry then has no link, or its label falls back to the subject, then the type. A rendered link that
is not http(s) or a path on this Orchestra is dropped.

### 4.4 Example

The test suite checks that this example is valid (`tests/unit/test_config_check.py`).

<!-- spec-example -->
```toml
[desk]
owner = ["person.danroblewis"]
every = "60s"
max_age = "15m"

# Story 20: my PRs stuck. The bridge's series, compared with a day.
[desk.conditions."reviews-wait"]
statement = "No PR of mine waits more than a day for review"
severity = "high"
link = "https://github.com/pulls?q=is%3Aopen+author%3A%40me"
series = "github_prs_awaiting_review_oldest_seconds"
labels = { author = "danroblewis" }
holds = "<= 86400"

# Story 14: tickets in progress with no activity, as a share.
[desk.conditions."few-stuck"]
statement = "Under a fifth of the tickets in progress have been idle for two days"
severity = "medium"
link = "/tickets"
expr = "idle / max(working, 1)"
holds = "< 0.2"
vars = { idle = { series = "tasks_tickets_idle", labels = { idle_for = "2d" } }, working = { series = "tasks_tickets", labels = { state = "working" } } }

# Story 8: no secret within 30 days, by a script in the owner's desk repository.
[desk.conditions."secrets"]
statement = "No secret expires within 30 days"
severity = "critical"
command = ["scripts/desk/secrets.sh"]
timeout = "20s"

# An alert series that exists only while something fires.
[desk.conditions."no-alerts"]
statement = "No alert is firing"
series = "alerts_firing"
reduce = "sum"
holds = "== 0"
when_missing = "holds"

[desk.ledger.types."jira.issue.transitioned"]
kind = "jira"
label = "{subject}"
link = "https://jira.example.com/browse/{subject}"

[desk.ledger.types."github.pr.review_submitted"]
kind = "reviewed"
label = "{subject}"
link = "https://github.com/{repo}/pull/{number}"
sources = ["person.danroblewis"]
```

### 4.5 `orchestra desk check`

```bash
orchestra desk check                       # the repository here: its configuration, overlay merged
orchestra desk check --repo ~/work         # that repository
orchestra desk check --file proposed.toml  # a whole proposed orchestra.toml, not yet in place
orchestra desk check --file - --json       # from stdin, answered in JSON
```

Exit 0: valid. Exit 1: invalid, with every problem found (each a sentence naming the key). Exit 2:
it could not be read. The JSON is `{"ok", "errors", "warnings", "conditions": {name: {check,
severity, holds}}, "ledger": {type: kind}}`. **Warnings** do not fail the check: a script that is
not a file or not executable, and (with `--repo`) a series this project's metrics store has never
had. Both may come after the configuration; until they do, the condition is unknown.

## 5. The ledger

### 5.1 Entries

| Field | Meaning |
|---|---|
| `id` | the event's id (CloudEvents `id`), or `desk:condition:<name>:<time>` for a change |
| `at` | when it happened: the event's `time` |
| `kind` | the rule's kind (`landed`, `merged`, `reviewed`, `sent`, ...) or `condition` |
| `type` | the event type, or `desk.condition.false` / `desk.condition.holds` (never on any bus) |
| `source` | who acted: the event's source |
| `subject` | the event's subject |
| `label` | what the page shows (the rule's label template) |
| `link` | where it happened (the rule's link template) |
| `origin` | `bus` or `desk` |
| `mine` | (computed when read) the source, or its machine, is one of `[desk] owner` |

Nothing else of an event is kept.

### 5.2 Built-in rules

From the other plugins' SPECs (`rules.py`):

| Event type | Published by | Kind | Label | Link |
|---|---|---|---|---|
| `gate.landed` | the task system's gate | `landed` | `{data.ticket}` | `/tickets#ticket={data.ticket}` |
| `ticket.created` | the task system (as the asker) | `ticket` | `{data.ticket}` | same |
| `review.approved` | a reviewer | `reviewed` | `{data.ticket}` | same |
| `github.pr.opened` | the GitHub bridge (as the author) | `opened` | `{subject}` | `https://github.com/{repo}/pull/{number}` |
| `github.pr.merged` | the GitHub bridge (as who merged) | `merged` | `{subject}` | same |
| `github.pr.review_submitted` | the GitHub bridge (as the reviewer) | `reviewed` | `{subject}` | same |
| `github.issue.closed` | the GitHub bridge | `closed` | `{subject}` | `https://github.com/{repo}/issues/{number}` |
| `outbox.sent` | the Outbox | `sent` | `{data.kind}` | `/outbox` |

A GitHub Enterprise owner replaces the GitHub rules with their host in the link.

### 5.3 Reading the bus

The reader follows the bus by offset (`Events.after`), from the offset kept in the ledger, and
writes the entries and the new offset in one transaction. The `desk.reader` process does this
every 2 s while `orchestra run` runs; the web server does it too before it answers for the
ledger, so the page is current with `orchestra web` alone. When the configuration is broken, the
reader keeps the last good rules and says so in its log.

### 5.4 Restarts, rules and duplicates

An entry's id is its event's id, so an event read twice (a restart, two readers at once, a lost
offset) is kept once. When the rules change, the reader reads the bus again from the start and
rewrites the entries it makes (a relabelled kind, a new link); entries no rule makes any more are
kept. When the bus is shorter than the offset (a new bus), it reads from the start.

### 5.5 Condition changes

The instrument writes an entry, kind `condition`, origin `desk`, when a condition turns false
("reviews-wait turned false") and when it holds again ("reviews-wait holds again after 3.2h"),
linked to the condition on the board (`/desk#condition=<name>`). These are never published: the
Desk is not a machine (§10, decision 3).

## 6. Measurements

The instrument `desk.conditions` (`python -m orchestra_desk measure`, every `[desk] every`,
timeout the same) prints, and `orchestra run` stores labelled `instrument=desk.conditions`:

| Series | Labels | Value |
|---|---|---|
| `desk_condition_holds` | `condition` | 1 holds, 0 false; left out while unknown |
| `desk_condition_false_seconds` | `condition` | how long it has been false; 0 when it holds; left out while unknown |
| `desk_conditions` | `state` (`holds`, `false`, `unknown`) | how many conditions are in each state |

A broken `[desk]` makes the round fail with the reason (on the Instruments page and in
`<state>/logs/instruments/desk.conditions.log`), and nothing is printed.

## 7. Pages and API

| Page | What |
|---|---|
| `/desk` ("Desk") | the board: counts, last check; each condition with its state and age, severity, statement, value, evidence, a script's reason, "act on it" (its link) and "readings" (`/api/core/metrics/query` for its first reading, 24 h). `#condition=<name>` highlights one. |
| `/ledger` ("Ledger") | the ledger by day, week (from Monday, local time) or everything; earlier and later; filter by kind (with counts) and to the owner's own acts; each entry linked to its source. The view is in the URL (`#period=week&at=2026-10-26&kind=merged&mine=1`). |

| Route (`/api/plugins/desk`) | Answer |
|---|---|
| `GET /board` | `{configured, error, now, checked_at, every, counts, conditions: [...]}`, ranked (§2) |
| `GET /ledger?period=day\|week\|all&at=YYYY-MM-DD&kind=a,b&mine=true` | `{configured, error, read_error, name, start, end, owner, kinds, counts, entries}`, newest first; at most 2000 |

Both are read only. Nothing on the Desk changes the system (Orchestra's rule 9). The pages, the routes and the
static files are behind Orchestra's login (its SPEC §10.2, PLUGINS.md §4.4.1): a browser's session
or `Authorization: Bearer <orchestra web token>`; the Desk adds no check of its own.

## 8. State

`~/.orchestrator/<key>/desk/` (0700):

| File | Written by | What |
|---|---|---|
| `conditions.json` | the instrument, under `conditions.lock` | the record of §2 |
| `ledger.db` (0600) | the reader, the web server, the instrument | SQLite: entries, the offset, the rules' fingerprint |

## 9. What builds on this

None of these is built in phase 1.

- **The morning brief** (story 20): a page, ready by a set time, of the false conditions ranked
  (the board), what waits for the owner (the Outbox's waiting drafts, Tasking's attention), the
  owner's PRs stuck and reviews owed (conditions over the bridge's series, linked), deadlines,
  and the overnight ledger. "By a set time" needs a clock: D7 gives scheduling to the task system,
  so the brief is a daily recurring ticket whose work is to build the page, with one cheap
  summarising pass by an agent. The Desk serves the parts; it keeps no timer of its own.
- **The status page** (story 3): entries per tracked item (from the owner config's list) built
  from ledger entries by subject, and `desk_status_items{state}` served by this instrument.
- **Nudges and the follow-up pacer** (stories 1, 3, 11, 14): a machine (not the Desk's reader)
  that reads the board's false conditions and the ledger, and drafts into the Outbox, whose
  per-recipient limit is "at most one per person per day". It needs the Outbox and a schedule (D7).
- **The weekly update** (story 15): the ledger's week (`GET /ledger?period=week&mine=true`),
  grouped by kind, every claim linked, drafted by an agent from a weekly recurring ticket, sent
  through the Outbox.
- **Remedies** (wake an agent, file a ticket when a condition turns false): need a listener that
  can act; see decision 3.

## 10. Not in phase 1, and open questions

Not built: the brief, nudges, the status page, the weekly draft, remedies, a timeline,
condition history beyond the series and the ledger's changes, a ledger rule that filters by `data`
(the author of a merged PR, for "PRs of mine merged").

Decisions for the owner:

1. **One plugin or several** (story placement, open question 9). Phase 1 is one plugin; the board
   and the ledger share only the plugin and its state directory, and could part later.
2. **Script conditions, or only instruments?** Story placement §2.4 puts a condition's check in a
   `[[collect]]` instrument of the Target or the owner config. The Desk supports that (a series
   condition over its 0/1), and adds script conditions because a reason is text, which a metric
   cannot carry. Keep both, or require every check to be an instrument?
3. **Condition changes are not events.** No agent can wake on a condition turning false, because
   the Desk publishes nothing. A remedy needs either a machine that watches `desk_condition_holds`
   or a Desk machine that publishes `desk.condition.*` (which would make the Desk a machine).
4. **"Mine" is by source only.** A merged PR's source is who merged it, not its author. Should
   rules filter on protocol `data` keys (`author`)?
5. **Defaults.** `when_missing = "unknown"`, `max_age = 15m`, `reduce = "max"`, four severities,
   GitHub links to github.com. Are these right for the work repository?
6. **Retention.** The ledger keeps everything, forever. When the rules change, entries older than
   the bus's own retention keep their old kind.
