# Code and data provenance

This is a newly authored attendee edition. Its Python, native JavaScript, CSS,
HTML, tests and invented demo were written specifically for this repository.
The permitted sibling attendee dashboard was inspected for its workbench
layout, tone, command conventions, README structure and safety posture.
No source, dataset, images, fonts, private infrastructure or measured search
results were copied. Demo URLs use only reserved example domains.

The runtime is Python 3.10+ standard library and native browser APIs. There
are no dependencies, CDN assets, remote scripts, analytics or font downloads.
API credentials belong to each attendee and come from environment variables
only. The local anti-forgery token is generated at server startup and is not
a provider credential. API/service terms and third-party data rights remain
separate from the MIT code licence.

## Official sources opened on 12 November 2026

- [Google Organic Live Advanced](https://docs.dataforseo.com/v3/serp/google/organic/live/advanced/): request array, keyword, location, language, depth, device; task envelope, cost and organic rank_group.
- [Bing Organic Live Advanced](https://docs.dataforseo.com/v3/serp/bing/organic/live/advanced/): same task shape, result keyword echo, organic rows and reported charge.
- [Google Organic pricing](https://dataforseo.com/pricing/google-serp/google-organic-serp-api): Live billing.
- [Bing Organic pricing](https://dataforseo.com/pricing/serp/bing-organic-serp-api): Live billing.
- [SERP pricing overview](https://dataforseo.com/pricing/serp): engine-specific pricing links.
- [Additional billing rules](https://dataforseo.com/help-center/serp-api-cost-explained): Live base price and depth billing, operator surcharge.
- [URL Inspection request](https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect): inspectionUrl, siteUrl and OAuth scopes.
- [URL Inspection result](https://developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult): indexStatusResult, verdict and coverageState.
- [Search Console quota](https://developers.google.com/webmaster-tools/limits): per-site 2,000/day and 600/minute; per-project 10,000,000/day and 15,000/minute.
- [Search Console pricing](https://developers.google.com/webmaster-tools/pricing): free use subject to quota.
- [Google OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server#offline): refresh-token exchange and offline access.

The older generic DataForSEO pricing address `/pricing/serp/serp` was not
accessible through the documentation tool. The current overview and both
engine-specific pages above opened successfully. Bing pricing prose mentions reduced deeper-page rates, but its parameter
table adds one base price per extra page. The preview uses that table as an
estimate; exact deeper billing was not verified with an account. No response field was
silently guessed because a reference was inaccessible. Provider examples
were not copied; tests use small hand-written reserved-domain fixtures.

## Verification boundaries

Live provider paths were **implemented against the linked documentation and
tested with fixtures**. No end-to-end DataForSEO, Google OAuth, or Search
Console call was made. No user credentials were available or needed for this
build. Tested on Linux only.

Bing API unreliability in October 2026 and browser operator false negatives
on 8 November 2026 are historical observations supplied in the brief. They
were not independently repeated for this edition. The Bing DOM selectors,
click-wrapper decoding rule and paired-search method were supplied in the
brief. The snippet's current behavior, clipboard access, challenge detection
and English no-results wording need review in a real signed-in browser.
No snippet requests data or automates a search.

Additional conservative choices: negative Bing pairs must share a UTC day
and market and have no next page; suspect API ranks do not confirm indexing.
Queue progress includes inconclusive checks and is distinct from Indexed.
Every change to these evidence rules should retain the Unknown state.
