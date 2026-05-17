import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-md space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-white">
          Sign in
        </h1>
        <p className="text-sm text-slate-400">
          Use your Datachain account email and password.
        </p>
      </div>
      <LoginForm />
    </div>
  );
}
