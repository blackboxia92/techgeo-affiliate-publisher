const MAX_BODY = 1024;
const MAX_PREVIEW = 5;
const TRACKING = /^(utm_|fbclid$|gclid$|dclid$|msclkid$|_ga$|_gl$)/i;

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
const text = (value) => String(value || "").replace(/\s+/g, " ").trim();
function cleanUrl(value) { try { const url = new URL(/^https?:\/\//i.test(text(value)) ? text(value) : `https://${text(value)}`); for (const key of [...url.searchParams.keys()]) if (TRACKING.test(key)) url.searchParams.delete(key); url.hash = ""; return url.toString(); } catch { return ""; } }
function whatsapp(phone, explicit) { if (explicit) return cleanUrl(explicit); const raw = text(phone); if (!/^\+54\s?9/.test(raw)) return ""; const digits = raw.replace(/\D/g, ""); return digits ? `https://wa.me/${digits}` : ""; }
const normalize = (value) => text(value).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const searchTerms = (value, fallback) => { try { const parsed = JSON.parse(value); const terms = Array.isArray(parsed) ? parsed.map((item) => text(item).slice(0, 80)).filter((item) => item.length >= 2) : []; const unique = [...new Set(terms)].slice(0, 8); return unique.length ? unique : [fallback]; } catch { return [fallback]; } };
async function resolveLocation(zone) {
  try {
    const endpoint = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&addressdetails=1&q=${encodeURIComponent(zone)}`;
    const response = await fetch(endpoint, { headers: { "User-Agent": "StackSignal-Leads/1.0 (support@stacksignal.tech)", Accept: "application/json" } });
    const result = await response.json(); const exact = (Array.isArray(result) ? result : []).filter((item) => normalize(item.name) === normalize(zone)); const match = exact.sort((left, right) => Number(right.importance || 0) - Number(left.importance || 0))[0] || null;
    const address = match?.address || {}; const locality = text(address.city || address.town || address.village || address.municipality || text(match?.display_name).split(",")[0]);
    return locality || zone;
  } catch { return zone; }
}
function record(raw) {
  const company = text(raw.title || raw.name);
  const phone = text(raw.phone || raw.phoneUnformatted);
  const website = cleanUrl(raw.website || raw.site);
  const address = text(raw.fullAddress || raw.address);
  if (!company || (!phone && !website && !address)) return null;
  return { company, category: text(raw.categoryName || raw.category), address, phone, website, rating: raw.totalScore ?? raw.rating ?? null, reviews: raw.reviewsCount ?? raw.reviews ?? null, maps_url: cleanUrl(raw.url || raw.googleMapsUrl), email: text(raw.email), instagram: cleanUrl(raw.instagram || raw.instagramUrl), facebook: cleanUrl(raw.facebook || raw.facebookUrl), linkedin: cleanUrl(raw.linkedin || raw.linkedinUrl), whatsapp_url: whatsapp(phone, raw.whatsapp || raw.whatsappUrl), source: "Google Maps / datos públicos" };
}
async function signJob(jobId) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(process.env.APIFY_TOKEN), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(jobId));
  return [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export default async (request) => {
  if (request.method !== "POST") return json({ status: "not_found" }, 404);
  if (Number(request.headers.get("content-length") || 0) > MAX_BODY) return json({ status: "payload_too_large" }, 413);
  let payload; try { payload = await request.json(); } catch { return json({ status: "invalid_json" }, 400); }
  const rubro = text(payload.rubro).slice(0, 80); const zona = text(payload.zona).slice(0, 120); const locationQuery = text(payload.location_query).slice(0, 240); const location = text(payload.location_name).slice(0, 120); const terms = searchTerms(payload.search_terms, rubro);
  if (!rubro || !zona || !locationQuery || !location) return json({ status: "selection_required", message: "Seleccioná una categoría y una ciudad de las sugerencias." }, 400);
  if (!process.env.APIFY_TOKEN) return json({ status: "preview_unavailable" }, 503);
  try {
    const endpoint = `https://api.apify.com/v2/acts/compass~crawler-google-places/runs?token=${encodeURIComponent(process.env.APIFY_TOKEN)}`;
    const started = await Promise.all(terms.map(async (term) => { const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ searchStringsArray: [term], locationQuery: locationQuery, language: "es", skipClosedPlaces: false, scrapePlaceDetailPage: true, includeWebResults: false }) }); if (!response.ok) return ""; const run = await response.json(); return text(run?.data?.id); }));
    const jobIds = started.filter(Boolean); if (!jobIds.length) return json({ status: "source_unavailable" }, 502);
    return json({ status: "pending", job_ids: jobIds, location, job_sig: await signJob(`${jobIds.join("|")}|${location}`) });
  } catch { return json({ status: "source_unavailable" }, 502); }
};

export { json, text, record, signJob, MAX_PREVIEW, normalize, resolveLocation };
