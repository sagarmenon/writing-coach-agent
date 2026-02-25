"""
SAGAR'S WRITING COACH AGENT v3 — FINAL
========================================
- Six writing metrics computed on every draft
- Live web search for reading recommendations matched to taste profile
- Google Sheets memory across sessions
- Adaptive Sunday prompts based on session history
- Full coaching context baked in
"""

import os
import re
import json
import math
import anthropic
import threading
from flask import Flask, request, jsonify
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ─────────────────────────────────────────────────────────────

SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "1goGH2ySpKLIMrDWBNb-7XoHObjJ_G90qW5FtHKQ6dBo")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheets_service():
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        return None
    try:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return build("sheets", "v4", credentials=creds).spreadsheets()
    except Exception as e:
        print(f"Sheets init error: {e}")
        return None

def read_sheet(sheets, range_name, max_rows=6):
    try:
        result = sheets.values().get(spreadsheetId=SHEET_ID, range=range_name).execute()
        rows = result.get("values", [])
        return rows[-max_rows:] if len(rows) > max_rows else rows
    except Exception as e:
        print(f"Sheet read error: {e}")
        return []

def append_sheet(sheets, range_name, row):
    try:
        sheets.values().append(
            spreadsheetId=SHEET_ID,
            range=range_name,
            valueInputOption="RAW",
            body={"values": [row]}
        ).execute()
    except Exception as e:
        print(f"Sheet append error: {e}")


# ─────────────────────────────────────────────────────────────
# SIX WRITING METRICS
# Based on: Gardner, Zinsser, Orwell, Lamott, Strunk & White
# ─────────────────────────────────────────────────────────────

ABSTRACT_WORDS = {
    "concept", "idea", "notion", "theory", "principle", "aspect", "factor",
    "element", "system", "process", "approach", "framework", "perspective",
    "context", "dynamic", "paradigm", "narrative", "discourse", "phenomenon",
    "essence", "nature", "reality", "truth", "value", "belief", "understanding",
    "experience", "knowledge", "awareness", "consciousness", "existence",
    "relationship", "situation", "condition", "environment", "culture", "society",
    "community", "structure", "institution", "development", "potential", "impact",
    "influence", "significance", "importance", "relevance", "implication"
}

QUALIFIER_WORDS = {
    "perhaps", "maybe", "possibly", "probably", "arguably", "seemingly",
    "apparently", "somewhat", "quite", "rather", "fairly", "relatively",
    "generally", "usually", "often", "sometimes", "occasionally", "largely",
    "mostly", "mainly", "essentially", "basically", "fundamentally", "virtually",
    "nearly", "almost", "sort", "kind", "way", "unsubstantiated", "subjective",
    "opinion", "think", "believe", "feel", "suppose", "guess", "reckon",
    "suspect", "wonder", "seem", "appear"
}

SCENE_INDICATORS = {
    "said", "walked", "sat", "stood", "looked", "heard", "saw", "felt",
    "touched", "smelled", "tasted", "opened", "closed", "moved", "turned",
    "smiled", "laughed", "cried", "whispered", "shouted", "nodded", "shook",
    "reached", "grabbed", "placed", "picked", "put", "took", "held", "carried",
    "entered", "left", "arrived", "stopped", "started", "began", "watched",
    "noticed", "realized", "remembered", "forgot", "asked", "answered",
    "replied", "told", "showed", "pointed", "pulled", "pushed"
}

def compute_metrics(text: str) -> dict:
    """Compute all six writing metrics on a draft."""
    words = text.split()
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip() and len(s.split()) > 2]
    word_count = len(words)
    
    if word_count < 50:
        return {}

    # 1. Concrete-to-Abstract Ratio (Gardner)
    words_lower = [w.lower().strip('.,!?;:"\'') for w in words]
    abstract_count = sum(1 for w in words_lower if w in ABSTRACT_WORDS)
    # Concrete = proper nouns (capitalized mid-sentence) + sensory verbs
    concrete_count = sum(1 for i, w in enumerate(words) if i > 0 and w[0].isupper() and w.lower() not in {'i', 'the', 'a', 'an'})
    concrete_ratio = round(concrete_count / max(abstract_count, 1), 2)

    # 2. Sentence Variety Score (Zinsser)
    sentence_lengths = [len(s.split()) for s in sentences if len(s.split()) > 1]
    if len(sentence_lengths) > 2:
        mean_len = sum(sentence_lengths) / len(sentence_lengths)
        variance = sum((l - mean_len) ** 2 for l in sentence_lengths) / len(sentence_lengths)
        variety_score = round(math.sqrt(variance), 1)
    else:
        variety_score = 0

    # 3. Qualifier Density (Orwell)
    qualifier_count = sum(1 for w in words_lower if w in QUALIFIER_WORDS)
    qualifier_per_500 = round((qualifier_count / word_count) * 500, 1)

    # 4. Scene Ratio (Gardner)
    scene_verb_count = sum(1 for w in words_lower if w in SCENE_INDICATORS)
    scene_ratio_pct = round((scene_verb_count / word_count) * 100, 1)

    # 5. Opening & Closing Strength
    # Measure specificity (proper nouns + concrete words) in first/last 50 words vs middle
    opening = words[:50]
    closing = words[-50:]
    middle = words[50:-50] if word_count > 100 else words
    
    def specificity(word_list):
        wl = [w.lower().strip('.,!?;:"\'') for w in word_list]
        proper = sum(1 for i, w in enumerate(word_list) if i > 0 and w[0].isupper() and w.lower() not in {'i', 'the', 'a', 'an', 'but', 'and', 'or'})
        scene = sum(1 for w in wl if w in SCENE_INDICATORS)
        abstract = sum(1 for w in wl if w in ABSTRACT_WORDS)
        return (proper + scene - abstract) / max(len(word_list), 1)
    
    opening_score = round(specificity(opening), 3)
    closing_score = round(specificity(closing), 3)
    middle_score = round(specificity(middle), 3) if middle else 0
    opening_strong = opening_score >= middle_score
    closing_strong = closing_score >= middle_score

    # 6. Proper Noun Specificity (Orwell clarity test)
    proper_nouns = [w for i, w in enumerate(words) if i > 0 and len(w) > 1 and w[0].isupper() 
                    and w.lower() not in {'i', 'the', 'a', 'an', 'but', 'and', 'or', 'so', 'yet',
                                          'for', 'nor', 'in', 'on', 'at', 'to', 'by', 'if', 'as',
                                          'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
                                          'saturday', 'sunday', 'january', 'february', 'march',
                                          'april', 'may', 'june', 'july', 'august', 'september',
                                          'october', 'november', 'december'}]
    proper_per_500 = round((len(proper_nouns) / word_count) * 500, 1)

    return {
        "word_count": word_count,
        "concrete_abstract_ratio": concrete_ratio,
        "sentence_variety_sd": variety_score,
        "qualifier_per_500": qualifier_per_500,
        "scene_ratio_pct": scene_ratio_pct,
        "opening_strong": opening_strong,
        "closing_strong": closing_strong,
        "proper_nouns_per_500": proper_per_500,
    }

def format_metrics_for_email(m: dict) -> str:
    """Format metrics as a clean section for the email."""
    if not m:
        return ""
    
    def status(condition, good="✓", bad="✗"):
        return good if condition else bad

    lines = [
        f"**DRAFT METRICS** ({m['word_count']} words)",
        "",
        f"Concrete-Abstract Ratio: {m['concrete_abstract_ratio']} {'↑ good' if m['concrete_abstract_ratio'] > 1.5 else '↓ too abstract'}",
        f"Sentence Variety: {m['sentence_variety_sd']} SD {'↑ good rhythm' if m['sentence_variety_sd'] > 6 else '↓ monotonous — vary length'}",
        f"Qualifier Density: {m['qualifier_per_500']}/500 words {'↑ hedging too much — cut qualifiers' if m['qualifier_per_500'] > 5 else '↓ good'}",
        f"Scene Ratio: {m['scene_ratio_pct']}% {'↑ above target' if m['scene_ratio_pct'] >= 30 else '↓ below 30% target — more scene'}",
        f"Opening Strength: {status(m['opening_strong'])} {'strong' if m['opening_strong'] else 'weaker than middle — rewrite your opening'}",
        f"Closing Strength: {status(m['closing_strong'])} {'strong' if m['closing_strong'] else 'weaker than middle — rewrite your ending (W1)'}",
        f"Proper Noun Specificity: {m['proper_nouns_per_500']}/500 words {'↑ specific' if m['proper_nouns_per_500'] > 8 else '↓ too vague — name people, places, things'}",
    ]
    return "\n".join(lines)

def format_metrics_for_sheet(m: dict) -> list:
    """Format metrics as a flat list for Google Sheets row."""
    if not m:
        return [""] * 7
    return [
        str(m.get("word_count", "")),
        str(m.get("concrete_abstract_ratio", "")),
        str(m.get("sentence_variety_sd", "")),
        str(m.get("qualifier_per_500", "")),
        str(m.get("scene_ratio_pct", "")),
        "Yes" if m.get("opening_strong") else "No",
        "Yes" if m.get("closing_strong") else "No",
        str(m.get("proper_nouns_per_500", "")),
    ]


# ─────────────────────────────────────────────────────────────
# SAGAR'S COACHING CONTEXT
# ─────────────────────────────────────────────────────────────

COACHING_CONTEXT = """
WRITER: Sagar Menon, 26, Bombay.
NEWSLETTER: Public Record on Substack. 22 articles across 4 years.
WORK: Founder of Mauka (communication education) and Citta (mental health for students).

TASTE PROFILE:
- Wants writing to: (1) make readers see something they couldn't see before, (2) make them think differently about something ordinary, (3) make them feel less alone, (4) make them feel something they've been avoiding
- Drawn to: writers who think in public without apology — Orwell, Paul Graham, Feynman
- Key influence: Fleabag — the dual consciousness of seeing yourself seeing yourself
- Pulls toward world-immersion in fiction — wants to be inside a specific place
- Dislikes: hedging, Western self-help aesthetics, sentimentality without earned weight

TIER RANKINGS:
S-Tier: EdTech failing (Dec 2024), Building Depth (Apr 2025)
A-Tier: Building Agency, Building Taste, On Grief, Light keeper, PUC certificates, Menon's Principles, Biryani, a night at the hospital, How to be interesting, curiosity with no economic utility
B-Tier: Grass, Sparkle, Design, How to run, Confidence Needs Curiosity, Turtle, On Mentorship
C-Tier: Cookie, 3 questions (founder), Pants

STRENGTHS:
S1. THE SENTENCE — writes sentences that stop readers. "Three minutes is appropriate to go into the past without spiraling."
S2. FORMAL RANGE — 6+ registers: analytical essay, timestamped vignette, city meditation, word-prompt, how-to, series
S3. COUNTER-INTUITIVE OBSERVATION — finds the unexpected flip of common wisdom
S4. CULTURAL SPECIFICITY — writes India from inside without explaining it
S5. EARNED PERSONAL ANCHOR — specific, unpretentious stories that ground abstract ideas
S6. DRY, POINTED HUMOR — never tries too hard, always has POV
S7. STRUCTURAL ARCHITECTURE — thinks in skeletons not just paragraphs

WEAKNESSES (track by code):
W1. ENDINGS DEFLATE — trails off with summary/restatement. Target: write 3 endings, pick the one that arrives somewhere new.
W2. THESIS PUBLISHED AS ESSAY — below 800-word floor. Target: 800 words minimum, no exceptions.
W3. SCENE-BUILDING AVOIDANCE — summarises instead of inhabits. Target: 30% scene ratio minimum in personal essays.
W4. WORD-ESSAY DILUTION — publishes without second-layer argument. Target: one-sentence test before writing.
W5. WESTERN CANON OVER-RELIANCE — Naval, Graham, Dewey over lived evidence. Target: max one external quote per essay.
W6. INCONSISTENT CADENCE — bursts then gaps. Target: something ships every two weeks.
W7. REFLEX DISCLAIMERS — hedges before the argument. Target: max one disclaimer per essay, placed after argument not before.

ACTIVE COMMITMENTS:
- 800 word minimum before publishing
- One scene minimum per personal essay
- Word essays only with stated second-layer argument first
- No ending that recaps
- Max one external quote per essay
- Bi-weekly publishing cadence
- The chawl visit essay — overdue (8th grade, PC under arm, one sentence for 3 years)
- The arranged marriage → communication essay — most important unwritten piece
- The full Confidence Needs Curiosity essay
"""

TASTE_PROFILE_FOR_RECS = """
Writer's taste: Orwell (clarity, no wasted words, political sharpness), Paul Graham (thinking out loud, trusts reader), 
Feynman (curiosity as method), Fleabag (dual consciousness, self-awareness without self-indulgence).
Wants: essays and books where the reader sees something they couldn't see before. 
World-immersive fiction set in specific places. Writers who find the systemic in the personal.
Diverse — not limited to Indian or Western literary traditions.
Dislikes: hedging, overwriting, sentimentality, self-help aesthetics.
Current writing problem to solve: {problem}
"""


# ─────────────────────────────────────────────────────────────
# LIVE READING RECOMMENDATIONS VIA CLAUDE WITH WEB SEARCH
# ─────────────────────────────────────────────────────────────

def get_live_reading_rec(dominant_weakness: str, patterns: str) -> dict:
    """Use Claude with web search to find a specific, current reading recommendation."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    
    problem_map = {
        "W1": "endings that deflate — needs to learn to end with resonance not summary",
        "W2": "publishing thesis-statements before they become full essays — needs models of fully developed essay thinking",
        "W3": "scene-building avoidance — summarises moments instead of inhabiting them",
        "W4": "word-essay series without second-layer argument — needs models of objects/words as genuine lenses",
        "W5": "over-reliance on Western canon — needs diverse voices who use lived evidence as primary authority",
        "W6": "inconsistent publishing cadence — needs writers who show up consistently",
        "W7": "reflexive disclaimers and hedging — needs writers who state things without apology",
    }
    
    problem = problem_map.get(dominant_weakness, "developing scene-building and specificity in personal essays")
    taste = TASTE_PROFILE_FOR_RECS.format(problem=problem)
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            system=f"""You are a literary coach finding one specific reading recommendation.

Writer taste profile:
{taste}

Find ONE specific essay, book, or piece of writing — published anywhere in the world, any tradition — 
that would directly help this writer with their current problem.
Search for recent critical writing or recommendations if needed.
Be specific and diverse — don't default to the obvious Western canon choices.

Respond in exactly this format:
TITLE: [exact title]
AUTHOR: [full name]
WHY: [one sentence — what specifically in this work solves the writer's current problem]
WHERE: [where to find it — publication name, or "book" or "online"]""",
            messages=[{"role": "user", "content": f"Find a reading recommendation for: {problem}. Patterns this session: {patterns}"}]
        )
        
        # Extract text from response
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text
        
        # Parse the structured response
        rec = {"title": "", "author": "", "why": "", "where": ""}
        for line in text.split("\n"):
            if line.startswith("TITLE:"): rec["title"] = line.replace("TITLE:", "").strip()
            elif line.startswith("AUTHOR:"): rec["author"] = line.replace("AUTHOR:", "").strip()
            elif line.startswith("WHY:"): rec["why"] = line.replace("WHY:", "").strip()
            elif line.startswith("WHERE:"): rec["where"] = line.replace("WHERE:", "").strip()
        
        return rec if rec["title"] else None
        
    except Exception as e:
        print(f"Reading rec search error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# HTML EMAIL FORMATTER
# ─────────────────────────────────────────────────────────────

def markdown_to_html(text: str, metrics_text: str = "", reading_rec: dict = None) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\n---\n', '\n<hr style="border:none;border-top:1px solid #e0e0e0;margin:24px 0;">\n', text)
    
    paragraphs = text.split('\n\n')
    html_parts = []
    for p in paragraphs:
        p = p.strip()
        if not p: continue
        if p.startswith('<hr'):
            html_parts.append(p)
        else:
            p = p.replace('\n', '<br>')
            html_parts.append(f'<p style="margin:0 0 18px 0;">{p}</p>')
    
    body = '\n'.join(html_parts)

    metrics_html = ""
    if metrics_text:
        metrics_text_formatted = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', metrics_text)
        metrics_text_formatted = metrics_text_formatted.replace('\n', '<br>')
        metrics_html = f"""
  <div style="margin-top:32px;padding:20px 24px;background:#f5f5f0;
              border-left:3px solid #888;font-family:monospace;font-size:13px;line-height:1.8;">
    {metrics_text_formatted}
  </div>"""

    reading_html = ""
    if reading_rec and reading_rec.get("title"):
        where = f" ({reading_rec['where']})" if reading_rec.get("where") else ""
        reading_html = f"""
  <div style="margin-top:32px;padding:20px 24px;background:#f9f9f9;border-left:3px solid #1a1a1a;">
    <p style="margin:0 0 6px 0;font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#888;">This week's reading</p>
    <p style="margin:0 0 6px 0;font-size:16px;"><strong>{reading_rec['title']}</strong> — {reading_rec['author']}{where}</p>
    <p style="margin:0;font-size:14px;color:#555;font-style:italic;">{reading_rec['why']}</p>
  </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Georgia,serif;font-size:16px;line-height:1.75;color:#1a1a1a;max-width:600px;margin:0 auto;padding:40px 24px;">
  <div style="border-left:3px solid #1a1a1a;padding-left:20px;margin-bottom:36px;">
    <p style="margin:0;font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#888;">Public Record — Writing Coach</p>
  </div>
  {body}
  {metrics_html}
  {reading_html}
  <div style="margin-top:48px;padding-top:20px;border-top:1px solid #e0e0e0;font-size:13px;color:#999;">
    Reply with your next draft.
  </div>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# CORE COACHING LOGIC
# ─────────────────────────────────────────────────────────────

def build_memory_context(session_log: list) -> str:
    if not session_log:
        return "No previous sessions. This is the first session."
    
    memory = "MEMORY FROM PREVIOUS SESSIONS:\n"
    for row in session_log[-4:]:
        if len(row) >= 5:
            memory += f"- {row[0]} | '{row[1]}' | Patterns: {row[3]} | {row[4]}\n"
            if len(row) > 5 and row[5]:
                memory += f"  Metrics: {row[5]}\n"
    return memory


def get_coaching_response(draft_text: str, session_log: list) -> dict:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    memory = build_memory_context(session_log)
    metrics = compute_metrics(draft_text)
    metrics_summary = f"Scene ratio: {metrics.get('scene_ratio_pct', 0)}%, Qualifiers/500: {metrics.get('qualifier_per_500', 0)}, Variety SD: {metrics.get('sentence_variety_sd', 0)}, Proper nouns/500: {metrics.get('proper_nouns_per_500', 0)}, Opening strong: {metrics.get('opening_strong')}, Closing strong: {metrics.get('closing_strong')}"

    system_prompt = f"""You are Sagar Menon's personal writing coach with full memory of his history.

{COACHING_CONTEXT}

{memory}

COMPUTED METRICS FOR THIS DRAFT:
{metrics_summary}

COACHING INSTRUCTIONS:
- Whiplash coach. Direct, specific, demanding. No cheerleading.
- Reference his actual published work AND session history when relevant.
- Reference the computed metrics where they illuminate a specific problem.
- If a pattern repeats from previous sessions, name it explicitly and escalate pressure.
- Structure with these exact headers:

**ONE-LINE OVERALL READ**
[one honest sentence — no hedging]

---

**WHAT'S WORKING**
[max 3 points — specific lines, specific reasons]

---

**WHAT'S BROKEN**
[name weakness codes W1-W7, specific fixes, reference metrics where relevant]

---

**THE ENDING**
[always address specifically]

---

**ONE INSTRUCTION**
[single concrete thing before next draft — not a list]

Under 650 words total.

End with on separate lines:
PATTERNS: [comma-separated weakness codes e.g. W1,W3]
SUMMARY: [one sentence for memory log]
DOMINANT_WEAKNESS: [single most important code e.g. W3]

— Your Coach"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Draft:\n\n{draft_text}"}]
    )
    
    full_response = message.content[0].text
    patterns = ""
    summary = ""
    dominant = "W3"
    clean_lines = []
    
    for line in full_response.split('\n'):
        if line.startswith("PATTERNS:"): patterns = line.replace("PATTERNS:", "").strip()
        elif line.startswith("SUMMARY:"): summary = line.replace("SUMMARY:", "").strip()
        elif line.startswith("DOMINANT_WEAKNESS:"): dominant = line.replace("DOMINANT_WEAKNESS:", "").strip()
        else: clean_lines.append(line)
    
    feedback = '\n'.join(clean_lines).strip()
    
    return {
        "feedback": feedback,
        "patterns": patterns,
        "summary": summary,
        "dominant_weakness": dominant,
        "metrics": metrics,
    }


def get_no_draft_response(reason: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=250,
        system=f"""You are Sagar Menon's writing coach. He hasn't sent a draft.
{COACHING_CONTEXT}
Be direct. Don't accept the excuse. Name the avoidance pattern. Redirect to the chawl visit essay or arranged marriage essay — whichever fits.
Under 100 words. Sign off: — Your Coach""",
        messages=[{"role": "user", "content": f"Sagar replied without a draft: \"{reason}\""}]
    )
    return message.content[0].text


def get_adaptive_prompt(session_log: list) -> dict:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    memory = build_memory_context(session_log)
    
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=350,
        system=f"""You are Sagar Menon's writing coach writing the weekly Sunday prompt.

{COACHING_CONTEXT}

{memory}

Write a short Sunday prompt (under 120 words) that:
- References last week's session if there is one
- Pushes on the most persistent weakness from recent history
- Gives one specific writing task
- Feels like it comes from a coach who knows his history, not a template

Format exactly:
SUBJECT: [subject line with emoji]
---
[prompt body]

— Your Coach""",
        messages=[{"role": "user", "content": "Write this week's Sunday prompt."}]
    )
    
    text = message.content[0].text
    subject = "🖊️ Writing Coach — Sunday"
    body = text
    
    if "SUBJECT:" in text and "---" in text:
        parts = text.split("---", 1)
        subject = parts[0].replace("SUBJECT:", "").strip()
        body = parts[1].strip()
    
    return {"subject": subject, "body": body}


# ─────────────────────────────────────────────────────────────
# WEBHOOK ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "coach v3 running", "writer": "Sagar Menon"}), 200


@app.route("/receive-draft", methods=["POST"])
def receive_draft():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    email_body = data.get("body", "").strip()
    sender = data.get("from", "")
    subject = data.get("subject", "")

    allowed = os.environ.get("SAGAR_EMAIL", "")
    if allowed and allowed.lower() not in sender.lower():
        return jsonify({"error": "Unauthorized"}), 403

    word_count = len(email_body.split())
    sheets = get_sheets_service()
    session_log = read_sheet(sheets, "Session Log!A2:H50") if sheets else []

    if word_count > 80:
        result = get_coaching_response(email_body, session_log)
        draft_title = re.sub(r"Re:|Writing Coach", "", subject).strip() or "Untitled"
        metrics = result.get("metrics", {})
        metrics_text = format_metrics_for_email(metrics)
        metrics_sheet_data = format_metrics_for_sheet(metrics)

        # Background thread: web search for rec + sheet logging (avoids Make.com timeout)
        def background_tasks(res=result, dt=draft_title, wc=word_count, ms=metrics_sheet_data):
            try:
                rec = get_live_reading_rec(res.get("dominant_weakness", "W3"), res.get("patterns", ""))
                if sheets:
                    rec_str = f"{rec.get('title', '')} by {rec.get('author', '')}" if rec else ""
                    row = [
                        datetime.now().strftime("%Y-%m-%d"),
                        dt, str(wc),
                        res.get("patterns", ""),
                        res.get("summary", ""),
                        ", ".join(ms),
                        rec_str,
                    ]
                    append_sheet(sheets, "Session Log!A:G", row)
                    if rec and rec.get("title"):
                        append_sheet(sheets, "Reading Queue!A:E", [
                            datetime.now().strftime("%Y-%m-%d"),
                            rec.get("title", ""), rec.get("author", ""),
                            rec.get("why", ""), "No"
                        ])
            except Exception as e:
                print(f"Background error: {e}")

        threading.Thread(target=background_tasks, daemon=True).start()
        html = markdown_to_html(result["feedback"], metrics_text, None)
        response_subject = f"Coach Feedback — {draft_title}"
    else:
        coaching = get_no_draft_response(email_body)
        html = markdown_to_html(coaching)
        response_subject = "No draft, Sagar."

    return jsonify({"subject": response_subject, "body": html}), 200


@app.route("/send-weekly", methods=["POST"])
def send_weekly():
    sheets = get_sheets_service()
    session_log = read_sheet(sheets, "Session Log!A2:H20") if sheets else []
    prompt = get_adaptive_prompt(session_log)
    
    return jsonify({
        "subject": prompt["subject"],
        "body": markdown_to_html(prompt["body"]),
        "to": os.environ.get("SAGAR_EMAIL", "")
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
