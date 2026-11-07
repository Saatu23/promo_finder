# Promo Finder: 3-minute walkthrough script

About 430 spoken words, roughly 2:50 at a relaxed pace. **[Screen]** = what to show, then what to say.
Record with the deployed web app in one tab and the repo (or `outputs/final/`) in another.

---

### 0:00-0:20 · The problem
**[Screen]** The brief (Problem 1), then the sample show folder: 50 episode files.

> Every week a new microdrama ships, and today an editor watches every episode to pick promo moments for
> Instagram, TikTok and YouTube. I built Promo Finder for Problem 1. It reads the screenplays and returns
> ready-to-cut promos: episode, exact start and end times, the hook, the cliffhanger, and why it works.
> This show has 50 episodes and about 100 minutes of content.

### 0:20-1:05 · How it works
**[Screen]** README pipeline diagram (or the table on page 1 of the solution doc).

> The key idea is a split. AI judges drama, and code does every number.
> The model never writes a timestamp. It names line IDs like "5 colon 24", and code turns those into exact cut
> points, snapped to shot boundaries so we never chop a spoken line. Code then checks the rules: 20 to 60
> seconds, hook inside the first 3 seconds, the clip ends on the cliffhanger, and the next line doesn't give
> the answer away. Anything that fails goes back to the model once with the exact error.
> Then two separate checks. A cheap "cold viewer" model sees only the clip, no show context, like a stranger
> scrolling. A judge model scores the clip on a rubric. Code blends the two, ranks the promos, and a final
> call plans which ten to post first. A human approves in the app.

### 1:05-1:55 · Demo
**[Screen]** The web app's home page: the show and its 10 "Post these first" cards. Click #3, "Stripped of Everything".

> The home page only shows what an editor needs: the ten promos to post first, in order. Each card says what it
> opens on. Open one and you get the cut: episode 5, 15.8 to 58.5 seconds. It opens on "Your dowry is revoked.
> Your inheritance is revoked." and cuts as her dead mother's ledger lands in the mud. If you want more, "More
> details" has the scores and what a first-time viewer was left wondering, and "Read the script" shows the clip.

**[Screen]** Click **Approve**; go back (the card now says Approved); reject another with a reason; open "All promos" and filter by story type.

> The editor approves or rejects with a reason, and the decisions export as a CSV.
> Confidence tells you whether the judge and the stranger agreed.

**[Screen]** "How it works" page.

> The whole show is 276 model calls: about four dollars eighty at list price on Gemini 3.5 Flash, or about ten
> cents an episode, and around 24 minutes on a free key.

### 1:55-2:40 · Is it good? Honest results
**[Screen]** `outputs/final/eval.md`, then page 2 of the solution doc.

> I checked it against 18 reference promos across 12 episodes. The tool found all 18; a keyword baseline found 14.
> Seven came out cut almost exactly as an editor would, versus two for the baseline.
> Reading the first run's top picks myself, the number-one promo was a speech that finishes. The judge scored it
> 8 for cliffhanger while its own note said the speech resolves. So now both models answer a yes/no question:
> does the clip answer its own question? If so, code caps the score. Resolved endings in the top ten went from 4 to 0.
> Where it still picks badly: the same clip scores differently depending on which episodes it's judged alongside,
> two of the top picks are back-to-back beats of one scene, and the episode-1 betrayal ranks too low.

### 2:40-3:00 · Close
**[Screen]** `config.toml` models section; then `python run.py new_show.zip`.

> Models are one line in the config, so any Gemini or OpenAI-compatible model plugs in. For a new show,
> it's one command. Next I'd judge one episode per call and calibrate the weights on real click-through.
> Thanks for watching.

---

**Recording tips:** zoom the browser to about 110%; keep the eval table and doc
page 2 open in tabs before you start; one take per section is fine. Cut the "Run stats" beat if you run long.
