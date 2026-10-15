import { Eye, EyeOff, LogIn } from "lucide-react";
import { useState, type SyntheticEvent } from "react";
import { Navigate, useSearchParams } from "react-router";

import { Button } from "../../components/ui/Button";
import { Field, Input } from "../../components/ui/Form";
import { Notice } from "../../components/ui/Notice";
import { login, useAuth } from "../../lib/auth";
import { checkApiKey } from "./api";
import styles from "./LoginPage.module.css";

/** Chỉ quay về trang trong app: chặn `next=//evil.com` hay URL tuyệt đối. */
function safeNext(next: string | null): string {
  return next?.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginPage() {
  const { apiKey, rejected } = useAuth();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [key, setKey] = useState("");
  const [visible, setVisible] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Vừa đăng nhập, hoặc đã đăng nhập trong tab này (mở lại /login): vào thẳng trang cần tới.
  if (apiKey !== null) return <Navigate to={next} replace />;

  const submit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecking(true);
    setError(null);
    try {
      const result = await checkApiKey(key.trim());
      if (!result.ok) {
        setError(result.message);
        return;
      }
      login(key);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Lỗi không xác định.");
    } finally {
      setChecking(false);
    }
  };

  return (
    <main className={styles.page}>
      <form className={styles.card} onSubmit={(event) => void submit(event)} noValidate>
        <header className={styles.heading}>
          <p className={styles.eyebrow}>Clinicalbot · Console nội bộ</p>
          <h1>Đăng nhập</h1>
          <p>Nhập API key của bot để dùng console: gọi thử, thử STT và observability.</p>
        </header>

        {rejected && <Notice tone="warning">API key không còn hợp lệ. Đăng nhập lại.</Notice>}

        <Field
          label="API key"
          htmlFor="api-key"
          error={error}
          hint="Bearer key trong BOT_API_KEYS. Chỉ lưu trong tab này; bot tắt auth thì để trống."
        >
          <div className={styles.secret}>
            <Input
              id="api-key"
              type={visible ? "text" : "password"}
              autoComplete="off"
              autoFocus
              placeholder="sk_…"
              value={key}
              invalid={error !== null}
              onChange={(event) => {
                setKey(event.target.value);
                setError(null);
              }}
            />
            <button
              type="button"
              className={styles.reveal}
              aria-label={visible ? "Ẩn API key" : "Hiện API key"}
              aria-pressed={visible}
              onClick={() => {
                setVisible((value) => !value);
              }}
            >
              {visible ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
            </button>
          </div>
        </Field>

        <Button type="submit" variant="primary" icon={<LogIn />} loading={checking}>
          Đăng nhập
        </Button>
      </form>
    </main>
  );
}
