import type { Metadata } from "next";
import Link from "next/link";

import { AuthCard } from "@/components/auth/AuthCard";
import { RegisterForm } from "@/components/auth/RegisterForm";

export const metadata: Metadata = {
  title: "Create Account · Clone Me",
};

export default function RegisterPage() {
  return (
    <AuthCard
      title="Create Your Account"
      subtitle="Build and manage your consent-based AI clone."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-accent-soft hover:underline">
            Login
          </Link>
        </>
      }
    >
      <RegisterForm />
    </AuthCard>
  );
}
