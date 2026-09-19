import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "片场 · AI 导演工作台",
  description: "面向中文 AI 漫剧的多 Agent 导演工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
