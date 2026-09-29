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
const MarketplaceBrowsePage = lazy(() => import("@/features/marketplace/MarketplaceBrowsePage"));
const MarketplaceListingPage = lazy(() => import("@/features/marketplace/MarketplaceListingPage"));
const MarketplaceNewListingPage = lazy(() => import("@/features/marketplace/MarketplaceNewListingPage"));
const MyListingsPage = lazy(() => import("@/features/marketplace/MyListingsPage"));
const MyOrdersPage = lazy(() => import("@/features/marketplace/MyOrdersPage"));
const AdminLayout = lazy(() => import("@/features/admin/AdminLayout"));
const SettingsTab = lazy(() => import("@/features/admin/tabs/SettingsTab"));
const UsersTab = lazy(() => import("@/features/admin/tabs/UsersTab"));
const UserDetail = lazy(() => import("@/features/admin/UserDetail"));
const FinancesTab = lazy(() => import("@/features/admin/tabs/FinancesTab"));
const ErrorsTab = lazy(() => import("@/features/admin/tabs/ErrorsTab"));
const JobsTab = lazy(() => import("@/features/admin/tabs/JobsTab"));
const TasksTab = lazy(() => import("@/features/admin/tabs/TasksTab"));
const WorkLogTab = lazy(() => import("@/features/admin/tabs/WorkLogTab"));
const WorkersTab = lazy(() => import("@/features/admin/tabs/WorkersTab"));
const SitesTab = lazy(() => import("@/features/admin/tabs/SitesTab"));
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
              { path: "marketplace", element: <MarketplaceBrowsePage /> },
              { path: "marketplace/new", element: <MarketplaceNewListingPage /> },
              { path: "marketplace/mine", element: <MyListingsPage /> },
              { path: "marketplace/orders", element: <MyOrdersPage /> },
              { path: "marketplace/:id", element: <MarketplaceListingPage /> },
              { path: "marketplace/:id/edit", element: <MarketplaceNewListingPage /> },
            ],
          },
          {
            element: <AdminGuard />,
            children: [
              {
                path: "/admin",
                element: <AdminLayout />,
                children: [
                  { index: true, element: <Navigate to="settings" replace /> },
                  { path: "settings", element: <SettingsTab /> },
                  { path: "users", element: <UsersTab /> },
          { path: "users/:id", element: <UserDetail /> },
                  { path: "finances", element: <FinancesTab /> },
                  { path: "errors", element: <ErrorsTab /> },
                  { path: "jobs", element: <JobsTab /> },
                  { path: "tasks", element: <TasksTab /> },
                  { path: "work-log", element: <WorkLogTab /> },
                  { path: "workers", element: <WorkersTab /> },
                  { path: "sites", element: <SitesTab /> },
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
