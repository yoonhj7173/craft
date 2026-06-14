"use client";

// 프로젝트 오피스 맵 — 실 /map 엔드포인트 연결. HUD/패널은 item 23-25에서 얹는다.
import { useEffect, useState } from "react";
import { useAuth, UserButton } from "@clerk/nextjs";
import dynamic from "next/dynamic";
import { apiFetch, E2E } from "@/lib/api";
import { useStore } from "@/lib/store";
import { connectSSE } from "@/lib/sse";
import type { MapData } from "@/lib/map/types";
import Hud from "@/components/hud/Hud";
import { PanelController, type Selection } from "@/components/panels/PanelController";
import { BoardOverlay, OutputsOverlay, SettingsOverlay, type OverlayKind } from "@/components/overlays/Overlays";

const MapCanvas = dynamic(() => import("@/components/map/MapCanvas"), { ssr: false });

export default function ProjectMap({ params }: { params: { projectId: string } }) {
  const { getToken: clerkToken } = useAuth();
  const getToken = async () => (E2E ? "e2e" : await clerkToken());
  const [data, setData] = useState<MapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<Selection>({ kind: "none" });
  const [overlay, setOverlay] = useState<OverlayKind>(null);

  async function loadMap() {
    const token = await getToken();
    const map = await apiFetch<MapData>(`/api/projects/${params.projectId}/map`, { token });
    useStore.getState().setSnapshot(map);
    setData(map);
  }

  useEffect(() => {
    let disconnect: (() => void) | null = null;
    (async () => {
      try {
        await loadMap();
        const token = await getToken();
        if (token) disconnect = connectSSE(params.projectId, token); // 라이브 SSE
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load map");
      }
    })();
    return () => disconnect?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.projectId]);

  async function persistRoom(teamId: string, x: number, y: number) {
    const token = await getToken();
    await apiFetch(`/api/teams/${teamId}`, { method: "PATCH", token, body: JSON.stringify({ room_x: x, room_y: y }) }).catch(() => {});
  }

  // 패널/모달 ↔ 오버레이 상호배타 — 하나 열면 다른 건 닫힌다.
  function openPanel(s: Selection) { setOverlay(null); setSel(s); }
  function openOverlay(o: OverlayKind) { setSel({ kind: "none" }); setOverlay(o); }
  function closeAll() { setSel({ kind: "none" }); setOverlay(null); }

  // Escape로 열린 패널/오버레이 닫기.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeAll(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // E2E QA 훅 — 캔버스 클릭 없이 패널/모달을 열 수 있게(테스트 전용).
  useEffect(() => {
    if (!E2E) return;
    (window as unknown as { __qa: unknown }).__qa = {
      selectAgent: (id: string) => openPanel({ kind: "agent", id }),
      selectTeam: (id: string) => openPanel({ kind: "team", id }),
      addAgent: (teamId: string) => openPanel({ kind: "addAgent", teamId }),
      addTeam: () => openPanel({ kind: "addTeam" }),
      openOverlay: (k: OverlayKind) => (k ? openOverlay(k) : closeAll()),
    };
  });

  async function sendChat(message: string): Promise<string | void> {
    try {
      const token = await getToken();
      const res = await apiFetch<{ reply: string }>(`/api/projects/${params.projectId}/chat`, {
        method: "POST", token, body: JSON.stringify({ message }),
      });
      return res.reply;
    } catch { /* HUD가 유저 버블만 보존 */ }
  }

  if (error) return <Centered>{error}</Centered>;
  if (!data) return <Centered>Loading office…</Centered>;

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <MapCanvas
        data={data}
        callbacks={{
          onRoomMoved: persistRoom,
          onSelectAgent: (id) => openPanel({ kind: "agent", id }),
          onSelectTeam: (id) => openPanel({ kind: "team", id }),
          onDeselect: closeAll,
        }}
      />
      <Hud
        projectName={data.project.name}
        onSend={sendChat}
        onFocusAgent={(id) => openPanel({ kind: "agent", id })}
        onOpen={(w) => {
          if (w === "addTeam") openPanel({ kind: "addTeam" });
          else openOverlay(w);
        }}
      />
      {!E2E && (
        // 계정 메뉴(아바타 → 로그아웃). 좌하단 고정.
        <div className="absolute bottom-5 left-5 z-20 rounded-full bg-white/80 p-0.5 shadow-card">
          <UserButton afterSignOutUrl="/" />
        </div>
      )}
      <PanelController projectId={params.projectId} getToken={getToken} mapData={data} sel={sel} setSel={setSel} onChanged={loadMap} />
      {overlay === "board" && <BoardOverlay projectId={params.projectId} getToken={getToken} onClose={() => setOverlay(null)} onFocus={(id) => { setOverlay(null); setSel({ kind: "agent", id }); }} />}
      {overlay === "outputs" && <OutputsOverlay projectId={params.projectId} getToken={getToken} onClose={() => setOverlay(null)} />}
      {overlay === "settings" && <SettingsOverlay projectId={params.projectId} getToken={getToken} projectName={data.project.name} paused={data.paused} onClose={() => setOverlay(null)} onChanged={loadMap} />}
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center font-nunito text-secondary" style={{ background: "#C6C9BC" }}>
      {children}
    </main>
  );
}
