"use client";

// 맵 위 HUD 레이어(item 23) — 오케스트레이터 챗 · Activity 피드 · 벨/드로어 · 토스트 ·
// 토큰 카운터 · 프로젝트 스위처 · 유틸 버튼. 전부 store에서 파생(D36).
import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { useStore, type FeedEvent } from "@/lib/store";
import { STATUS_CHIP, visualStatus } from "@/lib/tokens";

export interface HudProps {
  projectName: string;
  onSend?: (msg: string) => Promise<string | void> | string | void;
  onFocusAgent?: (agentId: string) => void;
  onOpen?: (what: "settings" | "board" | "outputs" | "addTeam") => void;
  onSwitch?: () => void;
}

export default function Hud(props: HudProps) {
  const [chatFocused, setChatFocused] = useState(false);
  return (
    <>
      {/* 챗 포커스 시 월드 디밍. */}
      {chatFocused && <div className="pointer-events-none absolute inset-0 z-10 bg-[rgba(40,46,40,0.28)]" />}
      <ProjectSwitcher name={props.projectName} onSwitch={props.onSwitch} />
      <ActivityFeedAndBell onFocusAgent={props.onFocusAgent} />
      <ToastStack onFocusAgent={props.onFocusAgent} />
      <UtilityStack onOpen={props.onOpen} />
      <TokenCounter />
      <OrchestratorChat focused={chatFocused} setFocused={setChatFocused} onSend={props.onSend} />
    </>
  );
}

// --- 프로젝트 스위처(top-left) ---
function ProjectSwitcher({ name, onSwitch }: { name: string; onSwitch?: () => void }) {
  return (
    <button onClick={onSwitch} className="btn-pill btn-primary absolute left-5 top-5 z-20 max-w-[200px] text-sm">
      <span className="truncate">{name}</span> ▾
    </button>
  );
}

// --- Activity 피드 + 벨(top-right) ---
function ActivityFeedAndBell({ onFocusAgent }: { onFocusAgent?: (id: string) => void }) {
  const events = useStore((s) => s.events);
  const unread = useStore((s) => s.unread);
  const connected = useStore((s) => s.connected);
  const markAllRead = useStore((s) => s.markAllRead);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="absolute right-5 top-5 z-20 flex items-start gap-2">
      <button
        onClick={() => { setDrawerOpen((o) => !o); markAllRead(); }}
        className="relative flex h-11 w-11 items-center justify-center rounded-tile bg-[rgba(36,46,66,0.92)] text-lg text-white"
      >
        🔔
        {unread > 0 && <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-status-failed px-1 text-[10px] font-bold">{unread}</span>}
      </button>
      <div className="w-[296px] rounded-tile bg-[rgba(36,46,66,0.92)] p-3 text-white">
        <div className="mb-2 flex items-center justify-between">
          <span className="font-baloo text-sm font-bold">Activity</span>
          <span className="flex items-center gap-1 font-mono text-[10px]"><span className={clsx("h-1.5 w-1.5 rounded-full", connected ? "bg-status-done" : "bg-muted")} />LIVE</span>
        </div>
        <div className="max-h-[40vh] overflow-y-auto">
          {events.length === 0 && <div className="py-2 text-xs opacity-40">No activity yet</div>}
          {events.slice(0, 30).map((e) => (
            <FeedRow key={e.id} e={e} onClick={() => onFocusAgent?.(e.agentId)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function FeedRow({ e, onClick }: { e: FeedEvent; onClick: () => void }) {
  const v = visualStatus(e.status as any);
  const tinted = v === "failed" || v === "needs-input";
  return (
    <button onClick={onClick} className={clsx("flex w-full items-center justify-between gap-2 rounded px-1.5 py-1 text-left font-nunito text-[11px] hover:bg-white/5", tinted && "bg-white/[0.06]")}>
      <span className="truncate">
        <span className="opacity-50">[{e.team}]</span> {e.agent} <span style={{ color: chipFg(v) }}>{e.status}</span>
      </span>
      <span className="shrink-0 font-mono text-[9px] opacity-40">{time(e.ts)}</span>
    </button>
  );
}

// --- 토스트(top-center) — terminal/needs-input 이벤트. ---
function ToastStack({ onFocusAgent }: { onFocusAgent?: (id: string) => void }) {
  const events = useStore((s) => s.events);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const toasts = events.filter((e) => ["needs-input", "failed", "done"].includes(visualStatus(e.status as any)) && !dismissed.has(e.id)).slice(0, 3);
  return (
    <div className="pointer-events-none absolute left-1/2 top-5 z-30 flex -translate-x-1/2 flex-col items-center gap-2">
      {toasts.map((e) => (
        <div key={e.id} className="pointer-events-auto flex items-center gap-3 rounded-pill border-[2.5px] border-white bg-floor px-4 py-2 shadow-card">
          <span className="flex h-6 w-6 items-center justify-center rounded-full text-white text-xs" style={{ background: chipFg(visualStatus(e.status as any)) }}>!</span>
          <span className="font-nunito text-sm"><b>{e.agent}</b> ({e.team}) {e.status}</span>
          <button onClick={() => onFocusAgent?.(e.agentId)} className="btn-pill btn-primary !px-3 !py-1 text-xs">View</button>
          <button onClick={() => setDismissed((s) => new Set(s).add(e.id))} className="text-muted">×</button>
        </div>
      ))}
    </div>
  );
}

// --- 유틸 버튼(bottom-left) ---
function UtilityStack({ onOpen }: { onOpen?: (w: "settings" | "board" | "outputs" | "addTeam") => void }) {
  return (
    <div className="absolute bottom-5 left-5 z-20 flex flex-col gap-2">
      <Util onClick={() => onOpen?.("settings")}>⚙ Settings</Util>
      <Util onClick={() => onOpen?.("board")}>▦ Board</Util>
      <Util onClick={() => onOpen?.("outputs")}>📄 Outputs</Util>
      <Util variant="confirm" onClick={() => onOpen?.("addTeam")}>+ Team</Util>
    </div>
  );
}
function Util({ children, onClick, variant = "primary" }: { children: React.ReactNode; onClick?: () => void; variant?: "primary" | "confirm" }) {
  return <button onClick={onClick} className={clsx("btn-pill text-[13px]", variant === "confirm" ? "btn-confirm" : "btn-primary")}>{children}</button>;
}

// --- 토큰 카운터(bottom-right) ---
function TokenCounter() {
  const usage = useStore((s) => s.usage);
  const total = usage.tokensIn + usage.tokensOut;
  return (
    <div className="absolute bottom-5 right-5 z-20 rounded-tile bg-[rgba(36,46,66,0.92)] px-4 py-2 text-white">
      <div className="font-baloo text-sm font-bold">🪙 {total.toLocaleString()}</div>
      <div className="font-mono text-[10px] opacity-70">TOKENS TODAY</div>
    </div>
  );
}

// --- 오케스트레이터 챗(bottom-center) ---
function OrchestratorChat({ focused, setFocused, onSend }: { focused: boolean; setFocused: (f: boolean) => void; onSend?: HudProps["onSend"] }) {
  const [msg, setMsg] = useState("");
  const [bubbles, setBubbles] = useState<{ role: "user" | "orchestrator"; text: string }[]>([]);
  const ref = useRef<HTMLInputElement>(null);

  async function send() {
    const m = msg.trim();
    if (!m) return;
    setBubbles((b) => [...b, { role: "user", text: m }]);
    setMsg("");
    const reply = await onSend?.(m);
    if (typeof reply === "string" && reply) setBubbles((b) => [...b, { role: "orchestrator", text: reply }]);
  }

  return (
    <div className="absolute bottom-5 left-1/2 z-30 w-[640px] max-w-[90vw] -translate-x-1/2">
      {focused && bubbles.length > 0 && (
        <div className="mb-3 max-h-[40vh] space-y-2 overflow-y-auto">
          {bubbles.map((b, i) => (
            <div key={i} className={clsx("flex", b.role === "user" ? "justify-end" : "justify-start")}>
              <div className={clsx("max-w-[80%] rounded-2xl px-4 py-2 font-nunito text-sm shadow", b.role === "user" ? "bg-primary-to text-white" : "bg-white text-ink")}>
                {b.role === "orchestrator" && <span className="mr-2 font-baloo font-bold">O</span>}
                {b.text}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2 rounded-pill border-[2.5px] border-white bg-white/90 px-2 py-1 shadow-card">
        <input
          ref={ref}
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Tell your team what to do…"
          className="flex-1 bg-transparent px-3 py-2 font-nunito text-sm outline-none"
        />
        <button onMouseDown={(e) => e.preventDefault()} onClick={send} className="btn-pill btn-primary !px-4 !py-2 text-sm">Send</button>
      </div>
    </div>
  );
}

function chipFg(v: string): string {
  return (STATUS_CHIP[v] ?? STATUS_CHIP.idle).fg;
}
function time(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
