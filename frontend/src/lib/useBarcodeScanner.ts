/**
 * Camera barcode decoding for the scan station.
 *
 * TWO DECODERS, ONE INTERFACE. Chrome on Android ships `BarcodeDetector`
 * natively: it decodes off the main thread, costs nothing to download, and is
 * what the demo phone will almost certainly use. Safari ships nothing, so
 * ZXing covers it -- but behind a dynamic `import()`, so a browser with the
 * native detector never downloads the fallback at all. Putting ZXing in the
 * main bundle would make every page of the app slower to load in order to
 * serve one page that most visitors never open.
 *
 * THE CAMERA NEEDS A SECURE CONTEXT. `getUserMedia` is refused on plain HTTP
 * from anything that is not localhost, which is worth knowing before you plug
 * a phone into a LAN address and conclude the code is broken. The deployed
 * site is HTTPS, so this only bites during development.
 *
 * DECODES ARE NOT EVENTS. A camera re-reads the same barcode on every frame,
 * perhaps thirty times a second. This hook reports every one of them; turning
 * that stream into one scan per physical presentation is the caller's job,
 * because only the caller knows what a sensible cooldown is.
 */

import { useEffect, useRef, useState } from "react";

export type ScannerStatus =
  | "idle"
  | "starting"
  | "running"
  | "denied"
  | "unsupported"
  | "error";

/** The symbologies a warehouse label realistically carries, plus QR. */
const FORMATS = [
  "code_128",
  "code_39",
  "ean_13",
  "ean_8",
  "upc_a",
  "upc_e",
  "itf",
  "qr_code",
] as const;

/** `BarcodeDetector` is not in TypeScript's DOM library yet. */
interface DetectedBarcode {
  rawValue: string;
}
interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<DetectedBarcode[]>;
}
type BarcodeDetectorCtor = new (options?: {
  formats?: readonly string[];
}) => BarcodeDetectorLike;

function nativeDetector(): BarcodeDetectorCtor | null {
  const ctor = (globalThis as { BarcodeDetector?: BarcodeDetectorCtor })
    .BarcodeDetector;
  return typeof ctor === "function" ? ctor : null;
}

interface Options {
  /** Called for every decode, including the repeats. Debounce downstream. */
  onDecode: (text: string) => void;
  /** Turning this off releases the camera; the indicator light goes out. */
  active: boolean;
}

export function useBarcodeScanner({ onDecode, active }: Options) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [status, setStatus] = useState<ScannerStatus>("idle");
  const [detail, setDetail] = useState("");
  const [engine, setEngine] = useState<"native" | "zxing" | null>(null);

  // The callback identity changes on every render of the calling component.
  // Holding it in a ref keeps the effect below from tearing the camera down
  // and building it back up several times a second.
  const decode = useRef(onDecode);
  useEffect(() => {
    decode.current = onDecode;
  }, [onDecode]);

  useEffect(() => {
    if (!active) {
      setStatus("idle");
      return;
    }

    const video = videoRef.current;
    if (!video) return;

    let stopped = false;
    let frame = 0;
    let stream: MediaStream | null = null;
    let zxingControls: { stop: () => void } | null = null;

    const fail = (next: ScannerStatus, message: string) => {
      if (stopped) return;
      setStatus(next);
      setDetail(message);
    };

    async function run() {
      if (!window.isSecureContext) {
        fail(
          "unsupported",
          "The camera needs HTTPS. Open the deployed site, or use localhost."
        );
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        fail("unsupported", "This browser exposes no camera API.");
        return;
      }

      setStatus("starting");

      const Native = nativeDetector();
      if (Native) {
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment" },
          });
          if (stopped) return;
          video!.srcObject = stream;
          await video!.play();

          const detector = new Native({ formats: FORMATS });
          setEngine("native");
          setStatus("running");

          const tick = async () => {
            if (stopped) return;
            try {
              // readyState guards the first frames, where the element has a
              // stream but no pixels and detect() throws on some builds.
              if (video!.readyState >= 2) {
                for (const found of await detector.detect(video!)) {
                  if (found.rawValue) decode.current(found.rawValue);
                }
              }
            } catch {
              // A single failed frame is not worth killing the camera over.
            }
            frame = requestAnimationFrame(tick);
          };
          frame = requestAnimationFrame(tick);
          return;
        } catch (error) {
          if (isDenied(error)) {
            fail("denied", "Camera permission was refused.");
            return;
          }
          // Native path broke for some other reason; ZXing gets a turn.
          stream?.getTracks().forEach((track) => track.stop());
          stream = null;
        }
      }

      try {
        const { BrowserMultiFormatReader } = await import("@zxing/browser");
        if (stopped) return;
        const reader = new BrowserMultiFormatReader();
        zxingControls = await reader.decodeFromConstraints(
          { video: { facingMode: "environment" } },
          video!,
          (result) => {
            if (result) decode.current(result.getText());
          }
        );
        if (stopped) {
          zxingControls.stop();
          return;
        }
        setEngine("zxing");
        setStatus("running");
      } catch (error) {
        if (isDenied(error)) {
          fail("denied", "Camera permission was refused.");
        } else {
          fail("error", messageOf(error));
        }
      }
    }

    void run();

    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      zxingControls?.stop();
      stream?.getTracks().forEach((track) => track.stop());
      if (video) video.srcObject = null;
    };
  }, [active]);

  return { videoRef, status, detail, engine };
}

function isDenied(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    (error.name === "NotAllowedError" || error.name === "SecurityError")
  );
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "The camera could not be started.";
}
