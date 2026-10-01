# Simulated eval: old vs new prompt
Model: gemini-flash-lite-latest | Runs per scenario: 1 | Max agent turns: 6

## Pass rate by scenario

| Scenario | Old prompt | New prompt |
| --- | --- | --- |
| Already paid (this transcript) | 0/1 | 0/1 |
| Partial payment | 0/1 | 1/1 |
| Wrong amount | 0/1 | 1/1 |
| Already paid, Hindi code-mix | 0/1 | 1/1 |
| Already paid, Tamil code-mix | 0/1 | 1/1 |
| Genuine refusal (must still follow 3-refusal rule) | 1/1 | 1/1 |
| Hardship / unable to pay | 1/1 | 1/1 |
| Callback request | 0/1 | 1/1 |

## Key metrics

| Metric | Old prompt | New prompt |
| --- | --- | --- |
| Customer hung up (all calls) | 6/8 | 1/8 |
| Customer hung up (dispute calls) | 5/5 | 1/5 |
| Asked for payment after dispute | 5/5 | 0/5 |
| Agent repeated a line verbatim | 0/8 | 0/8 |
| Dispute logged (dispute calls) | 0/5 | 4/5 |

Transcripts for every call are in transcripts/.
