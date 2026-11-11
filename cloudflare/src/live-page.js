export function livePage(nonce) {
  return `<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UDB Live</title>
<style nonce="__NONCE__">
  :root { color-scheme: dark; font: 15px/1.55 Inter, system-ui, sans-serif; color: #edf3f4; background: #101719; }
  * { box-sizing: border-box; }
  body { margin: 0; }
  main { max-width: 1400px; margin: auto; padding: clamp(20px, 4vw, 54px); }
  header, .toolbar { display: flex; justify-content: space-between; gap: 16px; align-items: center; flex-wrap: wrap; }
  header { margin-bottom: 26px; }
  h1 { margin: 0; font-size: clamp(28px, 4vw, 40px); letter-spacing: -.04em; line-height: 1.15; }
  h2 { margin: 0 0 12px; font-size: 16px; }
  p { margin: 8px 0 0; color: #b4c3c5; }
  button, select { border: 1px solid #3b5154; background: #1e2b2e; color: inherit; padding: 9px 13px; font: inherit; border-radius: 8px; }
  button { cursor: pointer; }
  button:hover:not(:disabled) { background: #2a3d40; }
  button:focus-visible, select:focus-visible { outline: 2px solid #6ce0c4; outline-offset: 3px; }
  button:disabled { opacity: .5; cursor: default; }
  #toggle { background: #8be1cd; color: #102422; border-color: #8be1cd; font-weight: 650; }
  .toolbar { padding: 14px; background: #182325; border: 1px solid #344649; border-radius: 12px 12px 0 0; }
  .select { display: flex; align-items: center; gap: 10px; min-width: 0; max-width: 100%; }
  select { min-width: 0; max-width: min(440px, 55vw); }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; }
  #viewer { margin: 0; min-height: min(60vh, 640px); display: grid; place-items: center; overflow: hidden; border: 1px solid #344649; border-top: 0; border-radius: 0 0 12px 12px; background: #080e10; }
  #viewer:fullscreen { border: 0; border-radius: 0; }
  #viewer img { display: block; max-width: 100%; max-height: 76vh; width: auto; height: auto; object-fit: contain; }
  #viewer:fullscreen img { max-height: 100vh; }
  #viewer img[hidden], [hidden] { display: none; }
  #empty { max-width: 430px; padding: 24px; text-align: center; }
  #status { margin-top: 12px; min-height: 24px; }
  dialog { color: inherit; background: #182325; border: 1px solid #42595c; border-radius: 12px; padding: 22px; }
  dialog::backdrop { background: #0009; }
  dialog dl { display: grid; grid-template-columns: auto 1fr; gap: 8px 20px; }
  dialog dd { margin: 0; }
  kbd { font: inherit; color: #8be1cd; }
</style>
</head>
<body>
<main>
  <header>
    <div><h1>UDB Live</h1><p>Xem tab trong trình duyệt riêng của UDB trên Windows.</p></div>
    <button id="help" type="button">Phím tắt</button>
  </header>
  <section class="toolbar" aria-label="Điều khiển Live">
    <label class="select" for="tab">Tab UDB <select id="tab" disabled><option>Chưa có tab</option></select></label>
    <div class="actions">
      <button id="reload" type="button">Làm mới tab</button>
      <button id="fullscreen" type="button" disabled>Toàn màn hình</button>
      <button id="toggle" type="button" disabled>Bắt đầu Live</button>
    </div>
  </section>
  <figure id="viewer" aria-label="Ảnh tab UDB đang xem">
    <div id="empty"><h2 id="empty-title">Đang kiểm tra Windows</h2><p id="empty-detail"></p></div>
    <img id="frame" alt="Ảnh mới nhất của tab UDB" hidden>
  </figure>
  <p id="status" role="status"></p>
</main>
<dialog id="shortcuts">
  <h2>Phím tắt UDB Live</h2>
  <dl>
    <dt><kbd>Space</kbd></dt><dd>Bắt đầu hoặc dừng Live</dd>
    <dt><kbd>R</kbd></dt><dd>Làm mới danh sách tab</dd>
    <dt><kbd>F</kbd></dt><dd>Bật hoặc thoát toàn màn hình</dd>
    <dt><kbd>Esc</kbd></dt><dd>Dừng Live</dd>
    <dt><kbd>?</kbd></dt><dd>Hiện phím tắt</dd>
  </dl>
  <button id="close-help" type="button">Đóng</button>
</dialog>
<script nonce="__NONCE__">
  const byId = (id) => document.getElementById(id);
  const tab = byId("tab");
  const frame = byId("frame");
  const viewer = byId("viewer");
  const status = byId("status");
  const toggle = byId("toggle");
  const reload = byId("reload");
  const fullscreen = byId("fullscreen");
  const help = byId("shortcuts");
  let tabs = [];
  let active = false;
  let generation = 0;
  let imageUrl;
  let timer;
  let controller;
  let refreshing = false;

  function notice(title, detail = "") {
    byId("empty-title").textContent = title;
    byId("empty-detail").textContent = detail;
    byId("empty").hidden = false;
    frame.hidden = true;
    frame.removeAttribute("src");
    fullscreen.disabled = true;
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    imageUrl = undefined;
  }

  function stop(message = "") {
    active = false;
    generation += 1;
    clearTimeout(timer);
    controller?.abort();
    controller = undefined;
    toggle.textContent = "Bắt đầu Live";
    status.textContent = message;
  }

  function data(name, parameters = {}, signal) {
    const url = new URL(location.href);
    url.search = new URLSearchParams({ view: "live", data: name, ...parameters });
    url.hash = "";
    return fetch(url, { credentials: "same-origin", cache: "no-store", signal }).then(response => {
      const expected = name === "frame" ? "image/png" : "application/json";
      if (!response.ok || !response.headers.get("Content-Type")?.startsWith(expected))
        throw new Error(String(response.status));
      return name === "frame" ? response.blob() : response.json();
    });
  }

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    reload.disabled = true;
    stop();
    notice("Đang kiểm tra Windows");
    const previous = tab.value;
    tabs = [];
    tab.replaceChildren(new Option("Chưa có tab", ""));
    tab.disabled = toggle.disabled = true;
    try {
      const result = await data("status");
      if (!result.enabled || !result.ready) {
        notice("Phiên nền chưa sẵn sàng", "Bật trình duyệt nền trong UDB Manager trên Windows.");
        return;
      }
      for (const session of result.sessions) {
        const result = await data("tabs", { session: session.id });
        for (const entry of result.tabs) tabs.push({ ...entry, session: session.id });
      }
      if (!tabs.length) {
        notice("Chưa có tab UDB để xem", "Mở một trang bằng trình duyệt nền của UDB rồi làm mới danh sách.");
        return;
      }
      tab.replaceChildren(...tabs.map(item => new Option(item.title || "Tab UDB", item.id)));
      if (tabs.some(item => item.id === previous)) tab.value = previous;
      tab.disabled = toggle.disabled = false;
      notice("Sẵn sàng xem Live", "Chọn tab và bấm Bắt đầu Live.");
    } catch {
      notice("Chưa đọc được danh sách tab", "Kiểm tra đăng nhập Cloudflare Access và trạng thái Windows Agent.");
    } finally {
      reload.disabled = false;
      refreshing = false;
    }
  }

  async function poll(run, item) {
    const request = new AbortController();
    controller = request;
    const timeout = setTimeout(() => request.abort(), 8000);
    try {
      const blob = await data("frame", { session: item.session, tab: item.id }, request.signal);
      if (!active || generation !== run) return;
      const old = imageUrl;
      imageUrl = URL.createObjectURL(blob);
      frame.src = imageUrl;
      if (old) URL.revokeObjectURL(old);
      frame.hidden = false;
      byId("empty").hidden = true;
      fullscreen.disabled = false;
      status.textContent = "Live · Khung hình lúc " + new Date().toLocaleTimeString("vi-VN");
    } catch (error) {
      if (!active || generation !== run) return;
      if (error.message === "401" || error.message === "403") {
        stop();
        notice("Phiên xem đã hết quyền", "Tải lại trang để đăng nhập Cloudflare Access.");
        return;
      }
      notice("Đang chờ khung hình mới", "UDB có thể đang bận hoặc tab đã đóng.");
      status.textContent = "Đang thử lại.";
    } finally {
      clearTimeout(timeout);
      if (controller === request) controller = undefined;
      if (active && generation === run) timer = setTimeout(() => poll(run, item), 1250);
    }
  }

  function toggleLive() {
    if (active) { stop("Đã dừng Live."); return; }
    const item = tabs.find(item => item.id === tab.value);
    if (!item) return;
    active = true;
    toggle.textContent = "Dừng Live";
    status.textContent = "Đang lấy khung hình…";
    poll(++generation, item);
  }

  function full() {
    if (fullscreen.disabled) return;
    const result = document.fullscreenElement ? document.exitFullscreen() : viewer.requestFullscreen?.();
    result?.catch(() => { status.textContent = "Trình duyệt không bật được toàn màn hình."; });
  }

  reload.addEventListener("click", refresh);
  toggle.addEventListener("click", toggleLive);
  fullscreen.addEventListener("click", full);
  tab.addEventListener("change", () => { stop(); notice("Sẵn sàng xem Live"); });
  byId("help").addEventListener("click", () => help.showModal());
  byId("close-help").addEventListener("click", () => help.close());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && active) {
      stop("Đã dừng khi bạn rời tab.");
      notice("Live đã tạm dừng");
    }
  });
  document.addEventListener("keydown", event => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.repeat || help.open ||
        /^(INPUT|SELECT|BUTTON|TEXTAREA)$/.test(event.target.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === " ") { event.preventDefault(); toggleLive(); }
    else if (key === "r") refresh();
    else if (key === "f") full();
    else if (key === "escape" && active) stop("Đã dừng Live.");
    else if (key === "?") help.showModal();
  });
  refresh();
</script>
</body>
</html>`.replaceAll("__NONCE__", nonce);
}
