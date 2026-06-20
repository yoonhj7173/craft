// 소셜 공유 썸네일(카톡/슬랙/X) — 로고 + pondas.ai. Next가 자동으로 OG 메타에 연결.
import { ImageResponse } from "next/og";
import { readFileSync } from "fs";

export const runtime = "nodejs";
export const alt = "pondas.ai — Run a virtual company of AI agents.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// 아이콘을 data URI로 임베드. import.meta.url 기준 경로라 Next가 에셋을 함수 번들에 포함시켜
// 동적 라우트(/app/[projectId]) 런타임에서도 존재한다. (process.cwd() 기반은 서버리스에서 ENOENT →
// OG 메타 생성 크래시 → 페이지 500이었음.) 그래도 못 읽으면 try/catch로 로고 없이 렌더(500 방지).
let logo = "";
try {
  logo = readFileSync(new URL("./icon.png", import.meta.url)).toString("base64");
} catch {
  /* asset not available in this runtime — render OG without the logo */
}

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 28,
          background: "#FBFAF6",
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {logo && <img src={`data:image/png;base64,${logo}`} width={200} height={200} style={{ borderRadius: 40 }} />}
        <div style={{ fontSize: 88, fontWeight: 800, color: "#1f2a44", letterSpacing: -2 }}>pondas.ai</div>
        <div style={{ fontSize: 34, color: "#6b7280" }}>Run a virtual company of AI agents.</div>
      </div>
    ),
    { ...size },
  );
}
