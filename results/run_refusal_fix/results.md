# Simulated eval: old vs new prompt
Model: gemini-flash-lite-latest | Runs per scenario: 3 | Max agent turns: 6

## Pass rate by scenario

| Scenario | Old prompt | New prompt |
| --- | --- | --- |
| Genuine refusal (must still follow 3-refusal rule) | 2/3 | 3/3 |

## Key metrics

| Metric | Old prompt | New prompt |
| --- | --- | --- |
| Customer hung up (all calls) | 1/3 | 0/3 |
| Customer hung up (dispute calls) | - | - |
| Asked for payment after dispute | - | - |
| Agent repeated a line verbatim | 0/3 | 0/3 |
| Dispute logged (dispute calls) | - | - |

Transcripts for every call are in transcripts/.
