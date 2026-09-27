# Sovrn Commerce assessment (not implemented)

This assessment is intentionally configuration-free. StackSignal keeps direct
Amazon Associates links as the priority route. No Sovrn key, JavaScript, edge
redirect, account, or link rewrite was added.

## What the official documentation says

- The [API onboarding guide](https://knowledge.sovrn.com/kb/api-onboarding-guide-for-commerce)
  recommends Redirect API or Link Check API. Redirect can wrap any outgoing
  URL but does **not** check an active merchant affiliation. Link Check returns
  an affiliate link, affiliatability and estimated EPC, but only after the
  Commerce campaign is approved.
- The [Commerce JavaScript guide](https://knowledge.sovrn.com/kb/javascript-for-commerce)
  can asynchronously scan and convert plain merchant links. Revenue/clicks
  apply only for merchants approved for that campaign; it requires a
  campaign-specific key. This makes it unsuitable as the first migration step
  for already-valid static Amazon links.
- [Amazon in Commerce](https://knowledge.sovrn.com/kb/how-to-connect-amazon-to-sovrn-commerce)
  requires an Amazon tracking ID for each country, permits the existing direct
  Amazon relationship to remain, and supports creating/managing Amazon links
  through its platform, JavaScript, mobile app, or API.
- Sovrn requires each site/campaign location to be submitted and approved;
  approval is not a guarantee for every raw merchant URL. Its API guide also
  documents merchant metadata, approved-merchant, reporting and product APIs.

## Recommendation

Use a **future build-time resolver** only after StackSignal has an approved
Sovrn campaign, stored secret outside Git, and an explicit merchant/market
allowlist. Persist the returned approved `affiliate_url`, raw destination,
verification date and route metadata in the content/feed used by the build.
The resolver should call Link Check for a changed URL, not every page view.

Do not use client-side rewriting: it makes static Markdown/JSON and rendered
HTML disagree and can override a currently working direct Amazon route. Do not
use a new redirect service yet: it creates uptime and observability work
without approved resolver data. For a non-monetizable merchant, render the raw
destination rather than manufacture a redirect. The V2 `Offer` +
`AffiliateRoute` interface supports this later without replacing the legacy
links now.
