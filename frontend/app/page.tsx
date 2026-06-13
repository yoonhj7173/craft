import Link from "next/link";

// 임시 홈 — 정식 랜딩은 item 27. Get started → 온보딩.
export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-5 font-nunito text-ink" style={{ background: "#C6C9BC" }}>
      <h1 className="font-baloo text-5xl font-extrabold">Craft</h1>
      <p className="text-lg text-secondary">Run a virtual company of AI agents.</p>
      <div className="flex gap-3">
        <Link href="/onboarding" className="btn-pill btn-primary text-[15px]">Get started →</Link>
        <Link href="/design" className="btn-pill btn-confirm text-[15px]">Design system</Link>
      </div>
    </main>
  );
}
