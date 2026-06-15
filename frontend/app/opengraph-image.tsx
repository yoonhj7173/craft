// 소셜 공유 썸네일(카톡/슬랙/X) — 로고 + pondas.ai. Next가 자동으로 OG 메타에 연결.
import { ImageResponse } from "next/og";
import { readFileSync } from "fs";
import { join } from "path";

export const runtime = "nodejs";
export const alt = "pondas.ai — Run a virtual company of AI agents.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// 512 아이콘을 data URI로 임베드(빌드 시 1회 읽음).
const logo = readFileSync(join(process.cwd(), "app/icon.png")).toString("base64");

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
        <img src={`data:image/png;base64,${logo}`} width={200} height={200} style={{ borderRadius: 40 }} />
        <div style={{ fontSize: 88, fontWeight: 800, color: "#1f2a44", letterSpacing: -2 }}>pondas.ai</div>
        <div style={{ fontSize: 34, color: "#6b7280" }}>Run a virtual company of AI agents.</div>
      </div>
    ),
    { ...size },
  );
}
