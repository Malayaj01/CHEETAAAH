"""Transcript -> structured extraction. One schema-enforced call, not a chat.

`verbatim` is mandatory on every decision and actionable: downstream disagreements
are settled by going back to what was actually said."""
import json
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

import config
import llm

Type = Literal["copy_change", "delete_block", "add_block", "data_change",
               "design_change", "external", "needs_design", "unknown"]


class Decision(BaseModel):
    component: str
    instruction: str = Field(description="imperative, one line, English")
    verbatim: str = Field(description="what was actually said, in the original language")
    said_by: str = Field(description="speaker label or name as it appears in the transcript")
    confidence: float = Field(ge=0, le=1)


class Actionable(BaseModel):
    type: Type
    component: str
    instruction: str
    verbatim: str
    said_by: str
    owner: str = Field(description="a name from the transcript, or 'unassigned'")
    due: Optional[str] = None
    blocks: Optional[str] = Field(default=None, description="for external items: what work on "
                                  "our side waits for this, e.g. 'page3.plans dynamic pricing'")
    confidence: float = Field(ge=0, le=1)


class Extraction(BaseModel):
    summary: str = Field(description="3-5 sentences, what the meeting was about and concluded")
    decisions: List[Decision]
    actionables: List[Actionable]
    open_questions: List[str]
    people: List[str] = Field(description="speaker labels/names seen, with role if stated")


def load_project(name):
    return yaml.safe_load((config.PROJECTS / f"{name}.yaml").read_text(encoding="utf-8"))


PROMPT = """You extract decisions and actionables from a meeting transcript.

PROJECT: {name} — {description}
PEOPLE KNOWN ON THIS PROJECT: {people}

COMPONENT VOCABULARY (use exactly one of these keys per item; use "other" only if nothing fits):
{components}

ACTIONABLE TYPES:
  copy_change   — change wording/text in an existing block
  delete_block  — remove a block or section
  add_block     — add a new block or section
  data_change   — change a number, query, threshold or data source
  design_change — layout, spacing, colour, font, graphics
  external      — work by someone outside this project/team (another team's API, get videos,
                  a decision someone else must take). Set `owner` to them and `blocks` to
                  what on our side waits for it. If the meeting says the external thing is
                  already delivered, the remaining work is OURS — classify that instead.
  needs_design  — something new to build or a design/product question with no existing
                  component to change; a human must design it first
  unknown       — could not classify

RULES
- A DECISION is something agreed or instructed that changes the product or the plan.
  An ACTIONABLE is a unit of work someone must do. Most decisions produce one actionable;
  discussion without a conclusion produces neither — put it in open_questions.
- `verbatim` must be a real quote from the transcript, in its original language and script.
  Never paraphrase it, never translate it. Keep it short (one or two sentences).
- `said_by` is the speaker label or name exactly as in the transcript. Do not guess real
  names from context unless a name is spoken.
- `owner`: the person told to do it, if named; otherwise "unassigned".
- If the same point is made twice, output it once with the clearest quote.
- Be exhaustive on decisions and actionables; be conservative on confidence.
- Instructions are written in English even when the quote is Hindi.

Return ONLY a JSON object matching this schema:
{schema}

TRANSCRIPT:
{transcript}
"""


CHUNK_WORDS = 2200          # ~8-9k tokens of Hinglish; prompt + output stays under the 30k/min key limit

MERGE = """You are merging extractions from consecutive parts of ONE meeting into a single result.
Rules:
- Merge duplicates (same decision/actionable stated in two parts) into one item, keeping the
  clearest verbatim quote. Keep everything else. Do not invent items.
- If a later part reverses an earlier part, keep only the later decision but mention the earlier
  one in the summary.
- Owners/speakers: keep as given.
- Summary: one paragraph for the whole meeting.
Return ONLY a JSON object matching this schema:
{schema}

PARTS:
{parts}
"""


def _one(transcript, p, model, label):
    comps = "\n".join(f"  {k}: {v}" for k, v in (p.get("components") or {}).items())
    prompt = PROMPT.format(name=p["name"], description=p.get("description", ""),
                           people=", ".join(p.get("people") or []) or "unknown",
                           components=comps,
                           schema=json.dumps(Extraction.model_json_schema(), indent=1),
                           transcript=transcript)
    messages = [{"role": "user", "content": prompt}]
    total = 0.0
    for attempt in range(2):
        raw, cost = llm.chat_json(messages, model, max_tokens=12000, label=label)
        total += cost
        try:
            return Extraction.model_validate(raw), total
        except ValidationError as e:
            messages += [{"role": "assistant", "content": json.dumps(raw)},
                         {"role": "user", "content": f"Fix these schema errors and return the "
                                                     f"full JSON again:\n{e}"}]
    raise RuntimeError("extraction did not validate after retry")


def _chunks(transcript):
    words = transcript.split()
    if len(words) <= CHUNK_WORDS:
        return [transcript]
    n = -(-len(words) // CHUNK_WORDS)
    size = -(-len(words) // n)
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def extract(transcript: str, project: str, model=config.EXTRACT_MODEL, context=None):
    """Returns (Extraction, cost). Long transcripts are split into parts, extracted
    separately (each call fits the gateway's per-minute token limit) and merged."""
    p = load_project(project)
    if context and context.get("attendees"):
        p = dict(p, people=(p.get("people") or []) + [
            a if isinstance(a, str) else f"{a.get('name')} ({a.get('team') or a.get('email', '')})"
            for a in context["attendees"]])
    parts = _chunks(transcript)
    results, total = [], 0.0
    for i, part in enumerate(parts, 1):
        label = f"extract {i}/{len(parts)}: " if len(parts) > 1 else "extract: "
        ex, cost = _one(part, p, model, label)
        results.append(ex)
        total += cost
    if len(results) == 1:
        ex = results[0]
    else:
        compact = [{"part": i, **r.model_dump()} for i, r in enumerate(results, 1)]
        messages = [{"role": "user", "content": MERGE.format(
            schema=json.dumps(Extraction.model_json_schema(), indent=1),
            parts=json.dumps(compact, ensure_ascii=False))}]
        raw, cost = llm.chat_json(messages, model, max_tokens=12000, label="merge: ")
        total += cost
        ex = Extraction.model_validate(raw)
    allowed = set((p.get("components") or {}).keys())
    for item in ex.decisions + ex.actionables:
        if allowed and item.component not in allowed:
            item.component = "other"
    return ex, total
