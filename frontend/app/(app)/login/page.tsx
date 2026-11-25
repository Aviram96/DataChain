import { LoginForm } from "@/components/login-form";
import { ui } from "@/lib/ui";

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-md space-y-6">
      <div className="space-y-2">
        <h1 className={ui.pageTitle}>Log in</h1>
        <p className={ui.pageSubtitle}>
          Use your Datachain account email and password.
        </p>
      </div>
      <div className={ui.panel}>
        <LoginForm />
      </div>
    </div>
  );
}
