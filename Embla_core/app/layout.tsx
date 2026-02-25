import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Embla Core",
  description: "Embla autonomous agent operations console",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
