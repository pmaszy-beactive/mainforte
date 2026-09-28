import React, { useEffect } from "react";
import { Link, useLocation } from "wouter";
import { useGetMe, getGetMeQueryKey, useGetDashboardSummary, getGetDashboardSummaryQueryKey } from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Loader2, Calendar, LogIn, Sparkles } from "lucide-react";
import { format } from "date-fns";

export default function Dashboard() {
  const [, setLocation] = useLocation();
  
  const { data: user, isLoading: isUserLoading, error: userError } = useGetMe({ 
    query: { enabled: true, queryKey: getGetMeQueryKey(), retry: false } 
  });

  const { data: summary, isLoading: isSummaryLoading } = useGetDashboardSummary({
    query: { 
      enabled: !!user, 
      queryKey: getGetDashboardSummaryQueryKey(),
    }
  });

  useEffect(() => {
    if (userError) {
      setLocation("/login");
    }
  }, [userError, setLocation]);

  if (isUserLoading || isSummaryLoading || !user) {
    return (
      <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <main className="container mx-auto px-4 py-12 md:py-16 max-w-5xl">
      {/* Full-bleed hero band with a real photograph behind a gradient
          overlay. The gradient sits underneath the image so the hero still
          looks designed if the photo ever fails to load. */}
      <div className="relative mb-12 overflow-hidden rounded-3xl bg-gradient-to-br from-primary via-primary/80 to-primary/40 shadow-lg">
        <img
          src="https://loremflickr.com/1600/600/workspace,desk,minimal"
          alt="A bright, modern workspace"
          className="absolute inset-0 h-full w-full object-cover opacity-40"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/20 to-transparent" />
        <div className="relative px-8 py-16 md:px-12 md:py-24 space-y-4">
          <div className="inline-flex items-center rounded-full border border-white/30 bg-white/15 px-3 py-1 text-xs font-semibold text-white backdrop-blur">
            <Sparkles className="mr-1.5 h-3.5 w-3.5" />
            Welcome to the new intranet
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-white drop-shadow-sm sm:text-5xl md:text-6xl">
            {summary?.greeting || "Hello"}, {summary?.userName || user.name}!
          </h1>
          <p className="max-w-2xl text-lg text-white/90 drop-shadow-sm">
            We're glad to have you here. This is your personal dashboard where you can find everything you need to start your day.
          </p>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <Card className="border-border/50 shadow-sm overflow-hidden relative group">
          <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Logins
            </CardTitle>
            <LogIn className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{summary?.loginCount || 1}</div>
            <p className="text-xs text-muted-foreground mt-1">
              times you've visited Hello World
            </p>
          </CardContent>
        </Card>

        <Card className="border-border/50 shadow-sm overflow-hidden relative group">
          <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Last Login
            </CardTitle>
            <Calendar className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">
              {summary?.lastLogin ? format(new Date(summary.lastLogin), 'MMM d, yyyy') : 'First time here!'}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary?.lastLogin ? format(new Date(summary.lastLogin), 'h:mm a') : 'Right now'}
            </p>
          </CardContent>
        </Card>

        <Card className="border-border/50 shadow-sm bg-primary/5 md:col-span-2 lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-lg">Profile Status</CardTitle>
            <CardDescription>Your account details</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <span className="text-sm font-medium text-muted-foreground">Name</span>
              <p className="font-medium">{user.name}</p>
            </div>
            <div className="space-y-1">
              <span className="text-sm font-medium text-muted-foreground">Email</span>
              <p className="font-medium">{user.email}</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
