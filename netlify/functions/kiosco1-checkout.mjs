const fields = ["rubro", "zona"];
const read = (form, name, max) => String(form.get(name) || "").trim().slice(0, max);

export default async (request) => {
  if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });
  const form = await request.formData();
  const brief = Object.fromEntries(fields.map((name) => [name, read(form, name, 120)]));
  if (fields.some((name) => !brief[name])) return new Response("Completá rubro y zona.", { status: 400 });
  const checkout = process.env.LEMON_SQUEEZY_CHECKOUT_URL;
  if (!checkout) return new Response("El checkout todavía no está configurado.", { status: 503 });
  const url = new URL(checkout);
  if (!url.hostname.endsWith(".lemonsqueezy.com") || !url.pathname.includes("/checkout/buy/")) return new Response("Configuración de checkout inválida.", { status: 503 });
  const custom = { brief_id: crypto.randomUUID(), rubro: brief.rubro, zona: brief.zona };
  for (const [key, item] of Object.entries(custom)) url.searchParams.set(`checkout[custom][${key}]`, item);
  return Response.redirect(url, 303);
};
