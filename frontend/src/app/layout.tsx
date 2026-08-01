import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NetaCheck — Public Record Verification Platform",
  description: "Every Politician. Every Record. Every Source.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
