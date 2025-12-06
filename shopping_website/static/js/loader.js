// static/js/loader.js

document.addEventListener("DOMContentLoaded", function () {
  const loader = document.getElementById("page-loader");
  if (!loader) return;

  // 從 <body data-page="..."> 讀目前是哪個 endpoint
  const page = document.body.dataset.page || "";

  // ✅ 1. 只有首頁 index 才顯示 Loader
  if (page !== "index") {
    // 其它頁面一載入就直接關掉 Loader，不要閃一下
    loader.classList.add("hide");
    return;
  }

  // ✅ 2. 首頁才需要顯示 Loader，這邊設定顯示 6000 ms（6 秒）
  const DISPLAY_MS = 3000;
  const startTime = performance.now();

  function hideLoader() {
    const elapsed = performance.now() - startTime;
    const remain = DISPLAY_MS - elapsed;

    if (remain <= 0) {
      loader.classList.add("hide");
    } else {
      setTimeout(() => loader.classList.add("hide"), remain);
    }
  }

  // 等整個頁面（含圖片、CSS）載完，再開始算 6 秒
  window.addEventListener("load", hideLoader);
});






