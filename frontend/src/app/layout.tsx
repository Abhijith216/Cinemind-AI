import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "CineMind — explainable movie discovery",
  description:
    "Describe the movie you're in the mood for; CineMind explains why each pick fits.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
