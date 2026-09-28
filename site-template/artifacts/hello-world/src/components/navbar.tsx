import React from "react";
import { Link, useLocation } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import { useGetMe, useLogout, getGetMeQueryKey } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { LogOut } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useVersion } from "@/hooks/use-version";

export function Navbar() {
  const { data: user } = useGetMe({ query: { enabled: true, queryKey: getGetMeQueryKey(), retry: false } });
  const logout = useLogout();
  const [, setLocation] = useLocation();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const version = useVersion();

  const handleLogout = () => {
    logout.mutate(undefined, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetMeQueryKey() });
        setLocation("/login");
        toast({ title: "Logged out successfully" });
      },
      onError: () => {
        toast({ title: "Failed to log out", variant: "destructive" });
      }
    });
  };

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-16 items-center justify-between px-4 md:px-6">
        <div className="flex items-center gap-3">
          <Link href={user ? "/dashboard" : "/"} className="flex items-center space-x-2 transition-opacity hover:opacity-80">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary text-primary-foreground font-bold">
              HW
            </div>
            <span className="font-bold text-xl tracking-tight text-foreground">Hello World</span>
          </Link>
          {version && (
            <span className="text-xs text-muted-foreground font-mono bg-muted px-2 py-0.5 rounded-md">
              v{version.version}
            </span>
          )}
        </div>
        
        {user && (
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 hidden sm:flex">
              <span className="text-sm font-medium text-foreground">{user.name}</span>
            </div>
            <Avatar className="h-8 w-8 border border-primary/20 bg-primary/10">
              <AvatarFallback className="text-primary font-semibold text-xs">
                {user.name.substring(0, 2).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <Button variant="ghost" size="icon" onClick={handleLogout} className="text-muted-foreground hover:text-foreground">
              <LogOut className="h-5 w-5" />
              <span className="sr-only">Log out</span>
            </Button>
          </div>
        )}
      </div>
    </header>
  );
}
