// 디자인 토큰의 TS 표현 — Pixi(월드)와 React(HUD)가 공유(D36).
// Tailwind는 클래스용, 여기는 Pixi/런타임 계산용 raw 값.

export type AgentStatus =
  | "idle"
  | "queued"
  | "working"
  | "blocked"
  | "needs-input"
  | "done"
  | "failed";

// 모니터 글로우 색(Workstation 스펙). blocked는 needs-input과 동일(D36).
export const STATUS_GLOW: Record<AgentStatus, string | null> = {
  idle: null,
  queued: "rgba(247,183,49,0.3)",
  working: "rgba(79,195,232,0.55)",
  blocked: "rgba(247,183,49,0.55)",
  "needs-input": "rgba(247,183,49,0.55)",
  done: "rgba(95,201,110,0.55)",
  failed: "rgba(232,80,58,0.55)",
};

// 머리 위 배지(없으면 null). 영속 배지: "!"(needs-input/blocked), "×"(failed).
export const STATUS_BADGE: Record<AgentStatus, { glyph: string; color: string } | null> = {
  idle: null,
  queued: null,
  working: null,
  blocked: { glyph: "!", color: "#F7B731" },
  "needs-input": { glyph: "!", color: "#F7B731" },
  done: { glyph: "✓", color: "#5FC96E" },
  failed: { glyph: "×", color: "#E8503A" },
};

// 상태 chip 페어(bg/fg) — README §Colors.
export const STATUS_CHIP: Record<string, { bg: string; fg: string }> = {
  working: { bg: "#DCEEF8", fg: "#2C6FA0" },
  "needs-input": { bg: "#FBEFCB", fg: "#8A6200" },
  queued: { bg: "#FBEFCB", fg: "#8A6200" },
  done: { bg: "#E0F2E5", fg: "#2C7A4A" },
  failed: { bg: "#F8DAD3", fg: "#B23A26" },
  idle: { bg: "#ECE8DD", fg: "#6A6258" },
  blocked: { bg: "#FBEFCB", fg: "#8A6200" },
};

export const CARPET: Record<string, string> = {
  research: "#C2DAC6",
  development: "#C8D6E4",
  planning: "#DDD3E4",
  design: "#EEE7D6",
  data: "#E2EAD8",
};

// 백엔드 7-상태 → UI 6-비주얼(blocked→needs-input, D36).
export function visualStatus(s: AgentStatus): AgentStatus {
  return s === "blocked" ? "needs-input" : s;
}
