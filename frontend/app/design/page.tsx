"use client";

// 디자인 시스템 레퍼런스 — 핸드오프 Design System 문서와 대조하는 라우트(item 19 verify).
import { PillButton, StatusChip, GlassPanel, DarkTile, Stepper } from "@/components/ui/primitives";
import { CARPET, STATUS_GLOW, STATUS_BADGE, type AgentStatus } from "@/lib/tokens";

const STATUSES: AgentStatus[] = ["idle", "queued", "working", "needs-input", "done", "failed"];

export default function DesignPage() {
  return (
    <main className="min-h-screen p-10 font-nunito text-ink" style={{ background: "#C6C9BC" }}>
      <h1 className="mb-8 font-baloo text-3xl font-extrabold">pondas — Design System</h1>

      <Section title="Pill buttons">
        <PillButton variant="primary">Get started →</PillButton>
        <PillButton variant="confirm">Enter the office →</PillButton>
        <PillButton variant="danger">Remove team</PillButton>
        <PillButton variant="primary" disabled>Disabled</PillButton>
      </Section>

      <Section title="Status chips">
        {STATUSES.map((s) => (
          <StatusChip key={s} status={s} />
        ))}
      </Section>

      <Section title="Status glow + badge (Workstation)">
        {STATUSES.map((s) => {
          const glow = STATUS_GLOW[s];
          const badge = STATUS_BADGE[s];
          return (
            <div key={s} className="flex flex-col items-center gap-2">
              <div
                className="relative h-14 w-14 rounded-tile bg-navy"
                style={{ boxShadow: glow ? `-4px 0 16px 5px ${glow}` : undefined }}
              >
                {badge && (
                  <span
                    className="absolute -right-2 -top-2 flex h-7 w-7 items-center justify-center rounded-full border-[3px] border-white font-baloo text-sm font-extrabold text-white"
                    style={{ background: badge.color }}
                  >
                    {badge.glyph}
                  </span>
                )}
              </div>
              <span className="font-mono text-[10px] text-secondary">{s}</span>
            </div>
          );
        })}
      </Section>

      <Section title="Team carpets">
        {Object.entries(CARPET).map(([team, color]) => (
          <div key={team} className="flex flex-col items-center gap-1">
            <div className="h-14 w-20 rounded-lg border-[3px] border-white" style={{ background: color }} />
            <span className="font-mono text-[10px] text-secondary">{team}</span>
          </div>
        ))}
      </Section>

      <Section title="Stepper">
        <Stepper steps={["Sign in", "Name", "Project", "Teams", "Context"]} current={2} />
      </Section>

      <Section title="Glass panel + dark tile">
        <GlassPanel className="!w-[300px] rounded-card">
          <div className="font-baloo text-xl font-extrabold">Team panel</div>
          <p className="mt-1 text-sm text-secondary">372px glassy side panel.</p>
        </GlassPanel>
        <DarkTile>
          <div className="font-baloo text-sm font-bold">🪙 12,480</div>
          <div className="font-mono text-[10px] opacity-70">TOKENS TODAY</div>
        </DarkTile>
      </Section>
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="mb-4 font-mono text-xs uppercase tracking-wider text-secondary">{title}</h2>
      <div className="flex flex-wrap items-center gap-4">{children}</div>
    </section>
  );
}
