# Voice2 execution plan policy

Use an implementation plan for changes that add a Provider, change runtime selection, alter realtime events, introduce a remote boundary, or affect release packaging.

Each plan must state:

1. User-visible outcome and non-goals.
2. Affected module boundaries and public API compatibility.
3. Runtime and model licenses, weight distribution policy, and consent/data flow.
4. RAM, VRAM, disk, backend, precision, and hardware assumptions for every variant.
5. Cold start, hot TTFA, RTF, peak memory, cancellation, queue, and soak-test method.
6. OOM and dependency-failure behavior, including the exact local fallback order.
7. Contract, unit, API, simulated-hardware, realtime interruption, and migration tests.
8. Documentation, upgrade, rollback, and release steps.

Provider work is incomplete until the adapter is discoverable through an entry point, unavailable installations fail truthfully, benchmarks are tied to a hardware fingerprint, and `THIRD_PARTY_NOTICES.md` is current.

