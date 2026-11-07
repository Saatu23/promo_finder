# Changes in v4 (final session, 7 Nov 2026)

What changed after running the full show on a new key and reading the top picks by hand.

## Models
- Gemini 2.5 Flash / Flash-Lite now return 404 for new keys, and `gemini-flash-latest` took ~2 min per call.
  Defaults are now `gemini-3.5-flash` (bible, propose, judge, plan) and `gemini-3.1-flash-lite` (cold viewer),
  with fallbacks `gemini-3-flash-preview` → `gemini-3.5-flash-lite`. Prices updated in `config.toml`.
- Fallback models no longer inherit a thinking budget: 3.5 Flash-Lite rejects `thinkingBudget: 0` with HTTP 400.

## Reliability (`promofinder/llm.py`)
- Only a 429 whose violated quotas are *all* per-day counts as "daily quota exhausted". Before, any 429 whose
  body mentioned a per-day quota switched the stage to a weaker model, likely after a per-minute limit.
- Retired models (404) are reported as "not available", not "daily quota exhausted".
- Resume works across fallbacks: before any call, the cache is checked for every model in the chain.
- Every fallback is printed to the log and recorded per stage in `run_summary.json`; `--check` shows the model
  that actually answered.

## Picking quality (`promofinder/pipeline.py`, `prompts.py`)
- The cold viewer reports `ended_unresolved`, and the judge reports `resolved_in_clip`. If either says the clip
  answers its own question, the cliffhanger sub-score is capped (`resolved_cliff_cap`). Result: top-10 promos
  with a resolved ending went from 4 to 0. A softer one-vote cap was tested and rejected (ranked recall 0.61 → 0.50).
- Judge and cold-viewer sub-scores become percentiles within the show before blending, so two models with
  different scales get equal say. Confidence = percentile agreement (ranked 40: 5 medium/35 low → 21 medium/19 low).
- Penalty when both scorers say a stranger would not follow the clip (`not_standalone_penalty`).
- Episode-1 funnel bonus raised from 0.4 to 0.8.
- The launch-plan prompt sees "ending resolves itself" / "strangers may not follow it" flags and is told to
  avoid them, and to use at most one promo from the final episodes.

## Bugs fixed
- A promo built entirely inside the continuation episode was labelled with the batch episode ('E06-4' played
  wholly in episode 7). It is now labelled where it plays, with an `x` id (`E07-x1`).
- The repair step counted promos the model re-sent after they had already passed as "repaired"
  (105 "repaired" from 32 failures). Re-sent promos are now skipped and counted separately.
- Rule failures are grouped by type ("hook later than 3s": 21) instead of one row per exact number.
- Streamlit app crashed on load (duplicate widget keys when a promo appears in two tabs); fixed. Replaced the
  deprecated `use_container_width`.

## Not fixed (see the solution doc)
- Batch-relative judging: the same clip scored 8/7/7/8 in one judge batch and 5/5/5/6 in another.
  Set `episodes_per_call = 1` on a paid key.
- Adjacent beats of one set piece can both rank high; the episode-1 altar reveal ranks #26.

## App redesign (same session, later)
- Calmer, plain-language look: light theme with a plum accent (`.streamlit/config.toml`), a 50 → 200 → 218 → 40 → 10
  flow strip instead of raw metrics, and tabs renamed "Post these first / All ranked promos / Every candidate /
  How it was made".
- Each clip is shown as a marked-up script page: green bar = first 3 seconds, highlighted hook line, red
  underline on the cut line, then a "cut at Ns" marker. Scores show as simple bars; confidence becomes
  "reviewers agree / mostly agree / disagree"; warnings become plain tags ("ending may answer itself").
- "How it was made" is now readable: a table of which model *actually* answered each step (with fallbacks
  explained), rule checks in one paragraph, and honest time and cost. A run served from cache now says so,
  and shows the 24-minute time of the first fresh run instead of "18 seconds".
- `run_summary.json` records calls per model for each stage.
- Locally, the app now reads `GEMINI_API_KEY` from `.env`, so you don't have to paste it each time.
- Larger, higher-contrast text (base 18px, darker greys) and a Text size choice in the sidebar.
- Sidebar simplified (Gemini or offline demo; no Advanced section). Text size now scales the root font instead of CSS zoom, which had cut off the bottom of the page. The launch-plan intro is written from the picks instead of the model's own strategy text.
- Promo cards restyled for easier reading: 'Opens on' / 'Cuts on' panels up top, varied type for details, cast names with muted roles, the stranger's reaction as a quote, and a script view with camera directions hidden by default.
- Simpler cards: Opens on / Cuts on, one line on why, the cut, scores and the viewer's open question; the script is behind a 'Read the script' switch; Approve/Reject is a two-option switch with a reason box only on Reject, and the decision shows as a check or cross in the card title. Fixed a bug where clicking Approve printed Streamlit's internal docs on the page.
- New look modelled on short-drama apps (ReelShort / DramaBox / Kuku TV): dark aubergine theme, the show as a title page, each promo as a 9:16 poster card (hook as on-screen caption, colour by kind of story), details in a pop-up with Approve/Reject and the script. Cards reflow to 4 or 3 per row at larger text sizes.
- Final look: light and plain (modelled on a clean consumer app): soft grey page, white cards, navy headings and buttons, a sand side panel with white cards; Merriweather headings, Catamaran text; text fixed at the large size (no size setting). Side panel reduced to: which show, which episodes, your key (or a no-key demo), Find promos.

## Web app moved to Flask
- The Streamlit app is replaced by a small Flask app (`webapp.py`, `templates/`, `static/style.css`).
- Home page shows only the show and the 10 promos to post first. Each promo has its own page: opens on / cuts on,
  why it works, where to cut, approve/reject. Scores, the viewer's question and the script are behind
  "More details" and "Read the script". Other pages: All promos (filter by story type), How it works,
  Try another show (runs in the background with a progress bar).
- Large, readable type (20px base), serif headings, navy and sand palette; works on phones.
- Deploy target is now Render (free) with gunicorn; see docs/DEPLOY.md.
- Any AI provider for live runs: "Try another show" now has an AI provider choice (Google Gemini, OpenAI,
  Anthropic Claude, GitHub Models, OpenRouter, Groq, or any OpenAI-compatible service with its address), an
  editable model name pre-filled per provider, and that provider's key. Gemini keeps its per-step models; other
  providers use the chosen model for every step.
- OpenAI-compatible calls now retry without a setting the provider refuses (newer OpenAI models reject a custom
  temperature) and remember that per model; Claude gets the output limit it requires; a rejected key gives a
  clear message. If every proposal call fails, the run stops with the provider's error instead of finishing empty.
- The answer cache now includes the service address, so the same model name at two services never shares answers.
- Model is now a dropdown of known model names per provider (recommended one first), with 'Another model (type its name)' for anything newer; 'Other' services still take a typed name.
