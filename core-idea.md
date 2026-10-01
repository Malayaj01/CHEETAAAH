# CHEETAAAH — core idea

**One line:** a meeting ends, and the work it asked for is already moving.

Owner: Malayaj Singh · Started: 28 Sept 2026

---

## The problem

Decisions made in a meeting decay on the way to execution. Someone has to
remember what was said, work out which parts are theirs, reconstruct the intent
days later, and then do the work. In practice a lot is lost: the detail of what
was actually asked, who owns which piece, and — worst — the fact that today's
instruction contradicts one given a week ago.

This is not hypothetical. Over the last fortnight the NSD seller-proposal work
ran exactly this loop twice, by hand:

| | Monday 15:35 | Friday 13:40 |
|---|---|---|
| Length | 16 min | 22 min |
| Transcript | 3,203 words | 4,580 words |
| Cost | $0.039 | $0.066 |
| Outcome | 12 change items | full 3-page restructure |

Both produced real, actioned change. Both also showed exactly where the process
breaks. That evidence is what this design is built on — not speculation.

---

## The loop

```
meeting ends
   ↓
transcript                    (solved — see below)
   ↓
extract: decisions, actionables by owner, open questions
   ↓
check against memory          → flag anything that reverses an earlier decision
   ↓
HUMAN APPROVES                ← permanent gate, not a training-wheel
   ↓
execute the approved items
   ↓
verify                        → machine-checkable proof, not a claim
   ↓
report back by mail
```

---

## What is already proven

**Recording → transcript.** Working today, in `proposal/transcribe.py`.
Audio goes through IndiaMART's own LiteLLM gateway to Gemini. Hinglish is
handled correctly — Hindi in Devanagari, English left in English. Roughly
**$0.18 per hour** of meeting. Chunked at 4 minutes with 45s pacing because the
gateway key caps at 30,000 tokens/minute.

**Transcript → actionables.** The Friday extraction pulled out every deletion,
every addition, and two reversed instructions, with nothing material missed.
It worked because the meeting was structured — they walked the document top to
bottom. Less structured meetings will be harder.

---

## Where it breaks — the honest part

### 1. Speaker attribution is the weak link

The whole "what *I* must do vs what *others* must do" split depends on knowing
who said what. Today that is inferred from people saying each other's names
out loud, plus grammatical gender in Hindi. It is not voice recognition.

Worse: each audio chunk is a separate API call, so **"Speaker 1" in part 1 is
not the same person as "Speaker 1" in part 4.**

Two ways out:

- **Cheap and better:** use Google Meet / Teams native transcripts. They label
  speakers with real names because the platform knows who is in the call.
- **Expensive:** `pyannote.audio` with voice enrolment — record each person
  once, store their voice embedding, match across all future meetings. Needs
  a HuggingFace licence, local compute, per-person enrolment upkeep, and
  alignment of pyannote's timestamps with the LLM's text. Degrades on
  crosstalk and phone audio.

**Decision: take the platform route. Do not build audio capture.**

### 2. Spoken instructions are ambiguous

Real example from this work: *"a live is written in both screenshots"* —
which meant *a line*. The guess was right. An unattended agent guessing wrong
would have deleted the wrong thing and reported success.

No model removes this. The approval gate exists because of it.

### 3. Contradictions across meetings

Monday said **"utilize this space"**. Friday said
**"ये सारे ब्लैंक स्पेसिस को खत्म करने के चक्कर में, समझ ही नहीं आ रहा"** —
stop removing white space. A direct reversal, five days apart.

An agent acting on Friday alone would silently undo Monday's work.

Note the trap: those two share **no keywords** and are in **different
languages**. Detection has to be semantic, and both decisions must be tagged to
the same component or they are never compared at all.

### 4. Execution is the least reliable step

Measured on this very project, applying approved changes by hand:

- HTML markup broken ~5 times by bad edits
- Page-fit verification reported "2 pages, verified" for several rounds while
  content was actually being **clipped** — the check was measuring through
  `overflow:hidden`
- One full revert required

Every one of those was caught because a human was looking. **This is the
strongest argument for the approval gate and for machine-checkable
verification.**

---

## Memory layer

Not a transcript archive — a **decision store**. One record per decision:

```json
{
  "id": "...",
  "date": "2026-09-26",
  "meeting": "friday-1340",
  "component": "page-1 whitespace",
  "instruction": "stop removing white space",
  "verbatim": "ये सारे ब्लैंक स्पेसिस को खत्म करने के चक्कर में...",
  "owner": "manager",
  "status": "active",
  "supersedes": "decision-2026-09-22-004"
}
```

On each new decision: retrieve prior decisions on the same component, judge the
pair — *same / refines / reverses / unrelated* — and surface any reversal with
**both quotes and both dates** for a human call.

**Default rule: latest wins, but always say it was a reversal.** Requirements
legitimately change; the agent must not block on every change. What it must
never do is let a reversal pass unnoticed.

A manual version of this already exists in `proposal/meeting-summary.md` and
`proposal/changes-required.md`. This formalises it.

**Memory fixes detection, not judgement.** It tells you Friday reversed Monday.
Deciding which is right stays human.

---

## Effectiveness — realistic

| Step | Reliability | Note |
|---|---|---|
| Recording → transcript | ~95% | Working now, cheap |
| Transcript → actionables + owners | ~80% | Needs review; owners are the weak part |
| Approved items → applied changes | ~50–60% first pass | Design/copy work. Higher with tests |
| Completion mail | ~100% | Trivial |

---

## Staged build

**Stage 1 — now.** Recording lands → transcript → structured MoM: decisions,
actionables grouped by owner, open questions, flagged reversals → mailed as a
**draft** for review. Nothing changes automatically. Most of the value, almost
none of the risk.

**Stage 2 — once Stage 1 has earned trust.** Approved items become a **branch
and a PR**, never a direct edit. You review a diff, not a claim. Each change
type carries a verification gate — for the deck, the true page-fit check; for
code, tests.

**Stage 3 — narrow classes only**, where success is machine-checkable.

---

## Principles

1. **The approval gate is permanent.** Not a phase. Spoken intent is ambiguous
   and always will be.
2. **Never trust a self-report.** The verification must be able to fail. A
   check that measures through `overflow:hidden` will happily confirm a lie.
3. **Diffs, not claims.** Show what changed, not that something changed.
4. **Do not build what the platform already does.** Recording and speaker
   naming are solved by Meet and Teams.
5. **Surface reversals, do not resolve them.**

---

## Open questions

- Which meeting platform is the source of truth — Meet, Teams, or both?
- Where do decision records live, and who else can read them?
- What is the smallest useful set of "components" for tagging decisions?
- Consent and retention: who is told that meetings are transcribed and stored,
  and for how long are recordings kept?
- Does this stay personal tooling, or is it aimed at the team?
