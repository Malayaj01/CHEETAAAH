# CHEETAAAH — architecture

Companion to `core-idea.md`. Written 28 Sept 2026.

---

## The central decision: this is a pipeline, not an autonomous agent

The reliability numbers in `core-idea.md` decide the architecture. Applied
changes land right ~50–60% of the time on first pass. An autonomous agent that
decides its own next step fails **opaquely** — you get "done" and a broken
artefact, which is exactly what happened repeatedly while building the seller
proposal by hand.

A fixed pipeline fails at a **named step**, with state you can inspect and
resume from. And the pipeline here is genuinely fixed — there is no branching
decision the model needs to make about *what to do next*:

```
ingest → normalise → extract → reconcile → APPROVE → execute → verify → report
```

The LLM does work *inside* steps. It does not choose the steps.

This mirrors what already works in your own stack: the disposition service is a
set of explicit paths with a durable inbox, not an agent loop — and that is
precisely why the 14 Sept outage was recoverable.

---

## The eight steps

### 1. Ingest
Webhook from Google Meet / Teams when the recording and transcript are ready.

**Do not build audio capture.** The platform already labels speakers with real
names because it knows who is in the call — which solves the single weakest
part of the whole design (see `core-idea.md` §1). Building capture yourself
buys a diarisation problem and a consent problem for nothing.

Fallback for meetings recorded on a phone: the existing `transcribe.py` path,
accepting that speaker names will be inferred rather than known.

### 2. Normalise
Transcript → a list of utterances: `{speaker, start, end, text}`.
One shape, whatever the source. Store raw alongside normalised — always keep
the original so an extraction can be re-run when the prompt improves.

### 3. Extract
**One LLM call, schema-enforced.** Not a conversation.

```python
class Actionable(BaseModel):
    type: Literal["copy_change", "delete_block", "add_block",
                  "data_change", "design_change", "external", "unknown"]
    component: str            # "page1.headline", "plans.mdc", "page2.buyleads"
    instruction: str          # imperative, one line
    verbatim: str             # what was actually said — never paraphrased away
    owner: str                # a real name from the transcript, or "unassigned"
    confidence: float

class Extraction(BaseModel):
    decisions:  list[Decision]
    actionables: list[Actionable]
    open_questions: list[str]
```

`verbatim` is non-negotiable. Every downstream disagreement gets settled by
going back to what was said.

### 4. Reconcile against memory
For each new decision, retrieve prior decisions on the **same component**, then
judge each pair: *same / refines / reverses / unrelated*.

Retrieval must be semantic, not keyword. The real example: "utilize this space"
versus *"ब्लैंक स्पेसिस को खत्म करने के चक्कर में"* — no shared words, different
languages, opposite meaning.

**Rule: latest wins, but a reversal is always surfaced** with both quotes and
both dates. Requirements legitimately change; the agent must not block on every
change. It must never let a reversal pass unnoticed.

### 5. Approve — the permanent gate
A page listing every actionable with: instruction, verbatim, owner, component,
and any reversal flag. Per item: **accept / edit / reject / not mine**.

This is not a trust-building phase that graduates away. Spoken instruction is
ambiguous — "a live is written in both screenshots" meant *a line* — and no
model removes that.

### 6. Execute — typed handlers, not a general agent
**The single biggest reliability lever.** Each actionable has a `type`, and only
**registered** types can run unattended:

```python
HANDLERS = {
    "copy_change": apply_copy_change,     # exact string swap in a known file
    "delete_block": delete_block,         # remove a named section
    "data_change": rerun_query,           # change a query or threshold
}
# everything else -> human queue, never guessed at
```

`unknown` and `design_change` deliberately have no handler. Design judgement is
where the first-pass failure rate lives.

Every handler must be **idempotent** — re-running a step is safe. Your
disposition sweep already learned this: it skips already-classified calls via
`NOT EXISTS`, which is why a capped or timed-out run is harmless.

### 7. Verify — the check must be able to fail
Per type, a machine-checkable gate:

| Type | Gate |
|---|---|
| copy_change | target string present, old string absent |
| delete_block | block absent, document still parses |
| deck change | true page-fit check (unclipped), no unfilled `{placeholders}` |
| code change | tests pass |

**Learn from the real failure:** the page-fit checker reported "2 pages,
verified" for several rounds while content was being clipped, because it
measured *through* `overflow:hidden`. A verification that cannot fail is worse
than none — it manufactures false confidence.

### 8. Report
Mail with: what was applied, what was skipped and why, links to diffs — not
claims. Plus the reversal flags and anything routed to a human.

---

## State, not memory

Every meeting is a **persisted row** moving through states:

```
ingested → normalised → extracted → reconciled
         → awaiting_approval → approved → executing
         → verified → reported
         (failed_<step> at any point)
```

Crash-safe, resumable, auditable. This is the same reason your disposition
inbox survives a bad deploy: durable state beats in-memory orchestration.

Two Postgres tables carry it:

- `meeting` — the state machine, raw + normalised transcript, extraction JSON
- `decision` — the memory layer, one row per decision, with
  `component`, `verbatim`, `status`, `supersedes`, and an embedding for retrieval

---

## Framework: don't adopt one

**Recommendation: plain Python on your existing stack.**

| Need | Use | Why |
|---|---|---|
| API + webhooks | **FastAPI on Cloud Run** | Every one of your 13 services already is this |
| Model calls | **your LiteLLM gateway** | Already there, budgeted, monitored. One key story, not two |
| Schemas | **Pydantic** | Already used throughout postcall |
| State + memory | **Postgres (Cloud SQL)** | Already there. Add `pgvector` for retrieval |
| Step orchestration | **Cloud Tasks**, or **n8n** if you prefer what you know | Both already in production |
| Scheduling | **Cloud Scheduler** | Already driving your sweeps |

**Why not an agent framework:**

- **LangGraph** is the closest fit and the one I would reconsider later — but it
  adds a dependency and a graph abstraction over what is a seven-step linear
  pipeline with one human gate. Reach for it when you genuinely need branching,
  retries with different strategies, or parallel fan-out per actionable.
- **CrewAI / AutoGen** are multi-agent negotiation frameworks. There is no
  agent-to-agent negotiation here. Actively wrong fit.
- **Any new framework fragments the stack.** Your services are FastAPI +
  LiteLLM + Postgres. A second paradigm means two debugging stories, two
  deployment stories, and one more thing that breaks at 3am.

**Reconsider LangGraph when** the pipeline grows real branches — different
execution strategies per type with fallbacks, or parallel per-actionable
execution with partial failure handling. Not before.

---

## Build order

**Stage 1 — steps 1 to 5, no execution.** Ingest, normalise, extract,
reconcile, and mail the MoM as a draft for approval. This is most of the value
at almost none of the risk. A week.

**Stage 2 — steps 6 to 8 for `copy_change` only.** One type, one handler, one
verification gate, output as a **branch and a PR** — never a direct edit. Let
it earn trust on the narrowest possible change class.

**Stage 3 — add types one at a time**, each with its own gate. `design_change`
may never qualify, and that is a fine outcome.

---

## Non-negotiables

1. The approval gate is permanent.
2. Only registered types execute; unknown goes to a human.
3. Verification must be capable of failing.
4. Every handler is idempotent.
5. `verbatim` is never discarded.
6. Diffs, not claims.

---

## Addendum — 1 Oct 2026: what was built, and the one design change

**Execute is an agent, the rest is a workflow.** The orchestrator (`pipeline.py`,
`execute.py`) is deterministic and holds every key. Inside step 6 it calls Claude Code
headless (`claude -p`) with a fixed prompt per change type, a repo on a fresh branch, and a
restricted tool set. Claude Code discovers the repo itself via the repo's `CLAUDE.md`; the
extractor never writes prompts. Verification runs outside the agent; its RESULT line is a
hint, the diff and the verify command are the truth.

Built: steps 2–8 for `copy_change`, `delete_block`, `add_block`, `data_change`.
Ingest is upload or in-page recording, not a Meet/Teams hook. State is SQLite + JSON files,
not Postgres. Report is a page and a Markdown file, not mail.

Measured on the first real run: Claude Code correctly recognised one approved change was
already in place and refused to touch a file `CLAUDE.md` marked off-limits; applied the
second (`deck3.py`), rendered with live data, passed the page-fit check, and left a note
about what it deliberately did not change. The "already_applied" status exists because of
that run.

---

## Expansion — context providers, and what the agent must not do

### Context providers (`providers/`)
Knowledge the organisation already has, read before extraction, **enrichment only**:

| question | source |
|---|---|
| who was in the room | calendar event attendees (Google Calendar / Outlook) |
| who is "Amit" | directory (Workspace / Entra / Slack profiles) |
| which project | calendar title + attendees → project registry |
| who owns `page3.plans` | repo index, `CODEOWNERS`, recent committers |
| discussed since last meeting | chat (Google Chat / Slack) in the project channel |

One interface (`attendees`, `person`, `repos`, `owners`, `messages`), one adapter per source.
IndiaMART profile: Google Calendar + Workspace + Google Chat + GitHub. Generic profile:
Outlook/Teams or Slack + GitLab. A provider can never create a decision; chat-derived
candidates pass the same approval gate. First adapter to build: calendar attendees — it fixes
the weakest link (who said what) with one OAuth.

### Two statuses the pipeline needed
- `needs_design` — new work with no existing component. Never executed; becomes a ticket with
  verbatim, nearby decision history and open questions. Humans invent, the agent maintains.
- `blocked_on_external` — someone else must act first (another team's API). Stored in the
  `dependency` table, drafted as an ask to the owner, carried into every following MoM as
  "still open since …" until a meeting resolves or drops it.

### Repo access: knowledge, not action
Indexing every org repo with owners improves routing and dependency tracking. It does **not**
make cross-repo or new-feature execution safe: risk grows with the number of files and
systems whose behaviour must be assumed, and the failure mode is confident, plausible, wrong
edits. Rule: a repo gets an executor only if it has a verify gate (tests) and a `CLAUDE.md`;
otherwise it gets a ticket. Positioning: *remembers and tracks everything; executes only what
it can verify.*

---

## Later — a decision model (Jev / TypeSafe) for the judgement calls

Jev takes a *state* plus typed questions (Choice / Score / Noul = truth 0–1) and returns
typed answers with probabilities — no text, no parsing. Everywhere the pipeline asks Claude
for one word and then parses it is a candidate. Not for transcription, extraction, the MoM or
Claude Code's work: Jev answers questions, it does not write.

| step | today | with Jev |
|---|---|---|
| Reconcile — reversal judge | one Claude call per decision, free-text label; ~60% of per-meeting cost | Choice over {same, refines, reverses, unrelated} + Noul "new undoes earlier"; show low-margin cases as *uncertain* instead of picking one |
| Dependency resolution | Claude reads transcript, says resolved/open/dropped | Noul "transcript shows this dependency is delivered", thresholded, probability shown in "Waiting on others" |
| Actionable type + routing | chosen inside the extraction call | Choice over types + Noul "small and verifiable enough to automate"; below the floor → human, not Claude Code. This is the gate that decides whether the agent acts |
| Owner assignment | a name or "unassigned", guessed | Score each attendee as owner; `unassigned` when nobody clears the bar |
| Execution safety (later) | verify command only | Noul "this diff does only what the instruction asked" over instruction + diff — an extra gate, not a replacement |

Order: reversal judge first (biggest cost, cleanest fixture: the Monday/Friday Maximiser
pair), then routing. Precondition to test before anything: Jev on Hinglish/Devanagari state
text — the judge's inputs are Hindi quotes. Plan: `judge_jev.py` behind a `JUDGE=jev` switch,
run both judges over the 33 real decisions, compare agreement and cost before switching.
