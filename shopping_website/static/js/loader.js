document.addEventListener("DOMContentLoaded", function () {
  const loader = document.getElementById("page-loader");
  if (!loader) return;

  // 從 body 讀取目前頁面的 endpoint 名稱（例如 "index", "order.order_page"...）
  const page = document.body.dataset.page || "";

  // 只在首頁 index 才啟用 Loader
  const isIndex = (page === "index");
  if (!isIndex) {
    loader.classList.add("hide");
    return;
  }

  const SEEN_KEY = "festo_seen_index_v2";  // ← 換個 key，方便你重新測試

  // 如果已經看過一次首頁 Loader，就直接隱藏
  const seen = window.localStorage.getItem(SEEN_KEY);
  if (seen === "1") {
    loader.classList.add("hide");
    return;
  }

  // 第一次進首頁：記錄已看過，4 秒後淡出
  window.localStorage.setItem(SEEN_KEY, "1");

  // 這裡決定顯示多久（毫秒），4 秒 = 4000
  setTimeout(function () {
    loader.classList.add("hide");
  }, 2000);
});



