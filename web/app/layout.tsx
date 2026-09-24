import type { Metadata, Viewport } from "next";
import { Geist_Mono, Noto_Sans_Sinhala, Noto_Sans_Tamil, Space_Grotesk, VT323 } from "next/font/google";

import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

// Space Grotesk carries the words; VT323, a terminal face, carries labels, numbers and one accent per headline.
const grotesk = Space_Grotesk({ variable: "--font-grotesk", subsets: ["latin"] });
const pixel = VT323({ variable: "--font-vt323", subsets: ["latin"], weight: "400" });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const notoSinhala = Noto_Sans_Sinhala({ variable: "--font-noto-sinhala", subsets: ["sinhala"] });
const notoTamil = Noto_Sans_Tamil({ variable: "--font-noto-tamil", subsets: ["tamil"] });

export const metadata: Metadata = {
  title: { default: "Lanka Link", template: "%s | Lanka Link" },
  description: "Fibre, home broadband and mobile data across Sri Lanka.",
};

// Edge to edge on notched phones; the bottom tab bar pads itself with the safe area inset.
export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${grotesk.variable} ${pixel.variable} ${geistMono.variable} ${notoSinhala.variable} ${notoTamil.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <TooltipProvider>
            {children}
            <Toaster />
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
