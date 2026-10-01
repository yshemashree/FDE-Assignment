# FDE Assignment (Medium): Collections call fix

Take-home for the Predixion AI Forward Deployed Engineer role.
A collections voice agent ("Priya") kept asking customers to pay even after
they said they had already paid, and they hung up angry. This repo has the
script I used to test my rewritten prompt against the original one.

## What's here

| Path | What it is |
| --- | --- |
| `eval_harness.py` | The eval script. One model plays the agent, one plays the customer, one grades the call. Contains both prompts (OLD_PROMPT, NEW_PROMPT). |
| `results/run_1x/` | First run, 1 call per scenario. Caught a problem in my first rewrite: the agent kept re-asking payment details the customer had already given. |
| `results/run_3x_final/` | Main results: 8 scenarios x 3 runs, old vs new prompt. |
| `results/run_refusal_fix/` | Refusal scenario re-run after I added a rule against threatening customers. |

Each results folder has `results.md` (tables), `results.json` (raw rows),
`run_log.txt` and a `transcripts/` folder with every simulated call.

## Results (simulated, gemini-flash-lite-latest, not production data)

| Scenario | Old prompt | New prompt |
| --- | --- | --- |
| Already paid | 0/3 | 3/3 |
| Partial payment | 0/3 | 3/3 |
| Wrong amount | 0/3 | 3/3 |
| Already paid, Hindi code-mix | 0/3 | 3/3 |
| Already paid, Tamil code-mix | 0/3 | 3/3 |
| Genuine refusal (re-run after no-threats fix) | 2/3 | 3/3 |
| Hardship / unable to pay | 3/3 | 3/3 |
| Callback request | 0/3 | 3/3 |

Customer hung up: 19/24 calls with the old prompt, 0/24 with the new one.
Asked for payment after a dispute: 15/15 old, 0/15 new.

## Prompt versions

The script in this repo is the final version (md5 `f9426587ab32a7cf92d748a8fd77cba5`).
Earlier runs used earlier versions of NEW_PROMPT:

- `run_1x`: my first rewrite.
- `run_3x_final`: dispute rule changed to "ask only for missing details, at most one
  follow-up, nothing if the customer is already irritated" and "always log the dispute".
- `run_refusal_fix`: added "never threaten consequences" to the refusal rule.
  This is the only difference from the `run_3x_final` version.

## How to run

    python3 -m venv evalenv
    source evalenv/bin/activate
    pip install requests
    export GEMINI_API_KEY="your-key"
    export GEMINI_MODEL="gemini-flash-lite-latest"
    python eval_harness.py --runs 3 --sleep 8

Dry run without an API key: `python eval_harness.py --provider mock`

## Limits

This is a simulation. One model plays every role, and 3 runs per scenario is a
small sample. It shows the new prompt behaves the way it was designed to; a
canary on real calls is what would actually prove it.
