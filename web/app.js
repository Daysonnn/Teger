// ==========================================
//  Teger Mini App — app.js v2
// ==========================================

const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

let currentUser = tg.initDataUnsafe?.user || { id: 0, first_name: 'Гость' };
const urlParams = new URLSearchParams(window.location.search);
let chatId = urlParams.get('chat_id') || tg.initDataUnsafe?.start_param;
let allRolesCache = [];
let chatMembersCache = [];
let activeModalRole = null;
let selectedRoleEmoji = '🛡️';
let isOwnerUser = false;
let currentSendMode = 'single';
let activeTab = 'roles';

// ---- Init UI ----
document.getElementById('user-display-name').textContent = currentUser.first_name || 'Гость';
document.getElementById('chat-info').textContent = chatId
  ? `Чат ${chatId}`
  : currentUser.first_name || 'Гость';

if (chatId) document.getElementById('admin-chat-id').value = chatId;

const savedDraft = localStorage.getItem('teger_broadcast_draft');
if (savedDraft) document.getElementById('admin-msg-text').value = savedDraft;

// ---- Utils ----
function esc(t) {
  return (t || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function haptic(type = 'light') {
  tg.HapticFeedback?.impactOccurred(type);
}

let _toastTimer;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('visible');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('visible'), 2800);
}

function saveDraftMessage() {
  localStorage.setItem('teger_broadcast_draft', document.getElementById('admin-msg-text').value);
}

function restoreLastMessage() {
  const s = localStorage.getItem('teger_broadcast_draft');
  if (s) { document.getElementById('admin-msg-text').value = s; haptic(); toast('Черновик восстановлен'); }
  else toast('Черновиков нет');
}

// ---- Animated counter ----
function animateCount(el, target) {
  const start = parseInt(el.textContent) || 0;
  if (start === target) return;
  const dur = 600, step = 16;
  let t = 0;
  const timer = setInterval(() => {
    t += step;
    const p = Math.min(t / dur, 1);
    const ease = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(start + (target - start) * ease);
    if (p >= 1) clearInterval(timer);
  }, step);
}

// ---- Tab switching ----
function switchTab(name, btn) {
  haptic('light');
  activeTab = name;

  document.querySelectorAll('.tab-page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

  const page = document.getElementById(`tab-${name}`);
  if (page) page.classList.add('active');
  if (btn) btn.classList.add('active');
  else {
    const navBtn = document.querySelector(`.nav-btn[data-tab="${name}"]`);
    if (navBtn) navBtn.classList.add('active');
  }

  if (name === 'stats') fetchChatMembers();
  else if (name === 'logs') fetchAuditLogs();
  else if (name === 'achievements') fetchAchievements();
  else if (name === 'admin') fetchAdminStats();
}

// ---- Pull-to-refresh ----
let _pullStart = 0, _pulling = false, _refreshThreshold = 72;
const _container = document.querySelector('.page-container');
const _pullEl = document.getElementById('pull-indicator');

_container.addEventListener('touchstart', e => {
  if (_container.scrollTop === 0) _pullStart = e.touches[0].clientY;
}, { passive: true });

_container.addEventListener('touchmove', e => {
  if (!_pullStart) return;
  const dy = e.touches[0].clientY - _pullStart;
  if (dy > 20 && _container.scrollTop === 0) {
    _pulling = true;
    if (dy > _refreshThreshold) _pullEl.classList.add('visible');
  }
}, { passive: true });

_container.addEventListener('touchend', async () => {
  if (_pulling && _pullEl.classList.contains('visible')) {
    haptic('medium');
    await refreshCurrentTab();
    await new Promise(r => setTimeout(r, 400));
  }
  _pullEl.classList.remove('visible');
  _pulling = false;
  _pullStart = 0;
});

async function refreshCurrentTab() {
  if (activeTab === 'roles') await fetchRoles();
  else if (activeTab === 'stats') await fetchChatMembers();
  else if (activeTab === 'logs') await fetchAuditLogs();
  else if (activeTab === 'achievements') await fetchAchievements();
  else if (activeTab === 'admin') await fetchAdminStats();
}

// ---- API ----
async function apiPost(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  return res.json();
}

// ---- Owner check ----
async function checkOwnerStatus() {
  if (!currentUser.id) return;
  try {
    const res = await fetch(`/api/admin/check?user_id=${currentUser.id}`);
    const data = await res.json();
    if (data.is_owner) {
      isOwnerUser = true;
      const btn = document.getElementById('admin-tab-btn');
      btn.style.display = 'flex';
    }
  } catch {}
}

// ---- Roles ----
async function fetchRoles() {
  const container = document.getElementById('roles-list');
  if (!chatId) {
    container.innerHTML = `<div class="loader-state">Откройте Mini App из группы</div>`;
    return;
  }
  // Show skeletons
  container.innerHTML = `<div class="skeleton-card"></div><div class="skeleton-card"></div><div class="skeleton-card"></div>`;
  try {
    const res = await fetch(`/api/roles?chat_id=${chatId}`);
    const data = await res.json();
    allRolesCache = data.roles || [];

    let total = 0;
    allRolesCache.forEach(r => { total += r.members.length; });

    animateCount(document.getElementById('stat-roles-count'), allRolesCache.length);
    animateCount(document.getElementById('stat-members-count'), total);

    renderRoles(allRolesCache);
  } catch {
    container.innerHTML = `<div class="loader-state" style="color:var(--red)">Ошибка соединения</div>`;
  }
}

function filterRoles() {
  const q = document.getElementById('search-input').value.toLowerCase().trim();
  renderRoles(allRolesCache.filter(r => r.name.toLowerCase().includes(q)));
}

function renderRoles(roles) {
  const container = document.getElementById('roles-list');
  container.innerHTML = '';

  if (!roles.length) {
    container.innerHTML = `<div class="loader-state">Ролей пока нет</div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  roles.forEach((role, i) => {
    const isMember = role.members.some(m => m.user_id === currentUser.id);
    const icon = role.emoji || '🛡️';

    const card = document.createElement('div');
    card.className = 'role-card';
    card.style.animationDelay = `${i * 35}ms`;

    const membersHtml = role.members.length
      ? role.members.map(m => {
          const me = m.user_id === currentUser.id;
          return `<span class="mbadge${me ? ' me' : ''}">${me ? '⭐ ' : ''}${esc(m.username)}</span>`;
        }).join('')
      : `<span class="no-members">пока никого нет</span>`;

    const joinBtn = isMember
      ? `<button class="btn-secondary grow" onclick="leaveRole('${esc(role.name)}')">Выйти</button>`
      : `<button class="btn-primary grow" onclick="joinRole('${esc(role.name)}')">Вступить</button>`;

    card.innerHTML = `
      <div class="role-card-top">
        <div class="role-identity">
          <div class="role-emoji">${icon}</div>
          <div class="role-name">${esc(role.name)}</div>
        </div>
        <span class="role-count">${role.members.length}</span>
      </div>
      <div class="members-wrap">${membersHtml}</div>
      <div class="role-actions">
        ${joinBtn}
        <button class="btn-icon" onclick="openMemberModal('${esc(role.name)}')" title="Участники">👤+</button>
        <button class="btn-icon" onclick="shareRoleLink('${esc(role.name)}')" title="Скопировать ссылку">🔗</button>
        <button class="btn-danger" onclick="deleteRole('${esc(role.name)}')" title="Удалить">🗑</button>
      </div>
    `;
    frag.appendChild(card);
  });
  container.appendChild(frag);
}

// ---- Emoji select ----
function selectEmoji(el, emoji) {
  haptic('light');
  document.querySelectorAll('.emoji-btn').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  selectedRoleEmoji = emoji;
}

// ---- Create role ----
async function createNewRole() {
  const input = document.getElementById('new-role-input');
  const name = input.value.trim();
  if (!name) { toast('Введите название роли'); return; }
  haptic('medium');
  try {
    const data = await apiPost('/api/create', {
      chat_id: parseInt(chatId), role_name: name, emoji: selectedRoleEmoji
    });
    if (data.status === 'success') {
      toast(`${selectedRoleEmoji} Роль "${name}" создана`);
      input.value = '';
      switchTab('roles', document.querySelector('.nav-btn[data-tab="roles"]'));
      fetchRoles();
    } else { toast('Такая роль уже есть'); }
  } catch { toast('Ошибка соединения'); }
}

// ---- Join / Leave ----
async function joinRole(name) {
  haptic('light');
  const username = currentUser.username ? `@${currentUser.username}` : currentUser.first_name;
  try {
    const data = await apiPost('/api/join', {
      chat_id: parseInt(chatId), role_name: name,
      user_id: currentUser.id, username
    });
    if (data.status === 'success') { toast(`Вступил в ${name}`); fetchRoles(); }
    else if (data.status === 'already_in') toast('Вы уже в этой роли');
    else toast('Ошибка');
  } catch { toast('Ошибка соединения'); }
}

async function leaveRole(name) {
  haptic('light');
  try {
    const data = await apiPost('/api/leave', {
      chat_id: parseInt(chatId), role_name: name, user_id: currentUser.id
    });
    if (data.status === 'success') { toast(`Покинул ${name}`); fetchRoles(); }
  } catch { toast('Ошибка соединения'); }
}

function shareRoleLink(name) {
  haptic('medium');
  const url = chatId
    ? `https://t.me/tegerrbot?start=join_${name}_${chatId}`
    : `https://t.me/tegerrbot?start=join_${name}`;
  navigator.clipboard?.writeText(url).then(() => toast(`🔗 Ссылка на "${name}" скопирована`));
}

async function deleteRole(name) {
  if (!confirm(`Удалить роль "${name}"?`)) return;
  haptic('medium');
  try {
    const data = await apiPost('/api/delete', { chat_id: parseInt(chatId), role_name: name });
    if (data.status === 'success') { toast(`Роль "${name}" удалена`); fetchRoles(); }
  } catch { toast('Ошибка соединения'); }
}

// ---- Chat members (Roster) ----
async function fetchChatMembers() {
  if (!chatId) return;
  try {
    const res = await fetch(`/api/chat_members?chat_id=${chatId}`);
    const data = await res.json();
    chatMembersCache = data.members || [];
    renderRoster(chatMembersCache);
  } catch {}
}

function renderRoster(members) {
  const el = document.getElementById('roster-list');
  el.innerHTML = '';
  if (!members.length) { el.innerHTML = `<div class="loader-state">Участников нет</div>`; return; }

  const frag = document.createDocumentFragment();
  members.forEach(m => {
    const row = document.createElement('div');
    row.className = 'list-item';
    const rolesTags = m.roles?.length
      ? m.roles.map(r => `<span style="font-size:11px;background:var(--surface-hover);border:1px solid var(--border);padding:2px 7px;border-radius:5px;margin-right:3px;">🛡️${esc(r)}</span>`).join('')
      : `<span style="font-size:11px;color:var(--text-3)">без ролей</span>`;
    row.innerHTML = `
      <div style="min-width:0;flex:1">
        <div class="list-item-main">👤 ${esc(m.username)}</div>
        <div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:3px">${rolesTags}</div>
      </div>
    `;
    frag.appendChild(row);
  });
  el.appendChild(frag);
}

// ---- Audit logs ----
async function fetchAuditLogs() {
  if (!chatId) return;
  try {
    const res = await fetch(`/api/audit_logs?chat_id=${chatId}`);
    const data = await res.json();
    renderLogs(data.logs || []);
  } catch {}
}

function renderLogs(logs) {
  const el = document.getElementById('logs-list');
  el.innerHTML = '';
  if (!logs.length) { el.innerHTML = `<div class="loader-state">История пуста</div>`; return; }

  const frag = document.createDocumentFragment();
  logs.forEach(l => {
    const row = document.createElement('div');
    row.className = 'list-item';
    row.innerHTML = `
      <div style="min-width:0;flex:1">
        <div class="list-item-main">${esc(l.username)} → ${esc(l.action)}</div>
        ${l.details ? `<div class="list-item-sub">${esc(l.details)}</div>` : ''}
      </div>
      <div class="list-item-side">${esc(l.time)}</div>
    `;
    frag.appendChild(row);
  });
  el.appendChild(frag);
}

// ---- Achievements ----
const ACH_ICONS = { first_join:'🛡️', multiclass:'🎭', party_starter:'🎉', party_hero:'⚡', sheriff:'👑', night_shift:'🌙', role_master:'🔥' };

async function fetchAchievements() {
  if (!chatId || !currentUser.id) return;
  try {
    const res = await fetch(`/api/achievements?chat_id=${chatId}&user_id=${currentUser.id}`);
    const data = await res.json();
    renderAchievements(data.achievements || []);
  } catch {}
}

function renderAchievements(achs) {
  const el = document.getElementById('achievements-list');
  el.innerHTML = '';
  if (!achs.length) { el.innerHTML = `<div class="loader-state">Ачивок пока нет</div>`; return; }

  const frag = document.createDocumentFragment();
  achs.forEach(a => {
    const div = document.createElement('div');
    div.className = `ach-item${a.unlocked ? ' unlocked' : ''}`;
    const icon = ACH_ICONS[a.id] || '🏆';
    div.innerHTML = `
      <div class="ach-icon">${icon}</div>
      <div class="ach-body">
        <div class="ach-name">${esc(a.title)}</div>
        <div class="ach-desc">${esc(a.desc)}</div>
      </div>
      <div class="ach-badge">${a.unlocked ? '✅' : '🔒'}</div>
    `;
    frag.appendChild(div);
  });
  el.appendChild(frag);
}

// ---- Admin ----
async function fetchAdminStats() {
  if (!isOwnerUser) return;
  try {
    const res = await fetch(`/api/admin/stats?user_id=${currentUser.id}`);
    const data = await res.json();
    if (data.stats) {
      animateCount(document.getElementById('admin-stat-chats'), data.stats.chats);
      animateCount(document.getElementById('admin-stat-roles'), data.stats.roles);
      animateCount(document.getElementById('admin-stat-users'), data.stats.users);
      animateCount(document.getElementById('admin-stat-logs'), data.stats.logs);
    }
  } catch {}
}

function setSendMode(mode) {
  currentSendMode = mode;
  haptic('light');
  document.getElementById('toggle-single').classList.toggle('active', mode === 'single');
  document.getElementById('toggle-global').classList.toggle('active', mode === 'global');
  document.getElementById('chat-id-group').style.display = mode === 'global' ? 'none' : 'block';
  document.getElementById('admin-send-btn').textContent =
    mode === 'global' ? '📢 Разослать всем чатам' : '🚀 Отправить в чат';
}

async function sendAdminMessage() {
  const chatTarget = document.getElementById('admin-chat-id').value.trim();
  const text = document.getElementById('admin-msg-text').value.trim();
  if (!text) { toast('Введите текст'); return; }
  if (currentSendMode === 'single' && !chatTarget) { toast('Укажите Chat ID'); return; }
  const isGlobal = currentSendMode === 'global';
  if (isGlobal && !confirm('Разослать ВО ВСЕ чаты?')) return;

  const btn = document.getElementById('admin-send-btn');
  btn.disabled = true; btn.textContent = '⏳ Рассылка...';

  try {
    const data = await apiPost('/api/admin/send', {
      user_id: currentUser.id, chat_id: chatTarget, message: text, is_global: isGlobal
    });
    if (data.status === 'success') {
      haptic('medium'); toast(data.message || '✅ Отправлено'); saveDraftMessage();
    } else toast(data.error || 'Ошибка');
  } catch { toast('Ошибка соединения'); }
  finally {
    btn.disabled = false;
    btn.textContent = isGlobal ? '📢 Разослать всем чатам' : '🚀 Отправить в чат';
  }
}

// ---- Member modal ----
async function openMemberModal(roleName) {
  activeModalRole = roleName;
  haptic('medium');
  document.getElementById('modal-title').textContent = roleName;
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
  const q = document.getElementById('modal-search').value.toLowerCase().trim();
  renderModalMembers(chatMembersCache.filter(m => m.username.toLowerCase().includes(q)));
}

function renderModalMembers(members) {
  const el = document.getElementById('modal-members-list');
  el.innerHTML = '';
  if (!members.length) { el.innerHTML = `<div class="loader-state">Список пуст</div>`; return; }

  const role = allRolesCache.find(r => r.name === activeModalRole);
  const memberIds = role?.members.map(m => m.user_id) || [];
  const memberNames = role?.members.map(m => m.username?.toLowerCase()) || [];

  const frag = document.createDocumentFragment();
  members.forEach(m => {
    const inRole = (m.user_id && memberIds.includes(m.user_id)) ||
                   (m.username && memberNames.includes(m.username.toLowerCase()));

    const row = document.createElement('div');
    row.className = 'modal-member-row';

    const nameEl = document.createElement('div');
    nameEl.className = 'modal-member-name';
    nameEl.textContent = `👤 ${m.username}`;

    const btn = document.createElement('button');
    if (inRole) {
      btn.className = 'btn-secondary';
      btn.style.cssText = 'min-height:36px;padding:0 12px;font-size:12px;';
      btn.textContent = '✅ В роли';
      btn.onclick = () => toggleMember(activeModalRole, m.user_id, m.username, false);
    } else {
      btn.className = 'btn-primary';
      btn.style.cssText = 'min-height:36px;padding:0 12px;font-size:12px;';
      btn.textContent = '+ Добавить';
      btn.onclick = () => toggleMember(activeModalRole, m.user_id, m.username, true);
    }

    row.appendChild(nameEl);
    row.appendChild(btn);
    frag.appendChild(row);
  });
  el.appendChild(frag);
}

async function toggleMember(roleName, userId, username, add) {
  haptic('light');
  try {
    const data = await apiPost(add ? '/api/join' : '/api/leave', {
      chat_id: parseInt(chatId), role_name: roleName, user_id: userId, username
    });
    if (data.status === 'success') {
      toast(add ? `${username} добавлен` : `${username} удалён`);
      await fetchRoles();
      await fetchChatMembers();
      renderModalMembers(chatMembersCache);
    }
  } catch { toast('Ошибка'); }
}

async function addManualUser() {
  const inp = document.getElementById('manual-user-input');
  const val = inp.value.trim();
  if (!val || !activeModalRole) return;
  const clean = val.startsWith('@') ? val : `@${val}`;
  await toggleMember(activeModalRole, null, clean, true);
  inp.value = '';
}

// ---- PC scroll for emoji ----
document.querySelectorAll('.emoji-row').forEach(el => {
  el.addEventListener('wheel', e => {
    if (e.deltaY) { e.preventDefault(); el.scrollLeft += e.deltaY; }
  }, { passive: false });
});

// ---- Boot ----
checkOwnerStatus();
fetchRoles();