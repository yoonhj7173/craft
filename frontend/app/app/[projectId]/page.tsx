// 프로젝트 오피스 맵 — Pixi 월드 + HUD는 item 21-25에서. 지금은 스텁.
export default function ProjectMap({ params }: { params: { projectId: string } }) {
  return (
    <main className="flex min-h-screen items-center justify-center font-nunito text-ink" style={{ background: "#C6C9BC" }}>
      <div className="text-center">
        <div className="font-baloo text-2xl font-extrabold">Office map</div>
        <p className="mt-1 text-secondary">Project {params.projectId.slice(0, 8)} — Pixi world coming (item 21).</p>
      </div>
    </main>
  );
}
