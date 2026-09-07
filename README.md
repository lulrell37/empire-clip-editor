# empire-clip-editor

R.O.G.U.E.'s clip-edit agent. Empire OS files a GitHub **issue** as the job;
a GitHub Actions workflow picks it up, edits the clip with **FFmpeg + Whisper +
one Claude planning pass**, uploads the result as a release asset, and comments
the finished link back on the issue.

Nothing here runs on a server. The queue *is* the issue tracker of this repo.

## The queue protocol

Empire OS (`src/services/buildAgent.js` → `fileClipJob`) opens an issue like:

```
Title:  CLIP: <first line of the brief>
Labels: rogue-clip

Body:
  R.O.G.U.E. wants this clip edited.

  **Source:** <media url>

  **Brief:**
  <edit direction>

  <!-- clip-job: {"media_url":"...","instructions":"..."} -->
  <!-- filed by Empire OS -->
```

The agent replies on the issue with HTML-comment markers that the app's
reconciler (`src/services/clipJobs.js`) scans for:

| Marker | Meaning |
| --- | --- |
| `<!-- clip-status: editing -->` | picked up, working |
| `<!-- clip-result: {"download":"<url>","share":"<url>"} -->` | done |
| `<!-- clip-failed: <short reason> -->` | gave up |

`media_url` may be a direct file link, a Google Drive share link, or a
YouTube / TikTok / Instagram / X URL.

## What it does

- Downloads the source (`yt-dlp` for social links, `gdown` for Drive, plain
  HTTP otherwise).
- Transcribes with `faster-whisper` (word-level timestamps).
- Asks Claude for an edit plan: which spans to keep, target length, aspect,
  caption style, whether to score it with music. Falls back to a sensible
  default plan when `ANTHROPIC_API_KEY` is not set.
- Cuts to the kept spans, reframes to vertical 9:16 (center-safe crop),
  burns in **static** captions built for the new timeline, and mixes a music
  bed if one was asked for and a matching track exists in `music/`.
- Publishes `out.mp4` as the asset of a `clip-<issue>` release and comments the
  download link back.

It does **clean cuts / captions / reframe / music** — not animated captions,
transitions, or motion graphics. Those get a human finish in CapCut.

## Setup

1. **`ANTHROPIC_API_KEY`** — repo secret (Settings › Secrets and variables ›
   Actions). Without it the planning pass is skipped and the whole clip is kept
   with a default reframe + captions.
2. **Actions enabled** with write permission (Settings › Actions › General ›
   Workflow permissions → *Read and write*). Needed so the agent can comment and
   cut releases. `GITHUB_TOKEN` is used automatically.
3. **Music (optional)** — drop `.mp3`/`.m4a` files in `music/` and describe each
   in `music/index.json` so the planner can match a vibe.

## Local test

```
pip install -r requirements.txt
GH_TOKEN=$(gh auth token) REPO=lulrell37/empire-clip-editor ISSUE_NUMBER=1 \
  ANTHROPIC_API_KEY=sk-ant-... python -m agent.run
```
