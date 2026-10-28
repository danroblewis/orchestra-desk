"""The Desk: one person's view over an Orchestra system. A board of standing conditions, checked
over the metrics store and served as an instrument, and a ledger of what happened, read from the
bus. See SPEC.md.

The Desk is no machine: it never announces itself, never publishes an event and never writes a
metric. Its reader follows the bus, its instrument prints measurements that ``orchestra run``
stores, and its pages read its own state."""

PACKAGE = "desk"            # the plugin's name: its URLs, its process's and its instrument's prefix
STATE = "desk"              # its directory under the project's state directory
