(() => {
  const state = { csrf: '', user: null, products: [], categories: [], orders: [] };
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const escapeHTML = (value = '') => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const pageTitles = { overview: 'نظرة عامة', products: 'إدارة المنتجات', categories: 'إدارة الأقسام', orders: 'إدارة الطلبات' };
  const statusNames = { new: 'جديد', accepted: 'تم القبول', preparing: 'قيد التجهيز', ready: 'جاهز للاستلام', completed: 'مكتمل', cancelled: 'ملغى' };
  const statusClasses = { new: 'status-new', accepted: 'status-accepted', preparing: 'status-preparing', ready: 'status-ready', completed: 'status-completed', cancelled: 'status-cancelled' };
  const imageFallback = { bakery: 'images/category-bread.svg', pastries: 'images/category-pastries.svg', sweets: 'images/category-sweets.svg', restaurant: 'images/category-restaurant.svg' };

  async function getCsrf() {
    const r = await fetch('/api/csrf', { credentials: 'same-origin' });
    const d = await r.json(); state.csrf = d.csrf_token || '';
  }
  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    if (['POST','PUT','PATCH','DELETE'].includes((options.method || 'GET').toUpperCase())) headers['X-CSRF-Token'] = state.csrf;
    const r = await fetch(path, { ...options, headers, credentials: 'same-origin' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { if (r.status === 401) showLogin(); throw new Error(d.error || 'تعذر إتمام العملية.'); }
    return d;
  }
  function toast(message) {
    const node = $('#adminToast'); node.textContent = message; node.classList.add('show');
    clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('show'), 2500);
  }
  function showLogin() { $('#loginScreen').classList.remove('hidden'); $('#adminApp').classList.add('hidden'); }
  function showApp() { $('#loginScreen').classList.add('hidden'); $('#adminApp').classList.remove('hidden'); }
  function showPage(name) {
    $$('.admin-page').forEach(p => p.classList.toggle('active', p.id === `page-${name}`));
    $$('.side-link').forEach(b => b.classList.toggle('active', b.dataset.page === name));
    $('#pageTitle').textContent = pageTitles[name] || 'لوحة الإدارة';
    $('#adminSidebar').classList.remove('open');
    if (name === 'overview') loadDashboard();
    if (name === 'products') loadProducts();
    if (name === 'categories') loadCategories();
    if (name === 'orders') loadOrders();
  }
  function dateFormat(value) {
    if (!value) return '—';
    const d = new Date(value.replace(' ', 'T') + (value.endsWith('Z') ? '' : 'Z'));
    if (Number.isNaN(d.getTime())) return value;
    return new Intl.DateTimeFormat('ar-JO', { dateStyle: 'medium', timeStyle: 'short' }).format(d);
  }
  function statusPill(status) { return `<span class="status-pill ${statusClasses[status] || ''}">${statusNames[status] || status}</span>`; }
  async function loadDashboard() {
    try {
      const data = await api('/api/admin/dashboard');
      $('#statProducts').textContent = data.stats.products;
      $('#statAvailable').textContent = data.stats.available;
      $('#statNew').textContent = data.stats.new_orders;
      $('#statPreparing').textContent = data.stats.preparing;
      $('#sidebarNewOrders').textContent = data.stats.new_orders;
      $('#recentOrders').innerHTML = data.recent_orders.length ? data.recent_orders.map(o => `<tr><td><b>${escapeHTML(o.public_ref)}</b></td><td>${escapeHTML(o.customer_name)}</td><td>${o.fulfillment_type === 'delivery' ? 'توصيل' : 'استلام'}</td><td>${statusPill(o.status)}</td><td>${dateFormat(o.created_at)}</td></tr>`).join('') : '<tr><td colspan="5" class="table-empty">لا توجد طلبات حالياً.</td></tr>';
    } catch (e) { toast(e.message); }
  }
  async function loadCategories() {
    try {
      const data = await api('/api/admin/categories'); state.categories = data.categories;
      const list = $('#categoriesList');
      list.innerHTML = state.categories.length ? state.categories.map(c => `<div class="category-list-item"><img src="/public/${escapeHTML(c.image_path)}" alt=""><div><b>${escapeHTML(c.name)}</b><small dir="ltr">${escapeHTML(c.slug)}</small></div><button class="action-button" data-edit-category="${c.id}">تعديل</button><button class="action-button danger" data-delete-category="${c.id}">حذف</button></div>`).join('') : '<div class="table-empty">لا توجد أقسام بعد.</div>';
      $$('[data-edit-category]', list).forEach(btn => btn.addEventListener('click', () => {
        const category = state.categories.find(c => c.id === Number(btn.dataset.editCategory));
        if (!category) return;
        const form = $('#categoryForm');
        form.elements.id.value = category.id;
        form.elements.name.value = category.name;
        form.elements.slug.value = category.slug;
        form.elements.description.value = category.description || '';
        form.elements.image_path.value = category.image_path;
        $('#saveCategoryButton').textContent = 'تحديث القسم';
        $('#cancelCategoryEdit').classList.remove('hidden');
        form.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }));
      $$('[data-delete-category]', list).forEach(btn => btn.addEventListener('click', async () => {
        if (!confirm('هل أنت متأكد من حذف هذا القسم؟ يجب ألا يحتوي على منتجات.')) return;
        try { await api(`/api/admin/categories/${btn.dataset.deleteCategory}`, { method: 'DELETE', body: '{}' }); toast('تم حذف القسم.'); loadCategories(); }
        catch (e) { toast(e.message); }
      }));
      populateCategorySelect();
    } catch (e) { toast(e.message); }
  }
  function populateCategorySelect() {
    const select = $('#productCategory');
    if (!select) return;
    const current = select.value;
    select.innerHTML = state.categories.map(c => `<option value="${c.id}">${escapeHTML(c.name)}</option>`).join('');
    if (state.categories.some(c => String(c.id) === current)) select.value = current;
  }
  async function loadProducts() {
    try {
      const [productData, categoryData] = await Promise.all([api('/api/admin/products'), api('/api/admin/categories')]);
      state.products = productData.products; state.categories = categoryData.categories; populateCategorySelect();
      $('#productsSummary').textContent = `${state.products.length} منتج مسجل`;
      renderProductsTable();
    } catch (e) { toast(e.message); }
  }
  function renderProductsTable() {
    const search = ($('#productSearch').value || '').trim().toLowerCase();
    const visible = state.products.filter(p => `${p.name} ${p.category_name}`.toLowerCase().includes(search));
    $('#productsTable').innerHTML = visible.length ? visible.map(p => {
      const img = p.image_path && p.image_path.startsWith('images/') ? `/public/${escapeHTML(p.image_path)}` : `/public/${imageFallback[p.category_slug] || imageFallback.bakery}`;
      const price = p.price_jod === null || p.price_jod === undefined ? 'غير محدد' : `${Number(p.price_jod).toFixed(3)} د.أ`;
      return `<tr><td><div class="product-cell"><img src="${img}" alt=""><span><b>${escapeHTML(p.name)}</b><small>${p.is_featured ? 'منتج مميز' : 'منتج عادي'}</small></span></div></td><td>${escapeHTML(p.category_name)}</td><td>${price}</td><td><span class="status-pill ${p.is_available ? 'badge-available' : 'badge-unavailable'}">${p.is_available ? 'متوفر' : 'غير متوفر'}</span></td><td><div class="action-group"><button class="action-button" data-edit-product="${p.id}">تعديل</button><button class="action-button danger" data-delete-product="${p.id}">حذف</button></div></td></tr>`;
    }).join('') : '<tr><td colspan="5" class="table-empty">لا توجد نتائج مطابقة.</td></tr>';
    $$('[data-edit-product]').forEach(b => b.addEventListener('click', () => openProductModal(state.products.find(p => p.id === Number(b.dataset.editProduct)))));
    $$('[data-delete-product]').forEach(b => b.addEventListener('click', async () => {
      const product = state.products.find(p => p.id === Number(b.dataset.deleteProduct));
      if (!product || !confirm(`حذف المنتج «${product.name}»؟`)) return;
      try { await api(`/api/admin/products/${product.id}`, { method: 'DELETE', body: '{}' }); toast('تم حذف المنتج.'); loadProducts(); }
      catch (e) { toast(e.message); }
    }));
  }
  async function loadOrders() {
    try { const data = await api('/api/admin/orders'); state.orders = data.orders; renderOrders(); }
    catch (e) { toast(e.message); }
  }
  function renderOrders() {
    const filter = $('#orderFilter').value;
    const orders = state.orders.filter(o => filter === 'all' || o.status === filter);
    $('#ordersList').innerHTML = orders.length ? orders.map(o => {
      const itemsText = o.items.map(i => `${escapeHTML(i.product_name)} × ${i.quantity}`).join('، ');
      const statusOptions = Object.entries(statusNames).map(([key, value]) => `<option value="${key}" ${o.status === key ? 'selected' : ''}>${value}</option>`).join('');
      return `<article class="order-card"><div class="order-card-head"><div><b>${escapeHTML(o.public_ref)} · ${escapeHTML(o.customer_name)}</b><small>${dateFormat(o.created_at)}</small></div>${statusPill(o.status)}</div><div class="order-card-meta"><div><small>رقم الهاتف</small><b dir="ltr">${escapeHTML(o.phone)}</b></div><div><small>طريقة الاستلام</small><b>${o.fulfillment_type === 'delivery' ? 'توصيل' : 'استلام من الفرع'}</b></div><div><small>العنوان</small><b>${o.address ? escapeHTML(o.address) : '—'}</b></div></div><div class="order-items">${itemsText}</div>${o.notes ? `<div class="order-items">ملاحظات: ${escapeHTML(o.notes)}</div>` : ''}<div class="order-card-actions"><span class="order-note">الأسعار والتوصيل بحاجة إلى تأكيد</span><div><select id="status-${o.id}" aria-label="حالة الطلب">${statusOptions}</select> <button class="action-button" data-save-status="${o.id}">حفظ الحالة</button></div></div></article>`;
    }).join('') : '<div class="table-empty">لا توجد طلبات في هذه القائمة.</div>';
    $$('[data-save-status]').forEach(b => b.addEventListener('click', async () => {
      const id = b.dataset.saveStatus; const status = $(`#status-${id}`).value;
      try { await api(`/api/admin/orders/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }); toast('تم تحديث حالة الطلب.'); loadOrders(); loadDashboard(); }
      catch (e) { toast(e.message); }
    }));
  }
  function openProductModal(product = null) {
    $('#productForm').reset(); $('#productError').textContent = '';
    $('#productModalTitle').textContent = product ? 'تعديل بيانات المنتج' : 'إضافة منتج جديد';
    $('#productForm').elements.id.value = product?.id || '';
    populateCategorySelect();
    if (product) {
      const form = $('#productForm');
      form.elements.name.value = product.name;
      form.elements.category_id.value = product.category_id;
      form.elements.description.value = product.description || '';
      form.elements.price_jod.value = product.price_jod ?? '';
      const imagePath = product.image_path || imageFallback[product.category_slug] || imageFallback.bakery;
      ensureImageOption(imagePath);
      form.elements.image_path.value = imagePath;
      form.elements.sort_order.value = product.sort_order ?? 0;
      form.elements.is_available.checked = product.is_available;
      form.elements.is_featured.checked = product.is_featured;
    } else {
      $('#productForm').elements.image_path.value = 'images/category-bread.svg';
      $('#productForm').elements.is_available.checked = true;
    }
    $('#productImageUpload').value = '';
    $('#productModalBackdrop').classList.add('open'); $('#productModal').classList.add('open');
  }
  function closeProductModal() { $('#productModalBackdrop').classList.remove('open'); $('#productModal').classList.remove('open'); }
  function ensureImageOption(path) {
    const select = $('#productImageSelect');
    if (![...select.options].some(option => option.value === path)) {
      const option = document.createElement('option');
      option.value = path; option.textContent = 'صورة مخصصة مرفوعة'; select.appendChild(option);
    }
  }
  function fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('تعذرت قراءة الصورة.'));
      reader.readAsDataURL(file);
    });
  }
  async function uploadProductImage(file) {
    if (!file) return;
    $('#productError').textContent = '';
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) {
      $('#productError').textContent = 'اختر صورة JPG أو PNG أو WebP.'; return;
    }
    if (file.size > 2 * 1024 * 1024) {
      $('#productError').textContent = 'يجب ألا يتجاوز حجم الصورة 2 ميغابايت.'; return;
    }
    try {
      const dataUrl = await fileToDataUrl(file);
      const result = await api('/api/admin/upload-image', { method: 'POST', body: JSON.stringify({ data_url: dataUrl }) });
      ensureImageOption(result.image_path);
      $('#productImageSelect').value = result.image_path;
      toast('تم رفع الصورة. احفظ المنتج لتطبيقها.');
    } catch (error) { $('#productError').textContent = error.message; }
  }
  function resetCategoryForm() {
    $('#categoryForm').reset();
    $('#categoryForm').elements.id.value = '';
    $('#saveCategoryButton').textContent = 'حفظ القسم';
    $('#cancelCategoryEdit').classList.add('hidden');
    $('#categoryError').textContent = '';
  }
  function bind() {
    $$('.side-link').forEach(b => b.addEventListener('click', () => showPage(b.dataset.page)));
    $$('[data-goto]').forEach(b => b.addEventListener('click', () => showPage(b.dataset.goto)));
    $('#sidebarToggle').addEventListener('click', () => $('#adminSidebar').classList.toggle('open'));
    $('#logoutButton').addEventListener('click', async () => {
      try { await api('/api/admin/logout', { method: 'POST', body: '{}' }); }
      catch (e) { /* the session may already have expired */ }
      showLogin(); getCsrf();
    });
    $('#loginForm').addEventListener('submit', async e => {
      e.preventDefault(); $('#loginError').textContent = '';
      const form = new FormData(e.currentTarget); const button = $('button[type="submit"]', e.currentTarget);
      button.disabled = true;
      try {
        await api('/api/admin/login', { method: 'POST', body: JSON.stringify({ username: form.get('username'), password: form.get('password') }) });
        await getCsrf();
        const me = await api('/api/admin/me'); state.user = me.user; $('#adminUsername').textContent = me.user.username;
        showApp(); showPage('overview'); e.currentTarget.reset();
      } catch (error) { $('#loginError').textContent = error.message; }
      finally { button.disabled = false; }
    });
    $('#addProductButton').addEventListener('click', async () => { if (!state.categories.length) await loadCategories(); openProductModal(); });
    $('#closeProductModal').addEventListener('click', closeProductModal); $('#cancelProduct').addEventListener('click', closeProductModal); $('#productModalBackdrop').addEventListener('click', closeProductModal);
    $('#productSearch').addEventListener('input', renderProductsTable);
    $('#productImageUpload').addEventListener('change', e => uploadProductImage(e.target.files[0]));
    $('#productForm').addEventListener('submit', async e => {
      e.preventDefault(); $('#productError').textContent = '';
      const form = e.currentTarget; const fd = new FormData(form); const id = fd.get('id');
      const body = { name: fd.get('name'), category_id: Number(fd.get('category_id')), description: fd.get('description'), price_jod: fd.get('price_jod') || null, image_path: fd.get('image_path'), sort_order: Number(fd.get('sort_order') || 0), is_available: form.elements.is_available.checked, is_featured: form.elements.is_featured.checked };
      const button = $('#saveProductButton'); button.disabled = true;
      try { await api(id ? `/api/admin/products/${id}` : '/api/admin/products', { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) }); closeProductModal(); toast(id ? 'تم تحديث المنتج.' : 'تمت إضافة المنتج.'); loadProducts(); }
      catch (error) { $('#productError').textContent = error.message; }
      finally { button.disabled = false; }
    });
    $('#categoryForm').addEventListener('submit', async e => {
      e.preventDefault(); $('#categoryError').textContent = '';
      const fd = new FormData(e.currentTarget); const id = fd.get('id');
      const body = { name: fd.get('name'), slug: fd.get('slug'), description: fd.get('description'), image_path: fd.get('image_path') };
      try {
        await api(id ? `/api/admin/categories/${id}` : '/api/admin/categories', { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) });
        resetCategoryForm(); toast(id ? 'تم تحديث القسم.' : 'تمت إضافة القسم.'); loadCategories();
      } catch (error) { $('#categoryError').textContent = error.message; }
    });
    $('#cancelCategoryEdit').addEventListener('click', resetCategoryForm);
    $('#orderFilter').addEventListener('change', renderOrders); $('#refreshOrders').addEventListener('click', loadOrders);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeProductModal(); });
  }
  async function init() {
    bind();
    try {
      await getCsrf();
      const me = await api('/api/admin/me');
      state.user = me.user; $('#adminUsername').textContent = me.user.username; showApp(); showPage('overview');
    } catch (e) { showLogin(); }
  }
  document.addEventListener('DOMContentLoaded', init);
})();
