# Roz-ier data refresh

`scripts/build_data.py` pulls FAST channel schedules from the PCC airings API and writes
`site/data/runway.json` (last airing per channel, tiers) and `site/data/grid.json` (airings for the EPG grid).
`.github/workflows/refresh.yml` runs it weekdays at 7:30 AM Pacific and publishes `site/` to GitHub Pages.

## Setup
1. Create a repo, add these files.
2. Settings > Secrets and variables > Actions: add secret `PCC_API_KEY`.
3. Settings > Pages: Source = GitHub Actions. Set visibility to your organization if available.
4. Actions tab > "Refresh Roz-ier data and publish site" > Run workflow to test.

A failed pull (any channel unreadable) fails the run and nothing is published, so the site keeps the last good data.
GitHub emails the workflow owner on failure by default.

## Changing channels
Edit `scripts/config.py` (monitored, inactive, suppressed, email-excluded).

## Local test
    PCC_API_KEY=... python3 scripts/build_data.py --out /tmp/out --only fast_channel_scrubs
