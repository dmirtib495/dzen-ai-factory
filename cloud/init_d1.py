from cloud_sync import init_schema, enabled
if not enabled(): raise SystemExit('Set CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_D1_DATABASE_ID first.')
print(init_schema())
