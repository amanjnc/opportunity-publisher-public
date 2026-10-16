# Public runner / private state handover

Public code and standard Linux Actions run here. Existing encrypted state remains in amanjnc/opportunity-publisher on publisher-state. NEVER make that repository public, copy state.enc here, or overwrite state with your old local snapshot.

Publishing is initially OFF. Scheduled jobs do not allocate a runner until repository variable PUBLISHER_ENABLED is exactly true. Manual Run workflow defaults to verification only: restore/decrypt/check SQLite integrity, no collection, no posting, no state writeback. Existing private publishing continues until handover.

## Secrets in THIS PUBLIC repository

STATE_REPO_TOKEN: fine-grained personal access token, restricted to ONLY the private amanjnc/opportunity-publisher repository, Contents read and write. Set an expiration and renew before it expires. Never paste the token in code, issues or chat. The public repository GITHUB_TOKEN cannot read your private state repository.

Copy these from your original local .env into this repository's Actions secrets: STATE_ENCRYPTION_KEY (SAME existing key), TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN, TELEGRAM_TARGET_CHANNEL. Existing private repository secrets are not copied automatically. Never generate a new encryption key.

STATE_REPOSITORY is fixed in the workflow to amanjnc/opportunity-publisher. The state helper refuses a public state repository. Contents permission for the public workflow's built-in token is read-only. Sensitive token is used only by the state helper. Do not add pull_request or pull_request_target triggers that run untrusted code with secrets. Audit changes before enabling them.

## Verify first

Run workflow on main with publish unchecked. Successful verification checks the newest live private state but does not overwrite it. Logs must not include credentials, decrypted records or session data.

## Switch exactly once

1. Disable Opportunity publisher workflow in OLD PRIVATE repository Actions page (workflow menu, Disable workflow).
2. Wait for any old queued/running job to finish, or cancel it and check its outcome before proceeding. Private and public concurrency groups are NOT shared.
3. Add repository Actions VARIABLE PUBLISHER_ENABLED=true here.
4. Manual Run workflow with publish checked can send up to six actual opportunities. It restores the latest private state; no data migration/reseed is needed.
5. Confirm final save succeeds. Keep old private workflow disabled and local workers stopped. The normal seven-run schedule is unchanged.

To pause, set PUBLISHER_ENABLED=false. Only this public repository should execute the publisher. Keep the private repository: it stores state. Native Telegram scheduling, five-minute spacing and additional source handles have NOT been implemented by this handover. Source channels remain configured in config.yaml.

Code is public and can be copied. Secrets remain private, but logs are public; don't add secret/payload debugging. This repository was created from code-only files with fresh history, not from the private state branch.

The hosting choice follows the user's reported confirmation from GitHub; no approval was independently obtained by this project. Free standard public runners still have technical and policy limits.
