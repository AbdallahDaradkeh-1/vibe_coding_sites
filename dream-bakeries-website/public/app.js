(() => {
  const state = { csrf: '', products: [], categories: [], filter: 'all', cart: new Map() };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHTML = (value = '') => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const categoryNames = { bakery: 'المخبوزات', pastries: 'المعجنات', sweets: 'الحلويات', restaurant: 'المطعم' };
  const imageFallback = {
    bakery: '/public/images/category-bread.svg',
    pastries: '/public/images/category-pastries.svg',
    sweets: '/public/images/category-sweets.svg',
    restaurant: '/public/images/category-restaurant.svg'
  };

  async function getCsrf() {
    const response = await fetch('/api/csrf', { credentials: 'same-origin' });
    const data = await response.json();
    state.csrf = data.csrf_token || '';
  }

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes((options.method || 'GET').toUpperCase())) {
      headers['X-CSRF-Token'] = state.csrf;
    }
    const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'تعذر إكمال العملية. حاول مرة أخرى.');
    return data;
  }

  function showToast(message) {
    const toast = $('#toast');
    toast.textContent = message;
    toast.classList.add('show');
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove('show'), 2600);
  }

  function renderProducts() {
    const filtered = state.filter === 'all' ? state.products : state.products.filter(p => p.category_slug === state.filter);
    $('#productCount').textContent = `${filtered.length} منتج`;
    const grid = $('#productGrid');
    if (!filtered.length) {
      grid.innerHTML = '<div class="empty-products">لا توجد منتجات في هذا القسم حالياً.</div>';
      return;
    }
    grid.innerHTML = filtered.map((p) => {
      const image = p.image_path && p.image_path.startsWith('images/') ? `/public/${escapeHTML(p.image_path)}` : imageFallback[p.category_slug] || imageFallback.bakery;
      const tag = p.is_featured ? '<span class="product-tag">اختيار مميز</span>' : '';
      const availability = p.is_available ? '' : '<span class="availability-badge">غير متوفر</span>';
      const price = p.price_jod !== null && p.price_jod !== undefined ? `${Number(p.price_jod).toFixed(2)} د.أ` : 'السعر عند الطلب';
      return `<article class="product-card">
        <div class="product-image"><img src="${image}" alt="${escapeHTML(p.name)}" loading="lazy">${tag}${availability}</div>
        <div class="product-details"><span class="product-category">${escapeHTML(p.category_name || categoryNames[p.category_slug] || '')}</span><h3>${escapeHTML(p.name)}</h3><p>${escapeHTML(p.description || 'تفاصيل المنتج متوفرة عند الطلب.')}</p>
        <div class="product-bottom"><span class="product-price">${price}</span><button class="add-button" data-add="${p.id}" ${p.is_available ? '' : 'disabled'}>${p.is_available ? '＋ أضف للسلة' : 'غير متوفر'}</button></div></div></article>`;
    }).join('');
    $$('[data-add]', grid).forEach(button => button.addEventListener('click', () => addToCart(Number(button.dataset.add))));
  }

  function setFilter(filter) {
    state.filter = filter;
    $$('.filter-tab').forEach(button => button.classList.toggle('active', button.dataset.filter === filter));
    renderProducts();
  }

  function addToCart(productId) {
    const product = state.products.find(p => p.id === productId);
    if (!product || !product.is_available) return;
    const current = state.cart.get(productId) || 0;
    if (current >= 30) return showToast('الحد الأقصى للكمية في المنتج الواحد هو 30.');
    state.cart.set(productId, current + 1);
    renderCart();
    showToast(`تمت إضافة ${product.name} إلى السلة`);
  }

  function updateCart(productId, delta) {
    const next = (state.cart.get(productId) || 0) + delta;
    if (next <= 0) state.cart.delete(productId);
    else if (next <= 30) state.cart.set(productId, next);
    renderCart();
  }

  function renderCart() {
    const count = [...state.cart.values()].reduce((sum, qty) => sum + qty, 0);
    $('#cartCount').textContent = count;
    $('#floatingCartCount').textContent = count;
    $('#cartTotalQty').textContent = count;
    const items = [...state.cart.entries()].map(([id, quantity]) => ({ product: state.products.find(p => p.id === id), quantity })).filter(row => row.product);
    const container = $('#cartItems');
    if (!items.length) {
      container.innerHTML = '<div class="empty-cart"><span>🧺</span><b>السلة فارغة حالياً</b><small>أضيفوا المنتجات التي ترغبون بها لتبدأوا الطلب.</small></div>';
    } else {
      container.innerHTML = items.map(({ product, quantity }) => {
        const image = product.image_path && product.image_path.startsWith('images/') ? `/public/${escapeHTML(product.image_path)}` : imageFallback[product.category_slug] || imageFallback.bakery;
        return `<div class="cart-item"><img src="${image}" alt=""><div><h4>${escapeHTML(product.name)}</h4><small>السعر عند الطلب</small><div class="quantity-controls"><button type="button" data-minus="${product.id}" aria-label="تقليل الكمية">−</button><span>${quantity}</span><button type="button" data-plus="${product.id}" aria-label="زيادة الكمية">＋</button></div></div><button class="remove-item" data-remove="${product.id}" aria-label="حذف المنتج">×</button></div>`;
      }).join('');
      $$('[data-minus]', container).forEach(b => b.addEventListener('click', () => updateCart(Number(b.dataset.minus), -1)));
      $$('[data-plus]', container).forEach(b => b.addEventListener('click', () => updateCart(Number(b.dataset.plus), 1)));
      $$('[data-remove]', container).forEach(b => b.addEventListener('click', () => { state.cart.delete(Number(b.dataset.remove)); renderCart(); }));
    }
    $('#checkoutButton').disabled = count === 0;
  }

  function openCart() {
    $('#cartDrawer').classList.add('open');
    $('#cartBackdrop').classList.add('open');
    $('#cartDrawer').setAttribute('aria-hidden', 'false');
    document.body.classList.add('no-scroll');
  }
  function closeCart() {
    $('#cartDrawer').classList.remove('open');
    $('#cartBackdrop').classList.remove('open');
    $('#cartDrawer').setAttribute('aria-hidden', 'true');
    if (!$('#checkoutModal').classList.contains('open')) document.body.classList.remove('no-scroll');
  }
  function openCheckout() {
    if (!state.cart.size) return;
    closeCart();
    $('#checkoutBackdrop').classList.add('open');
    $('#checkoutModal').classList.add('open');
    $('#checkoutModal').setAttribute('aria-hidden', 'false');
    $('#checkoutForm').classList.remove('hidden');
    $('#orderSuccess').classList.add('hidden');
    $('#checkoutError').textContent = '';
    document.body.classList.add('no-scroll');
  }
  function closeCheckout() {
    $('#checkoutBackdrop').classList.remove('open');
    $('#checkoutModal').classList.remove('open');
    $('#checkoutModal').setAttribute('aria-hidden', 'true');
    document.body.classList.remove('no-scroll');
  }

  function setFulfillmentVisibility() {
    const value = $('input[name="fulfillment_type"]:checked')?.value;
    const label = $('#addressLabel');
    const input = $('#deliveryAddress');
    const delivery = value === 'delivery';
    label.classList.toggle('hidden', !delivery);
    input.required = delivery;
  }

  async function submitOrder(event) {
    event.preventDefault();
    const errorNode = $('#checkoutError');
    errorNode.textContent = '';
    const form = event.currentTarget;
    const formData = new FormData(form);
    const body = {
      customer_name: formData.get('customer_name'),
      phone: formData.get('phone'),
      fulfillment_type: formData.get('fulfillment_type'),
      address: formData.get('address'),
      notes: formData.get('notes'),
      items: [...state.cart.entries()].map(([product_id, quantity]) => ({ product_id, quantity }))
    };
    const button = $('.form-submit', form);
    button.disabled = true;
    button.textContent = 'جارٍ إرسال الطلب…';
    try {
      const result = await api('/api/orders', { method: 'POST', body: JSON.stringify(body) });
      $('#checkoutForm').classList.add('hidden');
      $('#orderSuccess').classList.remove('hidden');
      $('#successMessage').textContent = result.message;
      $('#orderReference').textContent = `رقم الطلب: ${result.order_ref}`;
      state.cart.clear();
      renderCart();
    } catch (error) {
      errorNode.textContent = error.message;
    } finally {
      button.disabled = false;
      button.innerHTML = 'إرسال الطلب <span>←</span>';
    }
  }

  function bindInteractions() {
    $('#year').textContent = new Date().getFullYear();
    $('#menuToggle').addEventListener('click', () => {
      const nav = $('#mainNav');
      const open = nav.classList.toggle('open');
      $('#menuToggle').setAttribute('aria-expanded', String(open));
    });
    $$('.main-nav a').forEach(a => a.addEventListener('click', () => {
      $('#mainNav').classList.remove('open');
      $('#menuToggle').setAttribute('aria-expanded', 'false');
    }));
    $('#filterTabs').addEventListener('click', event => {
      const button = event.target.closest('[data-filter]');
      if (button) setFilter(button.dataset.filter);
    });
    $$('[data-category]').forEach(link => link.addEventListener('click', () => {
      const filter = link.dataset.category;
      if (filter === 'restaurant') {
        setFilter('restaurant');
      } else {
        setFilter(filter);
      }
    }));
    $$('[data-jump-filter]').forEach(button => button.addEventListener('click', () => setFilter(button.dataset.jumpFilter)));
    $$('[data-footer-filter]').forEach(link => link.addEventListener('click', () => setFilter(link.dataset.footerFilter)));
    $('#openCart').addEventListener('click', openCart);
    $('#floatingCart').addEventListener('click', openCart);
    $('#closeCart').addEventListener('click', closeCart);
    $('#cartBackdrop').addEventListener('click', closeCart);
    $('#checkoutButton').addEventListener('click', openCheckout);
    $('#heroOrder').addEventListener('click', () => state.cart.size ? openCheckout() : (document.querySelector('#products').scrollIntoView({ behavior: 'smooth' }), showToast('اختر المنتجات أولاً لإضافتها إلى السلة.')));
    $('#serviceOrder').addEventListener('click', () => document.querySelector('#products').scrollIntoView({ behavior: 'smooth' }));
    $('#closeCheckout').addEventListener('click', closeCheckout);
    $('#checkoutBackdrop').addEventListener('click', closeCheckout);
    $('#finishOrder').addEventListener('click', closeCheckout);
    $$('input[name="fulfillment_type"]').forEach(input => input.addEventListener('change', setFulfillmentVisibility));
    $('#checkoutForm').addEventListener('submit', submitOrder);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeCart(); closeCheckout(); } });
  }

  async function init() {
    bindInteractions();
    setFulfillmentVisibility();
    renderCart();
    try {
      await getCsrf();
      const data = await api('/api/store');
      state.categories = data.categories;
      state.products = data.products;
      renderProducts();
    } catch (error) {
      $('#productGrid').innerHTML = '<div class="empty-products">تعذر تحميل المنتجات حالياً. يرجى تحديث الصفحة أو المحاولة لاحقاً.</div>';
      $('#productCount').textContent = 'تعذر التحميل';
      console.error(error);
    }
  }
  document.addEventListener('DOMContentLoaded', init);
})();
