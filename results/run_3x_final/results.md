# Simulated eval: old vs new prompt
Model: gemini-flash-lite-latest | Runs per scenario: 3 | Max agent turns: 6

## Pass rate by scenario

| Scenario | Old prompt | New prompt |
| --- | --- | --- |
| Already paid (this transcript) | 0/3 | 3/3 |
| Partial payment | 0/3 | 3/3 |
| Wrong amount | 0/3 | 3/3 |
| Already paid, Hindi code-mix | 0/3 | 3/3 |
| Already paid, Tamil code-mix | 0/3 | 3/3 |
| Genuine refusal (must still follow 3-refusal rule) | 2/3 | 3/3 |
| Hardship / unable to pay | 3/3 | 3/3 |
| Callback request | 0/3 | 3/3 |

## Key metrics

| Metric | Old prompt | New prompt |
| --- | --- | --- |
| Customer hung up (all calls) | 19/24 | 0/24 |
| Customer hung up (dispute calls) | 15/15 | 0/15 |
| Asked for payment after dispute | 15/15 | 0/15 |
| Agent repeated a line verbatim | 0/24 | 0/24 |
| Dispute logged (dispute calls) | 0/15 | 14/15 |

Transcripts for every call are in transcripts/.
