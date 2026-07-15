"use client";

import {
  Activity,
  BarChart3,
  Bot,
  Building2,
  ClipboardList,
  CreditCard,
  Gauge,
  HeartPulse,
  History,
  Package,
  Receipt,
  RefreshCw,
  Settings
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { logout } from "@/lib/auth";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: Gauge },
  { href: "/products", label: "Products", icon: Package },
  { href: "/organizations", label: "Organizations", icon: Building2 },
  { href: "/plans", label: "Plans", icon: Receipt },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/revenue", label: "Revenue", icon: BarChart3 },
  { href: "/ai-pricing", label: "AI Pricing", icon: Bot },
  { href: "/ai-usage", label: "AI Usage", icon: Bot },
  { href: "/product-health", label: "Product Health", icon: HeartPulse },
  { href: "/sync-status", label: "Sync Status", icon: RefreshCw },
  { href: "/pending-changes", label: "Pending Changes", icon: ClipboardList },
  { href: "/audit", label: "Audit Logs", icon: History },
  { href: "/settings", label: "Settings", icon: Settings }
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <aside className="flex min-h-screen w-64 shrink-0 flex-col border-r border-border bg-white">
      <div className="border-b border-border px-5 py-4">
        <div className="text-sm font-semibold">Admin Portal</div>
        <div className="text-xs text-muted-foreground">Operations foundation</div>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex h-9 items-center gap-3 rounded-md px-3 text-sm ${
                active ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-border p-3">
        <Button variant="secondary" className="w-full" onClick={handleLogout}>
          Log out
        </Button>
      </div>
    </aside>
  );
}
