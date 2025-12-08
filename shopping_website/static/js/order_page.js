// static/js/order_page.js

document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("order-form");
  const qtyInputs = Array.from(
    document.querySelectorAll(".order-qty-input")
  );
  const summaryText = document.getElementById("order-summary-text");
  const totalPriceDisplay = document.getElementById("total-price-display");

  if (!form || qtyInputs.length === 0) {
    return;
  }

  // 更新「本次下單摘要」與「總金額」的顯示文字
  function updateSummary() {
    let totalQty = 0;
    let totalPrice = 0;
    const pickedItems = [];

    qtyInputs.forEach((input) => {
      const raw = input.value.trim();
      const qty = raw === "" ? 0 : parseInt(raw, 10) || 0;
      const price = parseFloat(input.dataset.basePrice) || 0;

      if (qty > 0) {
        totalQty += qty;
        totalPrice += qty * price;
        const name = input.dataset.productName || "產品";
        pickedItems.push(`${name} x ${qty}`);
      }
    });

    if (totalQty === 0) {
      summaryText.textContent = "目前尚未選擇任何產品。";
      if (totalPriceDisplay) {
        totalPriceDisplay.style.display = "none";
        totalPriceDisplay.textContent = "總金額：$0";
      }
    } else {
      summaryText.textContent =
        `已選擇 ${pickedItems.length} 種產品，共 ${totalQty} 件：` +
        pickedItems.join("、");

      if (totalPriceDisplay) {
        totalPriceDisplay.style.display = "block";
        totalPriceDisplay.textContent = `總金額：$${totalPrice.toLocaleString()}`; // 加千分位逗號
      }
    }
  }

  // 輸入時：做基本檢查 + 即時更新摘要
  qtyInputs.forEach((input) => {
    input.addEventListener("input", () => {
      const min = parseInt(input.min || "0", 10);
      const max = parseInt(input.max || "999999", 10);
      let value = input.value.trim();

      if (value === "") {
        input.value = "";
        updateSummary();
        return;
      }

      let num = parseInt(value, 10);
      if (isNaN(num)) {
        num = 0;
      }

      // 前端先幫你 clamp 在合理範圍
      if (num < min) num = min;
      if (num > max) num = max;

      input.value = num.toString();
      updateSummary();
    });
  });

  // 一開始進來先更新一次摘要（會顯示「尚未選擇」）
  updateSummary();

  // 送出表單前做一層前端檢查
  form.addEventListener("submit", function (event) {
    let totalQty = 0;
    let hasInvalid = false;
    let invalidMessage = "";

    qtyInputs.forEach((input) => {
      const name = input.dataset.productName || "產品";
      const min = parseInt(input.min || "0", 10);
      const max = parseInt(input.max || "999999", 10);
      let value = input.value.trim();

      if (value === "") {
        value = "0";
      }
      let num = parseInt(value, 10);
      if (isNaN(num)) {
        num = 0;
      }

      if (num < min) {
        hasInvalid = true;
        invalidMessage = `${name} 的數量不可小於 ${min}。`;
      }
      if (num > max) {
        hasInvalid = true;
        invalidMessage = `${name} 的數量不可超過庫存（最多 ${max} 件）。`;
      }

      totalQty += num;
    });

    if (hasInvalid) {
      event.preventDefault();
      alert(invalidMessage);
      return;
    }

    if (totalQty === 0) {
      event.preventDefault();
      alert("請至少選擇一項產品的數量大於 0，再進入製程規劃。");
      return;
    }

    // 通過前端檢查就讓表單照常送出，後端 app.py 仍然會做最後驗證
  });
});
