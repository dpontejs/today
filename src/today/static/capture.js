// Hold-to-talk capture: record while the mic button is pressed, send the audio to /capture on release and
// show the review card the server returns. iOS Safari records audio/mp4 (AAC); Chrome records webm/opus.
(() => {
  const mic = document.getElementById("capture-mic");
  const target = document.getElementById("capture-review");
  const status = document.getElementById("capture-status");
  const MAX_MS = 60_000;

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-discard]") && target) target.innerHTML = "";
  });
  if (!mic) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    mic.hidden = true;
    return;
  }

  let held = false;
  let recorder = null;
  let stream = null;
  let chunks = [];
  let startedAt = 0;

  const say = (text) => { status.textContent = text || ""; };

  async function start(event) {
    event.preventDefault();
    if (recorder) return;
    held = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      say(mic.dataset.denied);
      return;
    }
    if (!held) {
      // Released while the permission prompt was open: do not keep recording.
      stream.getTracks().forEach((t) => t.stop());
      say(mic.dataset.tooShort);
      return;
    }
    const type = ["audio/mp4", "audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/webm"]
      .find((t) => MediaRecorder.isTypeSupported(t));
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = [];
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = send;
    recorder.start();
    startedAt = Date.now();
    mic.classList.add("is-recording");
    say(mic.dataset.recording);
    setTimeout(stop, MAX_MS);
  }

  function stop() {
    held = false;
    if (!recorder || recorder.state !== "recording") return;
    recorder.stop();
    stream.getTracks().forEach((t) => t.stop());
    mic.classList.remove("is-recording");
  }

  async function send() {
    const done = recorder;
    recorder = null;
    if (Date.now() - startedAt < 500) {
      say(mic.dataset.tooShort);
      return;
    }
    const mime = (done.mimeType || "audio/mp4").split(";")[0];
    const ext = mime.includes("webm") ? "webm" : mime.includes("ogg") ? "ogg" : "m4a";
    const body = new FormData();
    body.append("audio", new Blob(chunks, { type: mime }), `note.${ext}`);
    say(mic.dataset.understanding);
    try {
      const res = await fetch("/capture", { method: "POST", body, headers: { "HX-Request": "true" } });
      const redirect = res.headers.get("HX-Redirect");
      if (redirect) {
        window.location.href = redirect;
        return;
      }
      target.innerHTML = await res.text();
      window.htmx?.process(target);
      say("");
    } catch {
      say(mic.dataset.failed);
    }
  }

  mic.addEventListener("pointerdown", start);
  ["pointerup", "pointercancel"].forEach((name) => mic.addEventListener(name, stop));
  mic.addEventListener("contextmenu", (e) => e.preventDefault());
})();
