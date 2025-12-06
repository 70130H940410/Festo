// 購物車暫存陣列
let cart = [];
let allProducts = [];

// 頁面載入時執行
document.addEventListener("DOMContentLoaded", function() {
    loadProducts();
});

// 1. 從後端 API 載入產品資料
function loadProducts() {
    fetch('/api/products')
        .then(response => response.json())
        .then(data => {
            allProducts = data; // 存起來備用
            const select = document.getElementById("product-select");
            
            // 建立下拉選單
            data.forEach(p => {
                let option = document.createElement("option");
                option.value = p.id;
                option.text = `${p.name} (庫存: ${p.total}) - $${p.base_price}`;
                // 庫存為 0 就不能選
                if (p.total <= 0) option.disabled = true;
                select.add(option);
            });
        })
        .catch(err => console.error("載入產品失敗:", err));
}

// 2. 加入購物車按鈕點擊事件
function addToCart() {
    const select = document.getElementById("product-select");
    const qtyInput = document.getElementById("product-qty");
    const pid = parseInt(select.value);
    const qty = parseInt(qtyInput.value);
    
    if (!pid || qty <= 0) {
        alert("請選擇商品並輸入正確數量");
        return;
    }

    // 檢查是否已在購物車內
    const existingItem = cart.find(item => item.id === pid);
    
    // 檢查庫存 (從前端簡單檢查，後端會再擋一次)
    const productInfo = allProducts.find(p => p.id === pid);
    if (qty > productInfo.total) {
        alert("庫存不足！");
        return;
    }

    if (existingItem) {
        existingItem.qty += qty;
    } else {
        cart.push({
            id: pid,
            name: productInfo.name,
            price: productInfo.base_price,
            qty: qty
        });
    }

    renderCartTable();
    qtyInput.value = 1; // 重置數量格
}

// 3. 渲染購物車表格
function renderCartTable() {
    const tbody = document.getElementById("cart-body");
    const totalSpan = document.getElementById("cart-total-price");
    tbody.innerHTML = "";
    
    let totalPrice = 0;

    cart.forEach((item, index) => {
        let subtotal = item.price * item.qty;
        totalPrice += subtotal;

        let row = `
            <tr>
                <td>${item.name}</td>
                <td>$${item.price}</td>
                <td>${item.qty}</td>
                <td>$${subtotal}</td>
                <td><button onclick="removeFromCart(${index})" class="btn-danger">刪除</button></td>
            </tr>
        `;
        tbody.innerHTML += row;
    });

    totalSpan.textContent = totalPrice;
}

// 移除項目
function removeFromCart(index) {
    cart.splice(index, 1);
    renderCartTable();
}

// 4. 送出訂單 (Checkout)
function submitOrder() {
    if (cart.length === 0) {
        alert("購物車是空的！");
        return;
    }

    // 準備要傳給後端的 JSON
    const payload = {
        cart: cart
    };

    fetch('/api/checkout', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            alert(result.message);
            cart = []; // 清空購物車
            renderCartTable();
            // 導向歷史紀錄
            window.location.href = "/history";
        } else {
            alert("結帳失敗：" + result.message);
        }
    })
    .catch(err => console.error("結帳錯誤:", err));
}