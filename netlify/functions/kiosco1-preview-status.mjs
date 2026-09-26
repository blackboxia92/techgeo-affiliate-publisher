import { json, text, record, signJob, MAX_PREVIEW, normalize } from "./kiosco1-preview.mjs";

const validJob = (value) => /^[A-Za-z0-9]{10,80}$/.test(value);
const matchesLocation = (raw, location) => {
  const needle = normalize(location); if (needle.length < 3) return false;
  const haystack = normalize([raw.fullAddress, raw.address, raw.city, raw.state, raw.country, raw.countryCode].filter(Boolean).join(" "));
  return haystack.includes(needle);
};

export default async (request) => {
  if (request.method !== "GET") return json({ status: "not_found" }, 404);
  const url = new URL(request.url); const jobId = text(url.searchParams.get("job")); const signature = text(url.searchParams.get("sig")); const location = text(url.searchParams.get("location")).slice(0, 160);
  if (!validJob(jobId) || !location || !signature || signature !== await signJob(`${jobId}|${location}`)) return json({ status: "not_found" }, 404);
  const token = encodeURIComponent(process.env.APIFY_TOKEN || "");
  if (!token) return json({ status: "preview_unavailable" }, 503);
  try {
    const runResponse = await fetch(`https://api.apify.com/v2/actor-runs/${jobId}?token=${token}`);
    if (!runResponse.ok) return json({ status: "source_unavailable" }, 502);
    const run = await runResponse.json(); const runStatus = text(run?.data?.status);
    if (runStatus === "RUNNING" || runStatus === "READY") return json({ status: "pending" });
    if (runStatus !== "SUCCEEDED") return json({ status: "source_unavailable" }, 502);
    const rowsResponse = await fetch(`https://api.apify.com/v2/actor-runs/${jobId}/dataset/items?token=${token}`);
    if (!rowsResponse.ok) return json({ status: "source_unavailable" }, 502);
    const rows = await rowsResponse.json(); const seen = new Set(); const records = [];
    for (const raw of Array.isArray(rows) ? rows : []) { if (!matchesLocation(raw, location)) continue; const item = record(raw); if (!item) continue; const key = text(raw.placeId) || item.maps_url || `${item.company}|${item.address}`; if (seen.has(key)) continue; seen.add(key); records.push(item); }
    return json({ status: "ok", total_found: records.length, preview: records.slice(0, MAX_PREVIEW), location, disclosure: "Sólo se muestran fichas cuya dirección pública coincide con la localidad buscada." });
  } catch { return json({ status: "source_unavailable" }, 502); }
};

export { matchesLocation };
