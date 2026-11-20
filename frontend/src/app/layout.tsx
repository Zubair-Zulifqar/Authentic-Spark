import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Shell } from "@/components/shell";

export const metadata: Metadata = { title: "Authentic Spark", description: "Agency operations platform" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers><Shell>{children}</Shell></Providers>
      </body>
    </html>
  );
}
