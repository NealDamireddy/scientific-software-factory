import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lab Factory",
};

// Applies the stored theme before first paint, so a dark choice never flashes light. It must use
// the same key and values as setTheme in components/ClientContext.tsx ("labfactory.theme").
const THEME_SCRIPT =
  'try{var t=localStorage.getItem("labfactory.theme");' +
  'if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}';

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
