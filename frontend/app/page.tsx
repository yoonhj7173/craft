import Link from "next/link";

// 임시 홈 — 온보딩/맵은 item 20-21에서. 지금은 디자인 시스템 링크.
export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 font-nunito text-ink">
      <h1 className="font-baloo text-4xl font-extrabold">Craft</h1>
      <p className="text-secondary">Run a virtual company of AI agents.</p>
      <Link href="/design" className="btn-pill btn-primary text-[15px]">
        Design system →
      </Link>
    </main>
  );
}
