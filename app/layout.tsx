import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Voice2 · 本地语音运行时",
  description: "硬件自适应、本地优先的音色克隆与实时语音平台。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
