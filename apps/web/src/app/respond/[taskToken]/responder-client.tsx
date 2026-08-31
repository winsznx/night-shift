"use client";

import { useEffect, useRef, useState, useTransition } from "react";

import { Badge } from "@/components/ui";
import type {
  CorroborationOutcome,
  CorroborationRecord,
  ResponderTask,
  ResponderView,
  ScanCaptures,
} from "@/lib/api";

/**
 * Largest edge, in pixels, that a capture is resized to before it is sent.
 *
 * A modern phone shoots twelve megapixels. Base64 inflates that to roughly eight million
 * characters, over the six million the scan route accepts, and the whole upload happens
 * over whatever signal reaches a basement cold room. A container label and a seven-segment
 * freezer display both stay legible at 1280px, so the resize costs the reader nothing and
 * saves the responder a minute of standing still.
 */
const MAX_CAPTURE_EDGE_PX = 1280;
const CAPTURE_JPEG_QUALITY = 0.8;

/**
 * Character ceiling applied before a capture is sent.
 *
 * The API rejects a field above six million characters and the reader drops anything that
 * decodes past four million bytes, which lands near 5.34 million characters of base64.
 * Checking here means an oversized capture is dropped with an explanation the responder
 * can act on rather than becoming a silent ABSENT after a slow upload.
 */
const MAX_CAPTURE_CHARS = 5_000_000;

/** A spoken confirmation is one sentence. The ceiling keeps the encoded audio small. */
const MAX_VOICE_SECONDS = 20;

type CaptureKey = keyof ScanCaptures;

const EMPTY_CAPTURES: ScanCaptures = {
  label_photo: null,
  display_photo: null,
  voice_note: null,
};

const CAPTURE_FOR_KIND: Record<string, CaptureKey> = {
  container_label: "label_photo",
  destination_display: "display_photo",
  voice_confirmation: "voice_note",
};

const KIND_LABEL: Record<string, string> = {
  container_label: "Container label",
  destination_display: "Destination display",
  voice_confirmation: "Voice confirmation",
};

/**
 * Which capabilities this browser actually has.
 *
 * Feature detection only has an answer in the browser, so `resolved` carries the third
 * state. Without it the server renders "capture is unavailable", the client immediately
 * contradicts itself, and the first thing a responder reads is wrong.
 */
interface CaptureSupport {
  resolved: boolean;
  photo: boolean;
  voice: boolean;
}

/**
 * The responder screen.
 *
 * Not a chat surface. One container at a time, big targets, and the destination
 * temperature front and centre — because that is the number that decides whether the
 * commit will be accepted, and a responder should know before they walk.
 *
 * Captures are the second channel. Every one of them is optional: a responder with a dead
 * battery, a locked-down browser, or thick enough gloves that the camera is hopeless still
 * has to be able to move specimens, and the receipt records that the scan rested on the
 * task token alone.
 */
export function ResponderClient({ token, initial }: { token: string; initial: ResponderView }) {
  const [view, setView] = useState(initial);
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [code, setCode] = useState("");
  const [captures, setCaptures] = useState<ScanCaptures>(EMPTY_CAPTURES);
  const [outcome, setOutcome] = useState<CorroborationOutcome | null>(null);
  const [refusal, setRefusal] = useState<CorroborationOutcome | null>(null);
  const [support, setSupport] = useState<CaptureSupport>({
    resolved: false,
    photo: false,
    voice: false,
  });

  useEffect(() => {
    const canvas = document.createElement("canvas");
    setSupport({
      resolved: true,
      photo: typeof canvas.getContext === "function" && canvas.getContext("2d") !== null,
      voice:
        typeof window.MediaRecorder === "function" &&
        typeof navigator.mediaDevices?.getUserMedia === "function",
    });
  }, []);

  const working = pending || busy;

  const active = view.tasks.filter(
    (t) => !["COMMITTED", "QUARANTINED"].includes(t.custody_state),
  );
  const current = active[0] ?? null;

  function setCapture(key: CaptureKey, value: string | null) {
    setCaptures((previous) => ({ ...previous, [key]: value }));
  }

  /** Drop only the captures that disagreed, so a confirmed label survives a bad display. */
  function clearContradicting(records: CorroborationRecord[]) {
    const keys = records
      .filter((record) => record.status === "MISMATCH")
      .map((record) => CAPTURE_FOR_KIND[record.kind])
      .filter((key): key is CaptureKey => Boolean(key));
    setCaptures((previous) => {
      const next = { ...previous };
      for (const key of keys) next[key] = null;
      return next;
    });
    setRefusal(null);
  }

  async function post(action: "pickup" | "receive" | "exception", body: Record<string, unknown>) {
    setMessage(null);
    setOutcome(null);
    setRefusal(null);
    setBusy(true);
    try {
      const response = await fetch(`/api/respond/${token}/${action}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));

      // A capture contradiction is not an error and nothing was written. It gets its own
      // panel, the captures stay put, and the responder retakes the one that disagreed.
      if (response.status === 409 && Array.isArray(data?.detail?.corroboration)) {
        setRefusal({
          reason: String(data.detail.reason ?? "a capture disagreed with the record"),
          records: data.detail.corroboration as CorroborationRecord[],
        });
        return;
      }

      if (!response.ok) {
        setMessage({
          tone: "bad",
          text: String(data?.detail?.reason ?? data?.detail?.error ?? "The request was refused."),
        });
      } else {
        const receipt = data?.receipt ?? data?.commit?.receipt;
        const decision = data?.commit?.decision ?? data?.decision;
        if (data?.corroboration) setOutcome(data.corroboration as CorroborationOutcome);
        if (receipt?.status === "REFUSED") {
          setMessage({
            tone: "bad",
            text: `Refused by ${decision?.invariant ?? "the safety kernel"}: ${decision?.reason ?? "precondition not met"}`,
          });
        } else if (receipt?.duplicate_returned) {
          setMessage({ tone: "ok", text: "Already recorded. Returning the original receipt." });
        } else {
          setMessage({ tone: "ok", text: "Recorded." });
        }
        setCaptures(EMPTY_CAPTURES);
      }

      const refreshed = await fetch(`/api/respond/${token}`).then((r) => (r.ok ? r.json() : null));
      if (refreshed) setView(refreshed as ResponderView);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-[560px] px-4 pb-24">
      <Summary view={view} />

      {message ? (
        <div
          role="status"
          className={`mt-3 rounded-[8px] border px-3 py-2.5 text-[14px] ${
            message.tone === "ok"
              ? "border-[#bbf7d0] bg-[#dcfce7] text-[#166534]"
              : "border-[#fecaca] bg-[#fef2f2] text-[#991b1b]"
          }`}
        >
          {message.text}
        </div>
      ) : null}

      {refusal ? (
        <RefusalPanel refusal={refusal} onRetake={() => clearContradicting(refusal.records)} />
      ) : null}

      {outcome ? <OutcomePanel outcome={outcome} /> : null}

      {current ? (
        <TaskCard
          task={current}
          code={code}
          setCode={setCode}
          pending={working}
          captures={captures}
          setCapture={setCapture}
          support={support}
          onPickup={() =>
            startTransition(() => {
              void post("pickup", {
                container_id: current.container_id,
                label_photo: captures.label_photo,
                voice_note: captures.voice_note,
              });
            })
          }
          onReceive={() =>
            startTransition(() => {
              void post("receive", {
                container_id: current.container_id,
                location_ref: code.trim() || current.destination_freezer || "",
                label_photo: captures.label_photo,
                display_photo: captures.display_photo,
                voice_note: captures.voice_note,
              });
            })
          }
          onException={(reason) =>
            startTransition(() => {
              void post("exception", {
                container_id: current.container_id,
                reason,
                disposition: "UNRESOLVED",
              });
            })
          }
        />
      ) : (
        <div className="mt-4 rounded-[12px] border border-[#bbf7d0] bg-[#dcfce7] p-5 text-center">
          <p className="text-[16px] font-semibold text-[#166534]">Batch complete</p>
          <p className="mt-1 text-[14px] text-[#166534]">
            Every container in this batch has reached a terminal state.
          </p>
        </div>
      )}

      <Remaining tasks={view.tasks} />
    </div>
  );
}

function Summary({ view }: { view: ResponderView }) {
  const s = view.summary;
  return (
    <div className="mt-3 rounded-[12px] border border-[#e5e5e5] bg-white p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="mono text-[12px] text-[#737373]">{view.incident_id}</span>
        <span className="rounded-full border border-[#bfdbfe] bg-[#dbeafe] px-2.5 py-[3px] text-[11px] font-medium text-[#1e40af]">
          {view.response_phase}
        </span>
      </div>
      <p className="mt-2 text-[15px] font-medium text-[#171717]">
        Move material out of {view.failed_freezer_id}
      </p>
      <div className="mt-3 grid grid-cols-4 gap-2 text-center">
        {[
          ["To move", s.at_source],
          ["In transit", s.picked_up],
          ["Done", s.committed],
          ["Flagged", s.exceptions],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-[8px] bg-[#f5f5f5] py-2">
            <div className="mono text-[18px] leading-none font-medium text-[#171717]">
              {String(value)}
            </div>
            <div className="mt-1 text-[11px] text-[#737373]">{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TaskCard({
  task,
  code,
  setCode,
  pending,
  captures,
  setCapture,
  support,
  onPickup,
  onReceive,
  onException,
}: {
  task: ResponderTask;
  code: string;
  setCode: (v: string) => void;
  pending: boolean;
  captures: ScanCaptures;
  setCapture: (key: CaptureKey, value: string | null) => void;
  support: CaptureSupport;
  onPickup: () => void;
  onReceive: () => void;
  onException: (reason: string) => void;
}) {
  const needsPickup = task.custody_state === "AT_SOURCE";
  const tempOk =
    task.destination_temp_c !== null &&
    task.destination_temp_c <= -60 &&
    (task.destination_reading_age_s ?? 0) <= 900;

  return (
    <div className="mt-3 rounded-[12px] border border-[#e5e5e5] bg-white">
      <div className="border-b border-[#e5e5e5] px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <span className="mono text-[18px] font-medium text-[#171717]">
            {task.container_id}
          </span>
          <span className="rounded-full border border-[#e5e5e5] bg-[#f5f5f5] px-2.5 py-[3px] text-[11px] font-medium text-[#404040]">
            {task.custody_state.replace(/_/g, " ")}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 divide-x divide-[#e5e5e5] border-b border-[#e5e5e5]">
        <div className="px-4 py-3">
          <div className="text-[11px] tracking-wide text-[#737373] uppercase">From</div>
          <div className="mono mt-1 text-[15px] font-medium text-[#171717]">
            {task.source_freezer}
          </div>
          <div className="mono mt-0.5 text-[12px] text-[#737373]">{task.source_slot}</div>
        </div>
        <div className="px-4 py-3">
          <div className="text-[11px] tracking-wide text-[#737373] uppercase">To</div>
          <div className="mono mt-1 text-[15px] font-medium text-[#171717]">
            {task.destination_freezer ?? "—"}
          </div>
          <div className="mono mt-0.5 text-[12px] text-[#737373]">
            {task.destination_slot ?? "awaiting reservation"}
          </div>
        </div>
      </div>

      {task.destination_freezer ? (
        <div
          className={`flex items-center justify-between gap-3 border-b border-[#e5e5e5] px-4 py-3 ${
            tempOk ? "bg-[#dcfce7]" : "bg-[#fef2f2]"
          }`}
        >
          <div>
            <div
              className={`text-[11px] tracking-wide uppercase ${tempOk ? "text-[#166534]" : "text-[#991b1b]"}`}
            >
              Destination temperature
            </div>
            <div
              className={`mono mt-0.5 text-[20px] leading-none font-medium ${tempOk ? "text-[#166534]" : "text-[#991b1b]"}`}
            >
              {task.destination_temp_c !== null
                ? `${task.destination_temp_c.toFixed(1)}°C`
                : "no reading"}
            </div>
          </div>
          <div className={`text-right text-[12px] ${tempOk ? "text-[#166534]" : "text-[#991b1b]"}`}>
            {task.destination_reading_age_s !== null
              ? `read ${Math.round(task.destination_reading_age_s)}s ago`
              : "—"}
            <br />
            {tempOk ? "safe to receive" : "commit will be refused"}
          </div>
        </div>
      ) : null}

      {task.exception_reason ? (
        <div className="border-b border-[#e5e5e5] bg-[#fff7ed] px-4 py-3 text-[13px] text-[#9a3412]">
          {task.exception_reason}
        </div>
      ) : null}

      <CaptureDeck
        phase={needsPickup ? "pickup" : "receive"}
        task={task}
        captures={captures}
        setCapture={setCapture}
        support={support}
        disabled={pending}
      />

      <div className="p-4">
        {needsPickup ? (
          <button
            type="button"
            onClick={onPickup}
            disabled={pending || !task.destination_freezer}
            className="min-h-[56px] w-full rounded-[8px] bg-black px-4 py-3.5 text-[17px] font-semibold text-white disabled:opacity-40"
          >
            {pending ? "Recording…" : "Confirm pickup"}
          </button>
        ) : (
          <>
            <label
              htmlFor="dest-code"
              className="block text-[12px] font-medium text-[#404040]"
            >
              Scan or type the destination freezer code
            </label>
            <input
              id="dest-code"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder={task.destination_freezer ?? "F-00"}
              autoComplete="off"
              inputMode="text"
              className="mono mt-1.5 min-h-[48px] w-full rounded-[6px] border border-black px-3 py-3 text-[16px] text-[#111827]"
            />
            <button
              type="button"
              onClick={onReceive}
              disabled={pending}
              className="mt-2.5 min-h-[56px] w-full rounded-[8px] bg-black px-4 py-3.5 text-[17px] font-semibold text-white disabled:opacity-40"
            >
              {pending ? "Recording…" : "Confirm receipt"}
            </button>
          </>
        )}

        <button
          type="button"
          onClick={() => onException("Responder flagged an exception in the field")}
          disabled={pending}
          className="mt-2 min-h-[48px] w-full rounded-[8px] border border-[#e5e5e5] px-4 py-3 text-[15px] font-medium text-[#171717] disabled:opacity-40"
        >
          Flag a problem
        </button>
      </div>
    </div>
  );
}

/**
 * The capture controls for whichever scan is next.
 *
 * The destination display only appears on a receipt. A pickup has no destination reading
 * to compare a photograph against, so the API would score a display photo taken there as
 * ABSENT, and asking a responder to take a picture that cannot corroborate anything is
 * how a second channel turns into busywork.
 */
function CaptureDeck({
  phase,
  task,
  captures,
  setCapture,
  support,
  disabled,
}: {
  phase: "pickup" | "receive";
  task: ResponderTask;
  captures: ScanCaptures;
  setCapture: (key: CaptureKey, value: string | null) => void;
  support: CaptureSupport;
  disabled: boolean;
}) {
  // Until detection has answered, the controls render in their normal shape but locked.
  // Claiming a capability is missing before anyone has checked is worse than a moment of
  // greyed-out buttons.
  const photoReady = !support.resolved || support.photo;
  const voiceReady = !support.resolved || support.voice;
  const pendingDetection = disabled || !support.resolved;

  return (
    <section className="border-b border-[#e5e5e5]" aria-labelledby="capture-heading">
      <div className="flex items-start justify-between gap-3 bg-[#fafafa] px-4 py-2.5">
        <div>
          <h2 id="capture-heading" className="text-[13px] font-semibold text-[#171717]">
            Evidence
          </h2>
          <p className="mt-0.5 text-[12px] text-[#525252]">
            Optional. A capture can only refuse this scan, never approve one.
          </p>
        </div>
        <Badge tone="neutral">second channel</Badge>
      </div>

      {support.resolved && !support.photo && !support.voice ? (
        <p className="px-4 py-3 text-[13px] text-[#525252]">
          Capture is unavailable in this browser. The scan will proceed on the task token.
        </p>
      ) : null}

      <div className="divide-y divide-[#e5e5e5]">
        <PhotoCapture
          id="capture-label"
          title="Container label"
          hint={`Photograph the label on ${task.container_id}.`}
          value={captures.label_photo}
          onChange={(value) => setCapture("label_photo", value)}
          supported={photoReady}
          disabled={pendingDetection}
        />
        {phase === "receive" ? (
          <PhotoCapture
            id="capture-display"
            title="Destination display"
            hint={`Photograph the temperature on ${task.destination_freezer ?? "the destination freezer"}.`}
            value={captures.display_photo}
            onChange={(value) => setCapture("display_photo", value)}
            supported={photoReady}
            disabled={pendingDetection}
          />
        ) : null}
        <VoiceCapture
          value={captures.voice_note}
          onChange={(value) => setCapture("voice_note", value)}
          supported={voiceReady}
          disabled={pendingDetection}
        />
      </div>
    </section>
  );
}

function PhotoCapture({
  id,
  title,
  hint,
  value,
  onChange,
  supported,
  disabled,
}: {
  id: string;
  title: string;
  hint: string;
  value: string | null;
  onChange: (value: string | null) => void;
  supported: boolean;
  disabled: boolean;
}) {
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    // Clearing the input means picking the same file twice still fires a change, which is
    // exactly what a retake of a blurry photo looks like.
    input.value = "";
    if (!file) return;
    setError(null);
    setPreparing(true);
    try {
      const encoded = await downscaleToJpegDataUrl(file);
      if (encoded.length > MAX_CAPTURE_CHARS) {
        setError("That photo is still too large to send. Try again from further back.");
        return;
      }
      onChange(encoded);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The photo could not be prepared.");
    } finally {
      setPreparing(false);
    }
  }

  const locked = disabled || !supported;

  return (
    <div className="px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[15px] font-medium text-[#171717]">{title}</div>
          <p className="mt-0.5 text-[13px] text-[#525252]">{hint}</p>
        </div>
        {value ? <Badge tone="green">captured</Badge> : <Badge tone="neutral">optional</Badge>}
      </div>

      {!supported ? (
        <p className="mt-2 text-[12px] text-[#737373]">
          This browser cannot prepare a photo. The scan will proceed on the task token.
        </p>
      ) : value ? (
        <div className="mt-2.5 flex items-center gap-3">
          {/*
            A plain img, because the source is an in-memory data URL that never reaches a
            server and so has nothing for the image optimiser to fetch or cache.
          */}
          <img
            src={value}
            alt={`${title} capture`}
            className="h-[56px] w-[56px] shrink-0 rounded-[8px] border border-[#e5e5e5] object-cover"
          />
          <div className="flex min-w-0 flex-1 gap-2">
            <label
              htmlFor={id}
              className={`flex min-h-[48px] flex-1 cursor-pointer items-center justify-center rounded-[8px] border border-[#e5e5e5] bg-white px-3 text-[15px] font-medium text-[#171717] ${
                locked ? "pointer-events-none opacity-40" : ""
              }`}
            >
              Retake
            </label>
            <button
              type="button"
              onClick={() => onChange(null)}
              disabled={locked}
              className="min-h-[48px] flex-1 rounded-[8px] border border-[#e5e5e5] bg-white px-3 text-[15px] font-medium text-[#525252] disabled:opacity-40"
            >
              Clear
            </button>
          </div>
        </div>
      ) : (
        <label
          htmlFor={id}
          className={`mt-2.5 flex min-h-[48px] w-full cursor-pointer items-center justify-center rounded-[8px] border border-[#171717] bg-white px-4 text-[15px] font-medium text-[#171717] ${
            locked ? "pointer-events-none opacity-40" : ""
          }`}
        >
          {preparing ? "Preparing…" : "Take photo"}
        </label>
      )}

      <input
        id={id}
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        disabled={locked}
        onChange={handleFile}
      />

      {error ? <p className="mt-1.5 text-[12px] text-[#991b1b]">{error}</p> : null}
    </div>
  );
}

function VoiceCapture({
  value,
  onChange,
  supported,
  disabled,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  supported: boolean;
  disabled: boolean;
}) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    if (!recording) return;
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setSeconds(elapsed);
      if (elapsed >= MAX_VOICE_SECONDS && recorderRef.current?.state === "recording") {
        recorderRef.current.stop();
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [recording]);

  // Walking away mid-recording must not leave the microphone open.
  useEffect(() => {
    return () => {
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function start() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      // The reader labels these bytes audio/webm on the way to the model, so ask for that
      // container where the browser can produce it rather than shipping a mislabelled one.
      const preferred = "audio/webm";
      const recorder =
        typeof MediaRecorder.isTypeSupported === "function" &&
        MediaRecorder.isTypeSupported(preferred)
          ? new MediaRecorder(stream, { mimeType: preferred })
          : new MediaRecorder(stream);
      const chunks: Blob[] = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      recorder.onerror = () => {
        setError("The recording stopped unexpectedly.");
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        recorderRef.current = null;
        setRecording(false);
        const blob = new Blob(chunks, { type: recorder.mimeType || preferred });
        const reader = new FileReader();
        reader.onload = () => {
          const encoded = String(reader.result);
          if (encoded.length > MAX_CAPTURE_CHARS) {
            setError("That recording is too long to send. Try a shorter one.");
            return;
          }
          onChange(encoded);
        };
        reader.onerror = () => setError("The recording could not be encoded.");
        reader.readAsDataURL(blob);
      };

      recorderRef.current = recorder;
      recorder.start();
      setSeconds(0);
      setRecording(true);
    } catch {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setError("The microphone is unavailable here. The scan will proceed without it.");
    }
  }

  function stop() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  const locked = disabled || !supported;

  return (
    <div className="px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[15px] font-medium text-[#171717]">Voice confirmation</div>
          <p className="mt-0.5 text-[13px] text-[#525252]">
            Say the container code and confirm out loud. Faster than a touchscreen in gloves.
          </p>
        </div>
        {value ? <Badge tone="green">captured</Badge> : <Badge tone="neutral">optional</Badge>}
      </div>

      {!supported ? (
        <p className="mt-2 text-[12px] text-[#737373]">
          Recording is unavailable in this browser. The scan will proceed on the task token.
        </p>
      ) : recording ? (
        <button
          type="button"
          onClick={stop}
          className="mt-2.5 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-[8px] border border-[#fecaca] bg-[#fef2f2] px-4 text-[15px] font-medium text-[#991b1b]"
        >
          <span className="h-2.5 w-2.5 rounded-full bg-[#dc2626]" aria-hidden />
          Stop recording
          <span className="mono text-[15px]">
            {seconds}s / {MAX_VOICE_SECONDS}s
          </span>
        </button>
      ) : value ? (
        <div className="mt-2.5 flex gap-2">
          <button
            type="button"
            onClick={start}
            disabled={locked}
            className="min-h-[48px] flex-1 rounded-[8px] border border-[#e5e5e5] bg-white px-3 text-[15px] font-medium text-[#171717] disabled:opacity-40"
          >
            Record again
          </button>
          <button
            type="button"
            onClick={() => onChange(null)}
            disabled={locked}
            className="min-h-[48px] flex-1 rounded-[8px] border border-[#e5e5e5] bg-white px-3 text-[15px] font-medium text-[#525252] disabled:opacity-40"
          >
            Clear
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={start}
          disabled={locked}
          className="mt-2.5 min-h-[48px] w-full rounded-[8px] border border-[#171717] bg-white px-4 text-[15px] font-medium text-[#171717] disabled:opacity-40"
        >
          Record a confirmation
        </button>
      )}

      {error ? <p className="mt-1.5 text-[12px] text-[#991b1b]">{error}</p> : null}
    </div>
  );
}

/** What the captures on a scan that went through were found to say. */
function OutcomePanel({ outcome }: { outcome: CorroborationOutcome }) {
  return (
    <div className="mt-3 rounded-[12px] border border-[#e5e5e5] bg-white">
      <div className="border-b border-[#e5e5e5] px-4 py-2.5">
        <h2 className="text-[13px] font-semibold text-[#171717]">Capture corroboration</h2>
        <p className="mt-0.5 text-[13px] text-[#525252]">{outcome.reason}</p>
      </div>
      {outcome.records.length === 0 ? (
        <p className="px-4 py-3 text-[13px] text-[#525252]">
          Nothing was captured, so this scan is recorded as resting on the task token alone.
        </p>
      ) : (
        <ul className="divide-y divide-[#e5e5e5]">
          {outcome.records.map((record) => (
            <li key={record.kind} className="px-4 py-3">
              <RecordBody record={record} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The 409. Nothing was written and nothing broke: a photograph disagreed with the record
 * and the commit stopped there, so the panel has to read as a decision rather than a
 * failure and put the two numbers that disagreed next to each other.
 */
function RefusalPanel({
  refusal,
  onRetake,
}: {
  refusal: CorroborationOutcome;
  onRetake: () => void;
}) {
  const contradictions = refusal.records.filter((record) => record.status === "MISMATCH");
  const rest = refusal.records.filter((record) => record.status !== "MISMATCH");

  return (
    <div role="alert" className="mt-3 rounded-[12px] border-2 border-[#fecaca] bg-[#fef2f2]">
      <div className="border-b border-[#fecaca] px-4 py-3">
        <Badge tone="red" dot>
          REFUSED ON EVIDENCE
        </Badge>
        <p className="mt-2 text-[17px] leading-tight font-semibold text-[#991b1b]">
          Nothing was recorded. A capture disagreed with the record.
        </p>
        <p className="mt-1.5 text-[14px] text-[#991b1b]">{refusal.reason}</p>
      </div>

      {contradictions.map((record) => (
        <div key={record.kind} className="border-b border-[#fecaca] px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[15px] font-medium text-[#991b1b]">
              {KIND_LABEL[record.kind] ?? record.kind}
            </span>
            <Badge tone="red">MISMATCH</Badge>
          </div>
          <p className="mt-1 text-[13px] text-[#991b1b]">{record.detail}</p>
          <ObservedExpected record={record} tone="bad" />
          <ReaderLine record={record} tone="bad" />
        </div>
      ))}

      {rest.length > 0 ? (
        <ul className="divide-y divide-[#fecaca] border-b border-[#fecaca]">
          {rest.map((record) => (
            <li key={record.kind} className="px-4 py-3">
              <RecordBody record={record} />
            </li>
          ))}
        </ul>
      ) : null}

      <div className="p-4">
        <button
          type="button"
          onClick={onRetake}
          className="min-h-[56px] w-full rounded-[8px] bg-[#991b1b] px-4 text-[17px] font-semibold text-white"
        >
          Clear that capture and retake
        </button>
        <p className="mt-2 text-[12px] text-[#991b1b]">
          Captures that held are kept. Only the one that disagreed is cleared.
        </p>
      </div>
    </div>
  );
}

function RecordBody({ record }: { record: CorroborationRecord }) {
  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[15px] font-medium text-[#171717]">
          {KIND_LABEL[record.kind] ?? record.kind}
        </span>
        <Badge tone={statusTone(record.status)} dot>
          {record.status}
        </Badge>
      </div>
      <p className="mt-1 text-[13px] text-[#525252]">{record.detail}</p>
      <ObservedExpected record={record} tone="plain" />
      <ReaderLine record={record} tone="plain" />
    </>
  );
}

function ObservedExpected({
  record,
  tone,
}: {
  record: CorroborationRecord;
  tone: "plain" | "bad";
}) {
  if (!record.observed && !record.expected) return null;
  const box = tone === "bad" ? "border border-[#fecaca] bg-white" : "bg-[#f5f5f5]";
  const label = tone === "bad" ? "text-[#991b1b]" : "text-[#737373]";
  const body = tone === "bad" ? "text-[#991b1b]" : "text-[#171717]";
  return (
    <div className={`mt-2 grid gap-2 ${record.expected ? "grid-cols-2" : "grid-cols-1"}`}>
      <div className={`rounded-[8px] px-3 py-2 ${box}`}>
        <div className={`text-[11px] tracking-wide uppercase ${label}`}>Observed in capture</div>
        <div className={`mono mt-0.5 text-[16px] leading-tight font-medium break-words ${body}`}>
          {record.observed || "nothing readable"}
        </div>
      </div>
      {record.expected ? (
        <div className={`rounded-[8px] px-3 py-2 ${box}`}>
          <div className={`text-[11px] tracking-wide uppercase ${label}`}>Expected on record</div>
          <div className={`mono mt-0.5 text-[16px] leading-tight font-medium break-words ${body}`}>
            {record.expected}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ReaderLine({ record, tone }: { record: CorroborationRecord; tone: "plain" | "bad" }) {
  if (!record.read_by_model && !record.capture_sha256) return null;
  return (
    <p className={`mt-1.5 text-[11px] ${tone === "bad" ? "text-[#991b1b]" : "text-[#737373]"}`}>
      {record.read_by_model ? (
        <>
          read by <span className="mono">{record.read_by_model}</span>
        </>
      ) : null}
      {record.capture_sha256 ? (
        <>
          {record.read_by_model ? " · " : null}
          capture <span className="mono">{record.capture_sha256}</span>
        </>
      ) : null}
    </p>
  );
}

function statusTone(status: string): "green" | "red" | "neutral" {
  if (status === "CONFIRMED") return "green";
  if (status === "MISMATCH") return "red";
  return "neutral";
}

function readAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsDataURL(blob);
  });
}

/**
 * Resize a camera capture onto a canvas and re-encode it as JPEG before sending.
 *
 * Sending the file straight off the sensor is what breaks this flow. A phone photo
 * base64-encodes past the six million character field limit, and even when it squeaks
 * under, the upload takes long enough on cold-room signal that a responder gives up. The
 * long edge is capped instead of the file size because that is what the reader depends
 * on: the model needs the label glyphs and the seven-segment digits, both of which survive
 * 1280px, and nothing else in the frame matters.
 */
async function downscaleToJpegDataUrl(file: File): Promise<string> {
  const source = await readAsDataUrl(file);
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const element = new Image();
    element.onload = () => resolve(element);
    element.onerror = () => reject(new Error("That file is not an image this browser can read."));
    element.src = source;
  });

  const longest = Math.max(image.naturalWidth || image.width, image.naturalHeight || image.height);
  if (longest === 0) throw new Error("That photo came back empty. Try again.");
  const scale = Math.min(1, MAX_CAPTURE_EDGE_PX / longest);

  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round((image.naturalWidth || image.width) * scale));
  canvas.height = Math.max(1, Math.round((image.naturalHeight || image.height) * scale));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("This browser cannot resize the photo, so it was not sent.");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", CAPTURE_JPEG_QUALITY);
}

function Remaining({ tasks }: { tasks: ResponderTask[] }) {
  if (tasks.length <= 1) return null;
  return (
    <div className="mt-4 rounded-[12px] border border-[#e5e5e5] bg-white">
      <div className="border-b border-[#e5e5e5] px-4 py-2.5">
        <h2 className="text-[13px] font-semibold text-[#171717]">Batch</h2>
      </div>
      <ul className="max-h-[280px] divide-y divide-[#e5e5e5] overflow-y-auto">
        {tasks.map((t) => (
          <li key={t.container_id} className="flex items-center justify-between gap-2 px-4 py-2">
            <span className="mono text-[13px] text-[#171717]">{t.container_id}</span>
            <span
              className={`rounded-full px-2 py-[2px] text-[11px] font-medium ${
                t.custody_state === "COMMITTED"
                  ? "bg-[#dcfce7] text-[#166534]"
                  : t.custody_state === "UNRESOLVED"
                    ? "bg-[#fef2f2] text-[#991b1b]"
                    : t.custody_state === "AT_SOURCE"
                      ? "bg-[#f5f5f5] text-[#404040]"
                      : "bg-[#dbeafe] text-[#1e40af]"
              }`}
            >
              {t.custody_state.replace(/_/g, " ")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
