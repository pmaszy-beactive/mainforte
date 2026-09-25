import { createBrowserRouter, Navigate } from "react-router";
import { lazy } from "react";
import { RootLayout } from "@/components/layout/RootLayout";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { AdminGuard } from "@/components/layout/AdminGuard";

const MarketingPage = lazy(() => import("@/features/marketing/MarketingPage"));
const SignupPage = lazy(() => import("@/features/auth/SignupPage"));
const LoginPage = lazy(() => import("@/features/auth/LoginPage"));
const ForgotPasswordPage = lazy(() => import("@/features/auth/ForgotPasswordPage"));
const ResetPasswordPage = lazy(() => import("@/features/auth/ResetPasswordPage"));
const MagicPage = lazy(() => import("@/features/auth/MagicPage"));
const OAuthCallbackPage = lazy(() => import("@/features/auth/OAuthCallbackPage"));
const AppLayout = lazy(() => import("@/features/app/AppLayout"));
const ChatPage = lazy(() => import("@/features/chat/ChatPage"));
const SettingsPage = lazy(() => import("@/features/settings/SettingsPage"));
const BillingPage = lazy(() => import("@/features/billing/BillingPage"));
const AdminLayout = lazy(() => import("@/features/admin/AdminLayout"));
const UsersTab = lazy(() => import("@/features/admin/tabs/UsersTab"));
const FinancesTab = lazy(() => import("@/features/admin/tabs/FinancesTab"));
const ErrorsTab = lazy(() => import("@/features/admin/tabs/ErrorsTab"));
const JobsTab = lazy(() => import("@/features/admin/tabs/JobsTab"));
const WorkersTab = lazy(() => import("@/features/admin/tabs/WorkersTab"));
const EventsTab = lazy(() => import("@/features/admin/tabs/EventsTab"));

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: "/", element: <MarketingPage /> },
      { path: "/signup", element: <SignupPage /> },
      { path: "/login", element: <LoginPage /> },
      { path: "/forgot-password", element: <ForgotPasswordPage /> },
      { path: "/reset-password", element: <ResetPasswordPage /> },
      { path: "/magic", element: <MagicPage /> },
      { path: "/oauth/callback", element: <OAuthCallbackPage /> },
      {
        element: <AuthGuard />,
        children: [
          {
            path: "/app",
            element: <AppLayout />,
            children: [
              { index: true, element: <ChatPage /> },
              { path: "settings", element: <SettingsPage /> },
              { path: "billing", element: <BillingPage /> },
            ],
          },
          {
            element: <AdminGuard />,
            children: [
              {
                path: "/admin",
                element: <AdminLayout />,
                children: [
                  { index: true, element: <Navigate to="users" replace /> },
                  { path: "users", element: <UsersTab /> },
                  { path: "finances", element: <FinancesTab /> },
                  { path: "errors", element: <ErrorsTab /> },
                  { path: "jobs", element: <JobsTab /> },
                  { path: "workers", element: <WorkersTab /> },
                  { path: "events", element: <EventsTab /> },
                ],
              },
            ],
          },
        ],
      },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
