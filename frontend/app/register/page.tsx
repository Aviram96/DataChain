import { RegisterForm } from "@/components/register-form";

export default function RegisterPage() {
  return (
    <div className="mx-auto max-w-md space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-white">
          Create account
        </h1>
        <p className="text-sm text-slate-400">
          Register with email and password to use Datachain.
        </p>
      </div>
      <RegisterForm />
    </div>
  );
}
