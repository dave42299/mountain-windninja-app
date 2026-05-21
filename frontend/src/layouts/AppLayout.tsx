import { Link, Outlet, useLocation } from "react-router";
import { Map, LayoutDashboard, Wind } from "lucide-react";
import { cn } from "@/lib/utils";
import ThemeToggle from "@/components/ThemeToggle";

const navLinks = [
  { to: "/", label: "Map", icon: Map },
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
] as const;

export default function AppLayout() {
  const location = useLocation();

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-14 shrink-0 items-center border-b bg-background px-4">
        <Link to="/" className="flex items-center gap-2 font-semibold">
          <Wind className="h-5 w-5" />
          <span className="hidden sm:inline">Mountain WindNinja</span>
        </Link>

        <nav className="ml-8 flex gap-1">
          {navLinks.map(({ to, label, icon: Icon }) => {
            const isActive =
              to === "/"
                ? location.pathname === "/"
                : location.pathname.startsWith(to);

            return (
              <Link
                key={to}
                to={to}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-1">
          <div id="nav-portal" />
          <ThemeToggle />
        </div>
      </header>

      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
