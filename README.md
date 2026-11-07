# Promo Finder

Reads microdrama screenplays and finds the best **20-60 second promos** in them: clips that open on a
scroll-stopping hook in the first 3 seconds, cut on an unresolved cliffhanger, and make sense to someone
who has never seen the show. For each promo it gives the episode and start/end timestamps of every segment
(in order), the hook, the cliffhanger, one line on why it works, a score, and a ranked "post these first" plan.

Built for the Kuku AI Generalist assignment, Problem 1.

## Run it (2 minutes)

```bash
pip install -r requirements.txt            # requests, flask, gunicorn
echo "GEMINI_API_KEY=your_key" > .env      # free key: aistudio.google.com -> Get API key

python run.py data/i-married-a-broken-soldier --out outputs/final   # full 50-episode show, ~15-30 min on the free tier
python eval/evaluate.py outputs/final                                # quality report -> outputs/final/eval.md
python webapp.py                     # then open http://localhost:5000 to browse, approve/reject
# "Try another show" in the web app runs a new show on Gemini, OpenAI, Claude, GitHub Models,
# OpenRouter, Groq, or any OpenAI-compatible service: pick the provider, check the model, paste the key.
```

Run it on any new show: `python run.py path/to/new_show.zip` (a folder, a .zip or single .txt files all work).
No key? `python run.py data/i-married-a-broken-soldier --provider mock` runs the whole pipeline offline.

If the free daily quota runs out partway through, run the same command again later: every model reply is
cached in `.cache/`, so finished calls are free and the run resumes where it stopped (a rerun reuses whichever
model in the fallback chain answered last time). Within a run, a stage whose model hits its *daily* quota, or
whose model is retired (HTTP 404), switches to the next model in `fallback` and says so in the log.

**Models (Nov 2026).** Gemini 2.5 Flash / Flash-Lite return 404 for new keys, so the defaults are
`gemini-3.5-flash` (bible, propose, judge, plan) and `gemini-3.1-flash-lite` (cold viewer). The free tier allows
only ~20 requests/day on 3.5 Flash, so a full show on a free key will finish on the fallbacks
(3 Flash preview, then 3.5 Flash-Lite); `run_summary.json` lists every model each stage actually used.

## Swap the model (one setting)

Every model call goes through `promofinder/llm.py`. Per-stage models live in `config.toml`, or override
all stages from the command line:

```bash
python run.py SHOW --model gemini-3-flash-preview                                    # another Gemini model
python run.py SHOW --provider openai --model gpt-4.1 \
      --base-url https://api.openai.com/v1 --api-key-env OPENAI_API_KEY             # any OpenAI-compatible API
python run.py --list-models                                                          # what your Gemini key can use
```

## How it works

```
screenplays (.txt)
  │  parser.py      [code]  scenes + 3,700 timed events; every line gets an ID like 5:024
  ▼
show bible          [AI x1] maps inconsistent speaker labels ("LADY IN GOLD GOWN" = Clarissa), premise, spoiler list
  ▼
propose             [AI]    per batch of episodes: 4 promo candidates each, as LINE IDs, never timestamps
  ▼
validate + repair   [code]  IDs -> exact times, cuts snapped to shot boundaries without chopping a spoken line,
                            20-60s, hook line inside the first 3s, cliffhanger is the last beat, the answer line
                            does not leak in; failures go back to the model once with the exact error
  ▼
cold-viewer test    [AI]    a separate cheap call sees ONLY the clip (no show context) and reports what it
                            understood, what confused it and whether it would tap through
  ▼
judge               [AI]    anchored 1-10 rubric (hook, cliffhanger, standalone, emotion, spoiler) with the
                            cold-viewer report attached
  ▼
score + rank        [code]  weighted score, spoiler/warning penalties, small early-episode bonus, de-duplication
                            and diversity (episodes, tropes); confidence = judge vs cold-viewer agreement
  ▼
launch plan         [AI x1] which promos to post first and why
  ▼
outputs + app       [human] editor approves/rejects in the web app; decisions export as CSV
```

Design choices that matter:
- **The model never writes a timestamp.** It names line IDs and code computes every number, so timestamps
  cannot be hallucinated and every cut lands on a clean shot boundary.
- **Standalone is tested, not asserted.** The cold-viewer call has no show context, like a real stranger.
- **Rules are enforced in code, then the model gets one chance to fix its own mistakes.**
- **Cheap where it can be:** the cold-viewer test runs on Flash-Lite; propose/judge are batched.
- **Two scorers, one scale.** Judge and cold-viewer sub-scores are converted to percentiles within the show
  before blending, because the two models use the 1-10 scale very differently. Confidence = how closely they agree.
- **A clip that answers its own question is not a cliffhanger.** If the judge or the cold viewer says the
  ending resolves, the cliffhanger sub-score is capped. If both say a stranger would not follow it, it is penalised.

## Quality on the sample show (`outputs/final/eval.md`)

| | tool | keyword baseline |
|---|---|---|
| reference promos found (18 hand-checked, 12 episodes) | 18/18 | 14/18 |
| ... cut like an editor would (start and end within 3s) | 7/18 | 2/18 |
| ... that made the ranked top 40 | 11/18 | - |
| top 10 whose ending resolves itself (v3 config: 4/10) | 0/10 | - |

Known weak spots are in the solution doc: batch-relative judging, a cold viewer that calls half of all clips
"finished", and adjacent beats of one set piece both ranking high.

## Outputs (`outputs/<run>/`)

| file | what |
|---|---|
| `promos_ranked.csv` / `.json` | ranked promos: segments with episode + start/end, hook, cliffhanger, why, scores, confidence |
| `launch_plan.json` | the first promos to post, in order, with reasons |
| `report.md` | human-readable version of the above |
| `candidates_all.json` | every proposal that passed the code checks, incl. duplicates and lower-ranked ones |
| `show_bible.json` | character alias map, premise, spoiler list |
| `llm_calls.jsonl` | every raw prompt and model reply (unedited) |
| `run_summary.json` | counts, rule-failure stats, tokens and estimated cost per stage |
| `eval.md` / `eval.json` | quality evaluation (after `eval/evaluate.py`) |

## Tests

```bash
python tests/test_core.py
```

## Layout

```
run.py            command line          webapp.py         web app (Flask): templates/, static/
config.toml       models, weights       promofinder/      parser, llm, prompts, validate, pipeline, report, heuristic
eval/             reference promos + evaluation script    data/             the 50-episode input pack
docs/             solution PDF, video script, deploy steps, changelog
outputs/final/    the submitted run      outputs/first-run-before-fixes/   same candidates, v3 scoring (for comparison)
```
