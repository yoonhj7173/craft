/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pixi 캔버스가 StrictMode의 dev 더블마운트(init/destroy 경합)와 충돌 → 끔.
  // 프로덕션 동작엔 영향 없음(StrictMode 더블마운트는 dev 전용). destroy도 별도 견고화됨.
  reactStrictMode: false,
};

export default nextConfig;
