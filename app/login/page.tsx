"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import AuthCard from "@/components/AuthCard";
import { useSession } from "@/components/SessionProvider";
import SignInForm from "@/components/SignInForm";

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { signIn } = useSession();

  // Return the user to wherever the middleware intercepted them.
  const next = params.get("next") || "/workspace";

  return (
    <AuthCard>
      <SignInForm
        onSubmit={async (email, password) => {
          await signIn(email, password);
          router.push(next);
          router.refresh();
        }}
        onSwitch={() => router.push("/register")}
      />
    </AuthCard>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
