import { clerkMiddleware } from "@clerk/nextjs/server";

// 앱 라우트는 Clerk 게이트(D24). 정적/마케팅은 제외.
export default clerkMiddleware();

export const config = {
  matcher: ["/((?!_next|.*\\..*).*)", "/(api|trpc)(.*)"],
};
