import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Night Shift — research freezer incident response",
  description:
    "Night Shift coordinates research-freezer rescue from alarm to reconciled custody. " +
    "Specialist agents decide the response; deterministic rules decide what is allowed " +
    "to become true.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
