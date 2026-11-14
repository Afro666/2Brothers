import nvidiaLogo from "@/assets/nvidia-logo.svg";

/** True when a model id or name is Nemotron (`nemotron-3.5-super-vl`, "Nemotron 3.5 Super VL"). */
export function isNemotron(model: string | null | undefined): boolean {
  return /nemotron/i.test(model ?? "");
}

/**
 * NVIDIA's logo next to the words that name Nemotron, so a tester sees where the model did the
 * work. The words stay; the logo is decoration (empty alt, hidden from screen readers).
 * The file is NVIDIA's own, unchanged (web/src/assets/nvidia-logo.svg, from Wikimedia Commons
 * "File:NVIDIA_logo.svg"). Its wordmark is black, so it sits on a small white chip that reads in
 * dark mode too. `when` false (the parser or a rule answered, no model ran) renders nothing.
 * `side` is where the mark sits against the words: "before" them or "after" them.
 */
export function NemotronMark({ when = true, side = "before" }: { when?: boolean; side?: "before" | "after" }) {
  if (!when) return null;
  return (
    <span
      aria-hidden="true"
      data-testid="nemotron-mark"
      className={`inline-flex h-[1em] shrink-0 items-center whitespace-nowrap rounded-[0.2em] bg-white px-[0.25em] align-[-0.15em] ring-1 ring-black/10 ${
        side === "before" ? "mr-[0.35em]" : "ml-[0.35em]"
      }`}
    >
      <img src={nvidiaLogo} alt="" draggable={false} className="block h-[0.75em] w-auto max-w-none" />
    </span>
  );
}
