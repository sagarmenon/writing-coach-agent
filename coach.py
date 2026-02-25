"""
SAGAR'S WRITING COACH AGENT
============================
A Flask webhook server that:
1. Receives emails from Make.com (when Sagar replies with a draft)
2. Runs the draft through Claude with full coaching context
3. Sends back a detailed coaching response via Gmail

Deploy this on Railway.app (free) - see SETUP.md for full instructions.
"""

import os
import json
import base64
import anthropic
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# SAGAR'S PERMANENT COACHING CONTEXT
# This is baked in. Update it as your writing evolves.
# ─────────────────────────────────────────────────────────────

COACHING_CONTEXT = """
WRITER: Sagar Menon, 26, Bombay.
NEWSLETTER: Public Record on Substack. 22 confirmed articles across 4 years.
WORK: Founder of Mauka (communication education) and Citta (mental health for students).

═══ TIER RANKINGS (from full assessment) ═══
S-Tier: EdTech failing (Dec 2024), Building Depth (Apr 2025)
A-Tier: Building Agency, Building Taste, On Grief, Light keeper, PUC certificates,
        Menon's Principles, Biryani, a night at the hospital, How to be interesting,
        curiosity with no economic utility
B-Tier: Grass, Sparkle, Design, How to run, Confidence Needs Curiosity, Turtle, On Mentorship
C-Tier: Cookie, 3 questions (founder), Pants

═══ STRENGTHS (never undermine these) ═══
S1. THE SENTENCE — writes sentences that stop readers cold. Protect at all costs.
    Best examples: "Three minutes is appropriate to go into the past without spiraling."
    "Quick, the city says, nobody's looking. Nobody needs to know."
    "90s kids now have adult money and, more importantly, adult problems."

S2. FORMAL RANGE — can write in 6+ registers: analytical essay, timestamped vignette,
    city meditation, word-prompt essay, how-to, essay series. Rare at this stage.

S3. COUNTER-INTUITIVE OBSERVATION — consistently finds the unexpected flip of common wisdom.
    "Being interesting is the fortunate byproduct, not the goal."
    "Expert should only be a posthumous term."

S4. CULTURAL SPECIFICITY — writes India from the inside, without explaining it to outsiders.
    PUC uncle. Roti-kapda-iPhone. Babas filling the mental health gap. Never over-explains.

S5. EARNED PERSONAL ANCHOR — specific, unpretentious stories that ground abstract ideas.
    Father's notebook-of-questions exercise. Chawl visit in 8th grade (underused).

S6. DRY, POINTED HUMOR — never tries too hard, always has a point of view.

S7. STRUCTURAL ARCHITECTURE — thinks in skeletons, not just paragraphs.

═══ WEAKNESSES (push hard on these) ═══
W1. ENDINGS THAT DEFLATE — most pieces trail off with a summary or restatement.
    Rule: Never end with a recap. End with a resonance. Write 3 endings, pick the best.

W2. THESIS-STATEMENTS PUBLISHED AS FULL ESSAYS — Confidence Needs Curiosity (400w),
    On Mentorship (200w). 800 word minimum before any piece ships.

W3. SCENE-BUILDING AVOIDANCE — summarizes instead of inhabits moments.
    "a night at the hospital" proved he CAN do scene. Must do it deliberately now.
    The chawl visit (8th grade, PC under arm) has been summarized in one sentence for 3 years.

W4. WORD-ESSAY SERIES DILUTION — only publish word essays when the second-layer
    argument can be stated in one sentence BEFORE writing. Biryani/Grass/Sparkle pass.
    Cookie/Pants/Turtle don't.

W5. OVER-RELIANCE ON WESTERN CANON — Naval, Dalio, Paul Graham, Dewey, Bourdieu.
    PUC certificates piece cites no one and is one of the best pieces. Model this.

W6. INCONSISTENT PUBLISHING CADENCE — 22 articles in 4 years. Needs bi-weekly rhythm.

W7. REFLEX DISCLAIMERS — "This is my unsubstantiated theory." "Highly subjective."
    One disclaimer max, placed AFTER the argument, never before.

═══ ACTIVE COMMITMENTS ═══
- 800 word minimum before publishing
- One scene minimum in every personal essay
- Word essay only if second-layer argument stated in one sentence first
- No ending that recaps
- The chawl visit essay (full scene, not summary) — overdue
- The arranged marriage → communication essay — most important unwritten piece
- The full Confidence Needs Curiosity essay — thesis needs its body

═══ NOVEL (5-year horizon) ═══
Material is there. Sensibility is there. Two more years of scene-first essays needed
before starting. The novel is contemporary Bombay, follows someone building something
while private life quietly comes apart. The chawl visit is in it. The ICU corridor is in it.

═══ COACHING PHILOSOPHY ═══
- Be a whiplash coach, not a cheerleader
- Name the avoidance for what it is
- Specific > general always
- If the piece is good, say why specifically. If it's weak, say why specifically.
- Always end with ONE concrete instruction for the next draft or next session
- Never give generic writing advice — everything must be calibrated to Sagar's specific work
"""

# ─────────────────────────────────────────────────────────────
# WEEKLY PROMPTS — rotate through these
# ─────────────────────────────────────────────────────────────

WEEKLY_PROMPTS = [
    {
        "subject": "🖊️ Writing Coach — Sunday Check-In #1",
        "body": """Sagar.

It's Sunday. Here's your question for the week:

**The chawl visit essay.** You've been carrying this for three years. 
One sentence in Menon's Principles. That's all it's gotten.

This week I want you to write the first 200 words — scene only, no argument. 
Put yourself in that staircase. What did it smell like. 
What were you carrying. What did the kids look at first.

Reply to this email with whatever you wrote this week — draft, fragment, 
even just a paragraph. Or reply with what you didn't write and why.

I'll respond with coaching within a few hours.

— Your Coach"""
    },
    {
        "subject": "🖊️ Writing Coach — Sunday Check-In #2",
        "body": """Sagar.

Sunday again.

This week's question: What is the second-layer argument of whatever 
you're currently writing? State it in one sentence. Not what the piece 
is about — the non-obvious thing it arrives at.

If you can't state it, the piece isn't ready to write yet.

Reply with your draft, fragment, or what stopped you this week.

— Your Coach"""
    },
    {
        "subject": "🖊️ Writing Coach — Sunday Check-In #3",
        "body": """Sagar.

Week three.

The arranged marriage → communication essay. You've mentioned this 
observation in at least two pieces and never written it. 

This week: just write the opening scene. One Mauka classroom session. 
One student. One specific moment where the communication gap became visible 
and you understood where it came from.

Don't write the argument yet. Just the scene.

Reply with whatever you have — draft, resistance, both.

— Your Coach"""
    },
    {
        "subject": "🖊️ Writing Coach — Sunday Check-In #4",
        "body": """Sagar.

Month one check-in.

You committed to: 800 word minimum, one scene per personal essay, 
no endings that recap, word essays only with a stated second-layer argument.

How many of those held this month? Be specific — which pieces, which rules broke.

Reply with your draft and your honest audit.

— Your Coach"""
    },
    {
        "subject": "🖊️ Writing Coach — Sunday Check-In #5",
        "body": """Sagar.

This week I want you to write zero frameworks.

No 'there are three things.' No numbered lists. No 'here's how to X.'
Just one scene, 600 words, from your life in the last seven days.
The more ordinary the better. You showed what you can do with a PUC uncle.
Do it again with something from this week.

Reply with the scene.

— Your Coach"""
    },
    {
        "subject": "🖊️ Writing Coach — Sunday Check-In #6",
        "body": """Sagar.

The Confidence Needs Curiosity essay. You published the thesis. 
400 words. Called it done.

This week: write the middle. Three specific people in three specific 
rooms where you watched someone try to perform confidence without 
the curiosity underneath it. What happened. What their face looked like. 
What you couldn't fix.

The essay is in those three moments. Everything else is connective tissue.

Reply with your draft.

— Your Coach"""
    },
    {
        "subject": "🖊️ Writing Coach — Sunday Check-In #7",
        "body": """Sagar.

Seven weeks in.

One question this week, and I want a real answer:

What piece are you most afraid to write? Not the hardest — the most afraid.
There's a difference. The hardest piece is the one you don't know how to do yet.
The piece you're afraid of is the one you know exactly how to do 
and haven't started because of what it will cost you.

Name it. Then reply with whatever you wrote this week.

— Your Coach"""
    },
    {
        "subject": "🖊️ Writing Coach — Sunday Check-In #8",
        "body": """Sagar.

Two months.

Read your two best pieces back to back — EdTech failing and PUC certificates.
Notice the difference in what they're doing formally. One argues. One inhabits.
Both work. Neither approach is your default — they're both choices you made deliberately.

This week: make a deliberate choice about what your current draft needs.
State the choice at the top of your reply. Then paste the draft.

— Your Coach"""
    },
]


def get_weekly_prompt(week_number: int) -> dict:
    """Rotate through weekly prompts based on week number."""
    idx = (week_number - 1) % len(WEEKLY_PROMPTS)
    return WEEKLY_PROMPTS[idx]


def get_coaching_response(draft_text: str, sender_note: str = "") -> str:
    """
    Send draft to Claude with full coaching context.
    Returns coaching feedback as formatted text.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    system_prompt = f"""You are Sagar Menon's personal writing coach. 
You have a full, detailed assessment of his writing built from reading all 22 of his published essays.

Here is your complete coaching brief — read it carefully before responding:

{COACHING_CONTEXT}

COACHING INSTRUCTIONS:
- You are a whiplash coach, not a cheerleader. Be direct, specific, demanding.
- Every note must reference his actual work — not generic writing advice.
- Name the avoidance patterns by their names from the assessment (W1, W2, etc.)
- When something is genuinely good, say why specifically. Don't just praise.
- Structure your response: 
  1. ONE-LINE OVERALL READ (honest, no hedging)
  2. WHAT'S WORKING (specific lines, specific reasons — max 3 points)
  3. WHAT'S BROKEN (specific problems, specific fixes — be demanding)
  4. THE ENDING (always address the ending specifically)
  5. ONE INSTRUCTION (single concrete thing to do before the next draft)
- Keep total response under 600 words. Tight. No padding.
- End with a single, specific instruction. Not a list. One thing.
- Sign off as: — Your Coach"""

    user_content = f"""Here is Sagar's draft this week.

{"Sagar's note: " + sender_note if sender_note else ""}

DRAFT:
{draft_text}

Give me your coaching response. Be specific. Be demanding. Reference his actual work where relevant."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}]
    )

    return message.content[0].text


def get_no_draft_response(reason: str = "") -> str:
    """Response when Sagar replies but sends no draft — just an excuse."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    system_prompt = f"""You are Sagar Menon's writing coach. 
He has not sent a draft this week. He has sent a reason or excuse instead.

Your coaching brief:
{COACHING_CONTEXT}

Be direct. Don't accept the excuse. Name the avoidance. 
Redirect him to the specific piece he committed to.
Keep it under 150 words. No warmth. Just the redirect.
Sign off as: — Your Coach"""

    user_content = f"""Sagar replied without a draft. Here's what he said:

"{reason}"

Respond as his coach."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}]
    )

    return message.content[0].text


# ─────────────────────────────────────────────────────────────
# WEBHOOK ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "coach is running", "writer": "Sagar Menon"}), 200


@app.route("/receive-draft", methods=["POST"])
def receive_draft():
    """
    Called by Make.com when Sagar replies to the weekly email.
    Expects JSON: { "body": "...", "from": "...", "subject": "..." }
    Returns coaching feedback that Make.com will send back as email.
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data received"}), 400

    email_body = data.get("body", "").strip()
    sender = data.get("from", "")
    subject = data.get("subject", "")

    # Security: only accept from Sagar's email
    allowed_email = os.environ.get("SAGAR_EMAIL", "")
    if allowed_email and allowed_email.lower() not in sender.lower():
        return jsonify({"error": "Unauthorized sender"}), 403

    # Detect if this is a draft or an excuse
    word_count = len(email_body.split())
    has_substantial_content = word_count > 80

    if has_substantial_content:
        # Looks like a real draft — coach it
        coaching = get_coaching_response(email_body)
        response_subject = f"Re: {subject} — Coach Feedback"
    else:
        # Short reply — probably an excuse or check-in without draft
        coaching = get_no_draft_response(email_body)
        response_subject = f"Re: {subject} — No draft, Sagar."

    return jsonify({
        "subject": response_subject,
        "body": coaching,
        "word_count_received": word_count
    }), 200


@app.route("/send-weekly", methods=["POST"])
def send_weekly():
    """
    Called by Make.com on a schedule (every Sunday).
    Returns the weekly prompt email content.
    """
    data = request.get_json() or {}
    week_number = data.get("week_number", 1)

    prompt = get_weekly_prompt(week_number)

    return jsonify({
        "subject": prompt["subject"],
        "body": prompt["body"],
        "to": os.environ.get("SAGAR_EMAIL", ""),
        "week_number": week_number
    }), 200


@app.route("/custom-prompt", methods=["POST"])
def custom_prompt():
    """
    For when you want a specific coaching prompt sent —
    not the weekly rotation. Call this manually when needed.
    Body: { "draft": "...", "note": "optional context" }
    """
    data = request.get_json()
    draft = data.get("draft", "")
    note = data.get("note", "")

    if not draft:
        return jsonify({"error": "No draft provided"}), 400

    coaching = get_coaching_response(draft, note)
    return jsonify({"feedback": coaching}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
