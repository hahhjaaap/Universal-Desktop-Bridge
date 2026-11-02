"use strict";

const button = document.getElementById("refresh");
const status = document.getElementById("relayStatus");
const labels = {
  online: "Cloudflare relay đang phản hồi.",
  unavailable: "Không kết nối được Cloudflare relay.",
  not_configured: "Chưa cấu hình URL Cloudflare trên Render.",
  unexpected_response: "Cloudflare phản hồi không đúng giao thức kiểm tra.",
};

button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Đang kiểm tra…";
  try {
    const response = await fetch("/api/relay-status", { cache: "no-store" });
    if (!response.ok) throw new Error("status_unavailable");
    const body = await response.json();
    status.textContent = labels[body.state] || "Không xác định trạng thái.";
  } catch {
    status.textContent = "Không kiểm tra được trạng thái.";
  } finally {
    button.disabled = false;
  }
});
