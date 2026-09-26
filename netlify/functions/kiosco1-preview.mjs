const MAX_BODY = 1024;
const MAX_PREVIEW = 5;
const TRACKING = /^(utm_|fbclid$|gclid$|dclid$|msclkid$|_ga$|_gl$)/i;

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
const text = (value) => String(value || "").replace(/\s+/g, " ").trim();
function cleanUrl(value) { try { const url = new URL(/^https?:\/\//i.test(text(value)) ? text(value) : `https://${text(value)}`); for (const key of [...url.searchParams.keys()]) if (TRACKING.test(key)) url.searchParams.delete(key); url.hash = ""; return url.toString(); } catch { return ""; } }
function whatsapp(phone, explicit) { if (explicit) return cleanUrl(explicit); const raw = text(phone); if (!/^\+54\s?9/.test(raw)) return ""; const digits = raw.replace(/\D/g, ""); return digits ? `https://wa.me/${digits}` : ""; }
function record(raw) {
  const company = text(raw.title || raw.name);
  const phone = text(raw.phone || raw.phoneUnformatted);
  const website = cleanUrl(raw.website || raw.site);
  const address = text(raw.fullAddress || raw.address);
  if (!company || (!phone && !website && !address)) return null;
  return { company, category: text(raw.categoryName || raw.category), address, phone, website, rating: raw.totalScore ?? raw.rating ?? null, reviews: raw.reviewsCount ?? raw.reviews ?? null, maps_url: cleanUrl(raw.url || raw.googleMapsUrl), email: text(raw.email), instagram: cleanUrl(raw.instagram || raw.instagramUrl), facebook: cleanUrl(raw.facebook || raw.facebookUrl), linkedin: cleanUrl(raw.linkedin || raw.linkedinUrl), whatsapp_url: whatsapp(phone, raw.whatsapp || raw.whatsappUrl), source: "Google Maps / datos públicos" };
}

export default async (request) => {
  if (request.method !== "POST") return json({ status: "not_found" }, 404);
  if (Number(request.headers.get("content-length") || 0) > MAX_BODY) return json({ status: "payload_too_large" }, 413);
  let payload; try { payload = await request.json(); } catch { return json({ status: "invalid_json" }, 400); }
  const rubro = text(payload.rubro).slice(0, 80); const zona = text(payload.zona).slice(0, 120);
  if (!rubro || !zona) return json({ status: "missing_search" }, 400);
  if (!process.env.APIFY_TOKEN) return json({ status: "preview_unavailable" }, 503);
  try {
    const endpoint = `https://api.apify.com/v2/acts/compass~crawler-google-places/run-sync-get-dataset-items?token=${encodeURIComponent(process.env.APIFY_TOKEN)}`;
    const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ searchStringsArray: [rubro], locationQuery: zona, language: "es", skipClosedPlaces: false, scrapePlaceDetailPage: true, includeWebResults: false }) });
    if (!response.ok) return json({ status: "source_unavailable" }, 502);
    const rows = await response.json(); const seen = new Set(); const records = [];
    for (const raw of Array.isArray(rows) ? rows : []) { const item = record(raw); if (!item) continue; const key = text(raw.placeId) || item.maps_url || `${item.company}|${item.address}`; if (seen.has(key)) continue; seen.add(key); records.push(item); }
    return json({ status: "ok", query: { rubro, zona }, total_found: records.length, preview: records.slice(0, MAX_PREVIEW), disclosure: "La vista previa muestra datos públicos observados. La disponibilidad de email, redes y WhatsApp depende de cada ficha." });
  } catch { return json({ status: "source_unavailable" }, 502); }
};
