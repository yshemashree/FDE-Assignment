"""
Predixion FDE Assignment - Simulated eval: old vs new collections prompt
------------------------------------------------------------------------
One LLM plays Priya (the agent), a second plays the customer, a third judges.
Each scenario runs against the OLD prompt and the NEW prompt; results are
written to results.md, results.json and transcripts/.

Setup:
    pip install requests
    # Free key: https://aistudio.google.com/apikey
    export GEMINI_API_KEY="your-key"          # Windows: set GEMINI_API_KEY=your-key

Run:
    python eval_harness.py                     # 8 scenarios x 2 prompts, 1 run each
    python eval_harness.py --runs 3            # 3 runs each (better, slower)
    python eval_harness.py --provider anthropic  # uses ANTHROPIC_API_KEY instead
    python eval_harness.py --provider mock     # dry run, no API, checks the plumbing

Free tiers are rate-limited; raise --sleep if you see 429 errors.
"""

import argparse
import json
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

OLD_PROMPT = """You are Priya, a collections voice agent calling on behalf of QuickLoan Finance.
Your goal is to inform the customer of their overdue amount and secure a
payment commitment date.

Rules:
- Always state the overdue amount and due date clearly.
- If the customer objects or raises a concern, acknowledge with "I understand"
  and repeat the ask for a payment commitment date.
- Do not end the call until a commitment date is given or the customer
  explicitly refuses three times.
- Do not discuss account details beyond the overdue amount and due date."""

NEW_PROMPT = """You are Priya, a collections voice agent calling on behalf of QuickLoan Finance.
Your goal is to inform the customer of their overdue amount and, where the
amount is genuinely owed, secure a payment commitment date.
Never press a customer for payment after they say they have already paid.

Rules:
- State the overdue amount and due date clearly once, at the start of the call.
  Never repeat a sentence word for word. If you must restate, rephrase.

- Before responding to any objection, decide which type it is:
  (A) PAYMENT DISPUTE: customer says they already paid, paid part of it,
      or the amount or date is wrong.
  (B) UNABLE TO PAY: money trouble, salary delay, asks for more time.
  (C) REFUSAL: customer declines to pay without disputing the amount.
  (D) CALLBACK: customer asks to be called later.

(A) PAYMENT DISPUTE - overrides all other rules:
- Stop asking for payment immediately. Do not mention the overdue amount again.
- Acknowledge what they said specifically, e.g. "Thank you for telling me you
  paid on the 3rd. I'll make sure this is checked."
- If the customer already sounds irritated, ask nothing more. Otherwise, ask
  only for details they have not already given (payment date, how they paid,
  amount paid, transaction or UTR reference), at most one follow-up question.
  If they don't have the reference, do not insist.
- Always call log_dispute before closing, even with partial details.
- Tell them: app and UPI payments can take up to 2 working days to reflect;
  the team will verify it, and we will not call about this amount until then.
- Thank them and end the call politely. Do not ask for a commitment date.

(B) UNABLE TO PAY: acknowledge the specific reason, ask what date is
    realistic. Ask at most twice, then offer a callback.
(C) REFUSAL: acknowledge and restate the ask once. After three explicit
    refusals, end the call politely. Never threaten consequences (charges,
    "further action", legal steps) and never ask why they won't pay.
(D) CALLBACK: confirm a time and call schedule_callback.

- Never say "I understand" and then repeat the same ask.
- If the customer is distressed, abusive, or asks for a person,
  call escalate_to_human.
- Do not share account details beyond the overdue amount and due date.
  You may discuss payment details the customer gives you."""

CALL_CONTEXT = """
--- Call context ---
Customer: Mr. Sharma. Personal loan account ending 4821.
Overdue amount: Rs. 8,400. Due date: the 5th."""

HARNESS_FORMAT = """
--- Simulation format (added by the test harness, same for both prompts) ---
You are speaking on a live phone call. Reply only with what you would say out
loud, 1-3 short sentences. When you end the call, put END_CALL on its own last line.
{tools}"""

TOOLS_NONE = "You have no tools available."
TOOLS_NEW = """To call a tool, write it on its own line as: TOOL: tool_name({"key": "value"})
Available tools: log_dispute, schedule_callback, escalate_to_human."""

PROMPTS = {
    "old": OLD_PROMPT + CALL_CONTEXT + HARNESS_FORMAT.format(tools=TOOLS_NONE),
    "new": NEW_PROMPT + CALL_CONTEXT + HARNESS_FORMAT.format(tools=TOOLS_NEW),
}

# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------

CUSTOMER_BASE = """You are role-playing a customer, Mr. Sharma, receiving a call from a loan
collections agent. Stay in character. Reply with only what you'd say on the
phone, 1-2 short sentences. If you feel ignored, pressured or harassed, reply
with exactly [HANGUP] and nothing else. If the agent resolves your issue and
closes politely, say a short goodbye.

Your situation: {persona}"""

SCENARIOS = [
    {
        "id": "already_paid",
        "name": "Already paid (this transcript)",
        "type": "dispute",
        "persona": "You paid the full Rs. 8,400 on the 3rd through the QuickLoan app, in the evening. You don't have the transaction reference handy. You're polite at first, but if the agent asks you for payment again after you've told them you paid, you get angry.",
    },
    {
        "id": "partial_paid",
        "name": "Partial payment",
        "type": "dispute",
        "persona": "You paid Rs. 5,000 on the 3rd by UPI and believe the rest was waived after a call with the branch. You're annoyed that you're being asked for the full Rs. 8,400.",
    },
    {
        "id": "wrong_amount",
        "name": "Wrong amount",
        "type": "dispute",
        "persona": "Your EMI is Rs. 7,400, not Rs. 8,400, and you paid Rs. 7,400 on the 4th via net banking. You think the agent's number is wrong and want it checked.",
    },
    {
        "id": "paid_hindi",
        "name": "Already paid, Hindi code-mix",
        "type": "dispute",
        "persona": "You speak in Hinglish (Hindi-English mix), e.g. 'Maine 3 tareekh ko app se pay kar diya tha.' You paid the full amount on the 3rd via the app. You get irritated quickly if not heard.",
    },
    {
        "id": "paid_tamil",
        "name": "Already paid, Tamil code-mix",
        "type": "dispute",
        "persona": "You speak in Tanglish (Tamil-English mix), e.g. 'Naan already 3rd-la app la pay pannitten.' You paid the full amount on the 3rd via GPay/UPI. You get irritated quickly if not heard.",
    },
    {
        "id": "refusal",
        "name": "Genuine refusal (must still follow 3-refusal rule)",
        "type": "refusal",
        "persona": "You do owe the money and you don't dispute the amount. You simply refuse to pay or commit to a date, clearly, each time you're asked. You stay calm and don't hang up; you let the agent end the call.",
    },
    {
        "id": "hardship",
        "name": "Hardship / unable to pay",
        "type": "hardship",
        "persona": "You lost your job last month and your final settlement comes on the 20th. You want to pay but can't right now. You'll agree to a realistic date if asked kindly.",
    },
    {
        "id": "callback",
        "name": "Callback request",
        "type": "callback",
        "persona": "You're in the middle of a work meeting. You ask to be called back at 6 PM today. You're polite but want to hang up soon.",
    },
]

EXPECTED = {
    "dispute": "The agent must stop asking for payment once the customer says they paid or disputes the amount, "
               "capture or acknowledge payment details, and close politely without the customer getting angry.",
    "refusal": "The customer does owe the money. The agent should NOT treat this as a payment dispute. "
               "It should ask for a commitment a limited number of times and then close politely.",
    "hardship": "The agent should acknowledge the hardship specifically, work towards a realistic date "
                "(the 20th) or offer a callback, and not repeat the same demand.",
    "callback": "The agent should agree to call back at the requested time and close quickly and politely.",
}

JUDGE_PROMPT = """You are grading a simulated loan collections call.

Scenario type: {stype}
Expected behaviour: {expected}

Transcript:
{transcript}

How the call ended: {outcome}

Return ONLY a JSON object, no markdown, with these keys:
"asked_for_payment_after_dispute": true/false (only relevant for dispute scenarios; false otherwise),
"handled_correctly": true/false (did the agent meet the expected behaviour?),
"reason": one short sentence."""

# --------------------------------------------------------------------------
# LLM providers
# --------------------------------------------------------------------------

def call_gemini(system, messages, temperature):
    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
        ],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 400},
    }
    r = requests.post(url, json=body, headers={"x-goog-api-key": key}, timeout=60)
    r.raise_for_status()
    cands = r.json().get("candidates") or [{}]
    parts = cands[0].get("content", {}).get("parts", [])
    # drop thinking parts so model reasoning never leaks into the call
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def call_anthropic(system, messages, temperature):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            "max_tokens": 400,
            "temperature": temperature,
            "system": system,
            "messages": messages,
        },
        timeout=60,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"]).strip()


def call_mock(system, messages, temperature):
    """Canned replies so the pipeline can be tested without an API key."""
    if system.startswith("You are grading"):
        return '{"asked_for_payment_after_dispute": false, "handled_correctly": true, "reason": "mock"}'
    if system.startswith("You are role-playing"):
        return "I already paid this on the 3rd." if len(messages) < 3 else "[HANGUP]"
    if "log_dispute" in system and len(messages) > 2:
        return 'Thanks, I have noted it.\nTOOL: log_dispute({"payment_date": "3rd"})\nEND_CALL'
    return "Our records show Rs. 8,400 overdue, due on the 5th. When can you pay?"


PROVIDERS = {"gemini": call_gemini, "anthropic": call_anthropic, "mock": call_mock}


def llm(provider, system, messages, temperature, sleep):
    for attempt in range(5):
        try:
            out = PROVIDERS[provider](system, messages, temperature)
            time.sleep(sleep)
            if out or attempt == 4:
                return out
            print("    Empty reply, retrying...")
            continue
        except (requests.ConnectionError, requests.Timeout):
            if attempt < 4:
                print("    Network error, retrying in 15s...")
                time.sleep(15)
                continue
            raise
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            if code in (429, 500, 503) and attempt < 4:
                wait = 15 * (attempt + 1)
                print(f"    API {code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("LLM call failed after retries")

# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

# tolerates markdown around the call (`TOOL: x(...)`, **TOOL:** x(...)) and speech on the same line
TOOL_RE = re.compile(r"[`*]*TOOL:[`*]*\s*(\w+)\((\{.*?\}|[^)]*)\)[`*]*")
END_RE = re.compile(r"[\[`*]*END_CALL[\]`*]*")
LABEL_RE = re.compile(r"^\s*(\*\*)?(Priya|AGENT)(\*\*)?\s*:\s*", re.I)


def parse_agent(text):
    spoken, tools, ended = [], [], False
    for line in text.splitlines():
        if END_RE.search(line):
            ended = True
            line = END_RE.sub("", line)
        for m in TOOL_RE.finditer(line):
            tools.append({"name": m.group(1), "args": m.group(2)})
        line = LABEL_RE.sub("", TOOL_RE.sub("", line)).strip()
        if line:
            spoken.append(line)
    return " ".join(spoken), tools, ended


def simulate(provider, prompt_key, scenario, max_turns, sleep):
    agent_sys = PROMPTS[prompt_key]
    cust_sys = CUSTOMER_BASE.format(persona=scenario["persona"])
    agent_msgs = [{"role": "user", "content": "[Call connected. The customer has picked up.]"}]
    transcript, outcome = [], "max_turns"

    for _ in range(max_turns):
        raw = llm(provider, agent_sys, agent_msgs, 0.3, sleep)
        spoken, tools, ended = parse_agent(raw)
        transcript.append({"speaker": "AGENT", "text": spoken, "tools": tools})
        agent_msgs.append({"role": "assistant", "content": raw})
        if ended:
            outcome = "agent_ended"
            break

        # customer sees agent lines as "user", own lines as "assistant"
        cust_msgs = [
            {"role": "user" if t["speaker"] == "AGENT" else "assistant", "content": t["text"] or "..."}
            for t in transcript
        ]
        reply = llm(provider, cust_sys, cust_msgs, 0.7, sleep)
        if "[HANGUP]" in reply:
            transcript.append({"speaker": "CUSTOMER", "text": "[HANGS UP]", "tools": []})
            outcome = "customer_hung_up"
            break
        transcript.append({"speaker": "CUSTOMER", "text": reply, "tools": []})
        agent_msgs.append({"role": "user", "content": reply})

    return transcript, outcome


def has_verbatim_repeat(transcript, threshold=0.85):
    lines = [t["text"] for t in transcript if t["speaker"] == "AGENT" and t["text"]]
    return any(
        SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold
        for i, a in enumerate(lines) for b in lines[i + 1:]
    )


def render(transcript):
    out = []
    for t in transcript:
        line = f"{t['speaker']}: {t['text']}"
        for tool in t["tools"]:
            line += f"\n    [tool] {tool['name']}({tool['args']})"
        out.append(line)
    return "\n".join(out)


OUTCOME_TEXT = {"agent_ended": "the agent ended the call",
                "customer_hung_up": "the customer hung up",
                "max_turns": "the simulation hit the turn limit with the call still open"}


def judge(provider, scenario, transcript, outcome, sleep):
    prompt = JUDGE_PROMPT.format(
        stype=scenario["type"], expected=EXPECTED[scenario["type"]], transcript=render(transcript),
        outcome=OUTCOME_TEXT[outcome],
    )
    raw = llm(provider, "You are grading a simulated call. Output JSON only.",
              [{"role": "user", "content": prompt}], 0.0, sleep)
    raw = re.sub(r"```(json)?", "", raw).strip()
    try:
        return json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {"asked_for_payment_after_dispute": None, "handled_correctly": False,
                "reason": f"Judge output unparseable: {raw[:80]}"}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="gemini", choices=PROVIDERS)
    ap.add_argument("--runs", type=int, default=1, help="runs per scenario per prompt")
    ap.add_argument("--max-turns", type=int, default=6, help="max agent turns per call")
    ap.add_argument("--sleep", type=float, default=4.0, help="seconds between API calls")
    ap.add_argument("--only", nargs="*", help="scenario ids to run")
    args = ap.parse_args()
    if args.provider == "mock":
        args.sleep = 0

    scenarios = [s for s in SCENARIOS if not args.only or s["id"] in args.only]
    Path("transcripts").mkdir(exist_ok=True)
    rows = []

    for s in scenarios:
        for pk in ("old", "new"):
            for run in range(1, args.runs + 1):
                print(f"[{s['id']}] {pk} prompt, run {run}...")
                transcript, outcome = simulate(args.provider, pk, s, args.max_turns, args.sleep)
                verdict = judge(args.provider, s, transcript, outcome, args.sleep)
                row = {
                    "scenario": s["id"], "name": s["name"], "type": s["type"], "prompt": pk, "run": run,
                    "outcome": outcome,
                    "hung_up": outcome == "customer_hung_up",
                    "verbatim_repeat": has_verbatim_repeat(transcript),
                    "dispute_logged": any(t["name"] == "log_dispute" for x in transcript for t in x["tools"]),
                    "asked_after_dispute": verdict.get("asked_for_payment_after_dispute"),
                    "judge_ok": bool(verdict.get("handled_correctly")),
                    "reason": verdict.get("reason", ""),
                }
                row["passed"] = row["judge_ok"] and not row["hung_up"]
                rows.append(row)
                Path(f"transcripts/{s['id']}_{pk}_run{run}.txt").write_text(
                    f"Scenario: {s['name']} | Prompt: {pk} | Outcome: {outcome}\n"
                    f"Judge: {json.dumps(verdict)}\n\n{render(transcript)}\n", encoding="utf-8")
                Path("results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    write_markdown(rows, scenarios, args)


def pct(rows, key):
    return f"{sum(1 for r in rows if r[key])}/{len(rows)}" if rows else "-"


def write_markdown(rows, scenarios, args):
    model = {"gemini": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
             "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
             "mock": "mock"}[args.provider]
    md = [f"# Simulated eval: old vs new prompt",
          f"Model: {model} | Runs per scenario: {args.runs} | Max agent turns: {args.max_turns}",
          "", "## Pass rate by scenario", "",
          "| Scenario | Old prompt | New prompt |", "| --- | --- | --- |"]
    for s in scenarios:
        o = [r for r in rows if r["scenario"] == s["id"] and r["prompt"] == "old"]
        n = [r for r in rows if r["scenario"] == s["id"] and r["prompt"] == "new"]
        md.append(f"| {s['name']} | {pct(o, 'passed')} | {pct(n, 'passed')} |")

    md += ["", "## Key metrics", "", "| Metric | Old prompt | New prompt |", "| --- | --- | --- |"]
    old = [r for r in rows if r["prompt"] == "old"]
    new = [r for r in rows if r["prompt"] == "new"]
    od = [r for r in old if r["type"] == "dispute"]
    nd = [r for r in new if r["type"] == "dispute"]
    md += [
        f"| Customer hung up (all calls) | {pct(old, 'hung_up')} | {pct(new, 'hung_up')} |",
        f"| Customer hung up (dispute calls) | {pct(od, 'hung_up')} | {pct(nd, 'hung_up')} |",
        f"| Asked for payment after dispute | {pct(od, 'asked_after_dispute')} | {pct(nd, 'asked_after_dispute')} |",
        f"| Agent repeated a line verbatim | {pct(old, 'verbatim_repeat')} | {pct(new, 'verbatim_repeat')} |",
        f"| Dispute logged (dispute calls) | {pct(od, 'dispute_logged')} | {pct(nd, 'dispute_logged')} |",
        "", "Transcripts for every call are in transcripts/.",
    ]
    Path("results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n" + "\n".join(md))


if __name__ == "__main__":
    main()
