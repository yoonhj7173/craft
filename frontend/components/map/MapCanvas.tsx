"use client";

// Pixi 맵 캔버스 래퍼 — 동적 import(클라이언트 전용). 데이터는 prop, 인터랙션은 콜백.
import { useEffect, useRef } from "react";
import type { MapData } from "@/lib/map/types";
import { PixiWorld, type WorldCallbacks } from "@/lib/map/world";
import { useStore } from "@/lib/store";

/**
 * MapCanvas — 사무실 맵을 실제로 그리는 화면. Pixi.js(게임용 2D 그래픽 엔진)로 방·캐릭터를 렌더한다.
 *
 * 무슨 일을 하나: 받은 맵 데이터(data)를 Pixi 월드에 그린다. 그리고 store를 '구독'해서, 에이전트
 *   상태가 바뀌면 React 화면을 다시 그리지 않고 Pixi에 직접 "이 캐릭터 표정 바꿔"라고 명령한다
 *   (성능 위해 React 리렌더 우회). 클릭·드래그 같은 상호작용은 callbacks로 부모(ProjectMap)에 알린다.
 * 누가 부르나: 메인 맵 화면 — frontend/app/app/[projectId]/page.tsx (무거워서 동적 import).
 * 연결: 실제 그리기 로직 → frontend/lib/map/world.ts. 상태 구독 → frontend/lib/store.ts.
 */
export default function MapCanvas({ data, callbacks }: { data: MapData; callbacks?: WorldCallbacks }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<PixiWorld | null>(null);

  useEffect(() => {
    let world: PixiWorld | null = null;
    let disposed = false;
    let unsub: (() => void) | null = null;
    const wrap = wrapRef.current!;
    (async () => {
      world = new PixiWorld(callbacks ?? {});
      await world.init(canvasRef.current!, wrap.clientWidth, wrap.clientHeight);
      if (disposed) { world.destroy(); return; }
      worldRef.current = world;
      world.render(data);
      // store 구독 — 상태 변경을 Pixi에 명령형으로 반영(React 리렌더 없이, D36).
      unsub = useStore.subscribe((state, prev) => {
        for (const id in state.agents) {
          if (state.agents[id].status !== prev.agents[id]?.status) {
            world!.updateAgentStatus(id, state.agents[id].status);
          }
        }
      });
    })();
    const ro = new ResizeObserver(() => world?.resize(wrap.clientWidth, wrap.clientHeight));
    ro.observe(wrap);
    return () => { disposed = true; unsub?.(); ro.disconnect(); world?.destroy(); worldRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 데이터 변경 시 재렌더.
  useEffect(() => { worldRef.current?.render(data); }, [data]);

  return (
    <div ref={wrapRef} className="relative h-full w-full overflow-hidden">
      <canvas ref={canvasRef} className="block" />
      {/* 줌 컨트롤(우측 중앙). */}
      <div className="absolute right-5 top-1/2 flex -translate-y-1/2 flex-col gap-1 rounded-tile bg-[rgba(36,46,66,0.92)] p-1 text-white">
        <button className="h-9 w-9 rounded-lg text-lg font-bold hover:bg-white/10" onClick={() => worldRef.current?.setZoom((worldRef.current?.zoom() ?? 1) * 1.15)}>+</button>
        <button className="h-9 w-9 rounded-lg font-mono text-[10px] hover:bg-white/10" onClick={() => worldRef.current?.render(data)}>fit</button>
        <button className="h-9 w-9 rounded-lg text-lg font-bold hover:bg-white/10" onClick={() => worldRef.current?.setZoom((worldRef.current?.zoom() ?? 1) / 1.15)}>−</button>
      </div>
    </div>
  );
}
