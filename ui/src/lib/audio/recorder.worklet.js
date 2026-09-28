// AudioWorklet chạy trên luồng audio: chép từng khối mẫu (128 frame) của kênh đầu về luồng chính.
// JS thuần vì Vite phục vụ file này nguyên văn qua `?url&no-inline` (xem useRecorder.ts).
// Nhận "stop" thì ngừng ghi và trả "stopped": message đi theo thứ tự, nên mọi khối đã gửi
// trước đó chắc chắn tới luồng chính trước "stopped".
class RecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.recording = true;
    this.port.onmessage = (event) => {
      if (event.data === "stop") {
        this.recording = false;
        this.port.postMessage("stopped");
      }
    };
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (this.recording && channel) this.port.postMessage(channel.slice(0));
    return this.recording;
  }
}

registerProcessor("recorder", RecorderProcessor);
