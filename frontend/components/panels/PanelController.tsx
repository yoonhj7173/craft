"use client";

// 패널/모달 컨트롤러(item 24) — 맵/HUD 선택을 받아 데이터 fetch + 패널/모달 렌더 + 제출.
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { MapData } from "@/lib/map/types";
import { AgentPanel, TeamPanel } from "./InspectorPanel";
import { AddAgentModal, AddTeamModal, ConfirmDialog, type AgentSubmit } from "./Modals";
import type { AgentPanelData, TeamPanelData, TeamTemplate } from "./types";

export type Selection =
  | { kind: "none" }
  | { kind: "team"; id: string }
  | { kind: "agent"; id: string }
  | { kind: "addAgent"; teamId: string }
  | { kind: "addTeam" };

export function PanelController({ projectId, getToken, mapData, sel, setSel, onChanged }: {
  projectId: string; getToken: () => Promise<string | null>; mapData: MapData;
  sel: Selection; setSel: (s: Selection) => void; onChanged: () => void;
}) {
  const [team, setTeam] = useState<TeamPanelData | null>(null);
  const [agent, setAgent] = useState<AgentPanelData | null>(null);
  const [templates, setTemplates] = useState<TeamTemplate[]>([]);
  const [confirm, setConfirm] = useState<null | { title: string; body: string; run: () => void }>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const token = await getToken();
      if (sel.kind === "team") setTeam(await apiFetch(`/api/teams/${sel.id}`, { token }));
      else if (sel.kind === "agent") setAgent(await apiFetch(`/api/agents/${sel.id}`, { token }));
      else if (sel.kind === "addTeam" || sel.kind === "addAgent") setTemplates(await apiFetch(`/api/templates`, { token }));
    })().catch(() => {});
  }, [sel, getToken]);

  async function call(path: string, method: string, body?: object) {
    try {
      const token = await getToken();
      await apiFetch(path, { method, token, body: body ? JSON.stringify(body) : undefined });
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Action failed");
      setTimeout(() => setErr(null), 4000);
      throw e;
    }
  }

  const errBanner = err ? (
    <div className="fixed left-1/2 top-20 z-[70] -translate-x-1/2 rounded-pill border-[2.5px] border-white bg-status-failed px-4 py-2 text-sm font-bold text-white shadow-card">{err}</div>
  ) : null;

  const close = () => setSel({ kind: "none" });

  if (sel.kind === "team" && team) {
    return (
      <>
        <TeamPanel data={team} onClose={close}
          onAddAgent={() => setSel({ kind: "addAgent", teamId: team.id })}
          onSelectAgent={(id) => setSel({ kind: "agent", id })}
          onRemove={() => setConfirm({ title: "Remove team?", body: `${team.name} and its agents/edges will be removed.`, run: async () => { await call(`/api/teams/${team.id}`, "DELETE"); close(); } })} />
        {confirmEl()}
        {errBanner}
      </>
    );
  }
  if (sel.kind === "agent" && agent) {
    return (
      <>
        <AgentPanel data={agent} onClose={close}
          onStop={async () => { if (agent.current_task_id) { await call(`/api/tasks/${agent.current_task_id}/stop`, "POST"); setSel({ kind: "agent", id: agent.id }); } }}
          onProvideInput={async (text) => { if (agent.current_task_id) { await call(`/api/tasks/${agent.current_task_id}/continue`, "POST", { input: text }); setSel({ kind: "agent", id: agent.id }); } }}
          onRemove={() => setConfirm({ title: "Remove agent?", body: `${agent.name} will be removed.`, run: async () => { await call(`/api/agents/${agent.id}`, "DELETE"); close(); } })} />
        {confirmEl()}
        {errBanner}
      </>
    );
  }
  if (sel.kind === "addAgent") {
    const teamRoom = mapData.teams.find((t) => t.id === sel.teamId);
    const roles = templates.find((t) => t.key === teamRoom?.template_key)?.roles ?? [];
    const full = (teamRoom?.agents.length ?? 0) >= 5;
    return (
      <>
        <AddAgentModal roles={roles} teamAgents={(teamRoom?.agents ?? []).map((a) => ({ ...a }))} full={full} onClose={close}
          onSubmit={async (a: AgentSubmit) => { try { await call(`/api/teams/${sel.teamId}/agents`, "POST", a); close(); } catch { /* banner */ } }} />
        {errBanner}
      </>
    );
  }
  if (sel.kind === "addTeam") {
    const inOffice = new Set(mapData.teams.map((t) => t.template_key));
    return (
      <>
        <AddTeamModal templates={templates} inOffice={inOffice} onClose={close}
          onSubmit={async (key) => { try { await call(`/api/projects/${projectId}/teams`, "POST", { template_key: key }); close(); } catch { /* banner */ } }} />
        {errBanner}
      </>
    );
  }
  return null;

  function confirmEl() {
    if (!confirm) return null;
    return <ConfirmDialog title={confirm.title} body={confirm.body} onCancel={() => setConfirm(null)} onConfirm={() => { confirm.run(); setConfirm(null); }} />;
  }
}
