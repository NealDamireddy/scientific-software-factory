import "./tokens.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { GeistSans } from "geist/font/sans";

export const metadata: Metadata = {
  title: "Emory Biophysics · Research workspace",
  description:
    "Project investigations, procedures, and analysis in Lab Factory.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={GeistSans.variable}>
      <body>{children}</body>
    </html>
  );
}
