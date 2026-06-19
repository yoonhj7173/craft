"use client";

// Stripe Embedded Checkout 완료 후 돌아오는 페이지(빌링 D46). 크레딧 적립은 웹훅이 비동기 처리하므로
// 여기선 "곧 반영" 안내만. 워크스페이스로 돌아가는 버튼 제공.
import Link from "next/link";

export default function BillingReturn() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center" style={{ background: "#C6C9BC" }}>
      <div className="font-baloo text-2xl font-extrabold text-ink">결제 완료 🎉</div>
      <p className="max-w-sm text-sm text-secondary">
        크레딧이 곧 treasury에 반영됩니다. 워크스페이스로 돌아가 잠시 후 잔액을 확인하세요.
      </p>
      <Link href="/" className="btn-pill btn-primary text-sm">
        워크스페이스로
      </Link>
    </main>
  );
}
