import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Instrument_Serif, Noto_Sans_Sinhala, Noto_Sans_Tamil } from "next/font/google";

import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const serif = Instrument_Serif({ variable: "--font-instrument-serif", subsets: ["latin"], weight: "400", style: ["normal", "italic"] });
const notoSinhala =Noto_Sans_Sinhala({ variable: "--font-noto-sinhala", subsets: ["sinhala"] });
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
      className={`${geistSans.variable} ${geistMono.variable} ${serif.variable} ${notoSinhala.variable} ${notoTamil.variable} h-full antialiased`}
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
