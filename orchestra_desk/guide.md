# The Desk: an operator's guide

For the operator (the Supervisor, or anyone) who sets the Desk up in a project. The design is the
Desk's SPEC.md; this is what to choose and why. Every key below is checked by the Desk's reader,
and an unknown key is refused.

The Desk is one person's view: the **board** (`/desk`), standing conditions checked against the
metrics store, false and severe first; and the **ledger** (`/ledger`), what happened, read from the
bus. It only reads. It never publishes an event, never writes a metric itself, sends nothing,
calls no paid service and changes no code. So most of its settings are safe for you to choose;
the exceptions are under "Ask the human".

## Turning it on

The section `[desk]` is the switch: when the merged configuration has it (from `orchestra.toml`
or from the overlay alone), `orchestra run` keeps the process `desk.reader` running (it follows the
bus into the ledger) and runs the instrument `desk.conditions` every `[desk] every`. Without it
the pages exist and say the Desk is not configured. The package `orchestra-desk` must be installed
in Orchestra's environment, or `[desk]` is a section nothing reads.

The smallest useful configuration: an empty board and the ledger with its built-in rules.

```toml
[desk]
owner = ["person.danroblewis"]
```

## Checking a change

- **The reader**: `orchestra_desk.config.problems(raw)` returns `(settings, errors)`: every
  problem in the merged configuration at once, each a sentence naming the key, and settings `None`
  when there is any. Its errors are what to give `project.config_edit` as the check
  (`lambda raw: problems(raw)[1]`). It also says "the configuration has no [desk] section" when
  `[desk]` is absent, so with that check, adding `[desk]` passes and removing it is refused as a
  new problem; removing the Desk is the human's decision anyway.
- **Warnings**: `orchestra_desk.check.check(raw, repo_root, store, project_key)` adds, without
  failing: a script that is not a file or not executable, and (given the store) a series this
  project's metrics store has never had. A warned condition will be `unknown` until the script or
  series exists; fix it or tell the human why it is expected. `orchestra desk check` is the same
  for a person at a terminal; you do not need to run it.
- **Proof it works**: one round (`every`) after the change, `GET /api/plugins/desk/board` shows
  each condition `holds` or `false`, with its evidence (the selector, the value, "holds when ...").
  `unknown` gives the cause in the evidence ("no such series", "last point 2h ago, older than
  15m", a script's exit or timeout). A round that failed as a whole shows on the Instruments page
  and in `<state>/logs/instruments/desk.conditions.log`.

## Repository or overlay

`orchestra.toml` is the team's file, committed. The overlay is the owner's private file, merged
over it and never committed. Put in the overlay what is the owner's own: `owner`, conditions about
"my" PRs or reviews, personal links. Put in the repository what the team shares: conditions about
the system, ledger rules for the team's event types. A change to the repository is a commit to a
shared repository: the human chooses that.

Merge pitfalls (tables merge key by key, the overlay winning; plain arrays are replaced whole):

- An overlay table `[desk.conditions."x"]` merges into the repository's condition `x`: adding
  `expr` to a `series` condition gives it two checks, which is refused. Use a new name instead.
- The overlay cannot delete a repository condition or ledger rule; only the repository can. An
  overlay rule with `ignore = true` drops a built-in rule, but merged into a rule the repository
  defines it is refused (`ignore = true` takes no other keys).
- `owner` in the overlay replaces the repository's list; it is not added to it.

## `[desk]`

| Key | Default | Range |
|---|---|---|
| `owner` | `[]` | a source or a list of sources |
| `every` | `"60s"` | 10 s to 1 h |
| `max_age` | `"15m"` | 1 s to 30 d |

Durations are a number with a unit (`ms`, `s`, `m`, `h`, `d`, `w`: `"60s"`, `"15m"`, `"26h"`) or a
number of seconds.

**`owner`** is who the owner is on the bus; it only decides the ledger's "mine" filter, so a
wrong value is harmless but leaves "mine" empty. Give machine names (`person.ana`), never an
instance (`worker/1`): "mine" compares the source's machine part. The bridges name people
`person.<key>` when the owner's identity map (`[bridges] people`) lists them, so one key covers
every system; otherwise `person.<github login>` on GitHub, `person.jira.<login>` and
`person.slack.<handle>`. List one per system when the map does not join them. Find the candidates
on the Machines page (sources seen on the bus) and the identity map; confirm with the human.

**`every`** is how often every condition is checked. Each round reads each reading once and runs
every script. Checking faster than the inputs change gains nothing: keep 60 s unless a condition
needs minutes-fresh answers and its inputs are that fresh. Raise it (5m) when scripts are slow or
costly to the systems they query. A script's `timeout` must be at most `every` minus 5 s, so
lowering `every` can make a script condition invalid.

**`max_age`** is how old a point may be and still count; older is missing. Set it at two or three
times the interval of the instrument that feeds the series: 15 minutes fits scrapes and collectors
running every 30 s to 5 m. A daily collector needs `max_age = "26h"` on that reading, not on the
whole Desk. Too short and conditions flap to unknown; too long and a dead instrument hides behind
its last value.

## Conditions: `[desk.conditions."<name>"]`

Every condition has `statement` (required, under 200 characters: what should hold, in the owner's
words), `severity` (`critical`, `high`, `medium` by default, `low`; it only ranks the board) and
`link` (an `https://` or `http://` URL, or a path on this Orchestra such as `/tickets`: where to act
on it). The name is lowercase letters, digits, `.`, `_` and `-`, up to 64 characters, and is the
only label on its metric, `desk_condition_holds{condition}`.

It has exactly one check: `series`, `expr` or `command`. Prefer them in that order. A series
already measured is the cheapest and most honest check; an expression combines several; a script
is for what no instrument measures and needs a sentence of reason on the board. If the check is a
measurement others should see, it belongs in an instrument (`[[collect]]`) with a series condition
over it, not in a script.

### One series

```toml
[desk.conditions."reviews-wait"]
statement = "No pull request waits more than a day for a review asked of someone"
severity = "high"
link = "https://github.com/acme/service/pulls"
series = "github_prs_review_request_oldest_seconds"
labels = { repo = "acme/service" }
reduce = "max"
holds = "<= 86400"
```

- `series` must be a name the store has: read it from the Instruments page, the store, or the
  producing plugin's documentation. Never guess; the warning "not in this project's metrics store
  yet" is the sign of a guess.
- `labels` must all equal the given strings; a label left out matches any value. `project` is
  refused: the Desk always reads this project's series only. Label values come from the producer's
  configuration (the GitHub PR bridge labels each series `repo`, from `[bridges.github_prs] repos`).
- `reduce` turns the matching series' latest fresh points into one number: `max` (default; for
  "the worst one"), `min`, `sum` (for totals across labels), `avg`, `count` (how many series have a
  fresh point; never missing, so `when_missing` does not apply to it).
- `holds` is one of `<`, `<=`, `>`, `>=`, `==`, `!=` and a number: `"<= 86400"`, `">= 1e3"`. Prefer
  `<=`/`>=` over `==` for anything not an integer count.
- `max_age` overrides `[desk] max_age` for this reading.
- `when_missing`: `unknown` (default), `holds` or `false`. Choose `holds` only for a series that
  exists only while something is wrong (a firing alert). It also makes a dead instrument look
  healthy, so pair it with a condition that the instrument is alive (`reduce = "count"`, `">= 1"`).
  Choose `false` when silence itself is the failure.
- The language has no rate or history: a counter (`*_total`) is compared as its cumulative value.
  Compare levels (gauges); for "how many in the last day", the instrument must serve that series.

### An expression

```toml
[desk.conditions."checks-mostly-green"]
statement = "Under a tenth of the open pull requests have failing checks"
severity = "medium"
expr = "failing / max(open, 1)"
holds = "< 0.1"
vars = { failing = { series = "github_prs_checks_failing", reduce = "sum" }, open = { series = "github_prs_open", reduce = "sum" } }
```

`expr` is numbers, the names in `vars`, `+ - * / %`, parentheses, unary minus, `min`, `max` and
`abs`; nothing else parses. Every name in `expr` must be in `vars` and every var used. Each var is
a series name or `{ series, labels, reduce, max_age }`; `labels`, `reduce` and `max_age` beside
`expr` are refused. Guard divisions (`max(x, 1)`): a division by zero or a non-finite result is
`unknown`. `when_missing` applies when any var is missing.

### A script

```toml
[desk.conditions."secrets"]
statement = "No secret expires within 30 days"
severity = "critical"
command = ["scripts/desk/secrets.sh"]
timeout = "20s"
```

The instrument runs `command` (a list, or a string split as a shell would, not run by one) in the
repository root every round, with the environment `orchestra run` has (the owner's) plus
`ORCHESTRA_REPO` and `DESK_CONDITION`. A first word with a `/` is relative to the repository root; a bare name is looked
up on `PATH`. Its first line of output is `1`/`0` (`true`/`false`, `ok`/`fail`), the rest a reason
up to 500 characters; exit 0 is required. `timeout` defaults to 20 s and is at most `every` minus
5 s. `holds`, `labels`, `reduce`, `max_age`, `when_missing` and `vars` are refused here.

A script runs code with the owner's credentials every round: only configure one the human has
written or approved, and do not write one yourself to make a condition work.

## The ledger: `[desk.ledger]`

`defaults = true` (the default) keeps the built-in rules: `gate.landed`, `ticket.created`,
`review.approved` (the task system), `github.pr.opened`, `github.pr.merged`,
`github.pr.review_submitted`, `github.issue.closed` (the GitHub bridges, linked to github.com) and
`outbox.sent`. A rule under `types` replaces the built-in rule of its type or adds one; `ignore =
true` (alone) drops one. `defaults = false` keeps only yours; rarely right.

A rule `[desk.ledger.types."<event type>"]` takes `kind` (required: a short lowercase word, not
`condition`), `label` (default `"{subject}"`), `link`, and `sources` (only events from these
sources: a machine, or one instance `worker/1`). Templates take `{type}`, `{source}`, `{subject}`,
`{id}`, `{repo}` and `{number}` (from a subject shaped `owner/name#7`) and `{data.<key>}`; use
`{data.<key>}` only for event types published as a protocol for listeners. A placeholder the event
cannot fill blanks the link (or the label falls back to the subject); a link must render to
http(s) or a path on this Orchestra, or it is dropped. Take event types from the bus (the Machines
page) or the publishing plugin's SPEC, never by guess: a rule for a type nobody publishes is valid
and silent.

GitHub Enterprise: override the GitHub rules with the host (from the bridge's configuration or the
repository's git remote).

```toml
[desk.ledger.types."github.pr.merged"]
kind = "merged"
label = "{subject}"
link = "https://github.example.com/{repo}/pull/{number}"

[desk.ledger.types."jira.issue.transitioned"]
kind = "jira"
link = "https://jira.example.com/browse/{subject}"

[desk.ledger.types."ticket.created"]
ignore = true
```

Any change to the rules makes the reader read the whole bus again and rewrite the entries the
rules make (entries no rule makes any more are kept). That is safe, but on a long bus it takes
time: batch rule changes rather than making them one at a time.

## Ask the human

The Desk spends nothing, sends nothing and pushes nothing, but these are the owner's to decide;
propose, then ask:

- what the conditions are, their statements and severities: they are the owner's priorities;
- `owner`: who they are on each system;
- any script condition, and anything that would need a script written;
- writing to the repository's `orchestra.toml` (a shared commit) rather than the overlay;
- removing `[desk]`, a condition someone else wrote, or the built-in ledger rules
  (`defaults = false`).

The Desk cannot nudge, remind, file a ticket or wake an agent when a condition turns false, and a
condition change is not an event. If the owner wants that, say it needs a machine (and the Outbox
for anything said as them); do not configure around it.
