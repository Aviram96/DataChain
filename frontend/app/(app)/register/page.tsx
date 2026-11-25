import { RegisterForm } from "@/components/register-form";
import { ui } from "@/lib/ui";

export default function RegisterPage() {
  return (
    <div className="mx-auto max-w-md space-y-6">
      <div className="space-y-2">
        <h1 className={ui.pageTitle}>Sign up</h1>
        <p className={ui.pageSubtitle}>
          Create an account with email and password to use Datachain.
        </p>
      </div>
      <div className={ui.panel}>
        <RegisterForm />
      </div>
    </div>
  );
}
