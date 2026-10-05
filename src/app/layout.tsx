import type { Metadata } from "next";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";
import "./independent.css";
import { Workspace } from "@/components/workspace";
import { ThemeProvider } from "@/components/theme-provider";
import { THEME_INITIALIZATION_SCRIPT } from "@/lib/theme";
export const metadata: Metadata = {
  title: "ARSIA — Road safety intelligence",
  description:
    "Explore road crash trends, severity and local areas using a read-only project snapshot of NSW, VIC and QLD source data, with definitions and limitations alongside the results.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="light" data-theme="light" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{ __html: THEME_INITIALIZATION_SCRIPT }}
        />
      </head>
      <body>
        <ThemeProvider>
          <Workspace>{children}</Workspace>
        </ThemeProvider>
      </body>
    </html>
  );
}
