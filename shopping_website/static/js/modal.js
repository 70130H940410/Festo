// static/js/modal.js
(function () {
  const backdrop = document.getElementById("appModalBackdrop");
  if (!backdrop) return;

  const titleEl   = document.getElementById("appModalTitle");
  const bodyEl    = document.getElementById("appModalBody");
  const btnOk     = document.getElementById("appModalOk");
  const btnCancel = document.getElementById("appModalCancel");
  const btnClose  = document.getElementById("appModalClose");

  let resolveFn = null;
  let lastActiveEl = null;

  function openModal({
    title = "確認",
    message = "",
    okText = "確定",
    cancelText = "取消",
    danger = true,
    hideCancel = false
  } = {}) {
    lastActiveEl = document.activeElement;

    titleEl.textContent = title;
    bodyEl.textContent = message;

    btnOk.textContent = okText;
    btnCancel.textContent = cancelText;

    // alert 模式只顯示確定
    btnCancel.style.display = hideCancel ? "none" : "";

    btnOk.classList.toggle("btn-danger", !!danger);
    btnOk.classList.toggle("btn-primary", !danger);

    backdrop.classList.add("is-open");
    backdrop.setAttribute("aria-hidden", "false");
    setTimeout(() => btnOk.focus(), 0);

    return new Promise((resolve) => {
      resolveFn = resolve;
    });
  }

  function closeModal(result) {
    backdrop.classList.remove("is-open");
    backdrop.setAttribute("aria-hidden", "true");

    if (resolveFn) resolveFn(result);
    resolveFn = null;

    if (lastActiveEl && typeof lastActiveEl.focus === "function") {
      setTimeout(() => lastActiveEl.focus(), 0);
    }
  }

  btnOk.addEventListener("click", () => closeModal(true));
  btnCancel.addEventListener("click", () => closeModal(false));
  btnClose.addEventListener("click", () => closeModal(false));

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) closeModal(false);
  });

  document.addEventListener("keydown", (e) => {
    if (!backdrop.classList.contains("is-open")) return;
    if (e.key === "Escape") closeModal(false);
  });

  function extractConfirmMessage(attr) {
    const m = attr.match(/confirm\((['"])(.*?)\1\)/);
    return m ? m[2] : null;
  }

  // ✅ 全域攔截 confirm（表單 submit）
  document.addEventListener("submit", async function (e) {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (form.dataset._confirmed === "1") {
      form.dataset._confirmed = "0";
      return;
    }

    let msg = null;

    if (form.dataset.confirm) msg = form.dataset.confirm;

    if (!msg) {
      const on = form.getAttribute("onsubmit");
      if (on && on.includes("confirm(")) msg = extractConfirmMessage(on);
    }

    if (!msg) return;

    e.preventDefault();
    e.stopImmediatePropagation();

    const ok = await openModal({
      title: "請確認操作",
      message: msg,
      okText: "確定",
      cancelText: "取消",
      danger: true
    });

    if (ok) {
      form.dataset._confirmed = "1";
      form.submit();
    }
  }, true);

  // ✅ 全域攔截 confirm（a[data-confirm]）
  document.addEventListener("click", async function (e) {
    const a = e.target.closest("a[data-confirm]");
    if (!a) return;

    e.preventDefault();

    const ok = await openModal({
      title: "請確認操作",
      message: a.dataset.confirm,
      okText: "確定",
      cancelText: "取消",
      danger: true
    });

    if (ok) window.location.href = a.href;
  });

  // ✅ 讓你手動呼叫
  window.appConfirm = (message, opt = {}) => openModal({ message, ...opt });

  // ✅ alert：只有確定
  window.appAlert = (message, opt = {}) => openModal({
    title: opt.title || "提示",
    message: String(message),
    okText: opt.okText || "確定",
    danger: false,
    hideCancel: true
  }).then(() => true);

  // ✅ 覆寫原生 alert（全站 alert 變漂亮）
  window.alert = function (message) {
    // 回傳 Promise 不會影響一般 `alert(); return;` 的用法
    return window.appAlert(message);
  };
})();

