"use client";

// 인스펙터 사이드 패널(item 24, D15/Flow 4) — 글래스 372px. 팀/에이전트 패널.
import { useState } from "react";
import clsx from "clsx";
import { GlassPanel, PillButton, StatusChip } from "@/components/ui/primitives";
import { STATUS_CHIP, visualStatus } from "@/lib/tokens";
import type { AgentPanelData, TeamPanelData } from "./types";

function Avatar({ label, color, size = 46 }: { label: string; color?: string; size?: number }) {
  return (
    <div className="flex items-center justify-center rounded-xl font-baloo font-extrabold text-ink"
      style={{ width: size, height: size, background: color ?? "#E2E4D0", fontSize: size * 0.4 }}>
      {label.slice(0, 1).toUpperCase()}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex-1 rounded-xl border border-white/60 bg-white/40 p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="font-baloo text-lg font-extrabold">{value}</div>
    </div>
  );
}

export function TeamPanel({ data, onClose, onAddAgent, onSelectAgent, onRemove }: {
  data: TeamPanelData; onClose: () => void; onAddAgent: () => void; onSelectAgent: (id: string) => void; onRemove: () => void;
}) {
  const attention = data.agents.filter((a) => ["needs-input", "blocked", "failed"].includes(visualStatus(a.status))).length;
  return (
    <PanelShell onClose={onClose}>
      <div className="flex items-center gap-3">
        <Avatar label={data.name} />
        <div>
          <div className="font-baloo text-xl font-extrabold">{data.name}</div>
          <div className="text-xs text-secondary">{data.agent_count} agents{attention > 0 && ` · ${attention} need attention`}</div>
        </div>
      </div>
      <div className="mt-4 flex gap-3">
        <Tile label="Agents" value={String(data.agent_count)} />
        <Tile label="Tokens" value={data.tokens_total.toLocaleString()} />
      </div>
      <div className="mt-4 space-y-1">
        {data.agents.map((a) => (
          <button key={a.id} onClick={() => onSelectAgent(a.id)} className="flex w-full items-center justify-between rounded-xl bg-white/40 px-3 py-2 hover:bg-white/60">
            <span className="flex items-center gap-2"><Avatar label={a.name} size={28} /><span className="font-nunito text-sm font-bold">{a.name}</span><span className="font-mono text-[10px] text-muted">{a.model_tier}</span></span>
            <StatusChip status={a.status} />
          </button>
        ))}
      </div>
      <div className="mt-5 flex flex-col gap-2">
        <PillButton variant="confirm" onClick={onAddAgent}>+ Add agent</PillButton>
        <PillButton variant="danger" onClick={onRemove}>Remove team</PillButton>
      </div>
    </PanelShell>
  );
}

export function AgentPanel({ data, onClose, onStop, onRemove, onProvideInput }: {
  data: AgentPanelData; onClose: () => void; onStop: () => void; onRemove: () => void; onProvideInput: (text: string) => void;
}) {
  const v = visualStatus(data.status);
  const headerTint = v === "needs-input" ? "#FBEFCB" : v === "failed" ? "#F8DAD3" : "#DCEEF8";
  const working = data.status === "working" || data.status === "queued";
  const [input, setInput] = useState("");
  return (
    <PanelShell onClose={onClose}>
      <div className="-mx-5 -mt-5 mb-4 rounded-tr-card px-5 pb-4 pt-5" style={{ background: headerTint }}>
        <div className="font-mono text-[10px] uppercase tracking-wider text-secondary">Agent</div>
        <div className="mt-2 flex items-center gap-3">
          <Avatar label={data.name} size={50} />
          <div><div className="font-baloo text-xl font-extrabold">{data.name}</div><StatusChip status={data.status} /></div>
        </div>
      </div>

      <Section title="Role">{data.role_instructions.split("\n")[0]}</Section>
      <div className="mt-3"><Label>Model</Label><span className="inline-block rounded-pill bg-primary-to/20 px-3 py-0.5 text-sm font-bold text-primary-to">{data.model_tier}</span></div>

      <div className="mt-3">
        <Label>Connection</Label>
        {data.outgoing ? (
          <span className={clsx("inline-block rounded-pill px-3 py-0.5 text-xs font-bold", data.outgoing.type === "handoff" ? "bg-primary-to/15 text-primary-to" : "bg-purple-200 text-purple-700")}>
            {data.outgoing.type === "handoff" ? "→ handoff" : `⇄ review loop · max ${data.outgoing.max_iterations}`} · {data.outgoing.to_agent_name}
          </span>
        ) : <span className="text-xs text-muted">Final output (no downstream)</span>}
      </div>

      <div className="mt-4 flex gap-3">
        <Tile label="Tokens" value={data.tokens_total.toLocaleString()} />
        <Tile label="Status" value={visualStatus(data.status)} />
      </div>

      {(data.status === "needs-input" || data.status === "blocked") && (
        <div className="mt-4 rounded-xl border-2 border-status-needs-input/40 bg-status-needs-input/10 p-3">
          <Label>Provide human input</Label>
          {data.awaiting_prompt && <p className="mt-1 text-sm font-bold text-ink-soft">{data.awaiting_prompt}</p>}
          <textarea value={input} onChange={(e) => setInput(e.target.value)} className="mt-1 w-full rounded-lg border border-white bg-white/70 p-2 text-sm outline-none" rows={2} placeholder="Answer the agent's question…" />
          <PillButton variant="confirm" className="mt-2 w-full" onClick={() => onProvideInput(input)}>Send &amp; resume</PillButton>
        </div>
      )}
      {data.status === "failed" && (
        <div className="mt-4 rounded-xl border-2 border-status-failed/40 bg-status-failed/10 p-3 text-sm text-status-failed">{data.error_summary || "Failed — retry or check the verification record."}</div>
      )}

      <div className="mt-5 flex flex-col gap-2">
        {working && <PillButton variant="danger" onClick={onStop}>■ Stop task</PillButton>}
        <PillButton variant="primary" disabled={working} onClick={onRemove} className={working ? "" : "!bg-none !bg-white/40 !text-secondary !shadow-none"}>{working ? "Stop the task before removing" : "Remove agent"}</PillButton>
      </div>
    </PanelShell>
  );
}

function PanelShell({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="absolute left-0 top-0 z-40 h-full">
      <GlassPanel className="h-full overflow-y-auto rounded-none">
        <button onClick={onClose} className="absolute right-4 top-4 text-lg text-muted hover:text-ink">×</button>
        {children}
      </GlassPanel>
    </div>
  );
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="mt-3"><Label>{title}</Label><div className="text-sm text-ink-soft">{children}</div></div>;
}
function Label({ children }: { children: React.ReactNode }) {
  return <div className="font-mono text-[10px] uppercase tracking-wider text-muted">{children}</div>;
}
