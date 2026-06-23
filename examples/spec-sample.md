---
artifact_type: spec
title: CSV export
intent: Let a user export their records as a downloadable CSV.
---

# CSV export

When the user clicks Export, the system generates a CSV and downloads it.
Filtering by date range is supported.
For large datasets, generation happens asynchronously in the background.

<!--
Try it:  challenge-plans run examples/spec-sample.md --type spec --profile standard --sink markdown
This spec deliberately omits acceptance criteria, non-goals, the async-delivery
contract, and a size threshold — a good adversarial review should surface those.
-->
