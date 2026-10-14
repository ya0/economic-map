/** Usage counts with GoatCounter (no cookies, no personal data), on the published site only: the page view, and each
 * control a visitor uses, once per visit. Typed text (search, min and max) is never sent, only that the field was used. */
export const SITE = "https://yammann.ch/economic-map/"; // the published address
const GC = { src: "https://gc.zgo.at/count.v5.js", sri: "sha384-atnOLvQb9t+jTSipvd75X2yginT4PjVbqDdlJAmxMm+wYElFmeR6EmLP5bYeoRVQ", to: "https://yannikammann.goatcounter.com/count" };

type El = { id: string; tagName: string; type?: string; value?: string; checked?: boolean; open?: boolean };
/** The event a used control names, or "" for none: `set/<id>/<value>` for a select or checkbox, `set/<id>` for a
 * text field or radio button, `click/<id>` for a button, `open/<id>` for an opened section. */
export function eventName(e: El, kind: "change" | "click" | "toggle"): string {
  if (!e.id) return "";
  if (kind === "toggle") return e.open ? `open/${e.id}` : "";
  if (kind === "click") return e.tagName === "BUTTON" ? `click/${e.id}` : "";
  if (e.tagName === "SELECT") return `set/${e.id}/${e.value}`;
  if (e.type === "checkbox") return `set/${e.id}/${e.checked ? "on" : "off"}`;
  return e.tagName === "INPUT" ? `set/${e.id}` : "";
}

export function startTracking() {
  if (!location.href.startsWith(SITE)) return; // a local build or preview counts nothing
  const sent = new Set<string>(), waiting: string[] = [];
  const gc = () => (window as { goatcounter?: { count?: (o: object) => void } }).goatcounter?.count;
  const flush = () => { while (gc() && waiting.length) gc()!({ path: waiting.shift(), event: true }); };
  const track = (name: string) => { if (name && !sent.has(name)) { sent.add(name); waiting.push(name); flush(); } };
  const s = Object.assign(document.createElement("script"), { src: GC.src, integrity: GC.sri, crossOrigin: "anonymous", async: true, onload: flush });
  s.dataset.goatcounter = GC.to;
  document.head.append(s);
  for (const kind of ["change", "click", "toggle"] as const)
    document.addEventListener(kind, (ev) => {
      const t = ev.target as Element;
      if (kind === "click" && t.closest?.("#results li")) return track("search/pick");
      track(eventName((kind === "click" ? t.closest?.("button") : t) as unknown as El ?? { id: "", tagName: "" }, kind));
    }, true); // capture: `toggle` does not bubble
}
