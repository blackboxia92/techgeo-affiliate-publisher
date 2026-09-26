import { json, text, record, signJob, MAX_PREVIEW, normalize } from "./kiosco1-preview.mjs";

const validJob = (value) => /^[A-Za-z0-9]{10,80}$/.test(value);
const matchesLocation = (raw, location) => {
  const needle = normalize(location); if (needle.length < 3) return false;
  const haystack = normalize([raw.fullAddress, raw.address, raw.city, raw.state, raw.country, raw.countryCode].filter(Boolean).join(" "));
  return haystack.includes(needle);
};

export default async (request) => {
  if (request.method !== "GET") return json({ status: "not_found" }, 404);
  const url = new URL(request.url); const jobIds = text(url.searchParams.get("jobs")).split(",").filter(validJob).slice(0, 8); const signature = text(url.searchParams.get("sig")); const location = text(url.searchParams.get("location")).slice(0, 160);
  if (!jobIds.length || !location || !signature || signature !== await signJob(`${jobIds.join("|")}|${location}`)) return json({ status: "not_found" }, 404);
  const token = encodeURIComponent(process.env.APIFY_TOKEN || "");
  if (!token) return json({ status: "preview_unavailable" }, 503);
  try {
    const runs = await Promise.all(jobIds.map(async (jobId) => { const response = await fetch(`https://api.apify.com/v2/actor-runs/${jobId}?token=${token}`); return response.ok ? response.json() : null; }));
    const statuses = runs.map((run) => text(run?.data?.status)); if (statuses.some((status) => status === "RUNNING" || status === "READY")) return json({ status: "pending" });
    const succeeded = jobIds.filter((_, index) => statuses[index] === "SUCCEEDED"); if (!succeeded.length) return json({ status: "source_unavailable" }, 502);
    const datasets = await Promise.all(succeeded.map(async (jobId) => { const response = await fetch(`https://api.apify.com/v2/actor-runs/${jobId}/dataset/items?token=${token}`); return response.ok ? response.json() : []; })); const seen = new Set(); const records = [];
    for (const rows of datasets) for (const raw of Array.isArray(rows) ? rows : []) { if (!matchesLocation(raw, location)) continue; const item = record(raw); if (!item) continue; const key = text(raw.placeId) || item.maps_url || `${item.company}|${item.address}`; if (seen.has(key)) continue; seen.add(key); records.push(item); }
    return json({ status: "ok", total_found: records.length, preview: records.slice(0, MAX_PREVIEW), location, disclosure: "Sólo se muestran fichas cuya dirección pública coincide con la localidad buscada." });
  } catch { return json({ status: "source_unavailable" }, 502); }
};

export { matchesLocation };
