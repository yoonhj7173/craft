// 백엔드 API 클라이언트 — Clerk JWT를 Authorization으로 싣는다(D24).
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// E2E 모드(dev 전용) — Clerk 사인인 우회. 백엔드도 E2E_AUTH_BYPASS로 매칭.
export const E2E = process.env.NEXT_PUBLIC_E2E === "1";

export async function apiFetch<T>(
  path: string,
  opts: RequestInit & { token?: string | null } = {},
): Promise<T> {
  const { token, headers, ...rest } = opts;
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  });
  if (!res.ok) {
    // 4xx(클라이언트/검증)는 백엔드 detail이 유저용 메시지(예: "desks are full") → 노출.
    // 5xx(서버)는 내부 정보 누출 방지 → 일반 메시지(상세는 콘솔/서버 로그에만).
    if (res.status >= 500) {
      console.error("server error", res.status, await res.text().catch(() => ""));
      throw new Error("Something went wrong. Please try again.");
    }
    let detail = "";
    try {
      const j = await res.json();
      detail = typeof j?.detail === "string" ? j.detail : "";
    } catch { /* non-JSON */ }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// P0 팀 템플릿(GET /templates와 일치, D44 — Data 제외). 정적 폴백.
export const TEAM_TEMPLATES = [
  { key: "planning", name: "Product Planning", description: "Defines what to build and why — PRDs and specs.", starter: "PM" },
  { key: "research", name: "Research", description: "Investigates markets, competitors, user needs.", starter: "Researcher" },
  { key: "design", name: "Design", description: "Designs and builds the UI — code + screenshots.", starter: "Product Designer" },
  { key: "development", name: "Development", description: "Implements, verifies, and reviews working software.", starter: "Software Engineer" },
] as const;
