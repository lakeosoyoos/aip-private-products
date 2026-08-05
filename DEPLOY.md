# Deploy the app on Streamlit Community Cloud

Free hosting for the passcode-gated Streamlit app. Streamlit Cloud deploys from a
**GitHub repo** and rebuilds automatically whenever you push. All the data the app
serves (`data/catalog.db`, `data/assets/`) is committed; the scraper cache and the
352 MB ADM file are gitignored and never pushed.

## 1. Put the repo on GitHub

Create an empty repo at <https://github.com/new> (private is fine — Streamlit Cloud
can deploy from private repos). Then, from `~/Desktop/aip_products`:

```bash
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push origin main
```

GitHub will prompt for your username and a **personal access token** as the password
(create one at <https://github.com/settings/tokens> — a classic token with `repo`
scope, or a fine-grained token with Contents: read/write on this repo).

Before pushing, sanity-check nothing sensitive is staged (should print nothing):

```bash
git ls-files | grep -E 'secrets\.toml$|^data/cache/'
```

## 2. Create the app on Streamlit Cloud

1. Go to <https://share.streamlit.io> and sign in **with GitHub** (authorize it to
   see the repo — grant access to the private repo if you made one).
2. **Create app** → **Deploy a public app from GitHub** (or private — either works).
3. Fill in:
   - **Repository:** `<your-username>/<repo-name>`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
4. Click **Deploy**. First build takes a couple of minutes (installs
   `requirements.txt`: streamlit + pandas + openpyxl).

## 3. Set the passcode (required — the app is locked until you do)

In the app's page: **⋮ → Settings → Secrets**, and add (TOML format):

```toml
app_passcode = "choose-a-strong-passcode"
```

Save. The app restarts and now admits anyone who enters that passcode. (For several
named passcodes instead of one shared value, use a table:
`[passcodes]` then `alice = "…"`, `bob = "…"` — any of them works.)

## 4. Share

Give the app URL **and** the passcode to the specific people who should have access.
The URL alone shows only the gate. Rotate access anytime by editing the
`app_passcode` secret.

**Optional — per-person access on top of the passcode:** in **Settings → Sharing**,
set the app to private and invite specific email addresses. Invited viewers sign in
with their own Google/GitHub account; the passcode still gates the content beneath.
This gives true per-person, revocable access if you want it.

## 5. Updating later — one command

Once the `origin` remote is set (step 1), publishing an update is a single command:

```bash
./publish.command             # regenerate map + workbook, run tests, commit, push
./publish.command --refresh   # re-scrape all sources first, then publish
./publish.command --dry-run   # preview what would change, commit/push nothing
```

It regenerates the derived artifacts from `data/catalog.db`, runs the test suite as a
safety gate, refuses to stage any secret or `data/cache/` path, commits only what
changed, and pushes to GitHub. Streamlit Cloud sees the push and redeploys. Manual
equivalent: commit locally and `git push origin main`.

---

**Security recap:** the real passcode lives only in the Streamlit Cloud secret (and,
for local runs, your gitignored `.streamlit/secrets.toml`). `data/cache/` (incl. the
352 MB ADM file) and the real secrets file are gitignored and never pushed. Confirm
with the `git ls-files` check in step 1 before every push (the `publish.command`
script also hard-refuses to stage them).
