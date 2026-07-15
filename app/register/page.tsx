"use client";

import { useRouter } from "next/navigation";
import AuthCard from "@/components/AuthCard";
import { useSession } from "@/components/SessionProvider";
import SignUpForm from "@/components/SignUpForm";

export default function RegisterPage() {
  const router = useRouter();
  const { signUp } = useSession();

  return (
    <AuthCard>
      <SignUpForm
        onSubmit={async (input) => {
          await signUp(input);
          router.push("/workspace");
          router.refresh();
        }}
        onSwitch={() => router.push("/login")}
      />
    </AuthCard>
  );
}
