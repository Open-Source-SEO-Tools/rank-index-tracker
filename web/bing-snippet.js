/* Read the current Bing page only. No network calls and no automated searches. */
(async function () {
  "use strict";
  if (!/(^|\.)bing\.com$/i.test(location.hostname)) {
    alert("Open a Bing search results page first.");
    return;
  }
  const visible = (n) => !!(n.getClientRects().length && getComputedStyle(n).visibility !== "hidden");
  const box = document.querySelector("#sb_form_q");
  const query = box ? box.value.trim() : "";
  const results = Array.from(document.querySelectorAll("#b_results li.b_algo h2 a"))
    .filter(visible).slice(0, 100)
    .map((a, i) => ({rank: i + 1, url: a.href, title: a.textContent.trim()}));
  const body = document.body.innerText;
  const noResults = Array.from(document.querySelectorAll("#b_results .b_no, #b_results .b_noResults"))
    .some((n) => visible(n) && /no results|there are no results|did not match any/i.test(n.innerText));
  const next = Array.from(document.querySelectorAll("a.sb_pagN, a[title='Next page']")).some(visible);
  const challenge = Number(new URL(location.href).searchParams.get("first") || 1) > 1 || !box || !document.querySelector("#b_results") || /verify (?:that )?you are human|unusual traffic|solve (?:the |this )?challenge|captcha/i.test(body);
  let market = new URL(location.href).searchParams.get("cc")?.toLowerCase();
  if (market === "gb") market = "uk";
  if (!market || !["us", "uk", "au"].includes(market)) market = prompt("Market for this reading: us, uk or au", "us");
  if (!["us", "uk", "au"].includes(market)) return;
  const snapshot = {engine: "bing", query, market, at: new Date().toISOString(), results,
    next_page: next, no_results: !results.length && noResults, challenge};
  const json = JSON.stringify(snapshot, null, 2);
  try {
    await navigator.clipboard.writeText(json);
    alert("Copied visible Bing results. Paste into the tracker. This snippet made no requests.");
  } catch {
    prompt("Copy this JSON, then paste into the tracker:", json);
  }
})();
