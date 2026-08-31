import type { Metadata } from "next";
import "./globals.css";

const SITE_URL = "https://nightshift-web-xk6xxtobta-uc.a.run.app";

const DESCRIPTION =
  "Night Shift assesses a research-freezer incident, reserves safe backup capacity, " +
  "coordinates responders, verifies each transfer, and closes only when everything is " +
  "accounted for. Specialist agents decide the response, deterministic rules decide " +
  "what is allowed to become true, and every closed incident ships a signed manifest " +
  "anyone can re-verify.";

export const metadata: Metadata = {
  // Social cards need absolute URLs, and the image below is declared as a site-root path.
  metadataBase: new URL(SITE_URL),
  title: "Night Shift",
  description: DESCRIPTION,
  applicationName: "Night Shift",
  icons: {
    icon: [{ url: "/favicon.svg", type: "image/svg+xml" }],
    shortcut: "/favicon.svg",
  },
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "Night Shift",
    title: "Night Shift",
    description: DESCRIPTION,
    images: [
      {
        url: "/brand/thermal-proof.webp",
        width: 1448,
        height: 1086,
        alt: "Night Shift thermal trace artwork",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Night Shift",
    description: DESCRIPTION,
    images: ["/brand/thermal-proof.webp"],
  },
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
