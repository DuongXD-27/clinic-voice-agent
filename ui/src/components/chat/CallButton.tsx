import { PhoneCall, PhoneOff } from "lucide-react";

import { Button } from "../ui/Button";
import styles from "./CallButton.module.css";

/** Pha chung của hai trang gọi: HTTP (starting/active/sending) và LiveKit (connecting/connected). */
export type CallPhase = "idle" | "connecting" | "active";

interface Props {
  phase: CallPhase;
  onStart: () => void;
  onEnd: () => void;
}

/** Nút gọi / gác máy, giống hệt nhau ở mọi trang gọi thử. */
export function CallButton({ phase, onStart, onEnd }: Props) {
  if (phase === "active") {
    return (
      <Button icon={<PhoneOff />} className={`${styles.call} ${styles.end}`} onClick={onEnd}>
        Kết thúc
      </Button>
    );
  }
  return (
    <Button
      variant="primary"
      icon={<PhoneCall />}
      className={styles.call}
      loading={phase === "connecting"}
      onClick={onStart}
    >
      Bắt đầu cuộc gọi
    </Button>
  );
}
