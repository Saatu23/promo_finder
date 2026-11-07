"""All prompts in one file so they can be reviewed, versioned and A/B tested."""

PROMO_DEFINITION = """\
A PROMO is a 20-60 second clip cut from the show itself and posted on Instagram Reels, TikTok or
YouTube Shorts to pull NEW viewers into the show. It is unedited footage: no music, no text overlays,
no reordering inside a segment. It is usually one continuous stretch, but may join 2-3 moments
(in story order) from one episode or across episodes.
A great promo:
 1. HOOK - something in the FIRST 3 SECONDS makes a scrolling viewer stop: a slap, a shocking line,
    a reveal, a humiliation, a threat, a striking image. Not a slow establishing shot or small talk.
 2. CLIFFHANGER - it CUTS at an unresolved moment so the viewer must know what happens next
    (a question left hanging, a threat about to land, a reveal just before the reaction, a door opening).
    Never include the answer or resolution. Cutting one line early is often what makes it work.
 3. STANDALONE - it makes sense to someone who has never seen the show: who is hurting whom and what
    is at stake are clear from the clip itself. Avoid clips that lean on earlier episodes, unexplained
    names, or inside references.
Think like the editors of ReelShort / DramaBox ads: high emotion, clear power dynamics
(humiliated heroine, cruel family, secret powerful husband), and a question the viewer can't ignore."""

TROPES = ["betrayal", "humiliation", "comeback", "protector", "romance", "villain_scheme",
          "reveal", "danger", "sacrifice"]

# --------------------------------------------------------------------------- bible
BIBLE_SYSTEM = "You are a script coordinator building a character bible for a vertical microdrama series. Reply with JSON only."

BIBLE_PROMPT = """\
Below is a compact transcript of a series (loglines + dialogue only). Speaker labels are inconsistent:
the same person may appear under a description early on (e.g. "LADY IN GOLD GOWN") and a name later.

TASK
1. Map EVERY speaker label listed under SPEAKER LABELS to one canonical character name.
   Use the name the show eventually reveals. If a label is a generic one-off (e.g. "GUARD"), map it to itself.
2. For each main character give a role a stranger would understand in <=12 words
   (e.g. "Juliana's cruel sister who stole her fiance").
3. List the major twists/reveals with the episode where each is revealed (used to avoid spoiler promos).
4. Write a one-line premise a viewer of an ad would grasp.

Reply as JSON:
{{"premise": str,
  "characters": [{{"name": str, "role": str, "labels": [str, ...]}}],
  "reveals": [{{"episode": int, "reveal": str, "spoiler_level": "low"|"medium"|"high"}}]}}

SPEAKER LABELS (label: episodes where it appears)
{labels}

TRANSCRIPT
{transcript}"""

# ------------------------------------------------------------------------ propose
PROPOSE_SYSTEM = ("You are a senior performance-marketing editor for a microdrama app. You find the moments in "
                  "screenplays that make the best paid-social promos. Reply with JSON only.")

PROPOSE_PROMPT = """\
{definition}

SHOW CONTEXT (for your understanding only - a new viewer knows none of this)
Premise: {premise}
Characters: {characters}
Before these episodes: {prev_logline}

THE SCRIPT
Every line has an ID like [{ep}:012] (episode:line), a time span within its episode (MM:SS.ss) and its
content. CAMERA/ACTION/SFX lines are what is on screen; quoted lines are spoken dialogue.
Times restart at 00:00 in every episode.
{blocks}

TASK
For EACH episode marked "(find promos here)" - episodes {targets} - find the {n} best DISTINCT promos whose
main moment is in that episode. A segment may run into the start of the next episode, or a promo may join
moments in story order, when that makes a stronger promo.
Rules (code will check them):
- Refer to lines ONLY by their IDs. Do not write timestamps - code computes them from the IDs.
- Each segment runs from start_ref to end_ref inclusive. Total length of all segments: 20-60 seconds
  (aim for 25-45s). Use the time spans to estimate. Segments must be in story order and not overlap.
- hook_ref = the line that stops the scroll; it must start within the first 3 seconds of the clip, so the
  first segment should start AT or just before it (it is fine to start in the middle of a scene).
- cliffhanger_ref = the last line of the clip: an unresolved beat. Cut BEFORE the reply / reaction /
  resolution. If the episode itself resolves the beat, end earlier.
- Prefer promos a stranger understands. Different promos should use different moments.

Reply as JSON:
{{"promos": [{{
  "episode": <episode number this promo belongs to>,
  "title": "3-6 word label",
  "segments": [{{"start_ref": "{ep}:000", "end_ref": "{ep}:000"}}],
  "hook_ref": "{ep}:000",
  "hook": "what the viewer sees/hears in the first 3 seconds",
  "cliffhanger_ref": "{ep}:000",
  "cliffhanger": "the unanswered question the viewer is left with",
  "why": "one line on why this works as a promo",
  "trope": one of {tropes},
  "context_risk": "what a new viewer might not understand, or 'none'"
}}]}}"""

REPAIR_PROMPT = """\
Code checked your promos against the rules and some FAILED. Fix each failed promo by choosing different
line IDs (do not write timestamps), or drop it if it cannot be fixed. Keep the promos that passed out of
your reply.

FAILED PROMOS AND WHY
{failures}

Remember: total 20-60s; the hook line must start within 3s of the clip start; end on the unresolved beat;
segments in story order.
Reply as JSON in the same schema: {{"promos": [...]}}"""

# -------------------------------------------------------------------------- blind
BLIND_SYSTEM = ("You are a typical 25-40 year old scrolling short videos on your phone. You have NEVER heard of "
                "this show. Be honest and a bit impatient. Reply with JSON only.")

BLIND_PROMPT = """\
A video autoplays in your feed. Below is exactly what it shows, second by second
(speaker labels are just for reading; you only hear voices and see faces).

FIRST 3 SECONDS:
{first3}

FULL CLIP ({duration:.0f}s):
{clip}

Answer honestly as a viewer who knows nothing else:
{{"stopped_scrolling": 1-10 (would the first 3 seconds alone stop your thumb?),
  "understood": 1-10 (do you get who is who and what is at stake?),
  "need_to_know": 1-10 (how badly do you need to know what happens next?),
  "what_happened": "one sentence in your words",
  "ended_unresolved": true/false (true ONLY if it cut while something was still about to happen or be answered;
                      false if the last moment was a reply, a resolution, someone leaving, or a finished speech),
  "open_question": "the question in your head when it cut, or 'none' if it felt finished",
  "confused_by": ["anything that made no sense without more context"],
  "would_tap": true/false (would you tap through to watch the show?)}}"""

# -------------------------------------------------------------------------- judge
JUDGE_SYSTEM = ("You are the head of creative at a microdrama app reviewing promo cuts before ad spend. You are "
                "strict: most cuts are average. Reply with JSON only.")

JUDGE_PROMPT = """\
{definition}

Show premise: {premise}
Known later twists (spoilers): {reveals}

SCRIPTS (dialogue and action, for reference)
{script}

PROMO CUTS TO REVIEW. Each shows the exact clip, plus a report from a cold test viewer who never saw the show.
{promos}

Score each cut 1-10 on this anchored scale (5 = an average usable promo, 8 = would put real spend behind it,
10 = best in the show; most cuts should land 4-7):
- hook: do the first 3 seconds stop the scroll?
- cliffhanger: does it cut on an unresolved, must-know beat (not after the answer)?
- standalone: does a stranger get it? Weigh the test viewer's confusion heavily.
- emotion: intensity of the conflict / payoff.
- spoiler: 0 = none, 1 = mild, 2 = gives away a twist that would hurt the show.
- resolved_in_clip: true if the clip ALREADY contains the answer to the question it raises (the threat lands
  and is dealt with, the villain flees, the speech finishes on its point, the reply is heard). A resolved clip
  can score at most 4 on cliffhanger, however dramatic it is.
Also rank the cuts against each other (1 = best) and rewrite hook / cliffhanger / why to be precise.

Reply as JSON:
{{"reviews": [{{"id": str, "hook": int, "cliffhanger": int, "standalone": int, "emotion": int,
  "spoiler": int, "resolved_in_clip": bool, "rank_in_episode": int, "hook_text": str, "cliffhanger_text": str,
  "why": "<=25 words on why it works", "weakness": "<=15 words, the main risk"}}]}}"""

# --------------------------------------------------------------------------- plan
PLAN_SYSTEM = ("You are the growth lead for a microdrama app planning which promos to post first for a new show. "
               "Reply with JSON only.")

PLAN_PROMPT = """\
Show premise: {premise}
New viewers who tap a promo usually start at EPISODE 1, so early-episode promos match what they see next;
late-episode promos can spoil twists. You test several promos in parallel and scale the winners.

TOP PROMOS BY SCORE
{promos}

Do not choose promos marked ENDING RESOLVES ITSELF or STRANGERS MAY NOT FOLLOW IT unless nothing else is left.
Promos from the last few episodes risk spoiling the ending: use at most one, and only if spoiler is 0.
Choose the first {k} to post and their order. Balance proven strength (score), variety of hooks/tropes
(so the test tells you what this audience responds to), and funnel fit. Explain briefly.
Reply as JSON:
{{"strategy": "2-3 sentences",
  "order": [{{"id": str, "reason": "<=20 words"}}]}}"""
