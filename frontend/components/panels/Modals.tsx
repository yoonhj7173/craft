"use client";

// 관리 모달(item 24) — AddAgent(역할 카탈로그 프리필 + OUTPUT 3택, D38/D41) · AddTeam · Confirm.
import { useState } from "react";
import clsx from "clsx";
import { Overlay, PillButton } from "@/components/ui/primitives";
import { CARPET } from "@/lib/tokens";
import type { AgentRow, RoleTemplate, TeamTemplate } from "./types";

const TIERS = ["strong", "medium", "light"] as const;
const MAX = 5;

export interface AgentSubmit {
  role_key?: string; name: string; role_instructions: string; model_tier: string;
  output?: { type: "handoff" | "review_loop"; to_agent_id: string; max_iterations?: number };
}

export function AddAgentModal({ roles, teamAgents, full, onClose, onSubmit }: {
  roles: RoleTemplate[]; teamAgents: AgentRow[]; full: boolean; onClose: () => void; onSubmit: (a: AgentSubmit) => void;
}) {
  const [roleKey, setRoleKey] = useState<string>("");
  const [name, setName] = useState("");
  const [tier, setTier] = useState<string>("medium");
  const [role, setRole] = useState("");
  const [output, setOutput] = useState<"handoff" | "review_loop" | "final">("final");
  const [target, setTarget] = useState<string>(teamAgents[0]?.id ?? "");

  function pick(r: RoleTemplate) {
    setRoleKey(r.role_key); setName(r.display_name); setTier(r.default_tier);
    setRole(`(${r.display_name} — authored role; editable)`);
  }

  return (
    <Overlay onClose={onClose}>
      <div className="w-[660px] max-w-[92vw] p-7">
        <div className="font-baloo text-2xl font-extrabold">Hire an agent</div>
        {full && <div className="mt-3 rounded-xl bg-status-needs-input/15 px-4 py-2 text-sm font-bold text-status-needs-input">Desks are full — this team has the max {MAX} agents.</div>}

        <div className="mt-5">
          <Lbl>Pick a role</Lbl>
          <div className="mt-2 flex flex-wrap gap-2">
            {roles.map((r) => (
              <button key={r.role_key} onClick={() => pick(r)} className={clsx("rounded-pill border-2 px-3 py-1 text-sm font-bold", roleKey === r.role_key ? "border-primary-to bg-primary-to/15 text-primary-to" : "border-white bg-white/60")}>{r.display_name}</button>
            ))}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <div><Lbl>Name</Lbl><input value={name} onChange={(e) => setName(e.target.value)} className="mt-1 w-full rounded-pill border-2 border-white bg-white/70 px-4 py-2 outline-none" /></div>
          <div><Lbl>Model tier</Lbl><div className="mt-1 flex rounded-pill border-2 border-white bg-white/60 p-0.5">{TIERS.map((t) => (<button key={t} onClick={() => setTier(t)} className={clsx("flex-1 rounded-pill py-1.5 text-xs font-bold capitalize", tier === t ? "bg-primary-to text-white" : "text-secondary")}>{t}</button>))}</div></div>
        </div>

        <div className="mt-4"><Lbl>Role instructions</Lbl><textarea value={role} onChange={(e) => setRole(e.target.value)} rows={3} className="mt-1 w-full rounded-xl border-2 border-white bg-white/70 p-3 text-sm outline-none" placeholder="What this agent does, how it behaves…" /></div>

        <div className="mt-4">
          <Lbl>Output</Lbl>
          <div className="mt-1 flex gap-2">
            {([["handoff", "→ Hand off"], ["review_loop", "⇄ Review loop"], ["final", "✓ Final output"]] as const).map(([k, label]) => (
              <button key={k} onClick={() => setOutput(k)} className={clsx("flex-1 rounded-xl border-2 py-2 text-sm font-bold", output === k ? "border-primary-to bg-primary-to/15 text-primary-to" : "border-white bg-white/60")}>{label}</button>
            ))}
          </div>
          {output === "final" ? (
            <div className="mt-2 rounded-lg bg-status-done/10 px-3 py-2 text-xs text-status-done">Standalone — delivers straight to Outputs, no downstream agent.</div>
          ) : (
            <div className="mt-2 flex items-center gap-2 text-sm"><span className="font-mono text-[11px] text-muted">TO:</span>
              <select value={target} onChange={(e) => setTarget(e.target.value)} className="rounded-pill border-2 border-white bg-white/70 px-3 py-1">
                {teamAgents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-pill px-4 py-2 font-bold text-secondary">Cancel</button>
          <PillButton variant="confirm" disabled={full || !name.trim() || !role.trim()} onClick={() => onSubmit({
            role_key: roleKey || undefined, name, role_instructions: role, model_tier: tier,
            output: output === "final" ? undefined : { type: output, to_agent_id: target, max_iterations: output === "review_loop" ? 5 : undefined },
          })}>Hire agent</PillButton>
        </div>
      </div>
    </Overlay>
  );
}

export function AddTeamModal({ templates, inOffice, onClose, onSubmit }: {
  templates: TeamTemplate[]; inOffice: Set<string>; onClose: () => void; onSubmit: (key: string) => void;
}) {
  const [sel, setSel] = useState<string>("");
  return (
    <Overlay onClose={onClose}>
      <div className="w-[780px] max-w-[92vw] p-7">
        <div className="font-baloo text-2xl font-extrabold">Add a team</div>
        <div className="mt-5 grid grid-cols-2 gap-3">
          {templates.map((t) => {
            const here = inOffice.has(t.key);
            return (
              <button key={t.key} disabled={here} onClick={() => setSel(t.key)} className={clsx("relative rounded-2xl border-[3px] p-4 text-left", here ? "border-white opacity-50" : sel === t.key ? "border-primary-to" : "border-white")} style={{ background: sel === t.key ? CARPET[t.key] : "rgba(255,255,255,0.55)" }}>
                {here && <span className="absolute right-3 top-3 rounded-pill bg-muted/30 px-2 py-0.5 font-mono text-[10px]">In office</span>}
                <div className="font-baloo text-lg font-extrabold">{t.name}</div>
                <div className="mt-1 text-xs text-secondary">{t.description}</div>
              </button>
            );
          })}
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-pill px-4 py-2 font-bold text-secondary">Cancel</button>
          <PillButton variant="confirm" disabled={!sel} onClick={() => onSubmit(sel)}>Build room</PillButton>
        </div>
      </div>
    </Overlay>
  );
}

export function ConfirmDialog({ title, body, onCancel, onConfirm }: { title: string; body: string; onCancel: () => void; onConfirm: () => void }) {
  return (
    <Overlay onClose={onCancel}>
      <div className="w-[420px] p-7">
        <div className="font-baloo text-xl font-extrabold">{title}</div>
        <p className="mt-2 text-sm text-secondary">{body}</p>
        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-pill px-4 py-2 font-bold text-secondary">Cancel</button>
          <PillButton variant="danger" onClick={onConfirm}>Confirm</PillButton>
        </div>
      </div>
    </Overlay>
  );
}

function Lbl({ children }: { children: React.ReactNode }) {
  return <div className="font-mono text-[10px] uppercase tracking-wider text-muted">{children}</div>;
}
