import { VolumeX } from "lucide-react";

import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { Notice } from "../../../components/ui/Notice";
import type { Direction } from "../model/config";
import type { Scenario, ScenarioStep } from "../model/scenarios";
import styles from "./ScenarioGuide.module.css";

interface Props {
  scenarios: readonly Scenario[];
  /** Khung trống duy nhất của mock còn ngoài cửa sổ 14 ngày: kịch bản đặt lịch sẽ chuyển máy. */
  slotOutsideWindow: boolean;
  onPreset: (direction: Direction) => void;
  onSay: (text: string) => void;
  onSilence: () => void;
}

export function ScenarioGuide({ scenarios, slotOutsideWindow, onPreset, onSay, onSilence }: Props) {
  return (
    <div className={styles.guide}>
      <Notice tone="warning">
        <strong>Clinic mock dùng chung cho cả team.</strong> Call ID khác nhau vẫn dùng chung dữ
        liệu, nên mỗi lần chỉ một người test: báo nhóm → Reset clinic → gọi → báo xong. Lịch khác{" "}
        <code>SCHEDULED</code> trong dropdown là đã bị dùng, cần reset trước khi gọi.
      </Notice>
      <div className={styles.grid}>
        {scenarios.map((scenario) => (
          <article key={scenario.id} className={styles.scenario}>
            <header className={styles.head}>
              <h3>{scenario.title}</h3>
              <Badge tone="brand">{scenario.expect}</Badge>
            </header>
            <p className={styles.summary}>{scenario.summary}</p>
            {scenario.needsSlotWindow && slotOutsideWindow && (
              <Notice tone="error">
                Bot chỉ tìm khung giờ trong 14 ngày tới, mà khung trống duy nhất của mock là 15:00
                ngày 14/10. Trước ngày 30/09 bot sẽ chuyển máy (OUT_OF_SCOPE), không phải lỗi.
              </Notice>
            )}
            <div>
              <Button
                size="sm"
                onClick={() => {
                  onPreset(scenario.direction);
                }}
              >
                Điền cấu hình {scenario.direction}
              </Button>
            </div>
            <Steps steps={scenario.steps} onSay={onSay} onSilence={onSilence} />
            {scenario.variant && (
              <>
                <p className={styles.variant}>{scenario.variant.title}</p>
                <Steps steps={scenario.variant.steps} onSay={onSay} onSilence={onSilence} />
              </>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}

function Steps({
  steps,
  onSay,
  onSilence,
}: {
  steps: readonly ScenarioStep[];
  onSay: (text: string) => void;
  onSilence: () => void;
}) {
  return (
    <ol className={styles.steps}>
      {steps.map((step, index) => (
        <li key={index}>
          {step.kind === "say" ? (
            <button
              type="button"
              className={styles.say}
              onClick={() => {
                onSay(step.text);
              }}
            >
              {step.text}
            </button>
          ) : (
            <button type="button" className={styles.say} onClick={onSilence}>
              <VolumeX aria-hidden />
              Gửi im lặng
            </button>
          )}
          <span>{step.expect}</span>
        </li>
      ))}
    </ol>
  );
}
