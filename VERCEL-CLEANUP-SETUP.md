# Vercel deployment cleanup

This workflow targets the Vercel project `telegram-ai-bot`. It is manually triggered and does not run on pushes.

## One-time setup
1. Open the repository's Settings → Secrets and variables → Actions → New repository secret.
2. Name: `VERCEL_TOKEN`
3. Value: your Vercel token. Do not paste it into an issue, commit, or chat.
4. Open Actions → **Clean up old Vercel deployments** → Run workflow.

## Safe sequence
1. First run: keep `action = DRY_RUN` and `keep_latest_production = true`. This only lists eligible deployments.
2. Review the run log. The newest READY production deployment should be explicitly marked protected.
3. Only if the list is correct, run again with `action = DELETE`.

Deletion is permanent and removes old deployment URLs/rollback options. Active builds are skipped. If the workflow reports an API or permission error, stop and review the error; do not loosen the safeguards or paste the token into logs.
