const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
const normalize = (value) => clean(value).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff" } });

export default async (request) => {
  if (request.method !== "GET") return json({ status: "not_found" }, 404);
  const query = clean(new URL(request.url).searchParams.get("q")).slice(0, 100);
  if (query.length < 2) return json({ status: "ok", locations: [] });
  try {
    const endpoint = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=12&addressdetails=1&q=${encodeURIComponent(query)}`;
    const response = await fetch(endpoint, { headers: { "User-Agent": "StackSignal-Leads/1.0 (support@stacksignal.tech)", Accept: "application/json" } });
    if (!response.ok) return json({ status: "source_unavailable" }, 502);
    const rows = await response.json(); const needle = normalize(query); const locations = (Array.isArray(rows) ? rows : []).map((row) => {
      const address = row.address || {}; const locality = clean(address.city || address.town || address.village || address.municipality || row.name);
      return { label: clean(row.display_name), locality, query: clean(row.display_name), exact: normalize(row.name) === needle, importance: Number(row.importance || 0) };
    }).filter((row) => row.locality && (normalize(row.locality).includes(needle) || needle.includes(normalize(row.locality)))).sort((left, right) => Number(right.exact) - Number(left.exact) || right.importance - left.importance).slice(0, 6).map(({ label, locality, query: locationQuery }) => ({ label, locality, query: locationQuery }));
    return json({ status: "ok", locations });
  } catch { return json({ status: "source_unavailable" }, 502); }
};
