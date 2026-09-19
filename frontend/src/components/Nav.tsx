"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard" },
  { href: "/history", label: "History" },
  { href: "/status", label: "Status" },
  { href: "/disclaimer", label: "Disclaimer" },
];

const README_URL = "https://github.com/up2itnow0822/ReadyTrader-Crypto#readme";

export function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main">
      <ul className="nav-list">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href;
          return (
            <li key={item.href}>
              <Link href={item.href} aria-current={active ? "page" : undefined} onClick={onNavigate}>
                {item.label}
              </Link>
            </li>
          );
        })}
        <li>
          <a href={README_URL} target="_blank" rel="noopener noreferrer">
            Docs <span className="sr-only">(opens the README on GitHub in a new tab)</span>
          </a>
        </li>
      </ul>
    </nav>
  );
}
