import { readFile } from "node:fs/promises";
import path from "node:path";

import { ImageResponse } from "next/og";

import { site } from "@/lib/site";

export const alt = `${site.name}: Python, data and AI engineer`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const font = (file: string) =>
  readFile(path.join(process.cwd(), "node_modules/@fontsource/archivo/files", file));

export default async function OpenGraphImage() {
  const [semibold, regular] = await Promise.all([
    font("archivo-latin-600-normal.woff"),
    font("archivo-latin-400-normal.woff"),
  ]);
  const bars = [520, 360, 200];
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        background: "#0f1623",
        color: "#e8ebf1",
        padding: "72px 80px",
        fontFamily: "Archivo",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {bars.map((w, i) => (
          <div key={w} style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <div
              style={{
                width: w,
                height: 14,
                borderRadius: 7,
                background: i === 2 ? "#3a475c" : "#2a3547",
              }}
            />
            {i === 2 && (
              <div style={{ width: 22, height: 22, borderRadius: 11, background: "#62c7a6" }} />
            )}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ fontSize: 34, color: "#9ba6b9", fontWeight: 400 }}>{site.name}</div>
        <div
          style={{ fontSize: 66, fontWeight: 600, lineHeight: 1.08, marginTop: 14, maxWidth: 980 }}
        >
          Data, AI and computer-vision systems that are deployed, measured and maintained.
        </div>
        <div style={{ fontSize: 28, color: "#8290a5", marginTop: 30 }}>{site.domain}</div>
      </div>
    </div>,
    {
      ...size,
      fonts: [
        { name: "Archivo", data: semibold, weight: 600, style: "normal" },
        { name: "Archivo", data: regular, weight: 400, style: "normal" },
      ],
    },
  );
}
