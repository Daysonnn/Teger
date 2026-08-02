// ==========================================
//  Teger Mini App — app.js
//  Optimized, clean, GPU-friendly
// ==========================================

const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

let currentUser = tg.initDataUnsafe.user || { id: 0, first_name: 'Гость' };
const urlParams = new URLSearchParams(window.location.search);
let chatId = urlParams.get('chat_id') || tg.initDataUnsafe.start_param;
let allRolesCache = [];
let chatMembersCache = [];
let activeModalRole = null;
let selectedRoleEmoji = '🛡️';
let isOwnerUser = false;
let currentSendMode = 'single';

// ---- Init ----
document.getElementById('user-display-name').textContent = currentUser.first_name || 'Гость';
document.getElementById('chat-info').textContent = chatId
  ? `Группа ID: ${chatId}`
  : `Пользователь: ${currentUser.first_name}`;

if (chatId) document.getElementById('admin-chat-id').value = chatId;

const savedDraft = localStorage.getItem('last_broadcast_message');
if (savedDraft) document.getElementById('admin-msg-text').value = savedDraft;

// ---- Utils ----
function escapeHtml(text) {
  return (text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function triggerHaptic(type = 'light') {
  if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred(type);
}

let toastTimer = null;
function showToast(text) {
  const toast = document.getElementById('toast');
  toast.textContent = text;
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 3000);
}

function saveDraftMessage() {
  localStorage.setItem('last_broadcast_message', document.getElementById('admin-msg-text').value);
}

function restoreLastMessage() {
  const saved = localStorage.getItem('last_broadcast_message');
  if (saved) {
    document.getElementById('admin-msg-text').value = saved;
    triggerHaptic('light');
    showToast('Восстановлен последний текст!');
  } else {
    showToast('Черновиков пока нет');
  }
}

// ---- Tabs ----
function switchTab(tabName, btnElement) {
  triggerHaptic('light');
  document.querySelectorAll('.nav-item-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  const targetBtn = btnElement || document.querySelector(`.nav-item-btn[onclick*="${tabName}"]`);
  if (targetBtn) targetBtn.classList.add('active');
  const targetContent = document.getElementById(`tab-${tabName}`);
  if (targetContent) targetContent.classList.add('active');

  if (tabName === 'stats') fetchChatMembers();
  else if (tabName === 'logs') fetchAuditLogs();
  else if (tabName === 'achievements') fetchAchievements();
  else if (tabName === 'admin') fetchAdminStats();
}

// ---- Emoji ----
function selectEmoji(el, emoji) {
  triggerHaptic('light');
  document.querySelectorAll('.emoji-btn-item').forEach(e => e.classList.remove('active'));
  el.classList.add('active');
  selectedRoleEmoji = emoji;
}

// ---- Admin mode toggle ----
function setSendMode(mode) {
  currentSendMode = mode;
  triggerHaptic('light');
  const chatIdGroup = document.getElementById('chat-id-group');
  const sendBtn = document.getElementById('admin-send-btn');
  document.getElementById('toggle-single').classList.toggle('active', mode === 'single');
  document.getElementById('toggle-global').classList.toggle('active', mode === 'global');
  chatIdGroup.style.display = mode === 'global' ? 'none' : 'flex';
  sendBtn.textContent = mode === 'global'
    ? '📢 Запустить МАССОВУЮ рассылку во ВСЕ чаты'
    : '🚀 Отправить сообщение в чат';
}

// ---- API helpers ----
async function apiPost(endpoint, body) {
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  return res.json();
}

// ---- Check owner ----
async function checkOwnerStatus() {
  if (!currentUser.id) return;
  try {
    const res = await fetch(`/api/admin/check?user_id=${currentUser.id}`);
    const data = await res.json();
    if (data.is_owner) {
      isOwnerUser = true;
      document.getElementById('admin-tab-btn').style.display = 'flex';
    }
  } catch (e) {
    console.error('Ошибка проверки владельца:', e);
  }
}

// ---- Fetch roles ----
async function fetchRoles() {
  const container = document.getElementById('roles-list');
  if (!chatId) {
    container.innerHTML = `<div class="loader-text">Откройте Mini App из группы,<br>чтобы загрузить её роли.</div>`;
    return;
  }
  try {
    const res = await fetch(`/api/roles?chat_id=${chatId}`);
    const data = await res.json();
    allRolesCache = data.roles || [];

    let totalMembers = 0;
    allRolesCache.forEach(r => { totalMembers += r.members.length; });

    document.getElementById('stat-roles-count').textContent = allRolesCache.length;
    document.getElementById('stat-members-count').textContent = totalMembers;

    renderRoles(allRolesCache);
  } catch (err) {
    console.error('Ошибка загрузки:', err);
    container.innerHTML = `<div class="loader-text" style="color:var(--accent-red);">Ошибка подключения к серверу</div>`;
  }
}

// ---- Render roles (DocumentFragment for performance) ----
function renderRoles(roles) {
  const container = document.getElementById('roles-list');
  container.innerHTML = '';

  if (roles.length === 0) {
    container.innerHTML = `<div class="loader-text">Ролей пока нет</div>`;
    return;
  }

  const frag = document.createDocumentFragment();

  roles.forEach((role, idx) => {
    const isMember = role.members.some(m => m.user_id === currentUser.id);
    const roleIcon = role.emoji || '🛡️';

    const card = document.createElement('div');
    card.className = 'role-item-card';
    card.style.animationDelay = `${idx * 40}ms`;

    // Members row
    let membersHtml = '';
    if (role.members.length > 0) {
      membersHtml = role.members.map(m => {
        const isMe = m.user_id === currentUser.id;
        return `<span class="member-badge ${isMe ? 'is-me' : ''}">${isMe ? '⭐ ' : ''}${escapeHtml(m.username)}</span>`;
      }).join('');
    } else {
      membersHtml = `<span style="font-size:13px;color:var(--text-dim);font-style:italic;">участников нет</span>`;
    }

    const joinOrLeaveBtn = isMember
      ? `<button class="btn-action btn-glass" onclick="leaveRole('${role.name}')">Выйти</button>`
      : `<button class="btn-action btn-blue" onclick="joinRole('${role.name}')">Вступить</button>`;

    card.innerHTML = `
      <div class="role-header-row">
        <div class="role-identity">
          <div class="role-emoji-box">${roleIcon}</div>
          <div class="role-name-text">${escapeHtml(role.name)}</div>
        </div>
        <span class="member-count-tag">${role.members.length} чел.</span>
      </div>
      <div class="members-flex">${membersHtml}</div>
      <div class="role-action-row">
        ${joinOrLeaveBtn}
        <button class="btn-action btn-glass btn-icon-only" onclick="openMemberModal('${role.name}')" title="Участники">👤+</button>
        <button class="btn-action btn-glass btn-icon-only" onclick="shareRoleLink('${role.name}')" title="Ссылка">🔗</button>
        <button class="btn-action btn-danger-glass" onclick="deleteRole('${role.name}')" title="Удалить">🗑</button>
      </div>
    `;

    frag.appendChild(card);
  });

  container.appendChild(frag);
}

function filterRoles() {
  const query = document.getElementById('search-input').value.toLowerCase().trim();
  renderRoles(allRolesCache.filter(r => r.name.toLowerCase().includes(query)));
}

// ---- Fetch chat members ----
async function fetchChatMembers() {
  if (!chatId) return;
  try {
    const res = await fetch(`/api/chat_members?chat_id=${chatId}`);
    const data = await res.json();
    chatMembersCache = data.members || [];
    renderRoster(chatMembersCache);
  } catch (e) {
    console.error('Ошибка участников:', e);
  }
}

// ---- Render roster (DocumentFragment) ----
function renderRoster(members) {
  const container = document.getElementById('roster-list');
  container.innerHTML = '';

  if (members.length === 0) {
    container.innerHTML = `<div class="loader-text">Участники не найдены</div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  members.forEach(m => {
    const row = document.createElement('div');
    row.className = 'list-row-item';

    const rolesBadges = m.roles.length > 0
      ? m.roles.map(r => `<span style="background:rgba(255,255,255,0.06);border:1px solid var(--card-border);font-size:11px;padding:3px 8px;border-radius:6px;color:var(--text-dim);">🛡️ ${escapeHtml(r)}</span>`).join(' ')
      : `<span style="font-size:11px;color:var(--text-dim);">без ролей</span>`;

    row.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;font-weight:600;">👤 ${escapeHtml(m.username)}</div>
      <div style="display:flex;gap:4px;flex-wrap:wrap;">${rolesBadges}</div>
    `;
    frag.appendChild(row);
  });
  container.appendChild(frag);
}

// ---- Audit logs ----
async function fetchAuditLogs() {
  if (!chatId) return;
  try {
    const res = await fetch(`/api/audit_logs?chat_id=${chatId}`);
    const data = await res.json();
    renderAuditLogs(data.logs || []);
  } catch (e) {
    console.error('Ошибка истории:', e);
  }
}

function renderAuditLogs(logs) {
  const container = document.getElementById('logs-list');
  container.innerHTML = '';

  if (logs.length === 0) {
    container.innerHTML = `<div class="loader-text">История пока пуста</div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  logs.forEach(l => {
    const row = document.createElement('div');
    row.className = 'list-row-item';
    row.innerHTML = `
      <div style="display:flex;justify-content:space-between;width:100%;font-weight:600;">
        <span>${escapeHtml(l.username)} ➔ ${escapeHtml(l.action)}</span>
        <span style="font-size:11px;color:var(--text-dim);">${escapeHtml(l.time)}</span>
      </div>
      <div style="font-size:12px;color:var(--text-dim);margin-top:2px;">${escapeHtml(l.details || '')}</div>
    `;
    frag.appendChild(row);
  });
  container.appendChild(frag);
}

// ---- Achievements ----
async function fetchAchievements() {
  if (!chatId || !currentUser.id) return;
  try {
    const res = await fetch(`/api/achievements?chat_id=${chatId}&user_id=${currentUser.id}`);
    const data = await res.json();
    const achs = data.achievements || [];

    const container = document.getElementById('achievements-list');
    container.innerHTML = '';
    const frag = document.createDocumentFragment();
    achs.forEach(a => {
      const div = document.createElement('div');
      div.className = `ach-card ${a.unlocked ? 'unlocked' : ''}`;
      div.innerHTML = `
        <div class="ach-title-row">
          <div class="ach-title">${escapeHtml(a.title)}</div>
          <div class="ach-status">${a.unlocked ? '✅ Получено' : '🔒 Заблокировано'}</div>
        </div>
        <div class="ach-desc">${escapeHtml(a.desc)}</div>
      `;
      frag.appendChild(div);
    });
    container.appendChild(frag);
  } catch (e) {
    console.error('Ошибка загрузки ачивок:', e);
  }
}

// ---- Admin stats ----
async function fetchAdminStats() {
  if (!isOwnerUser) return;
  try {
    const res = await fetch(`/api/admin/stats?user_id=${currentUser.id}`);
    const data = await res.json();
    if (data.stats) {
      document.getElementById('admin-stat-chats').textContent = data.stats.chats;
      document.getElementById('admin-stat-roles').textContent = data.stats.roles;
      document.getElementById('admin-stat-users').textContent = data.stats.users;
      document.getElementById('admin-stat-logs').textContent = data.stats.logs;
    }
  } catch (e) {
    console.error('Ошибка админ статистики:', e);
  }
}

async function sendAdminMessage() {
  const targetChatId = document.getElementById('admin-chat-id').value.trim();
  const messageText = document.getElementById('admin-msg-text').value.trim();

  if (!messageText) { showToast('Введите текст сообщения'); return; }
  if (currentSendMode === 'single' && !targetChatId) { showToast('Укажите Chat ID чата'); return; }

  const isGlobal = (currentSendMode === 'global');
  if (isGlobal && !confirm('📢 Отправить это сообщение ВО ВСЕ чаты группы бота?')) return;

  const btn = document.getElementById('admin-send-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Выполнение рассылки...';

  try {
    const data = await apiPost('/api/admin/send', {
      user_id: currentUser.id,
      chat_id: targetChatId,
      message: messageText,
      is_global: isGlobal
    });
    if (data.status === 'success') {
      triggerHaptic('medium');
      showToast(data.message || '✅ Успешно отправлено!');
      saveDraftMessage();
    } else {
      showToast(data.error || 'Ошибка рассылки');
    }
  } catch (e) {
    showToast('Ошибка подключения к серверу');
  } finally {
    btn.disabled = false;
    btn.textContent = isGlobal ? '📢 Запустить МАССОВУЮ рассылку во ВСЕ чаты' : '🚀 Отправить сообщение в чат';
  }
}

// ---- Member modal ----
async function openMemberModal(roleName) {
  activeModalRole = roleName;
  triggerHaptic('medium');
  document.getElementById('modal-title').textContent = `Участники: ${roleName}`;
  document.getElementById('manual-user-input').value = '';
  document.getElementById('modal-search').value = '';
  document.getElementById('modal-backdrop').classList.add('open');

  await fetchChatMembers();
  renderModalMembers(chatMembersCache);
}

function closeMemberModal(event) {
  if (event && event.target !== document.getElementById('modal-backdrop')) return;
  document.getElementById('modal-backdrop').classList.remove('open');
  activeModalRole = null;
}

function filterModalMembers() {
  const query = document.getElementById('modal-search').value.toLowerCase().trim();
  renderModalMembers(chatMembersCache.filter(m => m.username.toLowerCase().includes(query)));
}

function renderModalMembers(members) {
  const container = document.getElementById('modal-members-list');
  const targetRole = allRolesCache.find(r => r.name === activeModalRole);
  const roleMemberIds = targetRole ? targetRole.members.map(m => m.user_id) : [];
  const roleMemberUsernames = targetRole ? targetRole.members.map(m => (m.username || '').toLowerCase()) : [];

  container.innerHTML = '';

  if (members.length === 0) {
    container.innerHTML = `<div class="loader-text">Список участников пуст</div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  members.forEach(m => {
    const inRole = (m.user_id && roleMemberIds.includes(m.user_id)) ||
                   (m.username && roleMemberUsernames.includes(m.username.toLowerCase()));

    const div = document.createElement('div');
    div.style.cssText = 'display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.05);padding:10px 12px;border-radius:10px;border:1px solid var(--card-border);';

    const nameEl = document.createElement('div');
    nameEl.style.cssText = 'display:flex;align-items:center;gap:8px;font-weight:600;';
    nameEl.textContent = `👤 ${m.username}`;

    const btn = document.createElement('button');
    if (inRole) {
      btn.className = 'btn-action btn-glass';
      btn.style.cssText = 'flex:initial;min-height:36px;padding:6px 12px;';
      btn.textContent = '✅ В роли';
      btn.onclick = () => toggleRoleUser(activeModalRole, m.user_id, m.username, false);
    } else {
      btn.className = 'btn-action btn-blue';
      btn.style.cssText = 'flex:initial;min-height:36px;padding:6px 12px;';
      btn.textContent = '+ Добавить';
      btn.onclick = () => toggleRoleUser(activeModalRole, m.user_id, m.username, true);
    }

    div.appendChild(nameEl);
    div.appendChild(btn);
    frag.appendChild(div);
  });

  container.appendChild(frag);
}

async function toggleRoleUser(roleName, userId, username, shouldAdd) {
  triggerHaptic('light');
  try {
    const endpoint = shouldAdd ? '/api/join' : '/api/leave';
    const data = await apiPost(endpoint, {
      chat_id: parseInt(chatId),
      role_name: roleName,
      user_id: userId,
      username: username
    });
    if (data.status === 'success') {
      showToast(shouldAdd ? `${username} добавлен` : `${username} удалён`);
      await fetchRoles();
      await fetchChatMembers();
      renderModalMembers(chatMembersCache);
    }
  } catch (e) {
    showToast('Ошибка операции');
  }
}

async function addManualUser() {
  const input = document.getElementById('manual-user-input');
  const val = input.value.trim();
  if (!val || !activeModalRole) return;
  const cleanUn = val.startsWith('@') ? val : `@${val}`;
  await toggleRoleUser(activeModalRole, null, cleanUn, true);
  input.value = '';
}

// ---- Role actions ----
async function joinRole(roleName) {
  triggerHaptic('light');
  const username = currentUser.username ? `@${currentUser.username}` : currentUser.first_name;
  try {
    const data = await apiPost('/api/join', {
      chat_id: parseInt(chatId),
      role_name: roleName,
      user_id: currentUser.id,
      username
    });
    if (data.status === 'success') {
      showToast(`Вы вступили в ${roleName}`);
      fetchRoles();
    } else if (data.status === 'already_in') {
      showToast(`Вы уже в роли ${roleName}`);
    }
  } catch (e) {
    showToast('Ошибка подключения');
  }
}

async function leaveRole(roleName) {
  triggerHaptic('light');
  try {
    const data = await apiPost('/api/leave', {
      chat_id: parseInt(chatId),
      role_name: roleName,
      user_id: currentUser.id
    });
    if (data.status === 'success') {
      showToast(`Вы покинули ${roleName}`);
      fetchRoles();
    }
  } catch (e) {
    showToast('Ошибка подключения');
  }
}

function shareRoleLink(roleName) {
  triggerHaptic('medium');
  const botUsername = 'tegerrbot';
  const shareUrl = chatId
    ? `https://t.me/${botUsername}?start=join_${roleName}_${chatId}`
    : `https://t.me/${botUsername}?start=join_${roleName}`;
  navigator.clipboard.writeText(shareUrl).then(() => {
    showToast(`🔗 Ссылка на роль ${roleName} скопирована!`);
  });
}

async function createNewRole() {
  const input = document.getElementById('new-role-input');
  const roleName = input.value.trim();
  if (!roleName) { showToast('Введите название роли'); return; }

  triggerHaptic('medium');
  try {
    const data = await apiPost('/api/create', {
      chat_id: parseInt(chatId),
      role_name: roleName,
      emoji: selectedRoleEmoji
    });
    if (data.status === 'success') {
      showToast(`Роль ${selectedRoleEmoji} ${roleName} создана`);
      input.value = '';
      switchTab('roles');
      fetchRoles();
    } else {
      showToast('Такая роль уже есть');
    }
  } catch (e) {
    showToast('Ошибка подключения');
  }
}

async function deleteRole(roleName) {
  if (!confirm(`Удалить роль "${roleName}"?`)) return;
  triggerHaptic('medium');
  try {
    const data = await apiPost('/api/delete', {
      chat_id: parseInt(chatId),
      role_name: roleName
    });
    if (data.status === 'success') {
      showToast(`Роль ${roleName} удалена`);
      fetchRoles();
    }
  } catch (e) {
    showToast('Ошибка подключения');
  }
}

// ---- PC wheel scroll for horizontal lists ----
document.querySelectorAll('.emoji-grid-select, .preset-chips').forEach(el => {
  el.addEventListener('wheel', e => {
    if (e.deltaY !== 0) { e.preventDefault(); el.scrollLeft += e.deltaY; }
  }, { passive: false });
});

// ---- Boot ----
checkOwnerStatus();
fetchRoles();