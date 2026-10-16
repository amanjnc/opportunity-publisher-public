# Opportunity Publisher

Collect trusted opportunity announcements, remove duplicates, format captions and publish to Telegram. Supported collectors: Telegram, RSS, Greenhouse and Lever. LinkedIn publishing requires separate official access; LinkedIn collection is not implemented.

This public repository runs the code. Its database and Telegram session remain encrypted in a separate private repository. Read [CLOUD_SETUP.md](CLOUD_SETUP.md) before enabling. Publishing starts disabled; manual verification never sends posts.

Run offline tests with `python -m unittest discover -s tests -v` after installing requirements-cloud.txt. No live credentials are needed for those tests.
