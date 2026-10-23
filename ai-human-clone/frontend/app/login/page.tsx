import type { Metadata } from "next";
import Link from "next/link";

import { AuthCard } from "@/components/auth/AuthCard";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata: Metadata = {
  title: "Login · Clone Me",
};

export default function LoginPage() {
  return (
    <AuthCard
      title="Welcome Back"
      subtitle="Login to manage your AI Clone"
      footer={
        <>
          Don&apos;t have an account?{" "}
          <Link href="/register" className="font-medium text-accent-soft hover:underline">
            Create Account
          </Link>
        </>
      }
    >
      <LoginForm />
    </AuthCard>
  );
}
