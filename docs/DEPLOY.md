# Deploy: GitHub + Render (free)

The web app opens on the saved run in `outputs/final/`, so it works with **no API key**. A key is only
needed for "Try another show". Locally the app reads `GEMINI_API_KEY` from `.env`.

## 1. Run it on your computer first

```bash
cd promo-finder
pip install -r requirements.txt
python webapp.py              # open http://localhost:5000
```

## 2. Keep the key out of git

```bash
git status --ignored      # .env should appear under "Ignored files"
```
Never commit `.env`. If a key was ever committed or pasted anywhere public, create a new one at
aistudio.google.com → API keys and delete the old one.

## 3. Push to GitHub

Create an empty repo on github.com (e.g. `promo-finder`, public, no README), then:
```bash
cd promo-finder
git init -b main
git add .
git commit -m "Promo Finder: microdrama promo finder (Kuku AI Generalist, Problem 1)"
git remote add origin https://github.com/<your-username>/promo-finder.git
git push -u origin main
```
Check on github.com that `outputs/final/`, `templates/`, `static/` and `data/` are there and `.env` is not.

## 4. Deploy on Render

1. Go to **render.com**, sign in with GitHub, click **New → Web Service**, and pick the `promo-finder` repo.
2. Settings:
   - Language: **Python 3**
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn webapp:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT`
   - Instance type: **Free**
3. Environment variables (optional, only for live runs). Add the key for whichever AI provider you use:
   `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `OPENROUTER_API_KEY`,
   `GROQ_API_KEY`, or `PROMO_API_KEY` for "Other". With a key set here, anyone with the link can start runs
   on your quota. For a public demo, leave them out; people can paste their own key on the
   "Try another show" page.
4. Click **Create Web Service**. The first build takes 2 to 3 minutes. Open the `.onrender.com` URL: you
   should see the show and its 10 "Post these first" promos.

Keep **one worker** (`--workers 1`). Live runs happen in a background thread and their progress is kept in
memory, so a second worker would not know about them.

## 5. Things to know about the free plan

| What happens | What to do |
|---|---|
| The app sleeps after 15 minutes without visitors and takes about a minute to wake up | Open the link a minute before a demo |
| Files written while it runs are lost when it restarts or sleeps: approve/reject decisions and live runs | Download the decisions CSV before you leave; the saved results in `outputs/final` are never lost |
| A full 50-episode live run takes 20 to 25 minutes | Keep the progress page open (it keeps the app awake), or run the full show from the command line and commit `outputs/final` |
| Live run fails with HTTP 404 | The model is retired: change `model` in `config.toml`; `python run.py --list-models` lists options |

Other hosts work the same way. Anything that runs `gunicorn webapp:app` (Railway, Fly.io, PythonAnywhere,
a VM) only needs the start command above. The included `Procfile` is picked up by hosts that read one.
