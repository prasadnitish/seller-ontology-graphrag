# INC-099 order ledger postmortem

The Order Ledger experienced elevated write latency after an index migration. Checkout requests
remained available, but order confirmation events were delayed for eleven minutes.

The team paused the migration, restored the prior index, drained the event backlog, and added a
pre-deployment query-plan comparison to the release checklist. No customer data was lost.
