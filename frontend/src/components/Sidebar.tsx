"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Database, FlaskConical, LayoutDashboard, Search, Zap } from "lucide-react";
import clsx from "clsx";

const links = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/playground", label: "Playground", icon: Search },
  { href: "/pipelines", label: "Pipelines", icon: Zap },
  { href: "/evaluations", label: "Evaluations", icon: Activity },
  { href: "/documents", label: "Documents", icon: Database },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col py-6 px-4 shrink-0">
      <div className="mb-8 flex items-center gap-2 px-2">
        <FlaskConical className="text-indigo-400" size={22} />
        <span className="font-bold text-lg tracking-tight text-white">NeuroFlow</span>
      </div>

      <nav className="space-y-1">
        {links.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={clsx(
              "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
              pathname === href
                ? "bg-indigo-600 text-white"
                : "text-gray-400 hover:bg-gray-800 hover:text-white"
            )}
          >
            <Icon size={16} />
            {label}
          </Link>
        ))}
      </nav>

      <div className="mt-auto px-2 text-xs text-gray-600">
        NeuroFlow v1.0.0
      </div>
    </aside>
  );
}
