const API_URL = (process.env.KIOSCO2_API_URL || "https://kiosco2-directory-submitter-production-46c1.up.railway.app").replace(/\/$/, "");
const API_KEY = process.env.KIOSCO2_API_KEY;

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});

const text = (value, max) => typeof value === "string" && value.trim().length > 0 && value.trim().length <= max;

export default async (request) => {
  if (request.method !== "POST") return json({ message: "Método no permitido." }, 405);
  if (!API_KEY) return json({ message: "La auditoría está siendo habilitada. No se envió tu ficha." }, 503);
  let payload;
  try { payload = await request.json(); } catch { return json({ message: "Datos inválidos." }, 400); }
  if (!text(payload.product_name, 120) || !text(payload.tagline, 160) || !text(payload.description, 5000) || !text(payload.category, 200) || !text(payload.contact_email, 254)) return json({ message: "Completá todos los campos requeridos." }, 400);
  try { new URL(payload.website_url); } catch { return json({ message: "Ingresá una URL pública válida." }, 400); }
  const safePayload = {
    product_name: payload.product_name.trim(), website_url: payload.website_url.trim(), tagline: payload.tagline.trim(), description: payload.description.trim(), category: payload.category.trim(), contact_email: payload.contact_email.trim(), pricing_model: text(payload.pricing_model, 80) ? payload.pricing_model.trim() : "Freemium", product_type: "ai_tool",
  };
  try {
    const response = await fetch(`${API_URL}/audit`, { method: "POST", headers: { "content-type": "application/json", "X-API-Key": API_KEY }, body: JSON.stringify(safePayload), signal: AbortSignal.timeout(90000) });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) return json({ message: body.detail || "No pudimos completar la auditoría." }, response.status === 401 ? 503 : 502);
    return json(body);
  } catch { return json({ message: "No pudimos conectar con la auditoría. No se envió tu ficha." }, 502); }
};
