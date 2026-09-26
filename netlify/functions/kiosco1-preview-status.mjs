import { json, text, record, signJob, MAX_PREVIEW } from "./kiosco1-preview.mjs";

const validJob = (value) => /^[A-Za-z0-9]{10,80}$/.test(value);

export default async (request) => {
  if (request.method !== "GET") return json({ status: "not_found" }, 404);
  const url = new URL(request.url); const jobId = text(url.searchParams.get("job")); const signature = text(url.searchParams.get("sig"));
  if (!validJob(jobId) || !signature || signature !== await signJob(jobId)) return json({ status: "not_found" }, 404);
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
    for (const raw of Array.isArray(rows) ? rows : []) { const item = record(raw); if (!item) continue; const key = text(raw.placeId) || item.maps_url || `${item.company}|${item.address}`; if (seen.has(key)) continue; seen.add(key); records.push(item); }
    return json({ status: "ok", total_found: records.length, preview: records.slice(0, MAX_PREVIEW), disclosure: "La vista previa muestra datos públicos observados. La disponibilidad de email, redes y WhatsApp depende de cada ficha." });
  } catch { return json({ status: "source_unavailable" }, 502); }
};
