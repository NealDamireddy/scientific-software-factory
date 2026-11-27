import "./tokens.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { GeistSans } from "geist/font/sans";

export const metadata: Metadata = {
  title: "Emory Biophysics · Research workspace",
  description:
    "Interactive scientific workspace with illustrative experiments.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={GeistSans.variable}
      style={
        { "--font-geist": "var(--font-geist-sans)" } as React.CSSProperties
      }
    >
      <body style={{ margin: 0, fontFamily: "var(--font-geist), sans-serif" }}>
        {children}
      </body>
    </html>
  );
}
