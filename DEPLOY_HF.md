# Deploying the catalog to Hugging Face Spaces

The app is a passcode-gated Streamlit app. It runs on a **public URL**, but no
one can see the catalog without the passcode you set. This guide takes you from
this local folder to a live, restricted Space.

## 0. Prerequisites

- A Hugging Face account (https://huggingface.co/join).
- Git installed, and this folder already initialized as a git repo (it is — see
  step 4 to confirm what will be committed).
- The repo already contains the runtime files: `streamlit_app.py`,
  `requirements.txt`, `README.md` (with the HF YAML frontmatter at the top),
  `.streamlit/config.toml`, `src/`, and the bundled `data/catalog.db` +
  `data/assets/`.

## 1. Create the Space

1. Go to https://huggingface.co/new-space.
2. **Owner / Space name**: pick a name, e.g. `aip-crop-catalog`.
3. **License**: your choice (e.g. `other`).
4. **Select the SDK**: choose **Streamlit**.
5. **Space hardware**: the free CPU basic tier is enough.
6. **Visibility**: you may choose **Public** (the passcode gate is what restricts
   access) or **Private** (only you / your org can open it at all — belt and
   suspenders). See step 6 for sharing.
7. Click **Create Space**. Note the git remote URL it shows, e.g.
   `https://huggingface.co/spaces/<your-username>/aip-crop-catalog`.

## 2. Confirm what will be committed (do this BEFORE adding the remote)

From this folder:

```bash
git status
git ls-files | sort
```

Verify the list **does NOT** include any of:

- `data/cache/**`  ← the 352 MB ADM file and brochure blobs (gitignored)
- `.streamlit/secrets.toml`  ← your real local passcode (gitignored)
- `.venv/**`  ← the virtualenv (gitignored)
- `output/*.xlsx`  ← regenerated exports (gitignored)

It **should** include: `streamlit_app.py`, `requirements.txt`,
`requirements-pipeline.txt`, `README.md`, `.gitignore`, `.streamlit/config.toml`,
`.streamlit/secrets.toml.example`, `DEPLOY_HF.md`, everything under `src/`,
`data/catalog.db`, `data/assets/*`, `data/seed/*`, and `tests/`.

If anything unexpected is staged, fix `.gitignore` and re-check before pushing.

## 3. Add the Hugging Face remote

```bash
git remote add hf https://huggingface.co/spaces/<your-username>/aip-crop-catalog
```

You will authenticate with your HF username and a **write access token** (create
one at https://huggingface.co/settings/tokens) as the password when prompted.

## 4. Push

```bash
git push hf main
```

(If your default branch is `master`, use `git push hf master:main`.)

The Space will build from `requirements.txt` and start `streamlit_app.py`
automatically (from the `app_file:` line in the README frontmatter). Watch the
**Logs** tab on the Space page for the build.

## 5. Set the passcode secret (REQUIRED — the app blocks until you do)

The passcode is never in the code. Set it on the Space:

1. On the Space page, open **Settings → Variables and secrets**.
2. Add a **Secret** (not a public variable):
   - **Name**: `APP_PASSCODE`
   - **Value**: a strong passcode you share only with the intended people.
3. Save. The Space restarts and the gate will now accept that passcode.

> Alternatively you can provide a Streamlit-style secret named `app_passcode`,
> or a `[passcodes]` table for multiple named users — the app reads all of them.
> `APP_PASSCODE` is the simplest.

## 6. Share with specific people

- **Simplest (public Space + passcode):** send the Space URL and the passcode
  only to the people who should have access. Anyone without the passcode sees
  only the gate. Rotate the passcode any time by editing the `APP_PASSCODE`
  secret.
- **Stronger (private Space):** in **Settings → Change visibility**, set the
  Space to **Private**, then invite individuals or your org under the Space's
  access controls. Now only invited HF accounts can even load the page, and the
  passcode gates it on top.

## 7. Updating later

Commit changes locally and `git push hf main` again — the Space rebuilds. Data
refreshes (new `data/catalog.db`) are just another commit; the app caches on the
DB file's mtime, so a new DB invalidates the cached map/tables automatically.

---

**Security recap:** the real passcode lives only in the HF secret / your local
gitignored `.streamlit/secrets.toml`. `data/cache/` (incl. the 352 MB ADM file)
and the real secrets file are gitignored and never pushed. Confirm with
`git ls-files` (step 2) before every push.
