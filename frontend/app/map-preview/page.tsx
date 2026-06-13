"use client";

// 맵 + 상태 파이프라인 프리뷰 — 시뮬레이트 버튼이 store.applyStatus를 쏘면
// 맵 글로우/배지 + 미니 피드가 같은 소스에서 동시에 갱신된다(item 22 증명).
import { useEffect } from "react";
import dynamic from "next/dynamic";
import type { MapData } from "@/lib/map/types";
import { useStore } from "@/lib/store";
import type { AgentStatus } from "@/lib/tokens";
import Hud from "@/components/hud/Hud";

const MapCanvas = dynamic(() => import("@/components/map/MapCanvas"), { ssr: false });

const MOCK: MapData = {
  project: { id: "preview", name: "Acme Studio", paused: false },
  paused: false,
  teams: [
    {
      id: "t1", name: "Development", template_key: "development", engine: "agent_sdk",
      room_x: 40, room_y: 40,
      agents: [
        { id: "a1", name: "SWE", model_tier: "strong", slot: 0, status: "idle" },
        { id: "a2", name: "QA", model_tier: "medium", slot: 1, status: "idle" },
      ],
    },
    {
      id: "t2", name: "Product Planning", template_key: "planning", engine: "crew",
      room_x: 540, room_y: 40,
      agents: [{ id: "b1", name: "PM", model_tier: "strong", slot: 0, status: "idle" }],
    },
  ],
  edges: [],
};

export default function MapPreview() {
  useEffect(() => { useStore.getState().setSnapshot(MOCK); }, []);
  const events = useStore((s) => s.events);

  function sim(agentId: string, status: AgentStatus) {
    useStore.getState().applyStatus(agentId, status);
  }

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <MapCanvas data={MOCK} />
      <Hud projectName="Acme Studio" onSend={() => "On it — Research is investigating; Planning will pick up the output."} />
      {/* 시뮬레이트 컨트롤(프리뷰 전용) */}
      <div className="absolute left-1/2 top-20 z-40 flex -translate-x-1/2 gap-1 rounded-tile bg-white/80 p-2 text-sm">
        <Btn onClick={() => sim("a1", "working")}>SWE working</Btn>
        <Btn onClick={() => sim("a2", "needs-input")}>QA needs-input</Btn>
        <Btn onClick={() => sim("b1", "failed")}>PM failed</Btn>
      </div>
    </div>
  );
}

function Btn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return <button onClick={onClick} className="rounded-pill border-2 border-white bg-primary-to px-2 py-1 text-[11px] font-bold text-white">{children}</button>;
}
