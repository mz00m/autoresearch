import type { Metadata } from "next";
import { Source_Serif_4 } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const serif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: "fund — daily research note",
  description: "Daily trade guide and closeout for the fund/ paper portfolio.",
};

const nav = [
  { href: "/", label: "Today" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/sell-guide", label: "Sell guide" },
  { href: "/history", label: "History" },
  { href: "/compare", label: "Compare" },
  { href: "/strategies", label: "Strategies" },
  { href: "/schedule", label: "Schedule" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={serif.variable}>
      <body>
        <header className="border-b border-rule bg-paper sticky top-0 z-10 backdrop-blur-sm bg-paper/85">
          <div className="max-w-6xl mx-auto px-6 lg:px-10 h-14 flex items-center justify-between">
            <Link href="/" className="flex items-baseline gap-3">
              <span className="font-serif text-xl font-semibold tracking-tight">
                fund
              </span>
              <span className="eyebrow hidden sm:inline">paper research</span>
            </Link>
            <nav className="flex gap-6 text-sm">
              {nav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="text-ink/70 hover:text-ink transition-colors"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="max-w-6xl mx-auto px-6 lg:px-10 py-10 lg:py-14">
          {children}
        </main>
        <footer className="border-t border-rule mt-24 py-8">
          <div className="max-w-6xl mx-auto px-6 lg:px-10 text-xs text-muted flex justify-between">
            <span>
              Pure paper research. Every live order remains human-gated per
              <code className="ml-1 font-mono text-[11px]">fund.md §7</code>.
            </span>
            <span className="num">
              {new Date().toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}
            </span>
          </div>
        </footer>
      </body>
    </html>
  );
}
