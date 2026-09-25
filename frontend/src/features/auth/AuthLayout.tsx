import type { ReactNode } from "react";
import { Link } from "react-router";
import { Logo } from "@/components/ui/Logo";
import { Card } from "@/components/ui/Card";

export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-5 py-12">
      <Link to="/" className="mb-8">
        <Logo />
      </Link>
      <Card className="w-full max-w-sm p-7 animate-fade-up">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-fog-500">{subtitle}</p>}
        <div className="mt-6">{children}</div>
      </Card>
      {footer && <div className="mt-5 text-sm text-fog-500">{footer}</div>}
    </div>
  );
}
