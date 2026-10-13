# Deploy a shareable URL (Render + Supabase)

The deploy produces one public URL, for example `https://breadcrumb-taxonomy-optimizer.onrender.com`. Your team signs in with a shared team password.

## 1. Create the Supabase database (about 3 min)
1. Go to supabase.com and click **New project**. Choose a region near your team (e.g. Singapore or Tokyo) and save the database password.
2. Optional: open **SQL Editor**, paste `supabase/migrations/0001_init.sql`, and click **Run**. The app also creates any missing tables on its first start.
3. Click **Connect** and choose **Session pooler**. Copy the URI, then change its start from `postgresql://` to `postgresql+psycopg://`:
   ```
   postgresql+psycopg://postgres.<ref>:<db-password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```

## 2. Push the code to GitHub (about 2 min)
1. On github.com, create a new **private** repository with no README.
2. From this folder, run:
   ```bash
   git remote add origin https://github.com/<you>/breadcrumb-taxonomy-optimizer.git
   git push -u origin main
   ```

## 3. Deploy on Render (about 10 min, mostly build time)
1. On render.com, go to **New → Blueprint**, connect GitHub and pick the repository. Render reads `render.yaml`.
2. Fill in the secret values when Render asks:
   - `DATABASE_URL`: the Supabase URI from step 1.
   - `API_TOKEN`: the team password you will share with colleagues. Make it long.
   - `OPENAI_API_KEY`: optional. Leave it empty to run on rules only. (`ANTHROPIC_API_KEY` also works.)
3. Click **Apply**. The first Docker build takes 5–10 minutes because it installs Chromium for the crawler.
4. When the service is live, open its `onrender.com` URL and sign in with the team password.

Share the URL and the password with your team; send the password separately.

## Notes
- **Plan:** `render.yaml` uses the **free** plan. It sleeps after 15 minutes idle, and the first visit after that takes 30–60 seconds. Upload your MOMO/PChome crawl files instead of crawling on the server; the free plan's 512 MB is too little for Chromium.
- **Your data:** it lives in Supabase, so redeploys keep it. Uploaded files and exports are temporary, which is fine because both are processed or generated on demand.
- **Custom domain:** in Render, go to **Settings → Custom Domains** to add one such as `seo-tools.yourcompany.com`.
- **Updates:** every `git push` to `main` redeploys automatically.
