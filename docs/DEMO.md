# Two-minute OpsGate walkthrough

Start the server and open http://127.0.0.1:8000. The initial workflow is Visual QA Phase 1B. If you have already experimented, submit the supplied source observations as a new run and restore prep to 22, base rework to 12, and estimated duplicates to 8.

1. **Show the real return.** The pilot reports 66 assisted minutes against an 84-minute directional baseline: 21.4% reduction. Point out that the dashboard includes preparation and review and claims $0 cash savings. The 40% unique precision reflects eight estimated duplicate entries.
2. **Stop an upstream process failure.** Turn **Scope marked** off. All observations route to the Product Owner, the rule evaluation stops, and zero LLM tokens are spent. Turn it back on. Turning **Device matrix** off has the same effect.
3. **Inspect evidence.** Open **View validation** or a row's arrow. F1 and F2 remain separate because element and popup state differ. F4 has no named element, viewport, or computed font size. The 18px request is not proof of a defect. Show the saved source text, rule pack, prompt, and verification log.
4. **Expose sensitivity.** Set preparation to 30 minutes. Total effort becomes 74 minutes and benefit drops to 11.9%. The gate changes to **Hold / extend trial**. Return preparation to 22.
5. **Recover a handoff.** Click **Simulate cross-hub stall**. The QA Lead, Product Owner, and Designer receive plain-English draft runbooks. Six unresolved observations add an estimated 30 minutes; assisted effort reaches 96 minutes and the benefit turns negative. The button disables to prevent recording the same demo incident twice. Nothing is sent to Asana.
6. **Show reuse.** Select CRO or PPC. The input, checklist, and accountable owner change. The simulation banner makes clear that the economics remain illustrative Visual QA figures.
7. **Explain the expansion decision.** Open **Record trial evidence**. The gate requires ten scope-matched tasks and two observed release cycles. An empty quality record never grants approval. Do not enter invented successes as actual trial evidence.
8. **Leave an artifact.** Export the report to include the validation receipt, recovery events, economics, assumptions, and entered trial records. A validation link opens the exact saved receipt while the server and its database remain available.

Human evidence decisions can be demonstrated with **Request evidence**, a clearly labeled test reviewer, and a clarification request. Confirmation is a reviewer attestation and requires references. It creates a linked revision; it does not rewrite an old receipt.
