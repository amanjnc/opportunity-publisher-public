# Opportunity Publisher

Collect trusted opportunity announcements, remove duplicates, format captions and publish to Telegram. Supported collectors: Telegram, RSS, Greenhouse and Lever. LinkedIn publishing requires separate official access; LinkedIn collection is not implemented.

This public repository runs the code. Its database and Telegram session remain encrypted in a separate private repository. Read [CLOUD_SETUP.md](CLOUD_SETUP.md) before enabling. Publishing starts disabled; manual verification never sends posts.

Run offline tests with `python -m unittest discover -s tests -v` after installing requirements-cloud.txt. No live credentials are needed for those tests.


### FIFO cloud publishing
The public workflow checks every five minutes, throughout the day. GitHub may
delay or skip scheduled runs; missed intervals are not replayed in a burst.
Collection runs when at least 30 minutes have elapsed since its last attempt.
Approved, unexpired opportunities are selected oldest first (creation time,
then ID), independently for each destination. Each run sends at most one
opportunity per channel, with at least five minutes between reservation times.
New collections append to the existing encrypted database queue.
Previous attempts remain protected from automatic retries, including failures
with uncertain delivery. Monday roundups are separate from the opportunity queue.
The old cloud_batch_size setting no longer controls cloud publishing.


### Source structure and optional photos
Telegram posts use only verified source-attached images (including album photos).
Without an image they publish as text; no fallback cards are generated and link
preview thumbnails are not downloaded as attachments.
Source messages with multiple opportunity headings and distinct links remain a
single grouped post, preserving Telegram bold text, sections and application
links while removing recognizable channel-follow promotions.
Mixed groups use general; scholarship/fellowship-only groups use education.
Grouped posts exceeding a photo caption publish as text to preserve all entries.
Text beyond Telegram's 4096-unit limit continues in balanced HTML messages;
ordinary short text stays a single message. Existing posted items are not resent.
