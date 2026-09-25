import { getStore } from "@netlify/blobs";

const STORE_NAME = "stacksignal-private-analytics";
const SUMMARY_KEY = "summary-v1";
const MAX_BODY_BYTES = 2048;
const MAX_PAGE_KEYS = 5000;
const MAX_REFERRER_KEYS = 500;
const RETENTION_DAYS = 31;

const responseHeaders = {
  "Cache-Control": "no-store, max-age=0",
  "Content-Type": "application/json; charset=utf-8",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Robots-Tag": "noindex, nofollow",
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: responseHeaders });
}

function cleanPath(value) {
  if (typeof value !== "string" || !value.startsWith("/")) return null;
  try {
    const path = new URL(value, "https://stacksignal.invalid").pathname;
    return path.length <= 300 ? path : null;
  } catch (_) {
    return null;
  }
}

function cleanReferrer(value) {
  if (typeof value !== "string") return "direct";
  const host = value.trim().toLowerCase().slice(0, 120);
  return /^[a-z0-9.-]+$/.test(host) ? host : "direct";
}

function emptySummary() {
  return {
    total: 0,
    days: {},
    pages: {},
    referrers: {},
    updated_at: null,
  };
}

function trimOldDays(days, today) {
  const cutoff = new Date(`${today}T00:00:00.000Z`);
  cutoff.setUTCDate(cutoff.getUTCDate() - (RETENTION_DAYS - 1));
  const cutoffKey = cutoff.toISOString().slice(0, 10);
  return Object.fromEntries(
    Object.entries(days).filter(([date]) => date >= cutoffKey && date <= today),
  );
}

function incrementMap(map, key, limit) {
  if (Object.hasOwn(map, key)) {
    map[key] += 1;
  } else if (Object.keys(map).length < limit) {
    map[key] = 1;
  } else {
    map.__other__ = (map.__other__ || 0) + 1;
  }
}

async function recordVisit(path, referrer) {
  const store = getStore({ name: STORE_NAME, consistency: "strong" });
  const now = new Date();
  const today = now.toISOString().slice(0, 10);

  for (let attempt = 0; attempt < 6; attempt += 1) {
    const current =
      (await store.getWithMetadata(SUMMARY_KEY, { type: "json" })) ||
      { data: null, etag: null };
    const summary = current.data || emptySummary();

    summary.total = Number(summary.total || 0) + 1;
    summary.days = trimOldDays(summary.days || {}, today);
    summary.days[today] = Number(summary.days[today] || 0) + 1;
    summary.pages = summary.pages || {};
    summary.referrers = summary.referrers || {};
    incrementMap(summary.pages, path, MAX_PAGE_KEYS);
    incrementMap(summary.referrers, referrer, MAX_REFERRER_KEYS);
    summary.updated_at = now.toISOString();

    const options = current.data
      ? { onlyIfMatch: current.etag }
      : { onlyIfNew: true };
    const result = await store.setJSON(SUMMARY_KEY, summary, options);
    if (result.modified) return summary;

    await new Promise((resolve) => setTimeout(resolve, 10 * (attempt + 1)));
  }

  throw new Error("Analytics counter was busy after all retries");
}

export default async (request) => {
  if (request.method !== "POST") {
    return jsonResponse({ status: "not_found" }, 404);
  }

  const contentLength = Number(request.headers.get("content-length") || 0);
  if (contentLength > MAX_BODY_BYTES) {
    return jsonResponse({ status: "payload_too_large" }, 413);
  }

  let payload;
  try {
    const rawBody = await request.text();
    if (rawBody.length > MAX_BODY_BYTES) {
      return jsonResponse({ status: "payload_too_large" }, 413);
    }
    payload = JSON.parse(rawBody);
  } catch (_) {
    return jsonResponse({ status: "invalid_json" }, 400);
  }

  const path = cleanPath(payload.path);
  if (!path) return jsonResponse({ status: "invalid_path" }, 400);

  try {
    await recordVisit(path, cleanReferrer(payload.referrer));
    return new Response(null, {
      status: 204,
      headers: {
        "Cache-Control": "no-store, max-age=0",
        "X-Analytics-Status": "recorded",
      },
    });
  } catch (error) {
    console.error("analytics_write_failed", error);
    return jsonResponse({ status: "temporarily_unavailable" }, 503);
  }
};
