# Two Telegram destination channels

Future Scholarship and Fellowship opportunities go to TELEGRAM_EDUCATION_CHANNEL. Every other category goes to TELEGRAM_TARGET_CHANNEL. Collection source channels in config.yaml are unrelated to destinations and are unchanged.

## Activate

1. Create the education channel and give the SAME publishing bot administrator permission to post.
2. In the PUBLIC repository's Actions secrets add TELEGRAM_EDUCATION_CHANNEL, value @your_education_channel or -100... numeric channel ID.
3. Keep TELEGRAM_TARGET_CHANNEL pointing at the general channel. Both values must identify different channels.
4. The next live run uses category routing. No extra token, app or GitHub job is needed. A manual live test may publish up to SIX opportunities TOTAL across both channels, not six per channel.

Missing education secret holds scholarships and fellowships in the queue; they do not fall back to general. No old failed attempt is reset. Already published scholarships remain in their original channel and will not be reposted to education automatically. Duplicate identity remains global across collection sources, approval and publication.

Each configured destination receives its own Monday roundup, containing only opportunities actually published there and closing that week. Public post URLs are generated using the channel that owns the message ID. A channel with no eligible records gets no empty roundup. Each channel has its own weekly guard, so restarting cannot resend a successful roundup. The same bot posts each roundup.

Historical destinations are remembered per route. Updating one channel secret after renaming that SAME channel migrates that route's saved destination/weekly guards only. Do not replace a route with an unrelated new channel and treat it as a rename. Channel identity validation against Telegram numeric IDs is not implemented; explicit multi-channel alias conflicts stop migration instead of mixing history.

Native Telegram scheduled releases/five-minute spacing remain a separate change. The existing GitHub collection and posting times and total batch limit remain unchanged. No live posts were sent while implementing this feature. User must add the new channel secret and bot permission.
