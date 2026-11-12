# Rank and Index Tracker: attendee edition

> **Status: private review build.** This repository is private pending maintainer review. Cloning requires an invited GitHub account and Git authentication. An approved public release will not need an invitation.

Track Google and Bing rankings and index evidence for pages and queries you choose. See **Indexed N of M** for each engine and **N of the top 10 are yours** for each query and market, with history and exports. Start offline with invented data, then use your own provider accounts or import visible Bing results from your own browser.

This scoped starter was prepared for LLM Mastery, Chiang Mai, 14-15 November 2026. The six views are Overview, Rankings, Indexation, Bing check queue, History, and Export and setup. Every reading carries a source and UTC time; **Unknown never means Not indexed**.

## Get this and the other free tools

No address to type. Search **Marc Moeller** on Google, open **marcmoeller.au** from the knowledge panel or the first result, and press the big **Download** button on the homepage. All the free tools from the talk are there, this one included.

## Start with the demo

Use **Python 3.10+** and Git. There are no dependencies to install: no pip, npm, Docker, frameworks, remote scripts, fonts or CDNs.

```bash
git clone https://github.com/SEOShipper/koa-tracker-attendee.git
cd koa-tracker-attendee
python3 tracker.py
```

Open **http://127.0.0.1:5064/** yourself. The server binds only to **127.0.0.1**, never opens a browser, and stops with Ctrl+C. To change the port:

```bash
python3 tracker.py serve --port 5065
```

Choose **Synthetic demo**. Its 40 pages, six queries, two markets and 14 days of rankings are invented, using reserved example domains. The Google 31 of 40 and Bing 24 of 40 figures are synthetic, including readings labelled with provider names. Demo is read-only. Viewing, switching views, filtering and exporting saved data spend nothing and make no external requests. External search links open only when you click them.

Tested on **Linux only**. On systems whose Python command is `python`, replace `python3` in all commands. Windows and macOS have not been run.

## Track your own pages

Keep the server running and use a second terminal in the same folder:

```bash
python3 tracker.py add-page https://example.com/trail-pack --name "Feather trail pack" --group "Gear"
python3 tracker.py add-page https://example.org/trail-guide --name "Trail guide" --group "Reference" --not-mine
python3 tracker.py add-query "light trail running packs" --market us,uk
python3 tracker.py list
```

`mine` means this exact page is yours. It controls owned-rank counts and eligibility for Search Console inspection. `--not-mine` pages can still receive index evidence from rank runs and manual Bing checks. Marking a page yours does not grant property access.

Choose **My data**, then **Reload data**. Personal data and the demo are separate. The web page imports browser readings only; page and query management happens in the CLI.

```bash
python3 tracker.py add-pages --sitemap https://example.com/sitemap.xml
python3 tracker.py remove-page https://example.org/trail-guide
python3 tracker.py remove-query "light trail running packs"
```

The sitemap command fetches your own HTTPS URL sitemap, up to 2 MB and 2,000 URLs. It rejects entities and document types, does not follow redirects, does not recurse into sitemap indexes, and refuses private network hosts. Imported pages default to yours, group `Sitemap`, with an empty name. Add descriptive names when creating pages individually, or edit the title in the Bing queue. Removing pages or queries keeps their saved history.

## Google rank with DataForSEO

Use your own **API login and API password**, supplied in your shell:

```bash
export DATAFORSEO_LOGIN="your-api-login"
export DATAFORSEO_PASSWORD="your-api-password"
```

PowerShell:

```powershell
$env:DATAFORSEO_LOGIN="your-api-login"
$env:DATAFORSEO_PASSWORD="your-api-password"
```

The application reads environment variables only. It never reads `.env`, accepts credentials in the web page, logs credentials or sends them to the browser. Use your shell's secret-entry facilities on shared computers to avoid shell history exposure.

Preview first:

```bash
python3 tracker.py rank --engine google
python3 tracker.py rank --engine google --query "light trail running packs" --market uk --depth 20
```

The preview prints the request count and estimated USD cost, needs no credentials, makes no requests and writes nothing. Add **`--spend`** to run:

```bash
python3 tracker.py rank --engine google --spend
```

Without `--query`, the command uses every configured query and its markets. `--market us|uk|au` overrides the markets for that command. An explicit `--query` defaults to `us` unless `--market` is supplied. Depth is 10 by default; 20 and 30 are available. All requests use desktop, English, and one task per query and market. Search operators such as `site:` and `intitle:` are refused before spending.

The provider-reported charge is stored per run. Requests use [Google Organic Live Advanced](https://docs.dataforseo.com/v3/serp/google/organic/live/advanced/). These live paths were **implemented against the linked documentation and tested with fixtures**. They have **not been run end to end by the authors in this edition**. No paid call was made to prepare it.

## Bing rank: API or browser import

The API path uses the same credentials and preview process:

```bash
python3 tracker.py rank --engine bing
python3 tracker.py rank --engine bing --spend
```

It follows [Bing Organic Live Advanced](https://docs.dataforseo.com/v3/serp/bing/organic/live/advanced/) and stores source `dataforseo-bing`. In the authors' own tests in **October 2026**, Bing API results were unreliable: results covered the wrong topic, and `site:` returned nothing even for huge sites. **Treat API Bing ranks as unverified and spot-check them in a real browser.** This historical finding was supplied for this edition; it was not repeated here.

The UI labels every Bing API run unverified. If the echoed keyword differs or fewer than three organic results return, the saved run has note **suspect** and a warning chip. Passing those cheap checks does not verify correctness. Suspect runs remain in rank history but do not count as positive index evidence.

The browser path is the one that worked in the authors' earlier tests:

1. Open Bing in your own normal, signed-in browser and search a configured query yourself. Use the **first results page**, in English.
2. Open **Bing check queue** or **Export and setup** in this dashboard. Drag **Copy visible Bing results** to your bookmarks bar. Review [the snippet](web/bing-snippet.js) before installing it.
3. Click the bookmark on the Bing results page. Confirm its market if prompted. It copies JSON to your clipboard; if clipboard access is blocked, copy from the prompt.
4. Choose **My data**. Paste into the Rankings or Export import box and click **Import browser reading**, or press **Ctrl+Enter**.

The snippet only reads the visible organic links, titles, query box and result-page indicators. It makes **no requests**, runs no searches and automates nothing. The Python importer decodes supported Bing click wrappers before matching URLs. Browser ranks describe visible organic order on the first page, not a complete search index. Bing page structure, translations, challenges and browser bookmarklet policies may change; these have not been checked in a live signed-in browser for this edition.

To import the same JSON from a file or standard input:

```bash
python3 tracker.py import-reading reading.json
python3 tracker.py import-reading -
```

Paste JSON and send your terminal's end-of-input signal for `-`. Source is `browser-import`; imports are local and free. The snippet market must match a configured query market for rank imports.

## Google indexed with Search Console

Only inspect **your own verified properties**, with the URL Inspection API enabled in your Google project and a suitable OAuth scope, such as `https://www.googleapis.com/auth/webmasters.readonly`. Obtain credentials using Google's [OAuth documentation](https://developers.google.com/identity/protocols/oauth2/web-server#offline); this tool does not perform the initial consent flow or store tokens.

Use an existing access token and property:

```bash
export GSC_ACCESS_TOKEN="your-short-lived-access-token"
export GSC_SITE_URL="sc-domain:example.com"
python3 tracker.py index --engine google --limit 20
python3 tracker.py index --engine google --limit 20 --run
```

Alternatively set all three of **GSC_CLIENT_ID**, **GSC_CLIENT_SECRET**, and **GSC_REFRESH_TOKEN**. The CLI exchanges them at Google's token endpoint once per command; tokens stay in memory. An access token takes precedence. Refresh is not automatically retried.

Use `--site-url sc-domain:example.com` or `--site-url https://example.com/` to override `GSC_SITE_URL` for one command. A URL-prefix property must have its trailing slash and match scheme, host and prefix. Run separate commands for different properties. `--url https://example.com/trail-pack` selects one tracked owned page. The default `--limit` is 20; maximum 2,000.

The [inspection request](https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect) supplies `inspectionUrl` and `siteUrl`. The saved index verdict `PASS` maps to Indexed; other returned verdicts map to Not indexed, retaining `coverageState`. Errors and missing verdicts map to Unknown with a safe error note. This is Google's saved index evidence, not a live crawl or request to index a page. See the [response and verdict reference](https://developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult).

Search Console is [free](https://developers.google.com/webmaster-tools/pricing), but [quota-limited](https://developers.google.com/webmaster-tools/limits): **2,000 inspections per site per day and 600 per site per minute**; per project, 10,000,000 per day and 15,000 per minute. The command is sequential, preview-first, bounded by `--limit`, and needs **`--run`** to make requests. There are no schedules, retries or browser-triggered provider calls. It only selects tracked `mine` pages under the supplied property. Other pages get no Google inspection and remain Unknown unless seen in a saved rank run.

## What works for Bing and what does not

The authors found **no Bing API that reliably answers whether this exact URL is indexed**. In their tests on **8 November 2026**, `url:` and `site:` searches gave false negatives. What worked was a signed-in browser, searching the page's **own title first**, and **`url:` second**. These are historical observations, not a live validation of this edition.

```bash
python3 tracker.py bing-queue
```

The CLI prints two ready-made search links for every page without current positive Bing evidence. The **Bing check queue** view provides the same links, an editable page-title query, market selection and a page selector. Default title is the page's name, otherwise host plus path words. Opening a link is an explicit user action, outside this local server.

For each page, run the title search yourself, click the snippet bookmark and paste the JSON into that page's queue box. Repeat for the URL search when needed. The queue advances to the next page after each paste; use the page selector to return to a pending page for its second search. Title edits survive view changes during the current tab session. **Checked** includes inconclusive attempts, while **Indexed** alone confirms a page.

Classification is conservative:

- Exact URL identity in either valid search: **Indexed**, with the matching result as evidence.
- At least three title results without the page, plus a URL search explicitly reporting no results: **Not found**. Both searches must use the same market and UTC day, and neither may indicate a next page.
- Missing search, challenge, mismatched query, short title sample, unrelated URL results, different markets, a next page or uncertain no-results wording: **Unknown**, with the reason. Unrelated results alone are never negative evidence.

The importer matches query text against the queue. Ambiguous titles require choosing the page in the queue. A file import can include `target_url` and `title_query` alongside the snippet fields to select a page or reproduce a title edit. Use `kind: "rank"` to force a rank import when a configured query also matches a page title. A mismatched target query becomes Unknown. Old search pairs from a previous UTC day are not reused.

## Costs, checked 12 November 2026

| Action | Estimated USD |
|---|---:|
| View, export, preview, or import browser evidence | 0 |
| Google or Bing Live rank, one query and market, depth 10 | 0.002 |
| Same, depth 20 | 0.004 |
| Same, depth 30 | 0.006 |
| Six queries, two markets, both engines, depth 10 | 0.048 |
| Google Search Console inspection | 0, quota-limited |

Sources: [Google Organic pricing](https://dataforseo.com/pricing/google-serp/google-organic-serp-api), [Bing Organic pricing](https://dataforseo.com/pricing/serp/bing-organic-serp-api), and [additional billing rules](https://dataforseo.com/help-center/serp-api-cost-explained). Depth estimates budget for the requested number of ten-result billing units; actual charges depend on returned depth and provider rules. Prices may change; check your own account before spending. Provider account funding is separate from request estimates. Bing pricing prose mentions reduced deeper-page rates, while its parameter table adds a base price per page. These estimates follow the table; confirm deeper billing in your account. Each run stores its reported cost, or null if the provider does not report one. No asynchronous extras are requested.

## Your files and server

Personal data lives in **`~/.rank-index-tracker/tracker.json`**, outside the clone. The single JSON schema contains `pages`, `queries`, append-only `rank_runs`, and append-only `index_readings`, with `schema_version: 1`. Derived current status, first observed indexed dates, charts and ownership counts are computed when reading. `demo.json` uses the same schema, with an invented-data notice.

Pass `--data-dir` **before the subcommand**, using the same path for the server and CLI:

```bash
python3 tracker.py --data-dir /path/to/private-data serve
python3 tracker.py --data-dir /path/to/private-data add-page https://example.com/trail-pack
python3 tracker.py --data-dir /path/to/private-data rank --engine google
```

The directory is created on the first writing command, never by a preview or normal viewing. Writes validate the schema, take an exclusive `.tracker.lock`, write a temporary file, flush and atomically replace `tracker.json`. Limits: 20 MB, 2,000 pages, 200 queries, 20,000 rank runs and 20,000 index readings. Browser imports are capped at 250 KB. Archive history before reaching the limits. Back up the file while no writer is active. Invalid JSON or schema errors appear in the UI; the server stays available.

The server has no login, never binds a public address and should remain local. It checks the exact localhost Host and port. The only write route is `POST /api/import-reading?source=mine`, protected by a random per-process token, an Origin check when supplied, JSON content type and body size limits. The token is a local anti-forgery value, not a provider credential. Demo cannot be changed through the API. All responses use a restrictive CSP, no-referrer and nosniff headers. Static assets use a fixed allow-list.

External provider and sitemap requests use HTTPS, ignore proxy environment variables, refuse redirects and have a timeout. No paid request is retried automatically. The server itself makes no provider calls.

Export from the **Export and setup** view or the CLI:

```bash
python3 tracker.py export --format json --out /path/to/export.json
python3 tracker.py export --format csv --out /path/to/export.csv
```

JSON preserves history and evidence; CSV includes saved rank rows, index history and derived latest index rows. CSV protects formula-leading cells for spreadsheet import. Real exports can contain sensitive queries, URLs and titles; keep them private unless you have permission to share them.

## Troubleshooting

**A paid call timed out or failed.** It may have been billed. Check your provider task history before repeating it. Missing credentials and rank request failures exit with code 2 and preserve the existing dataset. Search Console per-page errors are recorded as Unknown and the command completes; setup and token-exchange failures exit 2.

**Only part of a rank batch completed.** The original data is unchanged and successful responses are saved as `recovery-<id>.json` in your data directory when possible. Preserve these files and provider history. Merge unique record IDs into a validated backup offline; do not repeat paid calls to repair storage. Disk or permissions failure may prevent recovery too.

**The file is invalid.** Restore a schema-valid backup. Do not delete a damaged file to make a paid command proceed. A failed atomic replacement leaves the original file in place.

**The lock remains.** Check that your own writer is no longer running before removing a stale `.tracker.lock`. Do not remove an active writer's lock.

**Data does not appear.** Choose My data, check both terminals use the same `--data-dir`, and select Reload data. Demo and your file never merge automatically.

**Inspection selects zero pages.** Check `mine`, the property string, URL prefix, ownership and `--limit`. The tool does not inspect other people's properties. Missing access or quota produces Unknown, not Not indexed.

**The Bing import is Unknown or rejected.** Check the page selector, edited title, UTC date, exact query, market and result language. Use the first results page. A challenge needs manual browser attention. If the bookmarklet is blocked, review `web/bing-snippet.js` and run it in the browser console. Unsupported click wrappers should be checked using the actual destination URL. No missing evidence is converted into a negative conclusion.

## What the evidence means

- **URL identity:** ignore scheme and trailing path slashes only. Keep the host (`www` matters), path case, query string, port and fragment. Matching is exact page ownership, not whole-domain ownership.
- **Seen ranking:** a tracked URL in a saved rank run is positive index evidence for that engine, labelled **Indexed (seen ranking #N)**, source `rank-run`, with the underlying source and time. Suspect Bing API runs are excluded from index confirmation as a precaution.
- **Latest** means the newest saved observation for that URL and engine. A later Unknown can replace an older positive result without erasing history. First indexed is the earliest positive observation in this file, not the original indexing date.
- **Best rank** is the best owned page in that query, market and engine's saved sample. **N of the top 10 are yours** counts distinct tracked owned URL identities at ranks 1 to 10. A missing page is outside that sample, not necessarily unindexed.
- **Not found** is limited negative evidence from the paired Bing searches. It is not a claim about Bing's entire index. All results are snapshots, not ranking or indexing guarantees.

## Checks and licence

```bash
python3 -m unittest discover -s tests -v
```

The tests use hand-written synthetic provider fixtures and loopback server requests. They make no external calls and spend no credits. Live provider paths were **implemented against the linked documentation and tested with fixtures**, not run end to end by the authors in this edition. Browser and bookmarklet behavior still needs manual review on a normal signed-in browser.

Application code, assets and the demo were newly authored for this edition. [PROVENANCE.md](PROVENANCE.md) lists official sources and verification limits. Code is offered under the [MIT licence](LICENSE), Copyright (c) 2026 SEOShipper. External services, fees and third-party data rights apply separately.
